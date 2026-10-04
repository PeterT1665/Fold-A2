"""Where do we lose chips? Analyse our own scraped ladder games.

  python tools/our_leaks.py                      # every games/*.json that has love-of-da-game
  python tools/our_leaks.py games/game1.json:3   # file:our_bot_index (for files without names)

Reports: chips by how each hand ended, the biggest losers, big-bet calls grouped by hand
strength, folds that gave up the winner, and all-ins compared with our equity at the time.
"""
import glob, json, os, random, sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "macpoker-scaffold"))
from macpoker.cards import parse_card
from macpoker.evaluator import evaluate

ME = "love-of-da-game"
CAT = ["high card", "pair", "two pair", "trips", "straight", "flush", "full house", "quads", "str flush"]
rng = random.Random(7)


def targets():
    out = []
    for a in sys.argv[1:] or []:
        f, i = a.rsplit(":", 1)
        out.append((f, int(i)))
    if out:
        return out
    for f in sorted(glob.glob(os.path.join(ROOT, "games", "*.json"))):
        if f.endswith("index.json"):
            continue
        g = json.load(open(f))
        if ME in g.get("names", []):
            out.append((f, g["names"].index(ME)))
    g1 = os.path.join(ROOT, "games", "game1.json")
    if os.path.exists(g1) and not any(f == g1 for f, _ in out):
        out.append((g1, 3))
    return out


def equity_at(hole, board, opp_holes, samples=400):
    """Our share of the pot if the hand were run out from `board` against these hole cards."""
    me = [parse_card(c) for c in hole]
    b = [parse_card(c) for c in board]
    opp = [[parse_card(c) for c in h] for h in opp_holes]
    used = set(me) | set(b) | {c for o in opp for c in o}
    deck = [c for c in range(52) if c not in used]
    need = 5 - len(b)
    tot = 0.0
    for _ in range(samples):
        run = b + rng.sample(deck, need)
        mine = evaluate(me + run)
        vals = [evaluate(o + run) for o in opp]
        if mine >= max(vals):
            tot += 1.0 / (1 + sum(1 for v in vals if v == mine))
    return tot / samples


def analyse(path, me):
    g = json.load(open(path))
    H = g["hands"]
    n = len(H[0]["seat_map"])
    ends = defaultdict(lambda: [0, 0.0])
    rows, calls, folds, allins, gave_up = [], defaultdict(lambda: [0, 0.0]), [], [], []
    for h in H:
        seat = h["seat_map"].index(me)
        hole = h["holes"][str(seat)]
        delta = h["deltas_by_bot"][me]
        ev = h["events"]
        bl = next(e for e in ev if e["type"] == "blinds")
        contrib = [0] * n
        contrib[bl["sb_seat"]], contrib[bl["bb_seat"]] = bl["sb"], bl["bb"]
        street_bet = [0] * n
        street_bet[bl["sb_seat"]], street_bet[bl["bb_seat"]] = bl["sb"], bl["bb"]
        cur, street, board, pot = bl["bb"], "preflop", [], bl["sb"] + bl["bb"]
        line, folded_at, my_all = [], None, None
        end = ev[-1]
        for e in ev:
            if e["type"] == "street":
                street, board, cur, street_bet = e["street"], e["board"], 0, [0] * n
            elif e["type"] == "action":
                s, k, a = e["seat"], e["action"], e["amount"]
                faced = cur - street_bet[s]
                if s == seat:
                    line.append(f"{street[0]}:{k}{a if a else ''}")
                    if k == "fold":
                        folded_at = street
                        if faced > 0 and street != "preflop":
                            folds.append((h["hand"], street, hole, list(board), faced / max(pot - faced, 1)))
                    if k == "call" and street in ("turn", "river") and faced / max(pot - faced, 1) > 0.5:
                        full = [parse_card(c) for c in hole + board]
                        cat = evaluate(full)[0]
                        key = "two pair or better" if cat >= 2 else "one pair or less"
                        calls[key][0] += 1
                        calls[key][1] += delta
                if k == "raise":
                    add = a - street_bet[s]; contrib[s] += add; street_bet[s] = a; cur = a
                elif k == "call":
                    contrib[s] += a; street_bet[s] += a
                if s == seat and contrib[seat] >= 200 and my_all is None:
                    my_all = list(board)
                pot = e.get("pot", pot)
        revealed = end.get("revealed", {})
        invested = contrib[seat]
        if invested <= bl["bb"] and folded_at == "preflop":
            cat_ = "folded preflop (blind cost only)"
        elif folded_at:
            cat_ = "folded preflop after putting chips in" if folded_at == "preflop" else f"folded on the {folded_at}"
        elif str(seat) in revealed:
            cat_ = "went to showdown"
        elif delta > 0:
            cat_ = "won without showdown"
        else:
            cat_ = "other"
        ends[cat_][0] += 1
        ends[cat_][1] += delta
        if delta <= -15:
            villains = {k: v for k, v in revealed.items() if k != str(seat)}
            rows.append((delta, h["hand"], hole, end.get("board", []), " ".join(line), villains))
        if my_all is not None and str(seat) in revealed and len(revealed) >= 2 and len(my_all) < 5:
            opp = [v for k, v in revealed.items() if k != str(seat)]
            pot_total = sum(p["amount"] for p in end.get("pots", []))
            eq = equity_at(hole, my_all, opp)
            allins.append((h["hand"], hole, my_all, eq, delta, eq * pot_total - 200))
        # did a later fold give up the winner? (only when the board ran out to a showdown)
        if folded_at and folded_at != "preflop" and len(end.get("board", [])) == 5 and revealed:
            ours = evaluate([parse_card(c) for c in hole + end["board"]])
            best = max(evaluate([parse_card(c) for c in v + end["board"]]) for v in revealed.values())
            pot_end = sum(p["amount"] for p in end.get("pots", []))
            gave_up.append((h["hand"], hole, ours >= best, pot_end, -delta))
    return n, ends, sorted(rows), calls, folds, allins, H, gave_up


