"""Offline calibration of the flop range model -> macpoker-scaffold/range_tables.py

For random flops of each texture it
  * buckets every possible hole-card combo with the real PostFlopEvaluator,
  * records bucket frequencies for each preflop line (base/open/call/3bet,
    approximated as Chen-score slices until real ranges are plugged in),
  * measures bucket-vs-bucket showdown equity by simulating turn+river,
  * records the mean evaluator equity of each bucket (for in-bucket nudging).

  python tools/calibrate.py --flops 250 --pairs 8 --jobs 9
"""
import argparse, itertools, os, random, sys
from collections import defaultdict
from multiprocessing import Pool

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SC = os.path.join(ROOT, "macpoker-scaffold")
sys.path.insert(0, SC)

from macpoker.cards import card_str, parse_card
from macpoker.evaluator import evaluate
from postflop_evaluator import HandClass as HC, PostFlopEvaluator
from preflop import chen

BUCKET = {HC.NUT_HAND: 0, HC.STRONG_MADE: 1, HC.MEDIUM_MADE: 2,
          HC.STRONG_DRAW: 3, HC.WEAK_DRAW: 4, HC.TRASH: 5}
TEXTURES = ["DRY", "WET", "MONOTONE", "PAIRED"]
LINES = ["base", "open", "call", "3bet"]
ALL = [card_str(c) for c in range(52)]
COMBOS = [(a, b) for a, b in itertools.combinations(ALL, 2)]


def line_membership():
    sc = sorted(chen(list(h)) for h in COMBOS)
    n = len(sc)
    pct = lambda p: sc[min(n - 1, int(p * n))]
    open_lo, call_lo, call_hi, bet3_lo = pct(0.70), pct(0.55), pct(0.88), pct(0.92)
    m = {}
    for h in COMBOS:
        s = chen(list(h))
        m[h] = {"base": True, "open": s >= open_lo, "call": call_lo <= s < call_hi,
                "3bet": s >= bet3_lo}
    return m


