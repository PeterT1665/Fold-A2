"""Turn (4 board cards) decisions.

Same idea as river.py, one card earlier: for every hole-card combo an
opponent could hold, compute our exact share of the pot over all 46 possible
river cards (ties split). Each combo is weighted by the bucket range from
range_model.py, rebuilt from the opponent's preflop line plus every flop and
turn action. Then pick the best-EV action:

  not facing a bet : check  vs  bet {33..100% pot, all-in}
  facing a bet     : fold   vs  call  vs  value-raise / semi-bluff raise

Unlike the river, equity is not final: out of position we discount it a
little (realisation), and draws keep their real equity instead of a guess.
"""

from __future__ import annotations

import time

import range_model as rm
from opponent_tracker import OpponentClass as OC
from postflop_evaluator import RANKS, SUITS, parse
from river import _DECK, _weights, rank7
from strategy import default_postflop

# tunable knobs
BET_SIZES = (0.33, 0.5, 0.75, 1.0)
RAISE_SIZES = (0.75, 1.25)
BET_MARGIN = 0.03  # EV edge (x pot) a bet needs over checking
RAISE_MARGIN = 0.05
# Calling a big bet (> BIG_BET x pot) needs this much extra equity: on the ladder,
# turn/river calls of big bets lost with every hand class except the nuts.
BIG_BET = 0.5
BIG_CALL_MARGIN = 0.08
BLUFF_P = 0.3  # how often an EV-positive bet with < 40% equity is fired
VALUE_EQ = 0.60  # equity-when-called needed for a pure value raise
SEMI_EQ = 0.30  # a draw needs this much equity-when-called to raise
OOP_REALISE = 0.92  # share of equity realised when someone acts after us
MIN_CLOCK_MS = 4000  # below this, use the cheap shared policy
BUDGET_S = 0.35  # stop the exact enumeration early past this (then sample)

_cache: dict = {}


def _combos(state, ctx):
    """(my bucket, [(share, bucket)]) for every opponent combo; `share` is our
    pot share vs that combo averaged over all river cards. Cached per hand."""
    key = (tuple(state.hole), tuple(state.board))
    hit = _cache.get(key)
    if hit is not None:
        return hit
    hole, board = parse(state.hole), parse(state.board)
    used = set(hole) | set(board)
    deck = [c for c in _DECK if c not in used]
    rivers = list(deck)
    mine = {r: rank7(hole + board + [r]) for r in rivers}
    ev = ctx.evaluator
    end = time.perf_counter() + BUDGET_S
    out = []
    step = 1
    for i in range(len(deck)):
        a = deck[i]
        if step == 1 and time.perf_counter() > end:
            step = 3  # running long: use every third river card from here on
        for j in range(i + 1, len(deck)):
            b = deck[j]
            ab = [a, b] + board
            tot = n = 0.0
            for k in range(0, len(rivers), step):
                r = rivers[k]
                if r == a or r == b:
                    continue
                v, m = rank7(ab + [r]), mine[r]
                tot += 1.0 if m > v else 0.5 if m == v else 0.0
                n += 1
            names = [RANKS[a[0]] + SUITS[a[1]], RANKS[b[0]] + SUITS[b[1]]]
            out.append((tot / n if n else 0.5, rm.HC2B[ev.evaluate(names, state.board).hc]))
    res = (rm.HC2B[ev.evaluate(state.hole, state.board).hc], out)
    _cache.clear()
    _cache[key] = res
    return res


def _ranges(state, ctx, opps, ip_of):
    """Bucket range per opponent from preflop line + flop and turn actions."""
    lines, _ = rm.preflop_lines(state.history)
    # flat start tilted by the preflop line; river._weights adds the board's real combo counts
    init = {s: rm.normalize(list(rm._LINE[lines.get(s, "base")])) for s in opps}
    return rm.replay(state, ctx, opps, ip_of, init, ("flop", "turn"))


def _equity(combos, cw, fold=None):
    """(P(fold), our pot share vs the combos that continue)."""
    num = den = 0.0
    for (share, b), w in zip(combos, cw):
        if fold is not None:
            w *= 1.0 - fold[b]
        if w <= 0:
            continue
        den += w
        num += w * share
    if den <= 1e-12:
        return 1.0, 0.0
    return 1.0 - den, num / den


