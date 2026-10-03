"""Replay a downloaded ladder game through one of our bot builds.

The bot receives exactly the message stream it would have seen on the ladder
(hello, hand_start, blinds, action, street, act, hand_end). At each of our
decisions we compare its action with what our uploaded bot actually did.

Everyone else's actions are fixed by the recording, so after a divergence the
rest of that hand is not a true counterfactual. One case is still exact: if
the replayed bot folds where the ladder bot put more chips in and lost, the
fold would have saved everything from that point on. That is the "saved"
column, a lower bound on what a change is worth on real ladder hands.

  python tools/ladder_replay.py <bot main.py> <our bot index> game.json [...]
  (several games: pass index:file pairs, e.g. 1:g_a.json 4:g_b.json)
"""

from __future__ import annotations

import json
import sys
from collections import Counter

from macpoker.sdk import BotSession, load_bot_from_file


def _wire(action):
    w = action.to_wire()
    k = w.get("action")
    return ("raise" if k in ("allin", "all_in") else k), w.get("amount", 0)


def replay(bot_path: str, me: int, game: dict, verbose: bool = False):
    bot = load_bot_from_file(bot_path)
    sess = BotSession(bot)
    hands = game["hands"]
    n = len(hands[0]["seat_map"])
    sess.handle({"type": "hello", "num_players": n, "num_hands": len(hands), "stack": 200,
                 "blinds": [1, 2], "time_bank_ms": 30000, "increment_ms": 100, "player": me})
    stats, saved, rows = Counter(), 0, []
    for h in hands:
        sm = h["seat_map"]
        seat = sm.index(me)
        players = list(sm)
        sess.handle({"type": "hand_start", "hand": h["hand"], "seat": seat, "button": 0,
                     "stacks": [200] * n, "hole": h["holes"][str(seat)], "players": players})
        stacks, contrib, sb_ = [200] * n, [0] * n, [0] * n
        folded = [False] * n
        board: list[str] = []
        street, cur, min_inc, log = "preflop", 0, 2, []
        diverged = False
        for ev in h["events"]:
            t = ev["type"]
            if t == "blinds":
                for s, amt in ((ev["sb_seat"], ev["sb"]), (ev["bb_seat"], ev["bb"])):
                    stacks[s] -= amt; contrib[s] += amt; sb_[s] += amt
                cur, min_inc = ev["bb"], ev["bb"]
            elif t == "street":
                street, board = ev["street"], ev["board"]
                sb_, cur, min_inc = [0] * n, 0, 2
            elif t == "action" and ev["seat"] == seat and not diverged:
                to_call = min(cur - sb_[seat], stacks[seat])
                max_to = sb_[seat] + stacks[seat]
                view = {"type": "act", "hand": h["hand"], "seat": seat, "street": street,
                        "board": board, "hole": h["holes"][str(seat)], "pot": sum(contrib),
                        "to_call": to_call, "min_raise_to": min(cur + min_inc if cur else 2, max_to),
                        "max_raise_to": max_to, "can_raise": max_to > cur, "stacks": list(stacks),
                        "street_bets": list(sb_), "folded": list(folded), "button": 0,
                        "history": [list(a) for a in log], "clock_ms": 20000, "players": players}
                kind, amt = _wire(sess.handle(view))
                real = ev["action"]
                same = kind == real or (kind == "check" and real == "call" and to_call == 0)
                if kind == "raise" and real == "raise":
                    same = abs((amt or 0) - ev["amount"]) <= max(2, 0.15 * ev["amount"])
                stats["same" if same else "diff"] += 1
                if not same:
                    diverged = True
                    d = h["deltas_by_bot"][me]
                    gain = 0
                    if kind == "fold" and real in ("call", "raise") and d < 0:
                        gain = d + contrib[seat]  # negative d, we keep what was not yet in
                        gain = -gain
                        saved += gain
                    rows.append((h["hand"], street, real, ev["amount"], kind, amt, d, gain,
                                 "".join(h["holes"][str(seat)]), " ".join(board)))
            if t == "action":
                s, k, a = ev["seat"], ev["action"], ev["amount"]
                if k == "fold":
                    folded[s] = True
                elif k == "call":
                    stacks[s] -= a; contrib[s] += a; sb_[s] += a
                elif k == "raise":
                    add = a - sb_[s]
                    stacks[s] -= add; contrib[s] += add
                    if a - cur >= min_inc:
                        min_inc = a - cur
                    sb_[s], cur = a, max(cur, a)
                log.append([street, s, k, a])
            if t != "act":
                sess.handle({**ev, "players": players})
    return stats, saved, rows


if __name__ == "__main__":
    bot_path = sys.argv[1]
    total, total_saved = Counter(), 0
    for spec in sys.argv[2:]:
        idx, path = spec.split(":", 1)
        stats, saved, rows = replay(bot_path, int(idx), json.load(open(path)))
        total += stats
        total_saved += saved
        for r in rows:
            print(f"  {path.split('/')[-1][:12]} h{r[0]:<3}{r[1]:8} ladder={r[2]}{r[3] or ''} replay={r[4]}{r[5] or ''}"
                  f"  hand_result={r[6]:+} saved={r[7]:+}  {r[8]} | {r[9]}")
    agree = total["same"] / max(1, sum(total.values()))
    print(f"decisions matching the ladder: {total['same']}/{sum(total.values())} ({agree:.0%}); "
          f"chips saved by folds that differ: {total_saved:+}")