def work(args):
    tex_name, seed, nflops, pairs_per = args
    rng = random.Random(seed)
    ev = PostFlopEvaluator()
    mem = line_membership()
    freq = {l: [0.0] * 6 for l in LINES}
    eqsum, eqcnt = [0.0] * 6, [0] * 6
    msum = defaultdict(float)
    mcnt = defaultdict(int)
    reg = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0, 0])  # Sx,Sy,Sxx,Sxy,n (hero a vs villain b)
    done = 0
    while done < nflops:
        flop = rng.sample(ALL, 3)
        if ev.texture(flop).value != tex_name:
            continue
        done += 1
        used = set(flop)
        lists = [[] for _ in range(6)]
        heq = {}
        for h in COMBOS:
            if h[0] in used or h[1] in used:
                continue
            info = ev.evaluate(list(h), flop)
            b = BUCKET[info.hc]
            lists[b].append(h)
            heq[h] = info.eq
            eqsum[b] += info.eq
            eqcnt[b] += 1
            for l in LINES:
                if mem[h][l]:
                    freq[l][b] += 1
        for a in range(6):
            for b in range(a, 6):
                if not lists[a] or not lists[b]:
                    continue
                for _ in range(pairs_per):
                    h1, h2 = rng.choice(lists[a]), rng.choice(lists[b])
                    if set(h1) & set(h2):
                        continue
                    rest = [c for c in ALL if c not in used and c not in h1 and c not in h2]
                    wins = 0.0
                    for _r in range(2):
                        run = rng.sample(rest, 2)
                        board = [parse_card(c) for c in flop + run]
                        v1 = evaluate([parse_card(c) for c in h1] + board)
                        v2 = evaluate([parse_card(c) for c in h2] + board)
                        wins += 1.0 if v1 > v2 else (0.5 if v1 == v2 else 0.0)
                    y = wins / 2
                    msum[(a, b)] += y
                    mcnt[(a, b)] += 1
                    x = heq[h1]
                    r = reg[(a, b)]
                    r[0] += x; r[1] += y; r[2] += x * x; r[3] += x * y; r[4] += 1
    return tex_name, freq, eqsum, eqcnt, dict(msum), dict(mcnt), dict(reg)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--flops", type=int, default=200)
    ap.add_argument("--pairs", type=int, default=8)
    ap.add_argument("--jobs", type=int, default=9)
    a = ap.parse_args()
    chunks = 3
    tasks = [(t, 1000 * i + k, max(1, a.flops // chunks), a.pairs)
             for i, t in enumerate(TEXTURES) for k in range(chunks)]
    with Pool(a.jobs) as pool:
        res = pool.map(work, tasks, chunksize=1)
    agg = {t: {"freq": {l: [0.0] * 6 for l in LINES}, "eqs": [0.0] * 6, "eqc": [0] * 6,
               "ms": defaultdict(float), "mc": defaultdict(int), "rg": defaultdict(lambda: [0.0, 0.0, 0.0, 0.0, 0])} for t in TEXTURES}
    for t, freq, eqs, eqc, ms, mc, rg in res:
        g = agg[t]
        for l in LINES:
            for b in range(6):
                g["freq"][l][b] += freq[l][b]
        for b in range(6):
            g["eqs"][b] += eqs[b]; g["eqc"][b] += eqc[b]
        for k, v in ms.items():
            g["ms"][k] += v
        for k, v in mc.items():
            g["mc"][k] += v
        for k, v in rg.items():
            for i in range(5):
                g["rg"][k][i] += v[i]

    prior, match, nominal = {}, {}, [0.0] * 6
    slope, mx = {}, {}
    tot_s, tot_c = [0.0] * 6, [0] * 6
    for t in TEXTURES:
        g = agg[t]
        prior[t] = {}
        for l in LINES:
            w = [max(x, 0.5) for x in g["freq"][l]]
            s = sum(w)
            prior[t][l] = [round(x / s, 4) for x in w]
        M = [[0.5] * 6 for _ in range(6)]
        for (i, j), n in g["mc"].items():
            if i != j and n >= 5:
                M[i][j] = round(g["ms"][(i, j)] / n, 4)
                M[j][i] = round(1 - M[i][j], 4)
        match[t] = M
        SL = [[0.0] * 6 for _ in range(6)]
        MX = [[0.0] * 6 for _ in range(6)]
        for (i, j), (sx, sy, sxx, sxy, n) in g["rg"].items():
            if n < 30:
                continue
            mxv, myv = sx / n, sy / n
            var = sxx / n - mxv * mxv
            cov = sxy / n - mxv * myv
            sl = cov / var if var > 1e-6 else 0.0
            SL[i][j] = round(max(0.0, min(sl, 8.0)), 3)
            MX[i][j] = round(mxv, 4)
            M[i][j] = round(myv, 4)
        for i in range(6):
            for j in range(i + 1, 6):
                M[j][i] = round(1 - M[i][j], 4)
        slope[t], mx[t] = SL, MX
        for b in range(6):
            tot_s[b] += g["eqs"][b]; tot_c[b] += g["eqc"][b]
    nominal = [round(tot_s[b] / max(tot_c[b], 1), 3) for b in range(6)]

    out = os.path.join(SC, "range_tables.py")
    with open(out, "w") as f:
        f.write('"""GENERATED by tools/calibrate.py - do not edit by hand."""\n\n')
        f.write("PRIOR = %r\n\n" % prior)
        f.write("MATCH = %r\n\n" % match)
        f.write("NOMINAL_EQ = %r\n\n" % nominal)
        f.write("SLOPE = %r\n\n" % slope)
        f.write("MX = %r\n" % mx)
    print("wrote", out)
    for t in TEXTURES:
        print(t, "base prior", prior[t]["base"], "| 3bet", prior[t]["3bet"])
    print("nominal eq", nominal)
    for t in ("DRY", "WET"):
        print(t, "match:")
        for r in match[t]:
            print("  ", r)


if __name__ == "__main__":
    main()
