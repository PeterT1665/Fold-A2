"""Replacement test against ladder clones, tournament-shaped.

  python tools/v4/arena.py v4/main.py macpoker-scaffold/main.py --tables 40

Each table: 4 clones of real ladder bots (random from the pool) + one candidate, 100 hands,
played as a full duplicate set (5 games, every seat). Every candidate plays the exact same
tables, decks and clone random seeds, so the per-table difference is paired.
Reports placement points per game (5 = 1st .. 1 = last, ties shared, as in the tournament),
chips per game, and how often candidate B out-placed candidate A.
"""
import argparse, importlib.util, json, os, random, sys
from multiprocessing import Pool

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "opponents"))
from macpoker import Bot
from macpoker.match import MatchConfig, MatchRunner
from macpoker.transport import InProcessTransport

_CACHE = {}


def load(path):
    if path in _CACHE:
        return _CACHE[path]
    d = os.path.dirname(os.path.abspath(path))
    sys.path.insert(0, d)
    spec = importlib.util.spec_from_file_location("cand_" + str(len(_CACHE)), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    subs = [v for v in vars(mod).values() if isinstance(v, type) and issubclass(v, Bot) and v is not Bot and v.__module__ == mod.__name__]
    _CACHE[path] = subs[0]
    sys.path.remove(d)
    return subs[0]


def places(chips):
    n = len(chips)
    pts = []
    for c in chips:
        above = sum(1 for x in chips if x > c)
        ties = sum(1 for x in chips if x == c)
        # positions above+1 .. above+ties share points n-above .. n-above-ties+1
        pts.append(sum(n - above - i for i in range(ties)) / ties)
    return pts


def make_opp(o, seed):
    from clone import CloneBot
    if o.startswith("file:"):
        return load(os.path.join(ROOT, "opponents", o[5:] + ".py"))()
    if o.startswith("house:"):
        from macpoker.cli import resolve_bot
        return resolve_bot(o)
    return CloneBot(o, seed)


def run_table(args):
    cand, opps, seed, deals, seats = args
    from clone import CloneBot
    Cand = load(cand)
    tot_pts = tot_chips = 0.0
    firsts = 0
    for k in range(seats):
        bots = [Cand()] + [make_opp(o, f"{seed}:{k}:{i}") for i, o in enumerate(opps)]
        cfg = MatchConfig(seats=seats, deals=deals, offset=k, seed=seed)
        res = MatchRunner(cfg, [InProcessTransport(b) for b in bots]).run()
        if res.verdicts[0] != "OK":
            print("!!", cand, res.verdicts[0], seed, k, file=sys.stderr)
        p = places(res.chips)
        tot_pts += p[0]; tot_chips += res.chips[0]; firsts += p[0] == seats
    return tot_pts / seats, tot_chips / seats, firsts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cands", nargs="+")
    ap.add_argument("--tables", type=int, default=30)
    ap.add_argument("--deals", type=int, default=100)
    ap.add_argument("--seats", type=int, default=5)
    ap.add_argument("--min-hands", type=int, default=1500, help="clone pool: bots with at least this many ladder hands")
    ap.add_argument("--pool", default="", help="comma list of bot names instead")
    ap.add_argument("--seed", default="s")
    ap.add_argument("--jobs", type=int, default=8)
    a = ap.parse_args()
    data = json.load(open(os.path.join(ROOT, "opponents", "clone_data.json")))
    if a.pool:
        pool = a.pool.split(",")
    else:
        pool = sorted(n for n, h in data["hands"].items() if h >= a.min_hands and n != "love-of-da-game")
    rng = random.Random(a.seed)
    tables = [(rng.sample(pool, a.seats - 1), f"{a.seed}{i}") for i in range(a.tables)]
    jobs = [(c, opps, sd, a.deals, a.seats) for c in a.cands for opps, sd in tables]
    with Pool(a.jobs, maxtasksperchild=1) as p:
        res = p.map(run_table, jobs, chunksize=1)
    T = a.tables
    per = {c: res[i * T:(i + 1) * T] for i, c in enumerate(a.cands)}
    print(f"pool {len(pool)} bots, {T} tables x {a.seats} games x {a.deals} hands")
    for c in a.cands:
        r = per[c]
        print(f"{c:40} pts/game {sum(x[0] for x in r) / T:.3f}  chips/game {sum(x[1] for x in r) / T:+7.1f}  1sts {sum(x[2] for x in r)}/{T * a.seats}")
    for cb in a.cands[1:]:
        A, B = per[a.cands[0]], per[cb]
        d = [b[0] - x[0] for x, b in zip(A, B)]
        m = sum(d) / T
        sd = (sum((x - m) ** 2 for x in d) / max(T - 1, 1)) ** 0.5 / T ** 0.5
        print(f"{cb}: B - A placement pts/game {m:+.3f} +/- {sd:.3f}; B better on {sum(x > 0 for x in d)}/{T} tables, worse on {sum(x < 0 for x in d)}")


if __name__ == "__main__":
    main()
