"""Post-flop action abstraction + exploitative decision tree."""

from __future__ import annotations

from enum import Enum

from opponent_tracker import OpponentClass as OC
from postflop_evaluator import HandClass as HC
from postflop_evaluator import Texture


class Size(Enum):
    CHECK_FOLD = "CHECK_FOLD"
    BET_33 = "BET_33"
    BET_66 = "BET_66"
    BET_100 = "BET_100"
    ALL_IN = "ALL_IN"
    CALL = "CALL"  # internal: flat call when facing a bet


_FRAC = {Size.BET_33: 0.33, Size.BET_66: 0.66, Size.BET_100: 1.0}


def to_action(state, size: Size):
    """Map an abstract size to a legal SDK action (raise-to semantics)."""
    to_call = state.to_call
    if size is Size.CHECK_FOLD:
        return state.check() if to_call == 0 else state.fold()
    if size is Size.CALL:
        return state.call() if to_call > 0 else state.check()
    if not state.can_raise:
        return state.call() if to_call > 0 else state.check()
    if size is Size.ALL_IN:
        return state.all_in()
    mine = state.street_bets[state.seat]
    pot = state.pot
    target = int(round(mine + to_call + _FRAC[size] * (pot + to_call)))
    target = max(target, state.min_raise_to)
    target = min(target, state.max_raise_to)
    # don't leave a sliver behind: commit when the rest is < ~40% of the new pot
    if state.max_raise_to - target < 0.4 * (pot + target - mine):
        return state.all_in()
    return state.raise_to(target)


class _Ctx:
    pass


