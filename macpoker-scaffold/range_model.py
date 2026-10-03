"""Bucketed opponent-range model (street independent).

An opponent's range is a probability vector over six hand buckets *on the
current board* (same buckets as PostFlopEvaluator): NUT, STR(ong), MED(ium),
SDR (strong draw), WDR (weak draw), AIR. Each observed action multiplies the
vector by a likelihood table (flattened/sharpened by the opponent's profile),
and our hand is scored against the result with a small matchup table.
All numbers are hand-set priors, meant to be tuned in the arena.
"""

from __future__ import annotations

from opponent_tracker import OpponentClass as OC
from postflop_evaluator import HandClass as HC
from postflop_evaluator import Texture

NUT, STR, MED, SDR, WDR, AIR = range(6)
HC2B = {
    HC.NUT_HAND: NUT, HC.STRONG_MADE: STR, HC.MEDIUM_MADE: MED,
    HC.STRONG_DRAW: SDR, HC.WEAK_DRAW: WDR, HC.TRASH: AIR,
}
NOMINAL_EQ = [0.88, 0.64, 0.38, 0.32, 0.16, 0.04]

# --- matchup: our bucket (row) vs their bucket (col), flop equity -----------
_UP = {
    (NUT, STR): .85, (NUT, MED): .93, (NUT, SDR): .85, (NUT, WDR): .94, (NUT, AIR): .97,
    (STR, MED): .80, (STR, SDR): .62, (STR, WDR): .85, (STR, AIR): .92,
    (MED, SDR): .45, (MED, WDR): .70, (MED, AIR): .80,
    (SDR, WDR): .62, (SDR, AIR): .68,
    (WDR, AIR): .58,
}
MATCH = [[0.5] * 6 for _ in range(6)]
for (a, b), v in _UP.items():
    MATCH[a][b] = v
    MATCH[b][a] = 1.0 - v

# --- priors ----------------------------------------------------------------
_BASE = {
    Texture.DRY: [.04, .12, .28, .06, .10, .40],
    Texture.WET: [.05, .11, .26, .12, .14, .32],
    Texture.MONOTONE: [.06, .10, .22, .12, .16, .34],
    Texture.PAIRED: [.05, .08, .30, .05, .10, .42],
}
_LINE = {
    "open": [1.3, 1.6, 1.0, 1.0, .9, .8],
    "3bet": [1.6, 2.2, .9, .8, .7, .6],
    "call": [1.1, 1.0, 1.1, 1.1, 1.0, .9],
    "base": [1.0] * 6,
}


def normalize(w):
    s = sum(w)
    return [x / s for x in w] if s > 0 else [1 / 6] * 6


def prior(tex: Texture, line: str):
    return normalize([b * m for b, m in zip(_BASE[tex], _LINE[line])])


# --- likelihoods P(action | bucket) -----------------------------------------
_L_BET = {
    "s": [.5, .6, .7, .55, .4, .35],
    "m": [.8, .8, .4, .6, .25, .25],
    "l": [.9, .6, .15, .45, .15, .2],
}
# Medium/large bets from a player who bets selectively: ladder replays showed
# these are nearly always real (calling them lost ~58 chips per call).
_L_BET_TRUST = {
    "m": [.8, .8, .3, .6, .12, .10],
    "l": [.9, .6, .08, .45, .06, .06],
}
_L_RAISE = [.9, .35, .05, .3, .08, .1]
# Raises from a player who rarely raises: on the ladder, rare raisers were weak far less often.
_L_RAISE_TRUST = [.9, .35, .03, .3, .04, .04]

# --- per-opponent adaptation (shrunk toward a typical player, like preflop) --
ADAPT_TRUST = True  # trust a player's big bets by how often they bet
ADAPT_FOLD = True  # scale fold model by the player's own fold-to-bet rate
PRIOR_K = 8.0
BET_FREQ_PRIOR = 0.5
TRUST_LO, TRUST_HI = 0.65, 0.90  # bet freq: <= LO fully trusted, >= HI old model
FOLD_PRIOR = 0.45
ADAPT_SD = False  # stop trusting big bets from players caught bluffing at showdown
SD_K, SD_PRIOR = 4.0, 0.25
ADAPT_RAISE = True  # trust a player's raises by how rarely they raise
RAISE_FREQ_PRIOR = 0.12
RAISE_LO, RAISE_HI = 0.15, 0.35  # raise freq facing a bet: <= LO trusted, >= HI old model
SD_LO, SD_HI = 0.20, 0.40  # shrunk weak share of shown big bets: <= LO trust, >= HI old model


