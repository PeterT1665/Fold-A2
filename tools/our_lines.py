"""How do OUR lines do? Scores every postflop bet/raise and fold of ours against the opponents' real cards.

  python tools/our_lines.py [--worst 8]

1. Bets/raises by street and by our equity at that moment (vs the hands of players still in):
   bluff (<35%), middle (35-60%), value (>60%). Shows how often each took the pot at once, got called, got re-raised.
2. Folds: did we fold after betting earlier in the hand (gave up a bluff/semi-bluff), after only a preflop raise,
   or as a pure caller?
3. Our worst hands with our equity at every decision.
"""
import argparse, glob, json, os, sys
from collections import defaultdict
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from our_leaks import equity_at, ME


def our_games():
    out = []
    for f in sorted(glob.glob(os.path.join(ROOT, "games", "*.json"))):
        if f.endswith("index.json"): continue
        g = json.load(open(f))
        if f.endswith("game1.json"): out.append((f, g, 3))
        elif ME in g.get("names", []): out.append((f, g, g["names"].index(ME)))
    return out


def equity_vs_random(hole, board, k, samples=200):
    """Our equity against k RANDOM hands (what we could know at the time, no hindsight)."""
    from macpoker.cards import parse_card
    from macpoker.evaluator import evaluate
    import random
    r = random.Random(11)
    me = [parse_card(c) for c in hole]; b = [parse_card(c) for c in board]
    deck = [c for c in range(52) if c not in set(me) | set(b)]
    tot = 0.0
    for _ in range(samples):
        draw = r.sample(deck, 2 * k + 5 - len(b))
        run = b + draw[2 * k:]
        mine = evaluate(me + run)
        vals = [evaluate(draw[2 * i:2 * i + 2] + run) for i in range(k)]
        if mine >= max(vals): tot += 1.0 / (1 + sum(1 for v in vals if v == mine))
    return tot / samples


def bucket(eq): return "weak hand" if eq < 0.40 else "strong hand" if eq > 0.65 else "medium hand"


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--worst", type=int, default=8); a = ap.parse_args()
    raises, folds, worst = [], [], []
    for path, g, me in our_games():
        gname = os.path.basename(path)[:8]
        for h in g["hands"]:
            n = len(h["seat_map"]); seat = h["seat_map"].index(me); hole = h["holes"][str(seat)]
            delta = h["deltas_by_bot"][me]; ev = h["events"]
            bl = next(e for e in ev if e["type"] == "blinds")
            alive = set(range(n)); street, board = "preflop", []
            sbet = [0] * n; sbet[bl["sb_seat"]], sbet[bl["bb_seat"]] = bl["sb"], bl["bb"]
            cur, pot = bl["bb"], bl["sb"] + bl["bb"]
            pre_raised = post_raised = False
            decisions, my_raises = [], []
            for idx, e in enumerate(ev):
                if e["type"] == "street":
                    street, board, cur, sbet = e["street"], e["board"], 0, [0] * n
                    continue
                if e["type"] != "action": continue
                s, k, amt = e["seat"], e["action"], e["amount"]
                faced = cur - sbet[s]
                if s == seat and street != "preflop":
                    opp = [h["holes"][str(o)] for o in alive if o != seat]
                    eq = equity_at(hole, board, opp, 200) if opp else 1.0
                    eq_ex = equity_vs_random(hole, board, max(len(opp), 1), 150)
                    need = faced / (pot + faced) if faced > 0 else 0.0
                    decisions.append((street, k, amt, eq, need, pot))
                    if k == "raise":
                        # what happened after our bet/raise on this street?
                        later = [x for x in ev[idx + 1:] if x["type"] == "action" and x["street"] == street]
                        reraised = any(x["action"] == "raise" and x["seat"] != seat for x in later)
                        called = any(x["action"] == "call" and x["seat"] != seat for x in later)
                        my_raises.append(dict(street=street, eq=eq_ex, reraised=reraised, called=called, pot=pot, got_it=not (reraised or called)))
                        post_raised = True
                    if k == "fold":
                        kind = ("gave up after betting earlier" if post_raised else
                                "folded after only a preflop raise" if pre_raised else "pure caller")
                        folds.append((kind, street, delta, faced / max(pot - faced, 1) if faced else 0.0, eq, need))
                if s == seat and street == "preflop" and k == "raise": pre_raised = True
                if k == "fold": alive.discard(s)
                if k == "raise": sbet[s], cur = amt, amt
                elif k == "call": sbet[s] += amt
                pot = e.get("pot", pot)
            for r in my_raises: r["delta"] = delta; raises.append(r)
            if delta <= -40: worst.append((delta, gname, h["hand"], hole, ev[-1].get("board", []), decisions, {k: v for k, v in ev[-1].get("revealed", {}).items() if k != str(seat)}))
    print(f"{len(our_games())} games of ours\n")
    print("1) OUR POSTFLOP BETS/RAISES, by street and hand strength vs RANDOM hands (no hindsight): weak <40%, medium, strong >65%")
    print(f"   {'street':<7}{'type':<15}{'n':>4}{'took pot at once':>18}{'got called':>12}{'re-raised':>11}{'avg hand result':>17}")
    for st in ("flop", "turn", "river"):
        for b in ("weak hand", "medium hand", "strong hand"):
            r = [x for x in raises if x["street"] == st and bucket(x["eq"]) == b]
            if not r: continue
            print(f"   {st:<7}{b:<15}{len(r):>4}{100*sum(x['got_it'] for x in r)/len(r):>17.0f}%{100*sum(x['called'] and not x['reraised'] for x in r)/len(r):>11.0f}%{100*sum(x['reraised'] for x in r)/len(r):>10.0f}%{sum(x['delta'] for x in r)/len(r):>+17.0f}")
    print("\n2) OUR POSTFLOP FOLDS")
    d = defaultdict(lambda: [0, 0.0])
    for kind, st, delta, fr, eq, need in folds: d[kind][0] += 1; d[kind][1] += delta
    for kind, (c, s) in sorted(d.items(), key=lambda t: t[1][1]):
        print(f"   {kind:<34}{c:>4} folds  {s:+7.0f} chips  ({s/c:+.0f} each)")
    print(f"\n3) OUR {a.worst} WORST HANDS (street, action, our equity vs the opponents' real hands, equity we needed to call)")
    for delta, gname, hand, hole, board, dec, vil in sorted(worst)[:a.worst]:
        v = "; ".join(f"{''.join(c)}" for c in vil.values())
        print(f"   {gname} h{hand:<3} {delta:+5.0f}  {''.join(hole)}  board {' '.join(board)}  vs {v}")
        for st, k, amt, eq, need, pot in dec:
            print(f"        {st:<6}{k+(str(amt) if amt else ''):<11} equity {eq:>4.0%}" + (f"   needed {need:.0%}" if need else "") + f"   pot {pot}")


if __name__ == "__main__":
    main()
