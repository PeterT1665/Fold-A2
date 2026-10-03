"""Flop (3 board cards) decisions.

For every opponent still in the hand we rebuild a bucketed range from their
preflop line plus every flop action so far (range_model.py), score our hand
against it, and pick the action with the best expected value:

  not facing a bet : check  vs  bet {25..140% pot}   (size chosen by EV)
  facing a bet     : fold   vs  call  vs  raise {66..150%}

Fold equity comes from the same range model, flexed by opponent profile, so
sizing falls out of (our strength, their range, board, profile) instead of a
fixed ladder. Position enters through equity realisation and trap rules.
"""

from __future__ import annotations

import range_model as rm
from opponent_tracker import OpponentClass as OC
from postflop_evaluator import HandClass as HC
from strategy import default_postflop

# tunable knobs (tools/variants.py overrides these for A/B runs)
BET_SIZES = (0.25, 0.33, 0.5, 0.66, 0.85, 1.0)
RAISE_SIZES = (0.66, 1.0, 1.5)
BLUFF_BET_P = (0.55, 0.4, 0.3)  # bluff-bet freq: pfr in position / pfr out of position / not pfr
BLUFF_MULTIWAY = 0.4  # multiplier when 2+ opponents
BLUFF_RAISE_P = 0.3
BET_MARGIN = 0.02  # EV edge (x pot) a bet needs over checking
RAISE_MARGIN = 0.06


def _lines(state):
    """Each opponent's preflop line: open / 3bet / call / base."""
    raises, out = 0, {}
    for st, s, k, _ in state.history:
        if st != "preflop":
            continue
        if k == "raise":
            out[s] = "3bet" if raises >= 1 else "open"
            raises += 1
        elif k == "call" and s not in out:
            out[s] = "call"
    return out, raises


def _ranges(state, ctx, opps, tex, order, ip_of):
    lines, _ = _lines(state)
    cls = {s: ctx.tracker.classify(state.player_at(s)) for s in opps}
    pstats = {s: ctx.tracker.get(state.player_at(s)) for s in opps}
    ranges = {s: rm.prior(tex, lines.get(s, "base")) for s in opps}
    pot = state.pot - sum(state.street_bets)
    sb, cur = {}, 0
    for st, s, k, a in state.history:
        if st != "flop":
            continue
        kind, frac = None, 0.0
        if k == "raise":
            added = a - sb.get(s, 0)
            kind, frac = ("bet" if cur == 0 else "raise"), added / max(pot, 1)
            pot += added
            sb[s], cur = a, a
        elif k == "call":
            kind, frac = "call", a / max(pot - a, 1)
            pot += a
            sb[s] = sb.get(s, 0) + a
        elif k == "check":
            kind = "check"
        if kind and s in ranges:
            ranges[s] = rm.update(ranges[s], kind, frac, ip_of(s), cls[s], pstats[s])
    return ranges, cls


def decide(state, ctx):
    if len(state.board) != 3:
        return default_postflop(state, ctx)
    n, me = state.num_players, state.seat
    first = (state.button + 1) % n
    order = lambda s: (s - first) % n
    opps = [s for s in range(n) if not state.folded[s] and s != me]
    if not opps:
        return state.check() if state.to_call == 0 else state.call()
    live = [s for s in opps if state.stacks[s] > 0]
    ip = all(order(s) < order(me) for s in live)  # nobody left to act after us
    alive_acting = [s for s in range(n) if not state.folded[s] and state.stacks[s] > 0]
    last = max(alive_acting, key=order) if alive_acting else me
    ip_of = lambda s: s == last

    info = ctx.evaluator.evaluate(state.hole, state.board)
    tex = ctx.evaluator.texture(state.board)
    my_b = rm.HC2B[info.hc]
    ranges, cls = _ranges(state, ctx, opps, tex, order, ip_of)
    pstats = {s: ctx.tracker.get(state.player_at(s)) for s in opps}

    P = state.pot
    stack = state.my_stack
    mine = state.street_bets[me]
    c = state.to_call
    rng = ctx.rng
    _, pre_raises = _lines(state)
    pfr = any(st == "preflop" and k == "raise" and s == me for st, s, k, _ in state.history)
    R = 1.0 if ip else 0.92
    if info.hc is HC.MEDIUM_MADE and stack / max(P, 1) > 10:
        R -= 0.03

    eq_r = 1.0
    for s in opps:
        eq_r *= rm.equity(my_b, info.eq, ranges[s])

    def called(a, size):
        """(P(all fold), equity if called) for putting in `a` chips."""
        f, eq = 1.0, 1.0
        for s in opps:
            cr, pf = rm.call_range(ranges[s], rm.fold_probs(size, cls[s], pstats[s]))
            f *= pf
            eq *= rm.equity(my_b, info.eq, cr)
        return f, eq

    def commit(a):
        return stack if stack - a < 0.4 * (P + 2 * a) else a

    # ------------------------------------------------------------ no bet to face
    if c == 0:
        if not state.can_raise:
            return state.check()
        oa_behind = any(cls[s] is OC.OVER_AGGRESSIVE and order(s) > order(me) for s in live)
        if oa_behind and (my_b == rm.NUT or (my_b == rm.STR and info.top_tier)) and rng.random() < 0.7:
            return state.check()  # let the maniac bet, then raise
        best_ev, best_a, best_eq = R * eq_r * P, 0, eq_r
        for frac in BET_SIZES:
            a = commit(min(frac * P, stack))
            f, eq_c = called(a, a / max(P, 1))
            if eq_c < 0.5 and frac > 0.66:
                continue  # no overbet bluffs / thin overbets
            ev = f * P + (1 - f) * (R * eq_c * (P + 2 * a) - a)
            if ev > best_ev + BET_MARGIN * P:
                best_ev, best_a, best_eq = ev, a, eq_c
        if best_a == 0:
            return state.check()
        if best_eq < 0.42:  # mostly fold equity: gate bluffs
            p = (BLUFF_BET_P[0] if (pfr and ip) else BLUFF_BET_P[1] if pfr else BLUFF_BET_P[2]) * (BLUFF_MULTIWAY if len(opps) > 1 else 1.0)
            if rng.random() > p:
                return state.check()
        if best_a >= stack:
            return state.all_in()
        return state.raise_to(int(max(state.min_raise_to, min(round(best_a), state.max_raise_to))))

    # ------------------------------------------------------------ facing a bet
    ev_call = R * eq_r * (P + c) - c
    strong = (my_b == rm.NUT or (my_b == rm.STR and info.top_tier)) and eq_r >= 0.7
    best, best_ev, best_x, best_eq = "fold", 0.0, 0, 0.0
    if ev_call > best_ev:
        best, best_ev = "call", ev_call
    if state.can_raise:
        for frac in RAISE_SIZES:
            x = mine + c + frac * (P + c)
            x = int(max(state.min_raise_to, min(x, state.max_raise_to)))
            a = x - mine
            if stack - a < 0.4 * (P + 2 * a):
                x, a = state.max_raise_to, stack
            f, eq_c = called(a, a / max(P, 1))
            ev = f * P + (1 - f) * (R * eq_c * (P + 2 * a - c) - a)
            if eq_c < 0.55 and my_b not in (rm.SDR, rm.WDR):
                continue  # raise only for value, or as a semi-bluff with a draw
            if eq_c < 0.25:
                continue
            if strong and eq_c >= 0.65 and ev >= 0.9 * ev_call and ev > best_ev:
                best, best_ev, best_x, best_eq = "raise", ev, x, eq_c  # build the pot
                continue
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
