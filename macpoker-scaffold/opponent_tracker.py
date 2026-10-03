"""In-memory opponent profiler. Stats are keyed by the SDK's stable player id
and accumulate for the whole game (a fresh bot instance is made per game)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from postflop_evaluator import HandClass, PostFlopEvaluator

_EV = PostFlopEvaluator()

MIN_HANDS = 10


class OpponentClass(Enum):
    CALLING_STATION = "CALLING_STATION"
    TIGHT_FOLD = "TIGHT_FOLD"
    OVER_AGGRESSIVE = "OVER_AGGRESSIVE"
    BALANCED_GTO = "BALANCED_GTO"


@dataclass
class PlayerStats:
    hands: int = 0
    vpip: int = 0
    pfr: int = 0
    post_bets: int = 0
    post_raises: int = 0
    post_calls: int = 0
    post_checks: int = 0
    post_folds: int = 0
    facing: int = 0  # postflop decisions facing a bet
    facing_folds: int = 0
    big_facing: int = 0  # ... facing a bet > 50% pot
    big_folds: int = 0
    cbet_faced: int = 0
    cbet_folds: int = 0
    showdowns: int = 0
    bet_frac_sum: float = 0.0
    big_sd: int = 0  # big postflop bets (>= 70% pot) seen at showdown
    big_sd_weak: int = 0  # ... where the final hand was medium or worse

    # ---- derived (small Bayesian prior so early reads are not extreme) ----
    @staticmethod
    def _rate(x: int, n: int, prior: float, k: float = 3.0) -> float:
        return (x + prior * k) / (n + k)

    @property
    def vpip_pct(self) -> float:
        return self._rate(self.vpip, self.hands, 0.30)

    @property
    def pfr_pct(self) -> float:
        return self._rate(self.pfr, self.hands, 0.18)

    @property
    def fold_to_bet(self) -> float:
        return self._rate(self.facing_folds, self.facing, 0.45)

    @property
    def fold_to_big(self) -> float:
        return self._rate(self.big_folds, self.big_facing, 0.50)

    @property
    def fold_to_cbet(self) -> float:
        return self._rate(self.cbet_folds, self.cbet_faced, 0.45)

    @property
    def aggressive_acts(self) -> int:
        return self.post_bets + self.post_raises

    @property
    def aggression_factor(self) -> float:
        return self.aggressive_acts / max(self.post_calls, 1)

    @property
    def agg_freq(self) -> float:
        n = self.aggressive_acts + self.post_calls + self.post_checks + self.post_folds
        return self.aggressive_acts / n if n else 0.0

    @property
    def showdown_freq(self) -> float:
        return self.showdowns / self.hands if self.hands else 0.0


class OpponentTracker:
    def __init__(self, blinds=(1, 2)):
        self.blinds = tuple(blinds)
        self.stats: dict[int, PlayerStats] = {}
        self._cache: dict[int, tuple[int, OpponentClass]] = {}

    def get(self, player: int) -> PlayerStats:
        st = self.stats.get(player)
        if st is None:
            st = self.stats[player] = PlayerStats()
        return st

    # ------------------------------------------------------------ observe
    def observe_hand(self, events: list[dict], players: list[int], showdown_seats=(),
                     revealed=None, board=None):
        """Digest one finished hand. `events` are the SDK 'action' messages in
        order (street, seat, action, amount[, pot]); raise amounts are raise-to."""
        n = len(players)
        for p in players:
            self.get(p).hands += 1
        pot = sum(self.blinds)
        street = "preflop"
        street_bet = [0] * n
        cur = 0
        pf_raiser = None
        vpip: set[int] = set()
        pfr: set[int] = set()
        cbet_open = False
        big_bettors: set[int] = set()

        for ev in events:
            s = ev["seat"]
            if not 0 <= s < n:
                continue
            st = self.get(players[s])
            k = ev["action"]
            amt = ev.get("amount", 0) or 0
            if ev["street"] != street:
                street = ev["street"]
                street_bet = [0] * n
                cur = 0
                cbet_open = False
            if street == "preflop":
                if k == "call":
                    vpip.add(s)
                elif k == "raise":
                    vpip.add(s)
                    pfr.add(s)
                    pf_raiser = s
            else:
                faced = cur - street_bet[s]
                if faced > 0 and k in ("call", "fold", "raise"):
                    frac = faced / max(pot - faced, 1)
                    st.facing += 1
                    st.facing_folds += k == "fold"
                    if frac > 0.5:
                        st.big_facing += 1
                        st.big_folds += k == "fold"
                    if cbet_open:
                        st.cbet_faced += 1
                        st.cbet_folds += k == "fold"
                if k == "raise":
                    if cur == 0:
                        st.post_bets += 1
                        st.bet_frac_sum += (amt - street_bet[s]) / max(pot, 1)
                        if (amt - street_bet[s]) >= 0.7 * max(pot, 1):
                            big_bettors.add(s)
                        if street == "flop" and s == pf_raiser:
                            cbet_open = True
                    else:
                        st.post_raises += 1
                        cbet_open = False
                    street_bet[s] = amt
                    cur = amt
                elif k == "call":
                    st.post_calls += 1
                    street_bet[s] += amt
                elif k == "check":
                    st.post_checks += 1
                elif k == "fold":
                    st.post_folds += 1
            pot = ev.get("pot", pot) or pot

        for s in vpip:
            self.get(players[s]).vpip += 1
        for s in pfr:
            self.get(players[s]).pfr += 1
        for s in showdown_seats:
            if 0 <= s < n:
                self.get(players[s]).showdowns += 1
        # did their big bets turn out strong? (hand strength only, shown at showdown)
        if revealed and board and len(board) == 5:
            for s in big_bettors:
                hole = revealed.get(str(s)) or revealed.get(s)
                if hole:
                    st = self.get(players[s])
                    st.big_sd += 1
                    st.big_sd_weak += _EV.evaluate(hole, board).hc <= HandClass.MEDIUM_MADE

    # ------------------------------------------------------------ classify
    def classify(self, player: int) -> OpponentClass:
        st = self.stats.get(player)
        if st is None or st.hands < MIN_HANDS:
            return OpponentClass.BALANCED_GTO
        cached = self._cache.get(player)
        if cached and cached[0] == st.hands:
            return cached[1]
        res = self._classify(st)
        self._cache[player] = (st.hands, res)
        return res

    @staticmethod
    def _classify(st: PlayerStats) -> OpponentClass:
        aggro_n = st.aggressive_acts
        if (aggro_n >= 6 and st.agg_freq >= 0.40 and st.aggression_factor >= 2.0) or (
            st.pfr_pct >= 0.45 and st.vpip_pct >= 0.55
        ):
            return OpponentClass.OVER_AGGRESSIVE
        if st.vpip_pct >= 0.50 and st.agg_freq < 0.40 and (
            st.facing < 5 or st.fold_to_bet <= 0.30
        ):
            return OpponentClass.CALLING_STATION
        if (
            (st.big_facing >= 4 and st.fold_to_big >= 0.60)
            or (st.cbet_faced >= 4 and st.fold_to_cbet >= 0.65)
            or (st.facing >= 6 and st.fold_to_bet >= 0.65)
            or (st.hands >= 15 and st.vpip_pct <= 0.10)
        ):
            return OpponentClass.TIGHT_FOLD
        return OpponentClass.BALANCED_GTO
