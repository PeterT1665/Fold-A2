"""Like let-it-go / RaiseYourEdge: VPIP~13, PFR 0-6, folds a lot."""
from _ladder_base import LadderBot


class LadderNit(LadderBot):
    name = "ladder_nit"
    seed = 104
    open_t, call_t, three_t = 8.5, 7.5, 12.0
    p_bet = (0.6, 0.15, 0.0)
    bet_size = 0.55
    f_mid, f_weak, p_raise = 0.6, 0.9, 0.05