def bet_freq(st) -> float:
    """How often this player bets when checked to (postflop), shrunk."""
    n = st.post_bets + st.post_checks
    return (st.post_bets + PRIOR_K * BET_FREQ_PRIOR) / (n + PRIOR_K)


def fold_rate(st) -> float:
    """How often this player folds facing a postflop bet, shrunk."""
    return (st.facing_folds + PRIOR_K * FOLD_PRIOR) / (st.facing + PRIOR_K)


def raise_freq(st) -> float:
    """How often this player raises when facing a postflop bet, shrunk."""
    return (st.post_raises + PRIOR_K * RAISE_FREQ_PRIOR) / (st.facing + PRIOR_K)


def bluff_share(st) -> float:
    """Share of this player's big bets that were weak when shown down, shrunk."""
    return (st.big_sd_weak + SD_K * SD_PRIOR) / (st.big_sd + SD_K)


def _blend(a, b, w):
    return [x * (1 - w) + y * w for x, y in zip(a, b)]
_L_CALL = [.7, .9, .75, .85, .35, .08]
_L_CHECK_IP = [.25, .45, .8, .55, .7, .85]
_L_CHECK_OOP = [.5, .6, .85, .6, .85, .9]


def _lik(kind: str, frac: float, ip: bool, st=None):
    if kind == "bet":
        sz = "s" if frac <= 0.4 else ("m" if frac <= 0.85 else "l")
        if sz == "s" or st is None or not ADAPT_TRUST:
            return _L_BET[sz]
        w = min(1.0, max(0.0, (bet_freq(st) - TRUST_LO) / (TRUST_HI - TRUST_LO)))
        if ADAPT_SD:
            w = max(w, min(1.0, max(0.0, (bluff_share(st) - SD_LO) / (SD_HI - SD_LO))))
        return _blend(_L_BET_TRUST[sz], _L_BET[sz], w)
    if kind == "raise":
        if st is None or not ADAPT_RAISE:
            return _L_RAISE
        w = min(1.0, max(0.0, (raise_freq(st) - RAISE_LO) / (RAISE_HI - RAISE_LO)))
        return _blend(_L_RAISE_TRUST, _L_RAISE, w)
    if kind == "call":
        f = min(frac, 1.2)
        weak, drw = max(0.15, 1 - 0.55 * f), max(0.4, 1 - 0.3 * f)
        l = list(_L_CALL)
        l[MED] *= weak; l[WDR] *= weak; l[AIR] *= weak; l[SDR] *= drw
        return l
    return _L_CHECK_IP if ip else _L_CHECK_OOP


_K = {  # exponent applied to the likelihood: <1 flattens (action says less), >1 sharpens
    OC.OVER_AGGRESSIVE: {"bet": .45, "raise": .45, "call": 1.0, "check": 1.0},
    OC.TIGHT_FOLD: {"bet": 1.3, "raise": 1.3, "call": 1.0, "check": 1.0},
    OC.CALLING_STATION: {"bet": 1.2, "raise": 1.2, "call": .4, "check": .8},
    OC.BALANCED_GTO: {"bet": 1.0, "raise": 1.0, "call": 1.0, "check": 1.0},
}


def update(w, kind: str, frac: float, ip: bool, cls: OC, st=None):
    l = _lik(kind, frac, ip, st)
    k = _K[cls][kind]
    return normalize([x * (p ** k) for x, p in zip(w, l)])


# --- replaying the hand history ---------------------------------------------
# One implementation for flop, turn and river (they used to keep drifting copies).


