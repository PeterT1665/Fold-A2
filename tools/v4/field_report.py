"""Where do bots win their chips? One row per bot from games/*.json.

  python tools/v4/field_report.py [--min-games 15]

Columns (per 100-hand game unless noted):
  place    average finishing fraction (0 = always 1st, 1 = always last)
  chips    raw chips per game; adj = luck-adjusted (all-in pots before the river replaced by equity)
  nosd     chips from hands won/lost WITHOUT showdown (fold equity: steals, c-bets, bluffs, giving up)
  sd       chips from hands that reached showdown
  pre      chips from hands that ended preflop (steals, 3-bet wins, blinds lost)
  vpip/pfr preflop money-in / raise %, 3bet = re-raise % when facing one raise
  wtsd     went to showdown % of flops seen; wsd = won at showdown %
  agg      postflop bets+raises per call
  ftb      fold to a postflop bet %
"""
import argparse, glob, json, os, random, sys
from collections import defaultdict
from multiprocessing import Pool

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "v4"))
from cards7 import evaluate, parse


def game_rows(path):
    g = json.load(open(path))
    if not isinstance(g, dict) or "names" not in g or "result" not in g:
        return {}
    names = g["names"]
    ch = g["result"]["chips"]
    n = len(ch)
    out = {}
    for i, nm in enumerate(names):
        out[nm] = defaultdict(float)
        out[nm]["games"] = 1
        out[nm]["place"] = sum(1 for x in ch if x > ch[i]) / (n - 1)
        out[nm]["chips"] = ch[i]
        out[nm]["adj"] = ch[i]
    rng = random.Random(path)
    for h in g["hands"]:
        sm = h["seat_map"]
        k = len(sm)
        contrib = [0] * k; sb = [0] * k; folded = [False] * k
        board = []; last_board = []; street = "preflop"
        saw_flop = set(); vp = set(); pr = set(); faced3 = set(); did3 = set()
        nr = 0
        for e in h["events"]:
            t = e["type"]
            if t == "blinds":
                for s, a in ((e["sb_seat"], e["sb"]), (e["bb_seat"], e["bb"])):
                    contrib[s] += a; sb[s] += a
            elif t == "street":
                board = e["board"]; street = e["street"]; sb = [0] * k; nr = 0
                if street == "flop":
                    saw_flop = {x for x in range(k) if not folded[x]}
            elif t == "action":
                s = e["seat"]; a = e["action"]; amt = e["amount"]
                nm = names[sm[s]]
                tc = max(sb) - sb[s]
                last_board = list(board)
                R = out[nm]
                if street == "preflop":
                    if a in ("call", "raise"):
                        vp.add(s)
                    if a == "raise":
                        pr.add(s)
                    if nr == 1 and s not in faced3:
                        faced3.add(s); R["f3_opp"] += 1
                        if a == "raise":
                            R["f3"] += 1
                else:
                    if tc > 0:
                        R["ftb_opp"] += 1
                        if a == "fold":
                            R["ftb"] += 1
                    if a == "raise":
                        R["agg_br"] += 1
                    elif a == "call":
                        R["agg_c"] += 1
                if a == "fold":
                    folded[s] = True
                elif a == "call":
                    contrib[s] += amt; sb[s] += amt
                elif a == "raise":
                    contrib[s] += amt - sb[s]; sb[s] = amt; nr += 1
        end = [e for e in h["events"] if e["type"] == "hand_end"][0]
        live = [x for x in range(k) if not folded[x]]
        showdown = len(live) >= 2
        ended_pre = not end.get("board")
        for s in range(k):
            nm = names[sm[s]]; R = out[nm]; d = h["deltas_by_bot"][sm[s]]
            R["hands"] += 1
            R["vpip"] += s in vp; R["pfr"] += s in pr
            if s in saw_flop:
                R["flops"] += 1
                if showdown and s in live:
                    R["wtsd"] += 1
                    R["wsd"] += d > 0
            if showdown and s in live:
                R["sd"] += d
            else:
                R["nosd"] += d
            if ended_pre:
                R["pre"] += d
        # luck adjustment for all-ins before the river
        if showdown and max(contrib) >= 200 and len(last_board) < 5:
            bd = [parse(c) for c in last_board]
            hs = {x: [parse(c) for c in h["holes"][str(x)]] for x in live}
            dead = set(bd) | {c for v in hs.values() for c in v}
            deck = [c for c in range(52) if c not in dead]
            N = 600
            share = {x: 0.0 for x in live}
            for _ in range(N):
                r = bd + rng.sample(deck, 5 - len(bd))
                vals = {x: evaluate(hs[x] + r) for x in live}
                best = max(vals.values())
                w = [x for x in live if vals[x] == best]
                for x in w:
                    share[x] += 1 / len(w)
            pot = sum(contrib)
            for x in live:
                nm = names[sm[x]]
                exp = share[x] / N * pot - contrib[x]
                out[nm]["adj"] += exp - h["deltas_by_bot"][sm[x]]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-games", type=int, default=15)
    a = ap.parse_args()
    files = [f for f in glob.glob(os.path.join(ROOT, "games", "*.json")) if os.path.basename(f) not in ("index.json", "game1.json")]
    tot = defaultdict(lambda: defaultdict(float))
    with Pool(9) as p:
        for res in p.imap_unordered(game_rows, files):
            for nm, R in res.items():
                for k, v in R.items():
                    tot[nm][k] += v
    rows = []
    for nm, R in tot.items():
        G = R["games"]
        if G < a.min_games:
            continue
        H = max(R["hands"], 1); F = max(R["flops"], 1)
        rows.append((R["adj"] / G, nm, G, R["place"] / G, R["chips"] / G, R["nosd"] / G, R["sd"] / G, R["pre"] / G,
                     100 * R["vpip"] / H, 100 * R["pfr"] / H, 100 * R["f3"] / max(R["f3_opp"], 1),
                     100 * R["wtsd"] / F, 100 * R["wsd"] / max(R["wtsd"], 1),
                     R["agg_br"] / max(R["agg_c"], 1), 100 * R["ftb"] / max(R["ftb_opp"], 1)))
    rows.sort(reverse=True)
    print(f"{'bot':26} {'games':>5} {'place':>5} {'chips':>6} {'adj':>6} {'nosd':>6} {'sd':>6} {'pre':>6} "
          f"{'vpip':>5} {'pfr':>4} {'3bet':>4} {'wtsd':>4} {'wsd':>4} {'agg':>4} {'ftb':>4}")
    for r in rows:
        adj, nm, G, pl, chips, nosd, sd, pre, vpip, pfr, t3, wtsd, wsd, agg, ftb = r
        print(f"{nm[:26]:26} {G:5.0f} {pl:5.2f} {chips:+6.0f} {adj:+6.0f} {nosd:+6.0f} {sd:+6.0f} {pre:+6.0f} "
              f"{vpip:5.0f} {pfr:4.0f} {t3:4.0f} {wtsd:4.0f} {wsd:4.0f} {agg:4.1f} {ftb:4.0f}")


if __name__ == "__main__":
    main()
