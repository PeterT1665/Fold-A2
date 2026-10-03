"""Like preflop-warrior: VPIP~42 PFR~12, calls a lot, folds ~30% to bets, bets ~0.6 pot."""
from _ladder_base import LadderBot


class LadderStation(LadderBot):
    name = "ladder_station"
    seed = 102
    open_t, call_t, three_t = 8.5, 2.5, 12.0
    p_bet = (0.7, 0.25, 0.05)
    bet_size = 0.6
    f_mid, f_weak, p_raise = 0.1, 0.5, 0.05