def preflop_lines(history):
    """Each player's preflop line (open / 3bet / call) and the number of raises."""
    raises, out = 0, {}
    for st, s, k, _ in history:
        if st != "preflop":
            continue
        if k == "raise":
            out[s] = "3bet" if raises >= 1 else "open"
            raises += 1
        elif k == "call" and s not in out:
            out[s] = "call"
    return out, raises


def street_start_pots(state, streets):
    """Pot at the start of each street in `streets`; the last one is the current street."""
    added = {st: 0 for st in streets}
    sb, street = {}, None
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
    start = {streets[-1]: state.pot - sum(state.street_bets)}
    for i in range(len(streets) - 2, -1, -1):
        start[streets[i]] = start[streets[i + 1]] - added[streets[i]]
    return start


def replay(state, ctx, opps, ip_of, init, streets, call_frac="pot_after", draw_hit=None):
    """Update each opponent's bucket range with every postflop action so far.

    init      : {seat: starting range}
    streets   : postflop streets to replay, in order, ending with the current one
    call_frac : how a called bet is sized: "pot_before" = bet / pot before the bet
                (flop), "pot_after" = bet / pot including it (turn, river)
    draw_hit  : {draw bucket: (bucket it becomes, share)} applied before the river
    Returns (ranges, classes) keyed by seat.
    """
    cls = {s: ctx.tracker.classify(state.player_at(s)) for s in opps}
    pstats = {s: ctx.tracker.get(state.player_at(s)) for s in opps}
    ranges = dict(init)
    start = street_start_pots(state, streets)
    for st in streets:
        if draw_hit and st == "river":  # draws that missed are air now
            for s in ranges:
                w = list(ranges[s])
                for d, (to, share) in draw_hit.items():
                    w[to] += w[d] * share
                    w[AIR] += w[d] * (1 - share)
                    w[d] = 0.0
                ranges[s] = normalize(w)
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
                kind = "call"
                frac = a / max(pot - a, 1) if call_frac == "pot_before" else a / max(pot, 1)
                pot += a
                sb[s] = sb.get(s, 0) + a
            elif k == "check":
                kind = "check"
            if kind and s in ranges:
                ranges[s] = update(ranges[s], kind, frac, ip_of(s), cls[s], pstats[s])
    return ranges, cls


# --- fold model --------------------------------------------------------------
FOLD_SCALE = 0.7  # model is optimistic about folds; shade it (arena-tuned)
_FOLD0 = [.02, .12, .45, .25, .70, .90]
_FOLDK = [.05, .30, .70, .45, .40, .15]


def fold_probs(size: float, cls: OC, st=None):
    """P(fold | bucket) facing a bet/raise of `size` x pot."""
    # this player's own fold tendency vs a typical player (1.0 with no data)
    adj = fold_rate(st) / FOLD_PRIOR if (st is not None and ADAPT_FOLD) else 1.0
    adj = min(1.6, max(0.5, adj))
    out = []
    for b in range(6):
        f = min(.98, max(0.0, _FOLD0[b] + _FOLDK[b] * (size - 0.5)))
        per_player = st is not None and ADAPT_FOLD  # these two labels come from fold stats
        if cls is OC.TIGHT_FOLD and not per_player:
            f += (1 - f) * 0.35
        elif cls is OC.CALLING_STATION and not per_player:
            f *= 0.45
        elif cls is OC.OVER_AGGRESSIVE:
            f *= 0.7
        out.append(min(.98, f * adj) * FOLD_SCALE)
    return out


# --- equity ------------------------------------------------------------------
def equity(my_bucket: int, my_eq: float, w) -> float:
    """Our flop equity vs range `w`; `my_eq` (evaluator) nudges within-bucket strength."""
    adj = 0.5 * (my_eq - NOMINAL_EQ[my_bucket])
    row = MATCH[my_bucket]
    e = sum(wi * min(.99, max(.01, r + adj)) for wi, r in zip(w, row))
    return e


def call_range(w, fold):
    """Range that continues after folding `fold`; returns (range, P(fold))."""
    cont = [x * (1 - f) for x, f in zip(w, fold)]
    s = sum(cont)
    p_fold = 1.0 - s
    return (normalize(cont) if s > 1e-9 else w), p_fold
