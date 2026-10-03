"""Preflop range tables (100bb, 5-6 handed) in poker notation, plus a parser.

Every family is a *ladder*: index 0 is the tightest version, higher indices
are looser. Strategy code picks a level from position, then nudges it up or
down from opponent behaviour. Hand codes look like "AA", "AKs", "AKo".
"""

from __future__ import annotations

RANKS = "23456789TJQKA"
_R = {r: i for i, r in enumerate(RANKS)}


def hand_code(hole) -> str:
    """["As", "Kd"] -> "AKo"; ["7h", "7c"] -> "77"."""
    a, b = hole[0], hole[1]
    hi, lo = (a, b) if _R[a[0]] >= _R[b[0]] else (b, a)
    if hi[0] == lo[0]:
        return hi[0] * 2
    return hi[0] + lo[0] + ("s" if hi[1] == lo[1] else "o")


def _expand(tok: str) -> set[str]:
    tok = tok.strip()
    if not tok:
        return set()
    if "-" in tok:  # "77-22", "K9s-K6s", "AQo-ATo"
        a, b = (t.strip() for t in tok.split("-"))
        if a[0] == a[1]:  # pairs
            lo, hi = sorted((_R[a[0]], _R[b[0]]))
            return {RANKS[i] * 2 for i in range(lo, hi + 1)}
        lo, hi = sorted((_R[a[1]], _R[b[1]]))
        return {a[0] + RANKS[i] + a[2] for i in range(lo, hi + 1)}
    plus = tok.endswith("+")
    tok = tok.rstrip("+")
    if tok[0] == tok[1]:  # "TT" / "TT+"
        start = _R[tok[0]]
        return {RANKS[i] * 2 for i in range(start, 13 if plus else start + 1)}
    if plus:  # "A2s+" -> A2s..AKs (kicker climbs to just below the top card)
        return {tok[0] + RANKS[i] + tok[2] for i in range(_R[tok[1]], _R[tok[0]])}
    return {tok}


def parse(spec: str) -> frozenset[str]:
    out: set[str] = set()
    for tok in spec.split(","):
        out |= _expand(tok)
    return frozenset(out)


def combos(hands) -> int:
    return sum(6 if len(h) == 2 else 4 if h[2] == "s" else 12 for h in hands)


def pct(hands) -> float:
    return combos(hands) / 1326


def _ladder(*specs: str) -> list[frozenset[str]]:
    return [parse(s) for s in specs]


# ------------------------------------------------------------ opening (RFI)
# LJ / HJ / CO / BTN are standard 6-max 100bb solver opens (~18/21/28/44%).
# WIDE is for heads-up button and steals against blinds that over-fold.
OPEN = _ladder(
    "66+, A3s+, K8s+, Q9s+, J9s+, T9s, ATo+, KJo+, QJo",
    "55+, A2s+, K6s+, Q9s+, J9s+, T9s, 98s, 87s, 76s, ATo+, KTo+, QTo+",
    "33+, A2s+, K3s+, Q6s+, J8s+, T7s+, 97s+, 87s, 76s, 65s, A8o+, KTo+, QTo+, JTo",
    "22+, A2s+, K2s+, Q3s+, J4s+, T6s+, 96s+, 85s+, 75s+, 64s+, 53s+, A4o+, K8o+, Q9o+, J9o+, T8o+, 98o",
    "22+, A2s+, K2s+, Q2s+, J2s+, T3s+, 95s+, 84s+, 74s+, 63s+, 53s+, 43s, A2o+, K5o+, Q7o+, J7o+, T7o+, 97o+, 87o, 76o",
)
OPEN_LEVEL = {"LJ": 0, "HJ": 1, "CO": 2, "BTN": 3, "SB": 3, "HU": 4}

# ---------------------------------------------------- 3-bet vs an open (value)
# Linear and value-heavy: bots call too much, so 3-bets are mostly for value.
THREEBET = _ladder(
    "QQ+, AKs, AKo",
    "JJ+, AQs+, AKo",
    "TT+, AJs+, KQs, AQo+",
    "99+, ATs+, KJs+, QJs, AJo+, KQo",
    "77+, A8s+, KTs+, QTs+, JTs, ATo+, KJo+",
)
# Bluff 3-bets, added only against openers who fold to 3-bets a lot.
THREEBET_BLUFF = _ladder("A5s-A4s", "A5s-A2s, K9s, T8s, 97s")

