"""Detailed style profile of named ladder bots vs the whole field, from scraped games.

  python tools/bot_profile.py catherine tungbot love-of-da-game
"""
import glob, json, os, sys, statistics
from collections import Counter, defaultdict
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def profile(game_files, only=None):
    S = defaultdict(Counter); sizes = defaultdict(lambda: defaultdict(list)); games = defaultdict(list)
    for f in game_files:
        g = json.load(open(f)); names = g.get("names")
        if not names: continue
        n = len(names)
        tot = [sum(h["deltas_by_bot"][b] for h in g["hands"]) for b in range(n)]
        for b, nm in enumerate(names): games[nm].append((tot[b], sum(1 for t in tot if t > tot[b]) / (n - 1)))
        for h in g["hands"]:
            sm = h["seat_map"]; ev = h["events"]; end = ev[-1]
            bl = next(e for e in ev if e["type"] == "blinds")
            sbet = [0] * n; sbet[bl["sb_seat"]], sbet[bl["bb_seat"]] = bl["sb"], bl["bb"]
            street, cur, pot = "preflop", bl["bb"], bl["sb"] + bl["bb"]
            raises = limps = 0; lpr = None; acted_pre = set(); vp = set(); pf = set(); flop_seen = set()
            cbet_state = {}  # flop: seat -> handled
            first_flop_bet = None; flop_actors = set()
            for e in ev:
                if e["type"] == "street":
                    street, cur, sbet = e["street"], 0, [0] * n; continue
                if e["type"] != "action": continue
                s, k, a = e["seat"], e["action"], e["amount"]; b = sm[s]; nm = names[b]; c = S[nm]
                if street == "preflop":
                    first_time = s not in acted_pre; acted_pre.add(s)
                    if raises == 0 and limps == 0 and first_time and s != bl["bb_seat"]:
                        c["firstin_opp"] += 1; c["firstin_open"] += k == "raise"
                    if raises == 1 and first_time:
                        c["vs1raise_opp"] += 1; c["threebet"] += k == "raise"; c["fold_vs_raise"] += k == "fold"
                    if k in ("call", "raise"): vp.add(nm)
                    if k == "raise": pf.add(nm); raises += 1; lpr = s
                    elif k == "call": limps += 1 if raises == 0 else 0
                else:
                    flop_seen.add(nm)
                    if street == "flop":
                        if s == lpr and s not in flop_actors and cur == 0:
                            c["cbet_opp"] += 1; c["cbet"] += k == "raise"
                        if first_flop_bet is not None and s != first_flop_bet[0] and s not in flop_actors and cur > 0 and first_flop_bet[1] == lpr:
                            c["vs_cbet_opp"] += 1; c["fold_vs_cbet"] += k == "fold"
                        if k == "raise" and first_flop_bet is None: first_flop_bet = (s, s)
                        flop_actors.add(s)
                    faced = cur - sbet[s]
                    if k == "raise" and cur == 0: sizes[nm][street].append(a / max(pot, 1))
                    if faced > 0 and k in ("call", "fold", "raise"):
                        c["facing"] += 1; c["facing_fold"] += k == "fold"
                    c["post_" + k] += 1
                if k == "raise": sbet[s], cur = a, a
                elif k == "call": sbet[s] += a
                pot = e.get("pot", pot)
            for nm in vp: S[nm]["vpip"] += 1
            for nm in pf: S[nm]["pfr"] += 1
            for nm in flop_seen: S[nm]["flop_seen"] += 1
            rev = end.get("revealed", {})
            for sk in rev:
                nm = names[sm[int(sk)]]; S[nm]["showdown"] += 1; S[nm]["sd_won"] += h["deltas_by_bot"][sm[int(sk)]] > 0
            for sdx in range(n):
                S[names[sm[sdx]]]["hands"] += 1
    return S, sizes, games


def row(label, c, sz, gm):
    h = max(c["hands"], 1); pc = lambda a, b: 100 * c[a] / c[b] if c[b] else float("nan")
    avg = lambda st: statistics.mean(sz[st]) if sz and sz.get(st) else float("nan")
    return (f"{label:<17}{len(gm):>4}{statistics.median(x[0] for x in gm) if gm else 0:>+8.0f}{statistics.mean(x[1] for x in gm) if gm else 0:>7.2f}"
            f"{100*c['vpip']/h:>6.0f}{100*c['pfr']/h:>5.0f}{pc('firstin_open','firstin_opp'):>8.0f}{pc('threebet','vs1raise_opp'):>6.0f}"
            f"{pc('fold_vs_raise','vs1raise_opp'):>8.0f}{100*c['flop_seen']/h:>7.0f}{pc('cbet','cbet_opp'):>7.0f}{pc('fold_vs_cbet','vs_cbet_opp'):>8.0f}"
            f"{c['post_raise']/max(c['post_call'],1):>5.1f}{pc('facing_fold','facing'):>7.0f}{avg('flop'):>7.2f}{avg('turn'):>6.2f}{avg('river'):>6.2f}"
            f"{pc('showdown','flop_seen'):>7.0f}{pc('sd_won','showdown'):>6.0f}")


def main():
    want = sys.argv[1:] or ["love-of-da-game"]
    files = [f for f in glob.glob(os.path.join(ROOT, "games", "*.json")) if not f.endswith("index.json")]
    S, sizes, games = profile(files)
    field = Counter(); fsz = defaultdict(list); fgm = []
    for nm, c in S.items():
        if nm in want: continue
        field.update(c)
        for st, v in sizes[nm].items(): fsz[st] += v
    hdr = (f"{'':<17}{'gms':>4}{'median':>8}{'place':>7}{'vpip':>6}{'pfr':>5}{'open%':>8}{'3bet%':>6}{'fold2R':>8}{'flop%':>7}{'cbet%':>7}{'fold2cb':>8}"
           f"{'AF':>5}{'foldB%':>7}{'flopSz':>7}{'turn':>6}{'rvr':>6}{'SD%':>7}{'SDwin':>6}")
    print(hdr)
    for nm in want:
        if nm in S: print(row(nm[:16], S[nm], sizes[nm], games[nm]))
    print(row("rest of field", field, fsz, [x for nm, g in games.items() if nm not in want for x in g]))
    print("\nmedian = median chips per game;  place = avg finishing place (0 best, 0.5 middle);  open% = raise when first in (not BB);"
          "\n3bet% / fold2R = vs exactly one earlier raise;  cbet% = bet flop as last preflop raiser;  fold2cb = fold to that bet;"
          "\nAF = bets+raises per call postflop;  foldB% = fold when facing a postflop bet;  flopSz/turn/rvr = avg opening bet (x pot);"
          "\nSD% = share of flops seen that went to showdown;  SDwin = share of showdowns won")


if __name__ == "__main__":
    main()
