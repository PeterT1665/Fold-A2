"""Rank-based arena: mirrors the tournament scoring (5..1 pts per game by chips, ties share).

  python tools/arena.py me,tag,lag,equity,nit --deals 300 --seeds 4

Specs: `me` (macpoker-scaffold/main.py), an opponents/<name>.py basename, or house:<name>.
Prints average placement points, mean chips/game and win% per bot.
"""
import argparse, importlib.util, os, sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "opponents"))

from macpoker import Bot
from macpoker.cli import resolve_bot
from macpoker.match import MatchConfig, play_set
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
        path = (os.path.join(ROOT, "macpoker-scaffold", "main.py") if spec == "me"
                else os.path.join(ROOT, "opponents", spec + ".py"))
        if spec == "me":
            sys.path.insert(0, os.path.join(ROOT, "macpoker-scaffold"))
        cls = load(path, "bot_" + spec)
        f = cls
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("lineup")
    ap.add_argument("--deals", type=int, default=200)
    ap.add_argument("--seeds", type=int, default=3)
    a = ap.parse_args()
    specs = a.lineup.split(",")
    pts = defaultdict(float); chips = defaultdict(float); wins = defaultdict(int); games = 0
    for seed in range(a.seeds):
        cfg = MatchConfig(seats=len(specs), deals=a.deals, seed=f"arena{seed}")
        res = play_set(cfg, lambda k: [InProcessTransport(factory(s)(), name=s) for s in specs])
        for r in res:
            games += 1
            p = points(r.chips)
            for i, s in enumerate(specs):
                pts[i] += p[i]; chips[i] += r.chips[i]
                wins[i] += r.chips[i] == max(r.chips)
    print(f"{games} games x {a.deals} deals, {len(specs)} seats")
    print(f"{'bot':<18}{'avg pts':>9}{'chips/game':>12}{'win%':>8}")
    for i, s in sorted(enumerate(specs), key=lambda t: -pts[t[0]]):
        print(f"{s:<18}{pts[i]/games:>9.2f}{chips[i]/games:>12.0f}{100*wins[i]/games:>7.0f}%")


if __name__ == "__main__":
    main()
