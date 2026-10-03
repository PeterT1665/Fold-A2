"""Flop (3 board cards) decisions.

For every hole-card combo an opponent could hold we estimate our share of the
pot (ties split) over sampled turn+river cards. Combos are weighted by the
bucket range from range_model.py: a flat start over the combos the board
allows, tilted by the opponent's preflop line, then updated by every flop
action. Then pick the best-EV action:

  not facing a bet : check  vs  bet {25..100% pot}   (size chosen by EV, with
                     near-ties randomised so the size does not give away strength)
  facing a bet     : fold   vs  call  vs  value-raise / semi-bluff raise

If anything fails, or the clock is low, flop_buckets.py (bucket model) decides.
"""

from __future__ import annotations

import time

import flop_buckets
import range_model as rm
from opponent_tracker import OpponentClass as OC
from postflop_evaluator import RANKS, SUITS, parse
from river import _DECK, rank7

# tunable knobs (tools/variants.py overrides these for A/B runs)
BET_SIZES = (0.25, 0.33, 0.5, 0.66, 0.85, 1.0)
RAISE_SIZES = (0.66, 1.0, 1.5)
BLUFF_BET_P = (0.55, 0.4, 0.3)  # bluff-bet freq: pfr in position / pfr out of position / not pfr
BLUFF_MULTIWAY = 0.4  # multiplier when 2+ opponents
BLUFF_RAISE_P = 0.3
BET_MARGIN = 0.02  # EV edge (x pot) a bet needs over checking
RAISE_MARGIN = 0.06
SIZE_TOL = 0.0  # 0 = always best EV (0.15 lost 7/10 seeds, -906 chips in Chi's test); >0 picks randomly among bet sizes within SIZE_TOL x pot of the best EV
OOP_REALISE = 0.92
RUNOUTS = 16  # shared random turn+river pairs used for every combo
PER_BUCKET = 36  # opponent combos sampled per bucket
# range_model's bet/raise likelihoods were tuned for a bucket prior; over real hand
# combinations air is ~60% of hands, so scale how often weak buckets bet/raise
# (NUT, STR, MED, SDR, WDR, AIR). Applied only to bets and raises, only on the flop.
BET_SCALE = (1.0, 1.0, 0.8, 1.0, 0.5, 0.25)
MIN_CLOCK_MS = 4000  # below this, use the cheap bucket model

_cache: dict = {}


def _combos(state, ctx):
    """(my bucket, [(share, bucket, multiplicity)]) for sampled opponent combos.
    Every combo is bucketed; up to PER_BUCKET per bucket get a sampled equity and
    stand in (multiplicity = bucket size / sampled) for the rest. Cached per hand."""
    key = (tuple(state.hole), tuple(state.board))
    hit = _cache.get(key)
    if hit is not None:
        return hit
    hole, board = parse(state.hole), parse(state.board)
    used = set(hole) | set(board)
    deck = [c for c in _DECK if c not in used]
    rng = ctx.rng
    ev = ctx.evaluator
    by_b = [[] for _ in range(6)]
    for i in range(len(deck)):
        for j in range(i + 1, len(deck)):
            a, b = deck[i], deck[j]
            names = [RANKS[a[0]] + SUITS[a[1]], RANKS[b[0]] + SUITS[b[1]]]
            by_b[rm.HC2B[ev.evaluate(names, state.board).hc]].append((a, b))
    runs = []
    for _ in range(RUNOUTS):
        t, r = rng.sample(deck, 2)
        runs.append((t, r, rank7(hole + board + [t, r])))
    out = []
    for b, lst in enumerate(by_b):
        if not lst:
            continue
        pick = lst if len(lst) <= PER_BUCKET else rng.sample(lst, PER_BUCKET)
        mult = len(lst) / len(pick)
        for a, c in pick:
            tot = n = 0.0
            for t, r, mine in runs:
                if t == a or t == c or r == a or r == c:
                    continue
                v = rank7([a, c] + board + [t, r])
                tot += 1.0 if mine > v else 0.5 if mine == v else 0.0
                n += 1
            out.append((tot / n if n else 0.5, b, mult))
    res = (rm.HC2B[ev.evaluate(state.hole, state.board).hc], out)
    _cache.clear()
    _cache[key] = res
    return res