def decide(state, ctx):
    if len(state.board) != 4 or 0 < state.clock_ms < MIN_CLOCK_MS:
        return default_postflop(state, ctx)
    try:
        return _decide(state, ctx)
    except Exception as e:  # never let turn logic take the bot down
        print(f"turn fallback: {e!r}")
        return default_postflop(state, ctx)


def _decide(state, ctx):
    n, me = state.num_players, state.seat
    first = (state.button + 1) % n
    order = lambda s: (s - first) % n
    opps = [s for s in range(n) if not state.folded[s] and s != me]
    if not opps:
        return state.check() if state.to_call == 0 else state.call()
    live = [s for s in opps if state.stacks[s] > 0]
    alive_acting = [s for s in range(n) if not state.folded[s] and state.stacks[s] > 0]
    last = max(alive_acting, key=order) if alive_acting else me
    ip_of = lambda s: s == last
    R = 1.0 if all(order(s) < order(me) for s in live) else OOP_REALISE

    my_b, combos = _combos(state, ctx)
    ranges, cls = _ranges(state, ctx, opps, ip_of)
    pstats = {s: ctx.tracker.get(state.player_at(s)) for s in opps}
    cws = {s: _weights(ranges[s], combos) for s in opps}

    P, c = state.pot, state.to_call
    stack, mine = state.my_stack, state.street_bets[me]
    rng = ctx.rng

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
                pf, e = _equity(combos, cws[s], rm.fold_probs(size, cls[s], pstats[s]))
            f *= pf
            eq *= e
        return f, eq

    def commit(a):
        return stack if stack - a < 0.4 * (P + 2 * a) else a

    drawing = my_b in (rm.SDR, rm.WDR)
    no_bluff = len(opps) > 1 or any(cls[s] in (OC.CALLING_STATION, OC.OVER_AGGRESSIVE) for s in opps)

    # ------------------------------------------------------------ no bet to face
    if c == 0:
        if not state.can_raise or not live:
            return state.check()
        oa_behind = any(cls[s] is OC.OVER_AGGRESSIVE and order(s) > order(me) for s in live)
        if oa_behind and eq_r >= 0.75 and rng.random() < 0.7:
            return state.check()  # let the maniac bet, then raise
        best_ev, best_a, best_eq = R * eq_r * P, 0, eq_r
        for frac in BET_SIZES + (None,):
            a = stack if frac is None else commit(min(frac * P, stack))
            f, eq_c = called(a)
            if frac is None and eq_c < 0.6:
                continue  # jam only for value
            ev = f * P + (1 - f) * (R * eq_c * (P + 2 * a) - a)
            if ev > best_ev + BET_MARGIN * P:
                best_ev, best_a, best_eq = ev, a, eq_c
        if best_a == 0:
            return state.check()
        if best_eq < 0.4 and not drawing:  # profit only through folds
            if no_bluff or rng.random() > BLUFF_P:
                return state.check()
        if best_a >= stack:
            return state.all_in()
        return state.raise_to(int(max(state.min_raise_to, min(mine + round(best_a), state.max_raise_to))))

    # ------------------------------------------------------------ facing a bet
    big = c / max(P - c, 1) > BIG_BET
    ev_call = R * eq_r * (P + c) - c - (BIG_CALL_MARGIN * (P + c) if big else 0.0)
    best, best_ev, best_x = "fold", 0.0, 0
    if ev_call > best_ev:
        best, best_ev = "call", ev_call
    if state.can_raise and live:
        for frac in RAISE_SIZES + (None,):
            if frac is None:
                x = state.max_raise_to
            else:
                x = int(max(state.min_raise_to, min(mine + c + frac * (P + c), state.max_raise_to)))
            a = x - mine
            if stack - a < 0.4 * (P + 2 * a):
                x, a = state.max_raise_to, stack
            f, eq_c = called(a)
            if eq_c < (SEMI_EQ if (drawing and len(opps) == 1) else VALUE_EQ):
                continue
            ev = f * P + (1 - f) * (R * eq_c * (P + 2 * a - c) - a)
            if ev > best_ev + RAISE_MARGIN * P:
                best, best_ev, best_x = "raise", ev, x
    if best == "raise":
        return state.all_in() if best_x >= state.max_raise_to else state.raise_to(best_x)
    if best == "call":
        return state.call()
    return state.fold()
