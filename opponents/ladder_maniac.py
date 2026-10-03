"""Like merch-where: VPIP~44 PFR~38, bets nearly every spot ~0.9 pot, folds ~80% to bets."""
from _ladder_base import LadderBot


class LadderManiac(LadderBot):
    name = "ladder_maniac"
    seed = 101
    open_t, call_t, three_t = 3.5, 3.5, 9.0
    p_bet = (0.97, 0.92, 0.88)
    bet_size = 0.9
    f_mid, f_weak, p_raise = 0.7, 0.97, 0.12
