"""Replay the same real ladder hands through two builds; where they disagree on fold vs continue facing a postflop bet,
score the disagreement with the TRUE equity against the opponents' real cards.

  python tools/head2head.py <dirA with main.py> <dirB with main.py> <games> <heroes per game> <processes>
  e.g. python tools/head2head.py macpoker-scaffold /tmp/v4 120 3 5      (A = current, B = candidate; writes games/_h2h.json)

Only fold-vs-continue is scored (bets, raises, sizing and preflop are not), so it is one slice of a build, not a verdict.
"""
import glob, json, os, random, sys, time
from multiprocessing import Pool
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
A_DIR, B_DIR = sys.argv[1], sys.argv[2]
sys.path.insert(0, os.path.join(ROOT, "tools"))
from macpoker.sdk import BotSession, load_bot_from_file
from our_leaks import equity_at


def run(task):
    path, me = task
    g = json.load(open(path)); hands = g["hands"]; n = len(hands[0]["seat_map"])
    sess = {}
    for tag, d in (("A", A_DIR), ("B", B_DIR)):
        sys.path.insert(0, d)
        bot = load_bot_from_file(os.path.join(d, "main.py")); sess[tag] = BotSession(bot)
        sess[tag].handle({"type": "hello", "num_players": n, "num_hands": len(hands), "stack": 200, "blinds": [1, 2], "time_bank_ms": 30000, "increment_ms": 100, "player": me})
    out = []
    for h in hands:
        sm = h["seat_map"]; seat = sm.index(me); players = list(sm)
        for s_ in sess.values(): s_.handle({"type": "hand_start", "hand": h["hand"], "seat": seat, "button": 0, "stacks": [200] * n, "hole": h["holes"][str(seat)], "players": players})
        stacks, contrib, sb_ = [200] * n, [0] * n, [0] * n; folded = [False] * n
        board, street, cur, min_inc, log = [], "preflop", 0, 2, []
        for ev in h["events"]:
            t = ev["type"]
            if t == "blinds":
                for s, amt in ((ev["sb_seat"], ev["sb"]), (ev["bb_seat"], ev["bb"])): stacks[s] -= amt; contrib[s] += amt; sb_[s] += amt
                cur, min_inc = ev["bb"], ev["bb"]
            elif t == "street": street, board = ev["street"], ev["board"]; sb_, cur, min_inc = [0] * n, 0, 2
            elif t == "action" and ev["seat"] == seat and street != "preflop":
                to_call = min(cur - sb_[seat], stacks[seat])
                if to_call > 0:
                    max_to = sb_[seat] + stacks[seat]
                    view = {"type": "act", "hand": h["hand"], "seat": seat, "street": street, "board": board, "hole": h["holes"][str(seat)], "pot": sum(contrib),
                            "to_call": to_call, "min_raise_to": min(cur + min_inc if cur else 2, max_to), "max_raise_to": max_to, "can_raise": max_to > cur,
                            "stacks": list(stacks), "street_bets": list(sb_), "folded": list(folded), "button": 0, "history": [list(a) for a in log],
                            "clock_ms": 20000, "players": players}
                    acts = {tag: s_.handle(view).to_wire()["action"] for tag, s_ in sess.items()}
                    if (acts["A"] == "fold") != (acts["B"] == "fold"):
                        opp = [h["holes"][str(o)] for o in range(n) if o != seat and not folded[o]]
                        eq = equity_at(h["holes"][str(seat)], board, opp, 250)
                        out.append(dict(street=street, A=acts["A"], B=acts["B"], call=to_call, pot=sum(contrib), eq=eq, v=eq * (sum(contrib) + to_call) - to_call))
                    else: out.append(dict(street=street, A=acts["A"], B=acts["B"], same=True))
            if t == "action":
                s, k, a = ev["seat"], ev["action"], ev["amount"]
                if k == "fold": folded[s] = True
                elif k == "call": stacks[s] -= a; contrib[s] += a; sb_[s] += a
                elif k == "raise":
                    add = a - sb_[s]; stacks[s] -= add; contrib[s] += add
                    if a - cur >= min_inc: min_inc = a - cur
                    sb_[s], cur = a, max(cur, a)
                log.append([street, s, k, a])
            if t != "act":
                for s_ in sess.values(): s_.handle({**ev, "players": players})
    return out


if __name__ == "__main__":
    ngames, per, jobs = int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5])
    r = random.Random(8)
    files = [f for f in sorted(glob.glob(ROOT + "/games/j9*.json"))]; r.shuffle(files); tasks = []
    for f in files[:ngames]:
        n = len(json.load(open(f))["hands"][0]["seat_map"])
        for me in r.sample(range(n), min(per, n)): tasks.append((f, me))
    t0 = time.time()
    with Pool(jobs) as p: res = p.map(run, tasks, chunksize=1)
    D = [d for x in res for d in x]; json.dump(D, open(ROOT + "/games/_h2h.json", "w"))
    print(f"{len(D)} decisions from {len(tasks)} hero-games in {time.time()-t0:.0f}s")
