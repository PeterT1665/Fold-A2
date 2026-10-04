"""Score a build's river call/fold choices on real ladder spots, against the bettor's real cards.

  python tools/v4/river_check.py v4/main.py macpoker-scaffold/main.py

Every heads-up river spot in games/*.json where a bot faced a bet: the build is put in that bot's seat
with the exact message stream that bot saw (so its opponent stats are built from the real game), and
asked to act. Calling is worth +pot if the caller's hand beats the bettor's real hand, -to_call if not,
folding 0 (a raise counts as a call). Prints chips per spot for the build, for the real bot, for
"always call" and for "always fold", split by the size of the bet.
"""
import glob, json, os, sys
from collections import defaultdict
from multiprocessing import Pool

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "v4"))
from cards7 import evaluate, parse
from macpoker.sdk import BotSession, load_bot_from_file

STREET = os.environ.get("STREET", "river")  # STREET=turn scores turn calls by exact equity vs the real hand


def spots_in(game, me, bot_path):
    bot = load_bot_from_file(bot_path)
    sess = BotSession(bot)
    hands = game["hands"]
    n = len(hands[0]["seat_map"])
    sess.handle({"type": "hello", "num_players": n, "num_hands": len(hands), "stack": 200,
                 "blinds": [1, 2], "time_bank_ms": 30000, "increment_ms": 100, "player": me})
    out = []
    for h in hands:
        sm = h["seat_map"]
        seat = sm.index(me)
        players = list(sm)
        sess.handle({"type": "hand_start", "hand": h["hand"], "seat": seat, "button": 0,
                     "stacks": [200] * n, "hole": h["holes"][str(seat)], "players": players})
        stacks, contrib, sb_ = [200] * n, [0] * n, [0] * n
        folded = [False] * n
        board = []
        street, cur, min_inc, log = "preflop", 0, 2, []
        for ev in h["events"]:
            t = ev["type"]
            if t == "blinds":
                for s, amt in ((ev["sb_seat"], ev["sb"]), (ev["bb_seat"], ev["bb"])):
                    stacks[s] -= amt; contrib[s] += amt; sb_[s] += amt
                cur, min_inc = ev["bb"], ev["bb"]
            elif t == "street":
                street, board = ev["street"], ev["board"]
                sb_, cur, min_inc = [0] * n, 0, 2
            elif t == "action" and ev["seat"] == seat and street == STREET:
                to_call = min(cur - sb_[seat], stacks[seat])
                live = [x for x in range(n) if not folded[x]]
                if to_call > 0 and len(live) == 2:
                    opp = [x for x in live if x != seat][0]
                    max_to = sb_[seat] + stacks[seat]
                    view = {"type": "act", "hand": h["hand"], "seat": seat, "street": street,
                            "board": board, "hole": h["holes"][str(seat)], "pot": sum(contrib),
                            "to_call": to_call, "min_raise_to": min(cur + min_inc if cur else 2, max_to),
                            "max_raise_to": max_to, "can_raise": max_to > cur and stacks[opp] > 0, "stacks": list(stacks),
                            "street_bets": list(sb_), "folded": list(folded), "button": 0,
                            "history": [list(a) for a in log], "clock_ms": 20000, "players": players}
                    a = sess.handle(view)
                    b = [parse(c) for c in board]
                    hm = [parse(c) for c in h["holes"][str(seat)]]
                    ho = [parse(c) for c in h["holes"][str(opp)]]
                    left = [c for c in range(52) if c not in b + hm + ho]
                    if len(b) == 5:
                        rest = [()]
                    elif len(b) == 4:
                        rest = [(c,) for c in left]
                    else:  # flop: every turn+river pair
                        rest = [(x, y) for i, x in enumerate(left) for y in left[i + 1:]]
                    eq = 0.0
                    for r in rest:
                        bb = b + list(r)
                        mine, theirs = evaluate(hm + bb), evaluate(ho + bb)
                        eq += 1.0 if mine > theirs else (0.5 if mine == theirs else 0.0)
                    eq /= len(rest)
                    pot = sum(contrib)
                    val = eq * (pot + to_call) - to_call
                    frac = to_call / max(pot - to_call, 1)
                    out.append((frac, val, a.kind != "fold", ev["action"] != "fold"))
            if t == "action":
                s, k, amt = ev["seat"], ev["action"], ev["amount"]
                if k == "fold":
                    folded[s] = True
                elif k == "call":
                    stacks[s] -= amt; contrib[s] += amt; sb_[s] += amt
                elif k == "raise":
                    add = amt - sb_[s]
                    stacks[s] -= add; contrib[s] += add
                    if amt - cur >= min_inc:
                        min_inc = amt - cur
                    sb_[s], cur = amt, max(cur, amt)
                log.append([street, s, k, amt])
            if t != "act":
                sess.handle({**ev, "players": players})
    return out


def job(args):
    path, bot_path = args
    g = json.load(open(path))
    if not isinstance(g, dict) or "names" not in g:
        return []
    res = []
    for me in range(len(g["names"])):
        res += spots_in(g, me, bot_path)
    return res


def main():
    files = sorted(f for f in glob.glob(os.path.join(ROOT, "games", "*.json")) if os.path.basename(f) not in ("index.json", "game1.json"))
    for bot_path in sys.argv[1:]:
        with Pool(9, maxtasksperchild=4) as p:
            rows = [r for part in p.map(job, [(f, bot_path) for f in files]) for r in part]
        bins = defaultdict(lambda: [0, 0.0, 0.0, 0.0])
        for frac, val, ours, real in rows:
            k = "<0.5x" if frac < 0.5 else ("0.5-1x" if frac < 1.0 else ">=1x")
            for kk in (k, "all"):
                bins[kk][0] += 1
                bins[kk][1] += val if ours else 0
                bins[kk][2] += val if real else 0
                bins[kk][3] += val
        print(bot_path)
        for k in ("<0.5x", "0.5-1x", ">=1x", "all"):
            n, o, r, c = bins[k]
            if n:
                print(f"  bet {k:7} spots {n:5}  build {o / n:+6.2f}/spot  real bots {r / n:+6.2f}  always call {c / n:+6.2f}  always fold +0.00")


if __name__ == "__main__":
    main()