def _weights(w, combos):
    cw = [w[b] * m for _, b, m in combos]
    tot = sum(cw)
    return [x / tot for x in cw] if tot > 0 else [1.0 / len(combos)] * len(combos)


def _equity(combos, cw, fold=None):
    """(P(fold), our pot share vs the combos that continue)."""
    num = den = 0.0
    for (share, b, _), w in zip(combos, cw):
        if fold is not None:
            w *= 1.0 - fold[b]
        if w <= 0:
            continue
        den += w
        num += w * share
    if den <= 1e-12:
        return 1.0, 0.0
    return 1.0 - den, num / den


def _ranges(state, ctx, opps, ip_of):
    """Bucket likelihood per opponent: flat start tilted by preflop line, then flop actions."""
    lines, raises = {}, 0
    for st, s, k, _ in state.history:
        if st == "preflop":
            if k == "raise":
                lines[s] = "3bet" if raises else "open"
                raises += 1
            elif k == "call" and s not in lines:
                lines[s] = "call"
    cls = {s: ctx.tracker.classify(state.player_at(s)) for s in opps}
    ranges = {s: rm.normalize(list(rm._LINE[lines.get(s, "base")])) for s in opps}
    pot, sb, cur = state.pot - sum(state.street_bets), {}, 0
    for st, s, k, a in state.history:
        if st != "flop":
            continue
        kind, frac = None, 0.0
        if k == "raise":
            add = a - sb.get(s, 0)
            kind, frac = ("bet" if cur == 0 else "raise"), add / max(pot, 1)
            pot += add
            sb[s], cur = a, a
        elif k == "call":
            kind, frac = "call", a / max(pot - a, 1)
            pot += a
            sb[s] = sb.get(s, 0) + a
        elif k == "check":
            kind = "check"
        if kind and s in ranges:
            w = rm.update(ranges[s], kind, frac, ip_of(s), cls[s])
            if kind in ("bet", "raise"):
                w = rm.normalize([x * m for x, m in zip(w, BET_SCALE)])
            ranges[s] = w
    return ranges, cls


def decide(state, ctx):
    if len(state.board) != 3 or 0 < state.clock_ms < MIN_CLOCK_MS:
        return flop_buckets.decide(state, ctx)
    try:
        return _decide(state, ctx)
    except Exception as e:  # never let the combo model take the bot down
        print(f"flop fallback: {e!r}")
        return flop_buckets.decide(state, ctx)


