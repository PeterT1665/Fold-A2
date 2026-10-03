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
_L_RAISE = [.9, .35, .05, .3, .08, .1]
_L_CALL = [.7, .9, .75, .85, .35, .08]
_L_CHECK_IP = [.25, .45, .8, .55, .7, .85]
_L_CHECK_OOP = [.5, .6, .85, .6, .85, .9]


def _lik(kind: str, frac: float, ip: bool):
    if kind == "bet":
        return _L_BET["s" if frac <= 0.4 else ("m" if frac <= 0.85 else "l")]
    if kind == "raise":
        return _L_RAISE
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


def update(w, kind: str, frac: float, ip: bool, cls: OC):
    l = _lik(kind, frac, ip)
    k = _K[cls][kind]
    return normalize([x * (p ** k) for x, p in zip(w, l)])


# --- fold model --------------------------------------------------------------
FOLD_SCALE = 0.7  # model is optimistic about folds; shade it (arena-tuned)
_FOLD0 = [.02, .12, .45, .25, .70, .90]
_FOLDK = [.05, .30, .70, .45, .40, .15]


MAX_FOLD_SIZE = 1.0  # bets above pot size buy no extra folds (ladder bots call jams with real hands)


def fold_probs(size: float, cls: OC):
    """P(fold | bucket) facing a bet/raise of `size` x pot."""
    size = min(size, MAX_FOLD_SIZE)
    out = []
    for b in range(6):
        f = min(.98, max(0.0, _FOLD0[b] + _FOLDK[b] * (size - 0.5)))
        if cls is OC.TIGHT_FOLD:
            f += (1 - f) * 0.35
        elif cls is OC.CALLING_STATION:
            f *= 0.45
        elif cls is OC.OVER_AGGRESSIVE:
            f *= 0.7
        out.append(f * FOLD_SCALE)
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
