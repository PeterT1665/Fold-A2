"""Fast heuristic post-flop hand + board evaluator.

Pure-python integer bitmasks (a 13-bit rank mask, one rank mask per suit), so
a full analysis costs a few tens of microseconds. numpy would only add import
and array-allocation overhead at this size.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntEnum

RANKS = "23456789TJQKA"
SUITS = "cdhs"
_CARDS = {r + s: (i, j) for i, r in enumerate(RANKS) for j, s in enumerate(SUITS)}

ACE, KING, QUEEN, JACK, TEN = 12, 11, 10, 9, 8


class HandClass(IntEnum):
    TRASH = 0
    WEAK_DRAW = 1
    MEDIUM_MADE = 2
    STRONG_DRAW = 3
    STRONG_MADE = 4
    NUT_HAND = 5


class Texture(Enum):
    DRY = "DRY"
    WET = "WET"
    MONOTONE = "MONOTONE"
    PAIRED = "PAIRED"


@dataclass(frozen=True)
class HandInfo:
    hc: HandClass
    eq: float  # rough equity vs a *betting* range (used against pot odds)
    outs: int = 0
    top_tier: bool = False  # top-tier STRONG_MADE / NUT: worth max value
    made_cat: int = 0  # 0 high card .. 8 straight flush


def parse(cards) -> list[tuple[int, int]]:
    return [_CARDS[c] for c in cards]


def _straight_top(mask: int) -> int:
    """Top bit index (4..13) of the best straight in a 13-bit rank mask, or 0.
    Bit 0 is the ace playing low, bit r+1 is rank r."""
    m = (mask << 1) | (mask >> 12)
    for t in range(13, 3, -1):
        w = 0b11111 << (t - 4)
        if m & w == w:
            return t
    return 0


def _made(cnt, smask, nsuit, rmask):
    """(category, info) for the best hand in the given cards."""
    flush_suit = -1
    for s in range(4):
        if nsuit[s] >= 5:
            flush_suit = s
            break
    if flush_suit >= 0:
        t = _straight_top(smask[flush_suit])
        if t:
            return 8, (t,)
    quads = trips = pairs = None
    quads = [r for r in range(12, -1, -1) if cnt[r] == 4]
    if quads:
        return 7, (quads[0],)
    trips = [r for r in range(12, -1, -1) if cnt[r] == 3]
    pairs = [r for r in range(12, -1, -1) if cnt[r] == 2]
    if trips and (len(trips) > 1 or pairs):
        second = trips[1] if len(trips) > 1 else pairs[0]
        if pairs and len(trips) > 1:
            second = max(second, pairs[0])
        return 6, (trips[0], second)
    if flush_suit >= 0:
        m = smask[flush_suit]
        top = [r for r in range(12, -1, -1) if m >> r & 1][:5]
        return 5, tuple(top)
    t = _straight_top(rmask)
    if t:
        return 4, (t,)
    if trips:
        return 3, (trips[0],)
    if len(pairs) >= 2:
        return 2, (pairs[0], pairs[1])
    if pairs:
        return 1, (pairs[0],)
    return 0, ()


def _tally(cards):
    cnt = [0] * 13
    smask = [0, 0, 0, 0]
    nsuit = [0, 0, 0, 0]
    rmask = 0
    for r, s in cards:
        cnt[r] += 1
        smask[s] |= 1 << r
        nsuit[s] += 1
        rmask |= 1 << r
    return cnt, smask, nsuit, rmask


class PostFlopEvaluator:
    """evaluate(hole, board) -> HandInfo, texture(board) -> Texture."""

    # ------------------------------------------------------------ texture
    def texture(self, board) -> Texture:
        bc = parse(board) if board and isinstance(board[0], str) else board
        n = len(bc)
        cnt, smask, nsuit, rmask = _tally(bc)
        max_suit = max(nsuit)
        if max_suit >= (3 if n == 3 else 4):
            return Texture.MONOTONE
        if max(cnt) >= 2:
            return Texture.PAIRED
        # connectivity: most board ranks inside any 5-rank window (ace low too)
        m = (rmask << 1) | (rmask >> 12)
        best = max(bin(m >> lo & 0b11111).count("1") for lo in range(10))
        flush_draw = max_suit >= (2 if n == 3 else 3)
        if best >= 3 or (flush_draw and best >= 2):
            return Texture.WET
        return Texture.DRY

    # ------------------------------------------------------------ hand
    def evaluate(self, hole, board) -> HandInfo:
        hc = parse(hole)
        bc = parse(board)
        n_board = len(bc)
        hr = [c[0] for c in hc]
        cnt, smask, nsuit, rmask = _tally(hc + bc)
        bcnt, bsmask, bnsuit, brmask = _tally(bc)
        cat, info = _made(cnt, smask, nsuit, rmask)
        bcat, binfo = _made(bcnt, bsmask, bnsuit, brmask)
        tex = self.texture(board)

        made = None
        board_plays = False
        if cat > bcat or (cat == bcat and info != binfo):
            made = self._classify_made(cat, info, hc, hr, bc, bnsuit, brmask, bcnt, tex)
        elif cat == bcat and cat >= 4:
            board_plays = True

        outs = 0
        overs = 0
        bmax = max(c[0] for c in bc)
        overs = sum(1 for r in hr if r > bmax)
        if n_board < 5:
            outs = self._outs(hc, hr, cnt, nsuit, rmask, brmask)

        if made is not None and made.hc >= HandClass.STRONG_MADE:
            return made

        flop = n_board == 3
        if outs >= 8:
            eq = min(0.55, outs * (0.034 if flop else 0.0215) + 0.02 * min(overs, 2))
            if made is not None:
                eq = max(made.eq, eq) + 0.05
            return HandInfo(HandClass.STRONG_DRAW, eq, outs, False, cat)
        if made is not None:  # MEDIUM_MADE
            return HandInfo(made.hc, made.eq, outs, False, cat)

        weak = outs >= 4
        if not weak and flop:
            backdoor = any(nsuit[s] == 3 and any(c[1] == s for c in hc) for s in range(4))
            weak = (backdoor and overs >= 1) or overs >= 2
        if weak:
            eq = 0.10 + outs * (0.02 if flop else 0.012) + 0.01 * min(overs, 2)
            return HandInfo(HandClass.WEAK_DRAW, min(eq, 0.24), outs, False, cat)
        if board_plays:
            return HandInfo(HandClass.TRASH, 0.30, 0, False, cat)
        return HandInfo(HandClass.TRASH, 0.05 if overs else 0.03, 0, False, cat)

    # ------------------------------------------------------------ made hands
    def _classify_made(self, cat, info, hc, hr, bc, bnsuit, brmask, bcnt, tex):
        N, S, M = HandClass.NUT_HAND, HandClass.STRONG_MADE, HandClass.MEDIUM_MADE
        board_paired = max(bcnt) >= 2
        if cat >= 6:
            return HandInfo(N, 0.97 if cat >= 7 else 0.92, 0, True, cat)
        if cat == 5:
            suit = next(s for s in range(4) if bnsuit[s] + sum(1 for c in hc if c[1] == s) >= 5)
            top = max((c[0] for c in hc if c[1] == suit), default=0)
            if top >= QUEEN and not (board_paired and top < ACE):
                return HandInfo(N, 0.88, 0, True, cat)
            if top >= 5:
                return HandInfo(S, 0.64, 0, False, cat)
            return HandInfo(M, 0.42, 0, False, cat)
        if cat == 4:
            t = info[0]
            danger = board_paired or max(bnsuit) >= 3
            if not danger:
                m = (brmask << 1) | (brmask >> 12)
                for hi in range(t + 1, 14):
                    if bin(m >> (hi - 4) & 0b11111).count("1") >= 3:
                        danger = True
                        break
            if danger:
                return HandInfo(S, 0.68, 0, True, cat)
            return HandInfo(N, 0.88, 0, True, cat)
        if cat == 3:
            r = info[0]
            if hr[0] == hr[1] == r:  # set
                if tex is Texture.MONOTONE:
                    return HandInfo(S, 0.72, 0, True, cat)
                return HandInfo(N, 0.86, 0, True, cat)
            return HandInfo(S, 0.72, 0, True, cat)  # trips via paired board
        if cat == 2:
            hi, lo = info
            pocket = hr[0] == hr[1]
            hole_pairs = [p for p in (hi, lo) if p in hr]
            if len(hole_pairs) == 2 and not pocket:
                return HandInfo(S, 0.72, 0, True, cat)
            if pocket and hr[0] in (hi, lo):
                other = lo if hr[0] == hi else hi
                if hr[0] > other:  # pocket pair above the board pair
                    return HandInfo(S, 0.62, 0, False, cat)
            return HandInfo(M, 0.40, 0, False, cat)
        if cat == 1:
            pr = info[0]
            wet_pen = 0.04 if tex in (Texture.WET, Texture.PAIRED) else 0.0
            bd = sorted({c[0] for c in bc}, reverse=True)
            bmax = bd[0]
            if hr[0] == hr[1] == pr:  # pocket pair
                if pr > bmax:
                    if pr >= JACK:
                        return HandInfo(S, 0.66 - wet_pen, 0, pr >= JACK, cat)
                    return HandInfo(M, 0.48 - wet_pen, 0, False, cat)
                if len(bd) > 1 and pr > bd[1]:
                    return HandInfo(M, 0.36, 0, False, cat)
                return HandInfo(M, 0.30, 0, False, cat)
            if pr in hr:
                kicker = hr[1] if hr[0] == pr else hr[0]
                if pr == bmax:
                    if kicker >= TEN:
                        return HandInfo(S, 0.60 + (0.04 if kicker >= QUEEN else 0) - wet_pen,
                                        0, kicker >= QUEEN, cat)
                    return HandInfo(M, 0.42 - wet_pen, 0, False, cat)
                if len(bd) > 1 and pr == bd[1]:
                    return HandInfo(M, 0.36 - wet_pen, 0, False, cat)
                return HandInfo(M, 0.30, 0, False, cat)
        return None

    # ------------------------------------------------------------ draws
    def _outs(self, hc, hr, cnt, nsuit, rmask, brmask) -> int:
        flush_outs = 0
        for s in range(4):
            if nsuit[s] == 4:
                mine = [c[0] for c in hc if c[1] == s]
                if mine:
                    flush_outs = 9 if (len(mine) == 2 or max(mine) >= TEN) else 4
        straight_outs = 0
        if not _straight_top(rmask):
            for r in range(13):
                if rmask >> r & 1:
                    continue
                if _straight_top(rmask | 1 << r) and not _straight_top(brmask | 1 << r):
                    straight_outs += 4
        outs = flush_outs + straight_outs
        if flush_outs and straight_outs:
            outs -= 2
        return outs
