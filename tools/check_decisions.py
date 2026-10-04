"""Check each of our postflop fold/call decisions against the opponents' REAL hole cards.

  python tools/check_decisions.py [games/*.json]

For every time we faced a postflop bet: our equity against the hands of the players still in
(Monte Carlo over the rest of the board) versus the equity we needed (call / (pot + call)).
A fold with equity well above the need is a bad fold; a call well below it is a bad call.
All opponents still in the hand are counted, so with several opponents it is a bit harsh on calls.
"""
import glob, json, os, random, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from our_leaks import equity_at, ME   # same equity helper (tested against known matchups)


def main():
    files = sys.argv[1:] or sorted(glob.glob(os.path.join(ROOT, "games", "*.json")))
    rows = []
    for path in files:
        if path.endswith("index.json"):
            continue
        g = json.load(open(path))
        names = g.get("names")
        if names and ME in names: me = names.index(ME)
        elif path.endswith("game1.json"): me = 3
        else: continue
        for h in g["hands"]:
            n = len(h["seat_map"]); seat = h["seat_map"].index(me); hole = h["holes"][str(seat)]
            bl = next(e for e in h["events"] if e["type"] == "blinds")
            alive = set(range(n)); street, board = "preflop", []
            sbet = [0] * n; sbet[bl["sb_seat"]], sbet[bl["bb_seat"]] = bl["sb"], bl["bb"]; cur = bl["bb"]; pot = bl["sb"] + bl["bb"]
            for e in h["events"]:
                if e["type"] == "street":
                    street, board, cur, sbet = e["street"], e["board"], 0, [0] * n
                elif e["type"] == "action":
                    s, k, a = e["seat"], e["action"], e["amount"]
                    faced = cur - sbet[s]
                    if s == seat and street != "preflop" and faced > 0 and k in ("fold", "call"):
                        opp = [h["holes"][str(o)] for o in alive if o != seat]
                        need = faced / (pot + faced)
                        eq = equity_at(hole, board, opp, 250)
                        rows.append((os.path.basename(path)[:8], h["hand"], street, k, hole, board, faced, pot, need, eq,
                                     h["deltas_by_bot"][me], len(opp)))
                    if k == "fold": alive.discard(s)
                    if k == "raise": sbet[s], cur = a, a
                    elif k == "call": sbet[s] += a
                    pot = e.get("pot", pot)
    print(f"{len(rows)} postflop decisions facing a bet (folds and calls)\n")
    for kind in ("fold", "call"):
        r = [x for x in rows if x[3] == kind]
        if not r: continue
        wrong = [x for x in r if (kind == "fold" and x[9] > x[8] + 0.10) or (kind == "call" and x[9] < x[8] - 0.10)]
        print(f"{kind.upper()}S: {len(r)}   clearly wrong (equity off by more than 10 points): {len(wrong)}")
        for gname, hand, st, k, hole, board, faced, pot, need, eq, delta, nopp in sorted(wrong, key=lambda x: -abs(x[9] - x[8]))[:8]:
            print(f"   {gname} h{hand:<3} {st:<5} {''.join(hole)} on {' '.join(board):<17} vs {nopp} opp: needed {need:.0%}, had {eq:.0%}   to call {faced} into pot {pot}   hand result {delta:+.0f}")
        print()
    # expected cost of wrong decisions, in chips (rough: equity gap x pot after the call)
    cost_f = sum((x[9] - x[8]) * (x[7] + x[6]) for x in rows if x[3] == "fold" and x[9] > x[8])
    cost_c = sum((x[8] - x[9]) * (x[7] + x[6]) for x in rows if x[3] == "call" and x[9] < x[8])
    print(f"rough chips given away: folds that should have called {cost_f:.0f}, calls that should have folded {cost_c:.0f}")


if __name__ == "__main__":
    main()