# ------------------------------------------- flat an open (in position, cold)
# Hands also in the chosen 3-bet set are removed, so these lists can overlap.
CALL = _ladder(
    "QQ-66, AQs-ATs, KQs-KJs, QJs, JTs, AQo",
    "QQ-55, AQs-A9s, KQs-KTs, QJs-QTs, JTs, T9s, AQo-AJo, KQo",
    "QQ-22, AQs-A8s, KQs-K9s, QJs-Q9s, JTs-J9s, T9s, 98s, 87s, AQo-ATo, KQo-KJo",
    "QQ-22, AQs-A2s, KQs-K8s, QJs-Q9s, JTs-J8s, T9s-T8s, 98s-97s, 87s, 76s, 65s, AQo-A9o, KQo-KTo, QJo",
    "QQ-22, AQs-A2s, KQs-K8s, QJs-Q9s, JTs-J8s, T9s-T8s, 98s-97s, 87s, 76s, 65s, 54s, AQo-A5o, KQo-K9o, QJo-QTo, JTo",
)
# Opener position -> base level for the 3-bet and flat ladders.
VS_OPEN_LEVEL = {"LJ": 0, "HJ": 1, "CO": 2, "BTN": 3, "SB": 3, "HU": 4}

# ----------------------------------------------------- big blind defence (call)
_BB0 = ("JJ-22, AQs-A2s, KQs-K6s, QJs-Q8s, JTs-J8s, T9s-T8s, 98s-97s, 87s-86s, "
        "76s-75s, 65s, 54s, AQo-ATo, KQo-KTo, QJo-QTo, JTo")
_BB1 = _BB0 + ", K5s-K2s, Q7s-Q5s, J7s, T7s, 96s, 85s, 64s, 53s, A9o-A7o, K9o, Q9o, J9o, T9o, 98o"
_BB2 = _BB1 + (", Q4s-Q2s, J6s-J4s, T6s, 95s, 74s, 63s, 43s, A6o-A2o, K8o-K6o, Q8o, J8o, "
               "T8o, 97o, 87o, 76o")
BB_DEFEND = _ladder(_BB0, _BB1, _BB2)
BB_DEFEND_LEVEL = {"LJ": 0, "HJ": 0, "CO": 1, "BTN": 2, "SB": 2, "HU": 2}

# ---------------------------------------------- after we open and face a 3-bet
FOURBET = _ladder(
    "KK+, AKs",
    "QQ+, AKs, AKo",
    "JJ+, AQs+, AKo",
    "TT+, AJs+, KQs, AQo+",
)
CALL_3BET = _ladder(
    "QQ-TT, AQs, AKo",
    "JJ-88, AQs-AJs, KQs, AQo",
    "TT-66, AJs-ATs, A5s-A4s, KQs-KJs, QJs, JTs, T9s, AQo-AJo, KQo",
    "99-22, ATs-A2s, KJs-K9s, QJs-QTs, JTs, T9s, 98s, 87s, AJo-ATo, KQo-KJo",
)

# --------------------------------------------- calling off a jam / huge raise
# Level 3 is roughly "beats a random hand", for bots that shove anything.
CALL_JAM = _ladder(
    "QQ+, AKs, AKo",
    "TT+, AQs+, AQo+",
    "77+, ATs+, KQs, AJo+",
    "22+, A2s+, A2o+, K2s+, K7o+, Q8s+, QTo+, J9s+, JTo",
)
# Cold vs open + 3-bet: [normal 3-bettor, loose 3-bettor]. 4-bet hands removed.
COLD_CALL_3BET = _ladder("JJ", "JJ-TT, AQs")

# ------------------------------------------------------------- limped pots
ISO = _ladder(
    "88+, ATs+, KJs+, QJs, AJo+, KQo",
    "66+, A8s+, KTs+, QTs+, JTs, ATo+, KJo+",
    "44+, A2s+, K9s+, Q9s+, J9s+, T9s, A9o+, KTo+, QJo",
    "22+, A2s+, K7s+, Q8s+, J8s+, T8s+, 98s, 87s, A7o+, KTo+, QTo+, JTo",  # vs stations
)
OVERLIMP = parse("22+, A2s+, K9s+, QTs+, JTs, T9s, 98s, 87s, 76s, 65s")
