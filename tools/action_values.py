"""What was each postflop action actually worth, by situation? (every bot, every scraped game)

  python tools/action_values.py [--min 40]

Value of an action = hand result + chips already put in = chips gained from that moment on, relative to folding
(fold = 0). Situations: street x our hand class (PostFlopEvaluator) x size of the bet faced (or no bet).
Each row is checked on two random halves of the games; the sign has to agree to count.
"""
import argparse, glob, json, os, random, statistics, sys
from collections import defaultdict
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "macpoker-scaffold"))
from postflop_evaluator import PostFlopEvaluator
EV = PostFlopEvaluator(); US = "love-of-da-game"
TOP = {"Gladiators", "catherine", "merch where", "pocket-nuts", "wicked wings combo", "성진우", "tungbot", "MAC Projects Team Testing Bot 3"}
SHORT = {"NUT_HAND": "NUT", "STRONG_MADE": "STRONG", "MEDIUM_MADE": "MEDIUM", "STRONG_DRAW": "S-DRAW", "WEAK_DRAW": "W-DRAW", "TRASH": "TRASH"}
sz = lambda f: "small" if f < 0.4 else "medium" if f < 0.8 else "big"


def collect():
    rows = []
    games = [f for f in glob.glob(os.path.join(ROOT, "games", "*.json")) if not f.endswith(("index.json", "_decisions.json", "_calib.json", "game1.json"))]
    random.Random(3).shuffle(games)
    for gi, f in enumerate(games):
        g = json.load(open(f)); names = g.get("names")
        if not names: continue
        for h in g["hands"]:
            n = len(h["seat_map"]); sm = h["seat_map"]; ev = h["events"]
            bl = next(e for e in ev if e["type"] == "blinds")
            inv = [0] * n; inv[bl["sb_seat"]] += bl["sb"]; inv[bl["bb_seat"]] += bl["bb"]
            sbet = [0] * n; sbet[bl["sb_seat"]], sbet[bl["bb_seat"]] = bl["sb"], bl["bb"]
            street, cur, board, pot, alive = "preflop", bl["bb"], [], bl["sb"] + bl["bb"], set(range(n))
            for e in ev:
                if e["type"] == "street": street, board, cur, sbet = e["street"], e["board"], 0, [0] * n; continue
                if e["type"] != "action": continue
                s, k, a = e["seat"], e["action"], e["amount"]
                if street != "preflop":
                    faced = cur - sbet[s]
                    hc = SHORT[EV.evaluate(h["holes"][str(s)], board).hc.name]
                    frac = faced / max(pot - faced, 1) if faced > 0 else 0.0
                    grp = "us" if names[sm[s]] == US else "top" if names[sm[s]] in TOP else "rest"
                    rows.append((gi % 2, street, hc, sz(frac) if faced > 0 else "no bet", k, h["deltas_by_bot"][sm[s]] + inv[s], grp, len(alive) - 1))
                if k == "fold": alive.discard(s)
                if k == "raise": inv[s] += a - sbet[s]; sbet[s] = a; cur = a
                elif k == "call": inv[s] += a; sbet[s] += a
                pot = e.get("pot", pot)
    return rows


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--min", type=int, default=40); a = ap.parse_args()
    rows = collect(); print(f"{len(rows)} postflop decisions\n")
    assert all(abs(r[5]) < 1e-9 for r in rows if r[4] == "fold"), "fold value should be exactly 0"
    cell = defaultdict(list)
    for half, st, hc, size, k, v, grp, nopp in rows: cell[(st, hc, size, k, half)].append(v)
    cellall = defaultdict(list); ours = defaultdict(lambda: defaultdict(int))
    for half, st, hc, size, k, v, grp, nopp in rows:
        cellall[(st, hc, size, k)].append(v)
        if grp == "us": ours[(st, hc, size)][k] += 1
    print("FACING A BET: is calling (or raising) worth more than folding (0)?   mean chips from that moment on, halves agree = Y\n")
    print(f"{'street':<7}{'hand':<8}{'bet':<8}{'n call':>7}{'call value':>11} {'halves':>6}{'n raise':>9}{'raise value':>12} {'halves':>6}   {'we: fold/call/raise':>20}")
    out = []
    for (st, hc, size) in sorted({(r[1], r[2], r[3]) for r in rows if r[3] != "no bet"}, key=lambda x: (["flop", "turn", "river"].index(x[0]), x[1], x[2])):
        c = cellall.get((st, hc, size, "call"), []); r_ = cellall.get((st, hc, size, "raise"), [])
        if len(c) < a.min: continue
        def agree(k):
            h0 = cell.get((st, hc, size, k, 0), []); h1 = cell.get((st, hc, size, k, 1), [])
            return "Y" if len(h0) > 10 and len(h1) > 10 and (statistics.mean(h0) > 0) == (statistics.mean(h1) > 0) else "n"
        o = ours.get((st, hc, size), {}); ot = sum(o.values())
        wes = f"{o.get('fold',0)}/{o.get('call',0)}/{o.get('raise',0)}" if ot else "-"
        se = statistics.pstdev(c) / len(c) ** 0.5
        out.append((st, hc, size, len(c), statistics.mean(c), se, agree("call"), len(r_), statistics.mean(r_) if len(r_) >= 15 else None, agree("raise") if len(r_) >= 30 else "-", wes))
    for st, hc, size, nc, mc, se, ac, nr, mr, ar, wes in out:
        print(f"{st:<7}{hc:<8}{size:<8}{nc:>7}{mc:>+8.0f}+-{se:<3.0f}{ac:>5}{nr:>9}{(f'{mr:+.0f}' if mr is not None else '-'):>12} {ar:>6}   {wes:>20}")
    print("\nNOT FACING A BET: bet vs check (value = chips from that moment on)\n")
    print(f"{'street':<7}{'hand':<8}{'n check':>8}{'check value':>12}{'n bet':>8}{'bet value':>11} {'halves':>6}   {'we: check/bet':>14}")
    for st in ("flop", "turn", "river"):
        for hc in ("NUT", "STRONG", "MEDIUM", "S-DRAW", "W-DRAW", "TRASH"):
            ck = cellall.get((st, hc, "no bet", "check"), []); bt = cellall.get((st, hc, "no bet", "raise"), [])
            if len(ck) < a.min or len(bt) < a.min: continue
            def ag():
                try:
                    d = [statistics.mean(cell[(st, hc, "no bet", "raise", h)]) - statistics.mean(cell[(st, hc, "no bet", "check", h)]) for h in (0, 1)]
                    return "Y" if (d[0] > 0) == (d[1] > 0) else "n"
                except Exception: return "-"
            o = ours.get((st, hc, "no bet"), {}); wes = f"{o.get('check',0)}/{o.get('raise',0)}" if o else "-"
            print(f"{st:<7}{hc:<8}{len(ck):>8}{statistics.mean(ck):>+12.0f}{len(bt):>8}{statistics.mean(bt):>+11.0f} {ag():>6}   {wes:>14}")


if __name__ == "__main__":
    main()
