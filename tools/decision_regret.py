"""Decision quality of every bot, judged against the opponents' REAL hole cards.

  python tools/decision_regret.py collect [--jobs 5]   # slow part: equity of every postflop fold/call vs a bet
  python tools/decision_regret.py report               # per-bot regret table

For each postflop fold or call facing a bet: true equity vs the hands of the players still in (Monte Carlo over the
rest of the board), value of calling = eq*(pot+call) - call, value of folding = 0. Regret = chips lost versus the
better of the two. Raises are not scored (their value depends on later play). Saved to games/_decisions.json.
"""
import argparse, glob, json, os, random, sys
from multiprocessing import Pool
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "games", "_decisions.json")


def work(path):
    from our_leaks import equity_at
    g = json.load(open(path)); names = g.get("names")
    if not names: return []
    out = []
    for h in g["hands"]:
        n = len(h["seat_map"]); sm = h["seat_map"]
        bl = next(e for e in h["events"] if e["type"] == "blinds")
        alive = set(range(n)); street, board = "preflop", []; cur = 0; sbet = [0]*n; pot = bl["sb"] + bl["bb"]
        for e in h["events"]:
            if e["type"] == "street": street, board, cur, sbet = e["street"], e["board"], 0, [0]*n
            elif e["type"] == "action":
                s, k, a = e["seat"], e["action"], e["amount"]
                faced = cur - sbet[s]
                if street != "preflop" and faced > 0 and k in ("fold", "call"):
                    opp = [h["holes"][str(o)] for o in alive if o != s]
                    eq = equity_at(h["holes"][str(s)], board, opp, 200)
                    out.append(dict(game=os.path.basename(path)[:-5], hand=h["hand"], bot=names[sm[s]], street=street, k=k,
                                    call=faced, pot=pot, eq=eq, nopp=len(opp), frac=faced / max(pot - faced, 1),
                                    stack=200, hole=h["holes"][str(s)], board=list(board)))
                if k == "fold": alive.discard(s)
                if k == "raise": sbet[s], cur = a, a
                elif k == "call": sbet[s] += a
                pot = e.get("pot", pot)
    return out


def report():
    import statistics, collections
    D = json.load(open(OUT))
    by = collections.defaultdict(list)
    for d in D: by[d["bot"]].append(d)
    def regret(d):
        v = d["eq"] * (d["pot"] + d["call"]) - d["call"]          # value of calling
        return max(v, 0.0) if d["k"] == "fold" else max(-v, 0.0)
    rows = []
    for bot, L in by.items():
        if len(L) < 40: continue
        place = None
        rows.append((statistics.mean(regret(d) for d in L), bot, len(L)))
    print(f"{len(D)} scored decisions, {len(by)} bots.  Regret = average chips given away per fold/call decision (lower = better).\n")
    print(f"{'bot':<30}{'decisions':>10}{'regret/decision':>17}{'  of which folds too much':>26}{'calls too much':>16}")
    for r, bot, n in sorted(rows):
        L = by[bot]
        fo = sum(regret(d) for d in L if d["k"] == "fold") / len(L); ca = sum(regret(d) for d in L if d["k"] == "call") / len(L)
        print(f"{bot[:29]:<30}{n:>10}{r:>17.2f}{fo:>26.2f}{ca:>16.2f}")


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("cmd"); ap.add_argument("--jobs", type=int, default=5); a = ap.parse_args()
    if a.cmd == "collect":
        files = [f for f in sorted(glob.glob(os.path.join(ROOT, "games", "*.json"))) if not f.endswith(("index.json", "_decisions.json", "game1.json"))]
        with Pool(a.jobs) as p: res = p.map(work, files, chunksize=2)
        D = [d for r in res for d in r]; json.dump(D, open(OUT, "w")); print(f"saved {len(D)} decisions from {len(files)} games -> {OUT}")
    else:
        report()


if __name__ == "__main__":
    main()
