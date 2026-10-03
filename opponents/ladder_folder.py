"""Like tungbot / the GOON / BigBaller: VPIP 25-35, PFR 14-18, bets big, folds ~70% to bets."""
from _ladder_base import LadderBot


class LadderFolder(LadderBot):
    name = "ladder_folder"
    seed = 103
    open_t, call_t, three_t = 7.5, 4.5, 11.0
    p_bet = (0.85, 0.45, 0.15)
    bet_size = 1.1
    f_mid, f_weak, p_raise = 0.65, 0.92, 0.1
