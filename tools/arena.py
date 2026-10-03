"""Rank-based arena: mirrors the tournament scoring (5..1 pts per game by chips, ties share).

  python tools/arena.py me,tag,lag,equity,nit --deals 300 --seeds 4

Specs: `me` (macpoker-scaffold/main.py), `me_v0` (same, flop = shared default policy), an opponents/<name>.py basename, or house:<name>.
Prints average placement points, mean chips/game and win% per bot.
"""
import argparse, importlib.util, os, sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "opponents"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from macpoker import Bot
from macpoker.cli import resolve_bot
from dataclasses import replace
from multiprocessing import Pool
from macpoker.match import MatchConfig, MatchRunner
from macpoker.transport import InProcessTransport


def load(path, tag):
    spec = importlib.util.spec_from_file_location(tag, path)
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, os.path.dirname(path))
    spec.loader.exec_module(mod)
    subs = [v for v in vars(mod).values() if isinstance(v, type) and issubclass(v, Bot) and v is not Bot]
    return subs[0]


_factories = {}


def factory(spec):
    if spec in _factories:
        return _factories[spec]
    if spec.startswith("house:"):
        f = lambda: resolve_bot(spec)
    else:
        is_me = spec in ("me", "me_v0") or spec.startswith("me:")
        path = (os.path.join(ROOT, "macpoker-scaffold", "main.py") if is_me
                else os.path.join(ROOT, "opponents", spec + ".py"))
        if is_me:
            sys.path.insert(0, os.path.join(ROOT, "macpoker-scaffold"))
        cls = load(path, "bot_" + spec)
        f = cls
        if spec.startswith("me:"):
            import flop, range_model
            from variants import VARIANTS
            for key, val in VARIANTS[spec[3:]].items():
                mod, attr = key.split(".")
                if val == "BUCKETS":  # route the flop to the old bucket model
                    import flop_buckets
                    val = flop_buckets.decide
                setattr({"flop": flop, "range_model": range_model}[mod], attr, val)
        if spec == "me_v0":  # baseline: flop uses the shared default policy
            import flop, strategy
            flop.decide = strategy.default_postflop
    _factories[spec] = f
    return f


def points(chips):
    order = sorted(range(len(chips)), key=lambda i: -chips[i])
    pts = [0.0] * len(chips)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and chips[order[j + 1]] == chips[order[i]]:
            j += 1
        share = sum(len(chips) - k for k in range(i, j + 1)) / (j - i + 1)
        for k in range(i, j + 1):
            pts[order[k]] = share
        i = j + 1
    return pts


def run_game(task):
    specs, deals, seed, k = task
    cfg = MatchConfig(seats=len(specs), deals=deals, seed=f"arena{seed}", offset=k)
    return MatchRunner(cfg, [InProcessTransport(factory(sp)(), name=sp) for sp in specs]).run().chips


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("lineup")
    ap.add_argument("--deals", type=int, default=200)
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--jobs", type=int, default=8)
    a = ap.parse_args()
    specs = a.lineup.split(",")
    tasks = [(specs, a.deals, sd, k) for sd in range(a.seeds) for k in range(len(specs))]
    with Pool(a.jobs) as pool:
        results = pool.map(run_game, tasks, chunksize=1)
    pts = defaultdict(float); chips = defaultdict(float); wins = defaultdict(int); games = len(results)
    for c in results:
        p = points(c)
        for i in range(len(specs)):
            pts[i] += p[i]; chips[i] += c[i]
            wins[i] += c[i] == max(c)
    print(f"{games} games x {a.deals} deals, {len(specs)} seats")
    print(f"{'bot':<18}{'avg pts':>9}{'chips/game':>12}{'win%':>8}")
    for i, sp in sorted(enumerate(specs), key=lambda t: -pts[t[0]]):
        print(f"{sp:<18}{pts[i]/games:>9.2f}{chips[i]/games:>12.0f}{100*wins[i]/games:>7.0f}%")


if __name__ == "__main__":
    main()
