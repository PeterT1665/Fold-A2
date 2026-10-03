"""Same-table screen: is bot B better than bot A on identical cards?

Both bots sit at the same 8-seat table (as separate processes, like the
tournament), with test opponents, over N pinned seeds. Every seed plays one
game per seat rotation, so cards and positions are shared. Reports each
bot's chips per seed and how often B beat A.

  python tools/screen.py <dirA> <dirB>                    # e.g. a copy of main vs your change
  python tools/screen.py <dirA> <dirB> --seeds 10 --table tight

<dir> is a folder containing main.py (e.g. an extracted zip or a copy of
macpoker-scaffold). Copy the folders first: both sides need their own files.

Tables:
  stations : house:call, maniac_station, tag, lag, equity_bot, nit
  tight    : tag, lag, equity_bot, nit, shover, tag   (closest to the ladder)

Ship rule we use: B must beat A in about 7/10 seeds with a positive mean on
the tight table, and not lose clearly on the stations table.
"""

import argparse
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OPP = os.path.join(ROOT, "opponents")
TABLES = {
    "stations": ["house:call", f"{OPP}/maniac_station.py", f"{OPP}/tag.py", f"{OPP}/lag.py",
                 f"{OPP}/equity_bot.py", f"{OPP}/nit.py"],
    "tight": [f"{OPP}/tag.py", f"{OPP}/lag.py", f"{OPP}/equity_bot.py", f"{OPP}/nit.py",
              f"{OPP}/shover.py", f"{OPP}/tag.py"],
}


def play(a, b, table, seed):
    cmd = ["macpoker", "play", a, b, *TABLES[table], "--deals", "100", "--subprocess", "--seed", seed]
    out = subprocess.run(cmd, capture_output=True, text=True).stdout
    chips = {}
    for line in out.splitlines():
        m = re.match(r"^(\S+)\s+([+-]\d+)\s+\S+\s+(.*)$", line.strip())
        if not m:
            continue
        name, c, verdict = m.groups()
        if any(v in verdict for v in ("RTE", "TLE", "PV")):
            print(f"  !! {name} {verdict.strip()} (seed {seed})")
        if name in (a, b):
            chips[name] = int(c)
    return chips.get(a, 0), chips.get(b, 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--seeds", type=int, default=10)
    ap.add_argument("--table", choices=sorted(TABLES), default=None, help="default: both")
    ap.add_argument("--jobs", type=int, default=5)
    args = ap.parse_args()
    a = os.path.join(os.path.abspath(args.a), "main.py")
    b = os.path.join(os.path.abspath(args.b), "main.py")
    if a == b:
        sys.exit("A and B must be different folders")
    for table in ([args.table] if args.table else ["tight", "stations"]):
        seeds = [f"{table}{i}" for i in range(1, args.seeds + 1)]
        with ThreadPoolExecutor(args.jobs) as ex:
            res = list(ex.map(lambda s: play(a, b, table, s), seeds))
        diffs = [rb - ra for ra, rb in res]
        n = len(res)
        print(f"{table:9} A {sum(r[0] for r in res) / n:+7.0f}  B {sum(r[1] for r in res) / n:+7.0f}  "
              f"B better in {sum(d > 0 for d in diffs)}/{n} seeds, mean {sum(diffs) / n:+.0f}")


if __name__ == "__main__":
    main()