class PostflopStrategy:
    def __init__(self, tracker, rng):
        self.tracker = tracker
        self.rng = rng

    # ------------------------------------------------------------ context
    def _ctx(self, state, info, tex) -> _Ctx:
        c = _Ctx()
        n = state.num_players
        me = state.seat
        c.info, c.tex, c.rng = info, tex, self.rng
        c.hc = info.hc
        c.street = state.street
        c.to_call = state.to_call
        c.facing = state.to_call > 0
        c.pot = state.pot
        c.opps = [s for s in range(n) if not state.folded[s] and s != me]
        c.n_opps = max(len(c.opps), 1)
        first = (state.button + 1) % n
        my_pos = (me - first) % n
        c.after = [s for s in c.opps if state.stacks[s] > 0 and (s - first) % n > my_pos]
        c.pot_odds = state.to_call / (state.pot + state.to_call) if state.to_call else 0.0
        c.frac = state.to_call / max(state.pot - state.to_call, 1)
        pf_raisers = [h[1] for h in state.history if h[0] == "preflop" and h[2] == "raise"]
        c.is_pfr = bool(pf_raisers) and pf_raisers[-1] == me
        c.stack_pot = state.my_stack / max(state.pot, 1)

        cls = lambda s: self.tracker.classify(state.player_at(s))
        c.opp_cls = [cls(s) for s in c.opps]
        c.table = self._table_class(c.opp_cls)
        c.oa_after = any(cls(s) is OC.OVER_AGGRESSIVE for s in c.after)
        # who bet/raised into us this street?
        bettor = None
        raises_this_street = 0
        for h in state.history:
            if h[0] == state.street and h[2] == "raise":
                bettor = h[1]
                raises_this_street += 1
        c.bettor_cls = cls(bettor) if bettor is not None and bettor != me else c.table
        c.facing_raise = raises_this_street >= 2 or (
            raises_this_street == 1 and bettor is not None and bettor != me
            and any(h[0] == state.street and h[1] == me and h[2] == "raise" for h in state.history)
        )
        return c

    @staticmethod
    def _table_class(classes):
        if not classes:
            return OC.BALANCED_GTO
        for want in (OC.CALLING_STATION, OC.OVER_AGGRESSIVE):
            if want in classes:
                return want
        if all(k is OC.TIGHT_FOLD for k in classes):
            return OC.TIGHT_FOLD
        return OC.BALANCED_GTO

    # ------------------------------------------------------------ entry
    def decide(self, state, info, tex):
        c = self._ctx(state, info, tex)
        size = self._facing(c) if c.facing else self._open(c)
        return to_action(state, size)

    # ------------------------------------------------------------ no bet to face
    def _open(self, c) -> Size:
        r = c.rng.random
        hc, prof, tex, st = c.hc, c.table, c.tex, c.street
        river = st == "river"
        multi = c.n_opps >= 3
        S = Size

        if hc is HC.NUT_HAND or (hc is HC.STRONG_MADE and c.info.top_tier):
            # induce bluffs from maniacs who still act after us
            if prof is OC.OVER_AGGRESSIVE and c.oa_after and r() < 0.8:
                return S.CHECK_FOLD
            if prof is OC.CALLING_STATION:
                return S.ALL_IN if (river or c.stack_pot <= 1.3) else S.BET_100
            if prof is OC.TIGHT_FOLD:
                return S.BET_33 if st == "flop" else S.BET_66
            if hc is HC.NUT_HAND:
                return S.BET_100 if (river or tex is not Texture.DRY) else S.BET_66
            return S.BET_66

        if hc is HC.STRONG_MADE:
            if prof is OC.OVER_AGGRESSIVE and c.oa_after and r() < 0.5:
                return S.CHECK_FOLD
            if prof is OC.CALLING_STATION:
                return S.BET_66
            if prof is OC.TIGHT_FOLD:
                return S.BET_33
            return S.BET_66

        if hc is HC.MEDIUM_MADE:
            if prof is OC.CALLING_STATION:
                return S.BET_66 if c.info.eq >= 0.36 else S.BET_33
            if prof is OC.TIGHT_FOLD:
                return S.BET_33 if r() < 0.5 else S.CHECK_FOLD
            if prof is OC.BALANCED_GTO and c.n_opps == 1 and not river and tex is Texture.DRY and r() < 0.3:
                return S.BET_33
            return S.CHECK_FOLD

        if hc is HC.STRONG_DRAW:
            freq = {OC.CALLING_STATION: 0.5, OC.OVER_AGGRESSIVE: 0.3, OC.TIGHT_FOLD: 0.7}.get(prof, 0.65)
            if multi:
                freq *= 0.5
            return S.BET_66 if r() < freq else S.CHECK_FOLD

        # WEAK_DRAW / TRASH: bluffs
        if multi or prof in (OC.CALLING_STATION, OC.OVER_AGGRESSIVE):
            return S.CHECK_FOLD
        if prof is OC.TIGHT_FOLD:
            if tex is Texture.DRY:
                p = 0.5 if river else (0.65 if hc is HC.TRASH else 0.6)
            else:
                p = 0.25
            return S.BET_33 if r() < p else S.CHECK_FOLD
        # balanced / unknown: modest c-bet, rare river bluff
        if c.n_opps == 1 and c.is_pfr and st == "flop" and tex is Texture.DRY:
            return S.BET_33 if r() < 0.4 else S.CHECK_FOLD
        if c.n_opps == 1 and river and hc is HC.TRASH and r() < 0.10:
            return S.BET_66
        return S.CHECK_FOLD

    # ------------------------------------------------------------ facing a bet
    def _adj_equity(self, c) -> float:
        info, hc = c.info, c.hc
        eq = info.eq
        if hc is not HC.NUT_HAND:
            eq *= 0.93 ** (c.n_opps - 1)
        made = hc in (HC.STRONG_MADE, HC.MEDIUM_MADE)
        b = c.bettor_cls
        if b is OC.OVER_AGGRESSIVE and made:
            eq = min(0.9, eq * 1.3)  # widen: they bluff a lot
        elif b is OC.TIGHT_FOLD and (c.frac > 0.5 or c.facing_raise):
            if hc is HC.STRONG_MADE:
                eq *= 0.85
            elif hc is HC.MEDIUM_MADE:
                eq *= 0.65
        elif b is OC.CALLING_STATION:
            if made:
                eq *= 0.95
            elif hc in (HC.STRONG_DRAW, HC.WEAK_DRAW) and c.street != "river":
                eq *= 1.15  # implied odds
        return eq

    def _facing(self, c) -> Size:
        r = c.rng.random
        hc, b = c.hc, c.bettor_cls
        S = Size
        eq = self._adj_equity(c)
        call_ok = eq >= c.pot_odds + 0.02
        result = None

        if hc is HC.NUT_HAND:
            result = S.BET_100 if r() < 0.9 else None
        elif hc is HC.STRONG_MADE:
            if c.info.top_tier and b is OC.CALLING_STATION and r() < 0.5:
                result = S.BET_66
        elif hc is HC.STRONG_DRAW:
            if (c.street == "flop" and b is OC.BALANCED_GTO and c.n_opps == 1
                    and not c.facing_raise and r() < 0.25):
                result = S.BET_66  # semi-bluff raise

        if result is not None:
            return result
        return S.CALL if call_ok else S.CHECK_FOLD
