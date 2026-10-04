"""Aggregate every scraped ladder game (games/*.json) into one row per bot.

  python tools/ladder_profiles.py [--min-games 4] [--me love-of-da-game]

chips/hand is raw chips per hand (bb = 2). Place is the finishing place in each game as a
fraction of the table (0 = best, 1 = worst), so 6- and 8-seat tables are comparable.
"""
import argparse, glob, json, os, sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyze_game import walk

ap = argparse.ArgumentParser()
ap.add_argument("--min-games", type=int, default=4)
ap.add_argument("--me", default="love-of-da-game")
ap.add_argument("--top", type=int, default=14)
a = ap.parse_args()

agg = defaultdict(Counter)
places = defaultdict(list)
for f in glob.glob(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "games", "*.json")):
    if f.endswith("index.json"):
        continue
    g = json.load(open(f))
    names = g.get("names")
    if not names:
        continue
    n = len(names)
    tot = [sum(h["deltas_by_bot"][b] for h in g["hands"]) for b in range(n)]
    for b, nm in enumerate(names):
        places[nm].append((1 + sum(1 for t in tot if t > tot[b]) - 1) / max(n - 1, 1))
        agg[nm]["games"] += 1
        agg[nm]["chips"] += tot[b]
        agg[nm]["hands"] += len(g["hands"])
    vp, pf, flop = Counter(), Counter(), Counter()
    sd = Counter()
    for h in g["hands"]:
        sm = h["seat_map"]
        v, p, fl = set(), set(), set()
        for e in h["events"]:
            if e.get("type") != "action":
                continue
            b = sm[e["seat"]]
            if e["street"] == "preflop":
                if e["action"] in ("call", "raise"): v.add(b)
                if e["action"] == "raise": p.add(b)
            else:
                fl.add(b)
        for b in v: agg[names[b]]["vpip"] += 1
        for b in p: agg[names[b]]["pfr"] += 1
        for b in fl: agg[names[b]]["flop_seen"] += 1
    for hand, b, street, k, frac, ffrac, pot, first in walk(g):
        c = agg[names[b]]
        if street != "preflop":
            c["post_" + k] += 1
            if k == "raise": c["bet_frac_sum"] += frac; c["bet_n"] += 1
            if ffrac > 0:
                c["facing"] += 1
                c["facing_fold"] += k == "fold"

rows = [(nm, c) for nm, c in agg.items() if c["games"] >= a.min_games or nm == a.me]
rows.sort(key=lambda t: sum(places[t[0]]) / len(places[t[0]]))
print(f"{'bot':<26}{'gms':>4}{'chips/hand':>11}{'avg place':>10}{'vpip':>6}{'pfr':>5}{'flop%':>6}{'bet+rs':>7}{'calls':>6}{'AF':>5}{'fold%':>6}{'sz':>5}")
for nm, c in rows[: a.top] + [r for r in rows[a.top:] if r[0] == a.me]:
    h = c["hands"]
    ag, ca = c["post_raise"], c["post_call"]
    print(f"{nm[:25]:<26}{c['games']:>4}{c['chips']/h:>11.2f}{sum(places[nm])/len(places[nm]):>10.2f}"
          f"{100*c['vpip']/h:>6.0f}{100*c['pfr']/h:>5.0f}{100*c['flop_seen']/h:>6.0f}{100*ag/h:>7.0f}{100*ca/h:>6.0f}"
          f"{ag/max(ca,1):>5.1f}{100*c['facing_fold']/max(c['facing'],1):>6.0f}"
          f"{(c['bet_frac_sum']/c['bet_n'] if c['bet_n'] else 0):>5.2f}")
print("\n(vpip/pfr/flop%/bet+rs/calls are per 100 hands; fold% = folds when facing a postflop bet; sz = avg bet/raise as a fraction of pot)")