def _decide(state, ctx):
    n, me = state.num_players, state.seat
    first = (state.button + 1) % n
    order = lambda s: (s - first) % n
    opps = [s for s in range(n) if not state.folded[s] and s != me]
    if not opps:
        return state.check() if state.to_call == 0 else state.call()
    live = [s for s in opps if state.stacks[s] > 0]
    ip = all(order(s) < order(me) for s in live)
    alive_acting = [s for s in range(n) if not state.folded[s] and state.stacks[s] > 0]
    last = max(alive_acting, key=order) if alive_acting else me
    ip_of = lambda s: s == last
    R = 1.0 if ip else OOP_REALISE

    info = ctx.evaluator.evaluate(state.hole, state.board)
    my_b, combos = _combos(state, ctx)
    ranges, cls = _ranges(state, ctx, opps, ip_of)
    cws = {s: _weights(ranges[s], combos) for s in opps}

    P, c = state.pot, state.to_call
    stack, mine = state.my_stack, state.street_bets[me]
    rng = ctx.rng
    pfr = any(st == "preflop" and k == "raise" and s == me for st, s, k, _ in state.history)

    eq_r = 1.0
    for s in opps:
        eq_r *= _equity(combos, cws[s])[1]

    def called(a):
        """(P(everyone folds), equity vs the hands that call) for adding `a`."""
        size = a / max(P, 1)
        f, eq = 1.0, 1.0
        for s in opps:
            if state.stacks[s] == 0:
                pf, e = 0.0, _equity(combos, cws[s])[1]
            else:
                pf, e = _equity(combos, cws[s], rm.fold_probs(size, cls[s]))
            f *= pf
            eq *= e
        return f, eq

    def commit(a):
        return stack if stack - a < 0.4 * (P + 2 * a) else a

    drawing = my_b in (rm.SDR, rm.WDR)
    strong = (my_b == rm.NUT or (my_b == rm.STR and info.top_tier)) and eq_r >= 0.7

    # ------------------------------------------------------------ no bet to face
    if c == 0:
        if not state.can_raise or not live:
            return state.check()
        oa_behind = any(cls[s] is OC.OVER_AGGRESSIVE and order(s) > order(me) for s in live)
        if oa_behind and strong and rng.random() < 0.7:
            return state.check()  # let the maniac bet, then raise
        ev_check = R * eq_r * P
        opts = []
        for frac in BET_SIZES:
            a = commit(min(frac * P, stack))
            f, eq_c = called(a)
            if eq_c < 0.5 and frac > 0.66:
                continue  # no overbet bluffs / thin overbets
            ev = f * P + (1 - f) * (R * eq_c * (P + 2 * a) - a)
            if ev > ev_check + BET_MARGIN * P:
                opts.append((ev, a, eq_c))
        if not opts:
            return state.check()
        top = max(o[0] for o in opts)
        _, best_a, best_eq = rng.choice([o for o in opts if o[0] >= top - SIZE_TOL * P])
        if best_eq < 0.42 and not drawing:  # profit comes only from folds: gate bluffs
            p = (BLUFF_BET_P[0] if (pfr and ip) else BLUFF_BET_P[1] if pfr else BLUFF_BET_P[2])
            if len(opps) > 1:
                p *= BLUFF_MULTIWAY
            if rng.random() > p:
                return state.check()
        if best_a >= stack:
            return state.all_in()
        return state.raise_to(int(max(state.min_raise_to, min(mine + round(best_a), state.max_raise_to))))

    # ------------------------------------------------------------ facing a bet
    ev_call = R * eq_r * (P + c) - c
    best, best_ev, best_x, best_eq = "fold", 0.0, 0, 0.0
    if ev_call > best_ev:
        best, best_ev = "call", ev_call
    if state.can_raise and live:
        for frac in RAISE_SIZES:
            x = int(max(state.min_raise_to, min(mine + c + frac * (P + c), state.max_raise_to)))
            a = x - mine
            if stack - a < 0.4 * (P + 2 * a):
                x, a = state.max_raise_to, stack
            f, eq_c = called(a)
            if strong and eq_c >= 0.65 and (R * eq_c * (P + 2 * a - c) * (1 - f) + f * P - a * (1 - f)) >= 0.9 * ev_call:
                ev = f * P + (1 - f) * (R * eq_c * (P + 2 * a - c) - a)
                if ev > best_ev:
                    best, best_ev, best_x, best_eq = "raise", ev, x, eq_c  # build the pot
                continue
            if eq_c < 0.55 and not (drawing and len(opps) == 1 and eq_c >= 0.25):
                continue  # raise for value, or as a heads-up semi-bluff with a draw
            ev = f * P + (1 - f) * (R * eq_c * (P + 2 * a - c) - a)
            if ev > best_ev + RAISE_MARGIN * P and ev > ev_call + RAISE_MARGIN * P:
                best, best_ev, best_x, best_eq = "raise", ev, x, eq_c
    if best == "raise" and best_eq < 0.45:  # bluff-raise: heads-up, sparingly
        if len(opps) > 1 or rng.random() > BLUFF_RAISE_P:
            best = "call" if ev_call > 0 else "fold"
    if best == "raise":
        return state.all_in() if best_x >= state.max_raise_to else state.raise_to(best_x)
    if best == "call":
        return state.call()
    return state.fold()