def main():
    tot_end, tot_calls = defaultdict(lambda: [0, 0.0]), defaultdict(lambda: [0, 0.0])
    all_rows, all_allins, all_fold, hands = [], [], [], 0
    for path, me in targets():
        n, ends, rows, calls, folds, allins, H, gave_up = analyse(path, me)
        all_fold += gave_up
        hands += len(H)
        for k, v in ends.items():
            tot_end[k][0] += v[0]; tot_end[k][1] += v[1]
        for k, v in calls.items():
            tot_calls[k][0] += v[0]; tot_calls[k][1] += v[1]
        all_rows += [(os.path.basename(path)[:8],) + r for r in rows]
        all_allins += [(os.path.basename(path)[:8],) + r for r in allins]
        print(f"{os.path.basename(path)[:14]:<15} {len(H)} hands, {n} seats, our bot index {me}, chips {sum(h['deltas_by_bot'][me] for h in H):+.0f}")
    print(f"\n{hands} hands total. Chips by how each hand ended:")
    for k, (c, s) in sorted(tot_end.items(), key=lambda t: t[1][1]):
        print(f"  {k:<34}{c:>4} hands  {s:+7.0f} chips  ({s / max(c, 1):+.1f}/hand)")
    print("\nCalls of a bet > half pot on turn/river, by our hand (result = whole hand):")
    for k, (c, s) in tot_calls.items():
        print(f"  {k:<22}{c:>3} calls  {s / max(c, 1):+.0f} chips/call")
    if not tot_calls: print("  (none)")
    print("\nBiggest losing hands (>= 15 chips):")
    for gname, d, hand, hole, board, line, vil in sorted(all_rows)[:10]:
        v = "; ".join(f"seat{k}:{''.join(c)}" for k, c in vil.items())
        print(f"  {gname} h{hand:<3} {d:+4.0f}  {''.join(hole)} | {' '.join(board)}  [{line}]  vs {v}")
    print("\nFolds after the flop where the hand ran out to a showdown (could we have won?):")
    for hand, hole, wins, pot_end, lost in all_fold:
        print(f"  h{hand:<3} {''.join(hole)}  our hand would have {'WON' if wins else 'lost'}  (pot {pot_end}, we put in {lost:.0f})")
    if not all_fold: print("  (none)")
    print("\nAll-ins before the river, our equity at that moment vs the result:")
    for gname, hand, hole, bd, eq, delta, exp in all_allins:
        print(f"  {gname} h{hand:<3} {''.join(hole)} on {' '.join(bd) or 'preflop':<14} equity {eq:.0%}  result {delta:+4.0f}  (expected {exp:+.0f})")
    if not all_allins: print("  (none)")


if __name__ == "__main__":
    main()
