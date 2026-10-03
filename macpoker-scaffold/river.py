"""River (5 board cards) decisions. Owner: Chi.

The board is complete, so instead of bucket-vs-bucket guesses we score our
hand exactly against every hole-card combo an opponent could hold (990 of
them). Each combo is weighted by the bucket range from range_model.py, rebuilt
from the opponent's preflop line plus every flop/turn/river action, then:

  not facing a bet : check  vs  bet {33..150% pot, all-in}   (best EV)
  facing a bet     : fold   vs  call  vs  value-raise         (best EV)

Fold equity uses the same per-bucket fold model as the flop, applied combo by
combo, so "equity when called" is exact against the calling part of the range.
Bluffs are gated: heads-up only and never into calling stations or maniacs.
"""

from __future__ import annotations

import range_model as rm
from opponent_tracker import OpponentClass as OC
from postflop_evaluator import RANKS, SUITS, _straight_top, parse
from strategy import default_postflop

# tunable knobs
BET_SIZES = (0.33, 0.5, 0.75, 1.0, 1.5)
RAISE_SIZES = (0.75, 1.25)
BET_MARGIN = 0.03  # EV edge (x pot) a bet needs over checking
RAISE_MARGIN = 0.05
BLUFF_P = 0.35  # how often an EV-positive bluff is actually fired
VALUE_EQ = 0.60  # equity-when-called needed for a value raise
OVERBET_EQ = 0.70  # equity-when-called needed to bet more than pot
# where unresolved draws from flop/turn end up on the river: (hit bucket, share)
DRAW_HIT = {rm.SDR: (rm.STR, 0.30), rm.WDR: (rm.MED, 0.15)}
MIN_CLOCK_MS = 2000  # below this, use the cheap shared policy

_DECK = [(i, j) for i in range(len(RANKS)) for j in range(len(SUITS))]
_cache: dict = {}


# ------------------------------------------------------------ hand ranking
def rank7(cards) -> int:
    """Comparable strength of the best 5-card hand; higher is better."""
    cnt = [0] * 13
    smask = [0, 0, 0, 0]
    nsuit = [0, 0, 0, 0]
    rmask = 0
    for r, s in cards:
        cnt[r] += 1
        smask[s] |= 1 << r
        nsuit[s] += 1
        rmask |= 1 << r

    def top(mask, k, skip=()):
        out = []
        for r in range(12, -1, -1):
            if mask >> r & 1 and r not in skip:
                out.append(r)
                if len(out) == k:
                    break
        return out

    def pack(cat, ranks):
        v = cat
        for r in ranks:
            v = v << 4 | (r + 1)
        return v << 4 * (5 - len(ranks))

    for s in range(4):
        if nsuit[s] >= 5:
            t = _straight_top(smask[s])
            if t:
                return pack(8, [t])
            flush = pack(5, top(smask[s], 5))
            break
    else:
        flush = 0

    quads = trips = -1
    pairs = []
    for r in range(12, -1, -1):
        c = cnt[r]
        if c == 4 and quads < 0:
            quads = r
        elif c == 3:
            if trips < 0:
                trips = r
            else:
                pairs.append(r)  # second set plays as the pair of a boat
        elif c == 2:
            pairs.append(r)
    if quads >= 0:
        return pack(7, [quads] + top(rmask, 1, (quads,)))
    if trips >= 0 and pairs:
        return pack(6, [trips, max(pairs)])
    if flush:
        return flush
    t = _straight_top(rmask)
    if t:
        return pack(4, [t])
    if trips >= 0:
        return pack(3, [trips] + top(rmask, 2, (trips,)))
    if len(pairs) >= 2:
        hi, lo = pairs[0], pairs[1]
        return pack(2, [hi, lo] + top(rmask, 1, (hi, lo)))
    if pairs:
        return pack(1, [pairs[0]] + top(rmask, 3, (pairs[0],)))
    return pack(0, top(rmask, 5))


def _combos(state, ctx):
    """(my score, [(combo score, bucket)]) for every combo not blocked by
    our hole cards or the board. Cached per hand."""
    key = (tuple(state.hole), tuple(state.board))
    hit = _cache.get(key)
    if hit is not None:
        return hit
    hole, board = parse(state.hole), parse(state.board)
    used = set(hole) | set(board)
    deck = [c for c in _DECK if c not in used]
    ev = ctx.evaluator
    out = []
    for i in range(len(deck)):
        a = deck[i]
        for j in range(i + 1, len(deck)):
            b = deck[j]
            cards = [a, b] + board
            names = [RANKS[a[0]] + SUITS[a[1]], RANKS[b[0]] + SUITS[b[1]]]
            out.append((rank7(cards), rm.HC2B[ev.evaluate(names, state.board).hc]))
    res = (rank7(hole + board), out)
    _cache.clear()
    _cache[key] = res
    return res


