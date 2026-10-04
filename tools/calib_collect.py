"""Replay real ladder hands through an INSTRUMENTED copy of the bot and compare the bot's own equity estimate with the
TRUE equity vs the opponents' real cards, at every postflop decision facing a bet.

  python tools/make_instrumented.py /tmp/inst          # copy of macpoker-scaffold that records eq_r (never edits the repo)
  python tools/calib_collect.py /tmp/inst 150 4 5      # <instrumented dir> <games> <heroes per game> <processes> -> games/_calib.json
"""
import glob, json, os, random, sys, time
from multiprocessing import Pool
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INST = sys.argv[1]
sys.path.insert(0, os.path.join(ROOT, "tools")); sys.path.insert(0, INST)
from macpoker.sdk import BotSession, load_bot_from_file
from our_leaks import equity_at

MOD = {3: "flop", 4: "turn", 5: "river"}


def run(task):
    path, me = task
    g = json.load(open(path)); hands = g["hands"]; n = len(hands[0]["seat_map"])
    bot = load_bot_from_file(os.path.join(INST, "main.py")); sess = BotSession(bot)
    sess.handle({"type": "hello", "num_players": n, "num_hands": len(hands), "stack": 200, "blinds": [1, 2],
                 "time_bank_ms": 30000, "increment_ms": 100, "player": me})
    out = []
    for h in hands:
        sm = h["seat_map"]; seat = sm.index(me); players = list(sm)
        sess.handle({"type": "hand_start", "hand": h["hand"], "seat": seat, "button": 0, "stacks": [200] * n,
                     "hole": h["holes"][str(seat)], "players": players})
        stacks, contrib, sb_ = [200] * n, [0] * n, [0] * n; folded = [False] * n
        board, street, cur, min_inc, log = [], "preflop", 0, 2, []
        for ev in h["events"]:
            t = ev["type"]
            if t == "blinds":
                for s, amt in ((ev["sb_seat"], ev["sb"]), (ev["bb_seat"], ev["bb"])):
                    stacks[s] -= amt; contrib[s] += amt; sb_[s] += amt
                cur, min_inc = ev["bb"], ev["bb"]
            elif t == "street":
                street, board = ev["street"], ev["board"]; sb_, cur, min_inc = [0] * n, 0, 2
            elif t == "action" and ev["seat"] == seat and street != "preflop":
                to_call = min(cur - sb_[seat], stacks[seat])
                if to_call > 0:
                    max_to = sb_[seat] + stacks[seat]
                    view = {"type": "act", "hand": h["hand"], "seat": seat, "street": street, "board": board,
                            "hole": h["holes"][str(seat)], "pot": sum(contrib), "to_call": to_call,
                            "min_raise_to": min(cur + min_inc if cur else 2, max_to), "max_raise_to": max_to,
                            "can_raise": max_to > cur, "stacks": list(stacks), "street_bets": list(sb_),
                            "folded": list(folded), "button": 0, "history": [list(a) for a in log],
                            "clock_ms": 20000, "players": players}
                    m = sys.modules[MOD[len(board)]]; m.LAST_EQ[0] = None
                    act = sess.handle(view).to_wire()
                    eq_model = m.LAST_EQ[0]
                    if eq_model is not None:
                        opp = [h["holes"][str(o)] for o in range(n) if o != seat and not folded[o]]
                        out.append(dict(game=os.path.basename(path)[:-5], hero=me, hand=h["hand"], street=street,
                                        eq_model=eq_model, eq_true=equity_at(h["holes"][str(seat)], board, opp, 200),
                                        call=to_call, pot=sum(contrib), nopp=len(opp), frac=to_call / max(sum(contrib) - to_call, 1),
                                        model=act.get("action"), real=ev["action"], delta=h["deltas_by_bot"][me], contrib=contrib[seat],
                                        stack=stacks[seat]))
            if t == "action":
                s, k, a = ev["seat"], ev["action"], ev["amount"]
                if k == "fold": folded[s] = True
                elif k == "call": stacks[s] -= a; contrib[s] += a; sb_[s] += a
                elif k == "raise":
                    add = a - sb_[s]; stacks[s] -= add; contrib[s] += add
                    if a - cur >= min_inc: min_inc = a - cur
                    sb_[s], cur = a, max(cur, a)
                log.append([street, s, k, a])
            if t != "act": sess.handle({**ev, "players": players})
    return out


if __name__ == "__main__":
    ngames, per, jobs = int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
    r = random.Random(5)
    files = [f for f in sorted(glob.glob(ROOT + "/games/*.json")) if not f.endswith(("index.json", "_decisions.json", "game1.json"))]
    r.shuffle(files); tasks = []
    for f in files[:ngames]:
        n = len(json.load(open(f))["hands"][0]["seat_map"])
        for me in r.sample(range(n), min(per, n)): tasks.append((f, me))
    t0 = time.time()
    with Pool(jobs) as p: res = p.map(run, tasks, chunksize=1)
    D = [d for x in res for d in x]
    json.dump(D, open(ROOT + "/games/_calib.json", "w"))
    print(f"{len(D)} decisions from {len(tasks)} hero-games in {time.time()-t0:.0f}s")
