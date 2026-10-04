"""Fast hand evaluation and hand-strength buckets (pure python).

Cards are ints 0..51: rank = c % 13 (0 = deuce, 12 = ace), suit = c // 13.
evaluate() returns an int; higher wins. Category is value >> 20.
"""

RANKS = "23456789TJQKA"
SUITS = "cdhs"


def parse(s):
    return SUITS.index(s[1].lower()) * 13 + RANKS.index(s[0].upper())


# straight lookup: 13-bit rank mask -> high rank of best straight, or -1
_STRAIGHT = [-1] * 8192
for _m in range(8192):
    _ext = (_m << 1) | (1 if _m & (1 << 12) else 0)  # bit0 = ace-low
    for _hi in range(12, 2, -1):
        _w = 0b11111 << (_hi - 3)  # bits hi+1 .. hi-3 in extended mask
        if _ext & _w == _w:
            _STRAIGHT[_m] = _hi
            break

_BITS = [[r for r in range(12, -1, -1) if m >> r & 1] for m in range(8192)]


def _pack(cat, ranks):
    v = cat
    for i in range(5):
        v = (v << 4) | (ranks[i] if i < len(ranks) else 0)
    return v


def evaluate(cards):
    """Best 5-card value of 5..7 cards, as an int."""
    counts = [0] * 13
    sm = [0, 0, 0, 0]
    sc = [0, 0, 0, 0]
    mask = 0
    for c in cards:
        r = c % 13
        s = c // 13
        counts[r] += 1
        sm[s] |= 1 << r
        sc[s] += 1
        mask |= 1 << r
    for s in range(4):
        if sc[s] >= 5:
            fm = sm[s]
            st = _STRAIGHT[fm]
            if st >= 0:
                return _pack(8, (st,))
            flush = _BITS[fm][:5]
            break
    else:
        flush = None
    quads = trips = None
    pairs = []
    for r in range(12, -1, -1):
        n = counts[r]
        if n == 4:
            quads = r
        elif n == 3:
            if trips is None:
                trips = r
            else:
                pairs.append(r)
        elif n == 2:
            pairs.append(r)
    if quads is not None:
        k = [r for r in _BITS[mask] if r != quads][0]
        return _pack(7, (quads, k))
    if trips is not None and pairs:
        return _pack(6, (trips, pairs[0]))
    if flush is not None:
        return _pack(5, flush)
    st = _STRAIGHT[mask]
    if st >= 0:
        return _pack(4, (st,))
    if trips is not None:
        k = [r for r in _BITS[mask] if r != trips][:2]
        return _pack(3, [trips] + k)
    if len(pairs) >= 2:
        p1, p2 = pairs[0], pairs[1]
        k = [r for r in _BITS[mask] if r != p1 and r != p2][:1]
        return _pack(2, [p1, p2] + k)
    if pairs:
        p = pairs[0]
        k = [r for r in _BITS[mask] if r != p][:3]
        return _pack(1, [p] + k)
    return _pack(0, _BITS[mask][:5])


# ---------------------------------------------------------------- buckets
# 0 air, 1 draw, 2 weak pair, 3 middle pair, 4 top pair / overpair,
# 5 two pair (both hole cards) / set / trips, 6 straight or better using a hole card
NB = 7


def bucket(hole, board):
    """Coarse postflop strength class of `hole` on `board` (3..5 cards)."""
    allc = hole + board
    v = evaluate(allc)
    cat = v >> 20
    bv = evaluate(board) if len(board) == 5 else -1
    bcat = (bv >> 20) if bv >= 0 else _board_cat(board)
    if cat >= 4 and v > bv and cat > bcat:
        return 6
    if cat >= 4 and v > bv:
        # e.g. better flush/boat than the board's: still strong
        return 6 if cat >= 5 else 5
    hr = [c % 13 for c in hole]
    br = sorted((c % 13 for c in board), reverse=True)
    bset = set(br)
    paired_board = len(bset) < len(br)
    if cat == 3:
        return 5 if (hr[0] in bset or hr[1] in bset) else 2  # trips on board -> weak
    if cat == 2:
        hp = [r for r in hr if r in bset]
        if len(hp) == 2 and hr[0] != hr[1]:
            return 5
        if not paired_board and hr[0] == hr[1]:
            pass
        # one real pair plus a board pair: grade the hole pair below
    pair_rank = None
    if hr[0] == hr[1]:
        pair_rank = hr[0]
    else:
        hits = [r for r in hr if r in bset]
        if hits:
            pair_rank = max(hits)
    draw = _draw(hole, board) if len(board) < 5 else False
    if pair_rank is not None:
        top = br[0]
        if pair_rank >= top:
            return 4
        second = max([r for r in bset if r < top], default=-1)
        b = 3 if pair_rank >= second else 2
        return 3 if (draw and b == 2) else b
    return 1 if draw else 0


def _board_cat(board):
    br = [c % 13 for c in board]
    n = len(br) - len(set(br))
    if n == 0:
        return 0
    from collections import Counter
    m = max(Counter(br).values())
    return 3 if m >= 3 else (2 if n >= 2 else 1)


def _draw(hole, board):
    allc = hole + board
    sc = [0, 0, 0, 0]
    for c in allc:
        sc[c // 13] += 1
    for c in hole:
        if sc[c // 13] >= 4:
            return True
    mask = 0
    for c in allc:
        mask |= 1 << (c % 13)
    hmask = 0
    for c in hole:
        hmask |= 1 << (c % 13)
    # open-ended: 4 consecutive ranks containing a hole card, both ends open
    ext = (mask << 1) | (1 if mask & (1 << 12) else 0)
    hext = (hmask << 1) | (1 if hmask & (1 << 12) else 0)
    for lo in range(1, 10):  # window lo..lo+3 in extended bits, needs lo-1 and lo+4 in range
        w = 0b1111 << lo
        if ext & w == w and hext & w:
            return True
    return False


# ---------------------------------------------------------------- preflop
def hand_class(c1, c2):
    """169-class index string like 'AKs', 'QJo', '77'."""
    r1, r2 = c1 % 13, c2 % 13
    if r1 < r2:
        r1, r2 = r2, r1
    if r1 == r2:
        return RANKS[r1] * 2
    return RANKS[r1] + RANKS[r2] + ("s" if c1 // 13 == c2 // 13 else "o")


ALL_COMBOS = [(a, b) for a in range(52) for b in range(a + 1, 52)]