# ------------------------------------------------------------ ranges
def _ranges(state, ctx, opps, ip_of):
    """Bucket range per opponent from preflop line + all postflop actions."""
    lines, raises = {}, 0
    for st, s, k, _ in state.history:
        if st == "preflop":
            if k == "raise":
                lines[s] = "3bet" if raises else "open"
                raises += 1
            elif k == "call" and s not in lines:
                lines[s] = "call"
    cls = {s: ctx.tracker.classify(state.player_at(s)) for s in opps}
    tex = ctx.evaluator.texture(state.board[:3])
    ranges = {s: rm.prior(tex, lines.get(s, "base")) for s in opps}

    # chips added per street, to recover the pot at the start of each street
    added = {"flop": 0, "turn": 0}
    sb = {}
    street = None
    for st, s, k, a in state.history:
        if st != street:
            street, sb = st, {}
        if st in added:
            if k == "raise":
                added[st] += a - sb.get(s, 0)
                sb[s] = a
            elif k == "call":
                added[st] += a
                sb[s] = sb.get(s, 0) + a
    river_pot = state.pot - sum(state.street_bets)
    start = {"river": river_pot, "turn": river_pot - added["turn"]}
    start["flop"] = start["turn"] - added["flop"]

    for st in ("flop", "turn", "river"):
        if st == "river":  # draws that missed are air now
            for s in ranges:
                w = list(ranges[s])
                for d, (to, share) in DRAW_HIT.items():
                    w[to] += w[d] * share
                    w[rm.AIR] += w[d] * (1 - share)
                    w[d] = 0.0
                ranges[s] = rm.normalize(w)
        pot, sb, cur = start[st], {}, 0
        for hs, s, k, a in state.history:
            if hs != st:
                continue
            kind, frac = None, 0.0
            if k == "raise":
                add = a - sb.get(s, 0)
                kind, frac = ("bet" if cur == 0 else "raise"), add / max(pot, 1)
                pot += add
                sb[s], cur = a, a
            elif k == "call":
                kind, frac = "call", a / max(pot, 1)
                pot += a
                sb[s] = sb.get(s, 0) + a
            elif k == "check":
                kind = "check"
            if kind and s in ranges:
                ranges[s] = rm.update(ranges[s], kind, frac, ip_of(s), cls[s])
    return ranges, cls


def _weights(w, combos):
    """Spread each bucket's mass evenly over the combos in that bucket."""
    n = [0] * 6
    for _, b in combos:
        n[b] += 1
    per = [w[b] / n[b] if n[b] else 0.0 for b in range(6)]
    cw = [per[b] for _, b in combos]
    tot = sum(cw)
    return [x / tot for x in cw] if tot > 0 else [1.0 / len(combos)] * len(combos)


def _equity(me, combos, cw, fold=None):
    """(P(fold), equity vs the combos that continue)."""
    num = den = 0.0
    for (sc, b), w in zip(combos, cw):
        if fold is not None:
            w *= 1.0 - fold[b]
        if w <= 0:
            continue
        den += w
        num += w * (1.0 if me > sc else 0.5 if me == sc else 0.0)
    if den <= 1e-12:
        return 1.0, 0.0
    return 1.0 - den, num / den


# ------------------------------------------------------------ decision
def decide(state, ctx):
    if len(state.board) != 5 or 0 < state.clock_ms < MIN_CLOCK_MS:
        return default_postflop(state, ctx)
    try:
        return _decide(state, ctx)
    except Exception as e:  # never let river logic take the bot down
        print(f"river fallback: {e!r}")
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

    my_score, combos = _combos(state, ctx)
    ranges, cls = _ranges(state, ctx, opps, ip_of)
    cws = {s: _weights(ranges[s], combos) for s in opps}

    P, c = state.pot, state.to_call
    stack, mine = state.my_stack, state.street_bets[me]
    rng = ctx.rng

    eq_r = 1.0
    for s in opps:
        eq_r *= _equity(my_score, combos, cws[s])[1]

    def called(a):
        """(P(everyone folds), equity vs the hands that call) for adding `a`."""
        size = a / max(P, 1)
        f, eq = 1.0, 1.0
        for s in opps:
            if state.stacks[s] == 0:  # already all in: can't fold
                pf, e = _equity(my_score, combos, cws[s])
                pf = 0.0
            else:
                pf, e = _equity(my_score, combos, cws[s], rm.fold_probs(size, cls[s]))
            f *= pf
            eq *= e
        return f, eq

    def commit(a):
        return stack if stack - a < 0.4 * (P + 2 * a) else a

    no_bluff = len(opps) > 1 or any(cls[s] in (OC.CALLING_STATION, OC.OVER_AGGRESSIVE) for s in opps)

    # ------------------------------------------------------------ no bet to face
    if c == 0:
        if not state.can_raise or not live:
            return state.check()
        oa_behind = any(cls[s] is OC.OVER_AGGRESSIVE and order(s) > order(me) for s in live)
        if oa_behind and eq_r >= 0.75 and rng.random() < 0.7:
            return state.check()  # let the maniac bet, then raise
        best_ev, best_a, best_eq = eq_r * P, 0, eq_r
        for frac in BET_SIZES + (None,):
            a = stack if frac is None else commit(min(frac * P, stack))
            f, eq_c = called(a)
            if a > P and eq_c < OVERBET_EQ:
                continue
            ev = f * P + (1 - f) * (eq_c * (P + 2 * a) - a)
            if ev > best_ev + BET_MARGIN * P:
                best_ev, best_a, best_eq = ev, a, eq_c
        if best_a == 0:
            return state.check()
        if best_eq < 0.5:  # this bet makes money only through folds
            if no_bluff or rng.random() > BLUFF_P:
                return state.check()
        if best_a >= stack:
            return state.all_in()
        return state.raise_to(int(max(state.min_raise_to, min(mine + round(best_a), state.max_raise_to))))

    # ------------------------------------------------------------ facing a bet
    ev_call = eq_r * (P + c) - c
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
            if eq_c < VALUE_EQ:
                continue  # no river bluff-raises
            ev = f * P + (1 - f) * (eq_c * (P + 2 * a - c) - a)
            if ev > best_ev + RAISE_MARGIN * P:
                best, best_ev, best_x = "raise", ev, x
    if best == "raise":
        return state.all_in() if best_x >= state.max_raise_to else state.raise_to(best_x)
    if best == "call":
        return state.call()
    return state.fold()
