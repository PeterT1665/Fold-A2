"""Per-bot stats from a downloaded ladder game JSON (games/*.json; keep those out of git).

  python tools/analyze_game.py games/game1.json [--names BigBaller,RaiseYourEdge,...]

Bot index = the page header order. Seats rotate each hand; seat_map[seat] = bot.
Raise amounts in events are raise-to totals for the street.
"""
import argparse, json
from collections import Counter, defaultdict


def walk(game):
    """Yield (hand, bot, street, kind, frac_of_pot, faced_frac, pot_before, first_bet) per action."""
    for h in game["hands"]:
        sm = h["seat_map"]
        pot, street, sbet, cur, nbets = 3, "preflop", defaultdict(int), 0, 0
        sbet = defaultdict(int)
        for e in h["events"]:
            if e.get("type") == "blinds":
                sbet = defaultdict(int); sbet[e["sb_seat"]] = e["sb"]; sbet[e["bb_seat"]] = e["bb"]; cur = e["bb"]
                continue
            if e.get("type") != "action":
                continue
            if e["street"] != street:
                street, sbet, cur, nbets = e["street"], defaultdict(int), 0, 0
            s, k, a = e["seat"], e["action"], e["amount"]
            faced = cur - sbet[s]
            ffrac = faced / max(pot - faced, 1) if faced > 0 else 0.0
            frac = 0.0
            if k == "raise":
                frac = (a - sbet[s]) / max(pot, 1)
                first = cur == 0 or street == "preflop" and nbets == 0
                sbet[s], cur = a, a
                nbets += 1
            elif k == "call":
                sbet[s] += a
            yield h["hand"], sm[s], street, k, frac, ffrac, pot, (k == "raise" and nbets == 1)
            pot = e.get("pot", pot)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("game"); ap.add_argument("--names", default="")
    a = ap.parse_args()
    g = json.load(open(a.game))
    n = len(g["hands"][0]["seat_map"])
    names = a.names.split(",") if a.names else [f"bot{i}" for i in range(n)]
    st = defaultdict(Counter)
    sizes = defaultdict(list)
    seen = defaultdict(set)
    for hand, b, street, k, frac, ffrac, pot, first in walk(g):
        c = st[b]
        seen[b].add(hand)
        if street == "preflop":
            if k in ("call", "raise"): c["vpip_h"] += 0  # counted below
            c["pf_" + k] += 1
        else:
            c["post_" + k] += 1
            if k == "raise": sizes[b].append(frac)
            if ffrac > 0:
                c["facing"] += 1
                c["facing_fold"] += k == "fold"
                c["facing_raise"] += k == "raise"
    # vpip/pfr by hand
    vp, pf = Counter(), Counter()
    for h in g["hands"]:
        sm = h["seat_map"]; v, p = set(), set()
        for e in h["events"]:
            if e.get("type") == "action" and e["street"] == "preflop":
                if e["action"] in ("call", "raise"): v.add(sm[e["seat"]])
                if e["action"] == "raise": p.add(sm[e["seat"]])
        for b in v: vp[b] += 1
        for b in p: pf[b] += 1
    tot = [sum(h["deltas_by_bot"][b] for h in g["hands"]) for b in range(n)]
    print(f"{'bot':<16}{'chips':>6}{'vpip':>6}{'pfr':>5}{'bet/rs':>7}{'calls':>6}{'AF':>5}{'chk':>5}{'fold%vsBet':>11}{'reraise%':>9}{'avg sz':>7}")
    for b in sorted(range(n), key=lambda i: -tot[i]):
        c = st[b]
        ag = c["post_raise"]; ca = c["post_call"]
        fb = c["facing"]
        print(f"{names[b]:<16}{tot[b]:>6}{vp[b]:>6}{pf[b]:>5}{ag:>7}{ca:>6}{ag/max(ca,1):>5.1f}{c['post_check']:>5}"
              f"{100*c['facing_fold']/max(fb,1):>10.0f}%{100*c['facing_raise']/max(fb,1):>8.0f}%"
              f"{(sum(sizes[b])/len(sizes[b]) if sizes[b] else 0):>7.2f}")


if __name__ == "__main__":
    main()
