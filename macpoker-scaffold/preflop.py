"""Preflop policy: solver-style range tables, nudged by position and by what
each opponent has done so far this game (see preflop_memory).

Flow: classify the spot from the action history, pick a ladder level from
the relevant player's position, shift it from their stats, then look up our
hand. Everything is set lookups, so a decision costs microseconds.
"""

from __future__ import annotations

import ranges as R
from preflop_memory import PreflopMemory


# ------------------------------------------------------------ table geometry
def position(n: int, seat: int, button: int) -> str:
    if n == 2:
        return "HU" if seat == button else "BB"
    rel = (seat - button) % n
    if rel == 1:
        return "SB"
    if rel == 2:
        return "BB"
    return {0: "BTN", 1: "CO", 2: "HJ"}.get((button - seat) % n, "LJ")


def preflop_order(n: int, button: int) -> list[int]:
    first = button if n == 2 else (button + 3) % n
    return [(first + i) % n for i in range(n)]


def _clamp(x: int, ladder: list) -> int:
    return max(0, min(len(ladder) - 1, x))


class _Spot:
    """What has happened preflop before our decision."""

    def __init__(self, state):
        self.raises: list[tuple[int, int]] = []  # (seat, raise-to)
        self.limpers: list[int] = []
        self.callers: list[int] = []  # flat calls after the last raise
        for street, seat, kind, amt in state.history:
            if street != "preflop":
                continue
            if kind == "raise":
                self.raises.append((seat, amt))
                self.callers = []
            elif kind == "call":
                (self.callers if self.raises else self.limpers).append(seat)


# ------------------------------------------------------------ main entry
def preflop_action(state, rng, bb: int, memory: PreflopMemory | None = None):
    mem = memory or PreflopMemory()
    n, me, btn = state.num_players, state.seat, state.button
    hand = R.hand_code(state.hole)
    pos = position(n, me, btn)
    spot = _Spot(state)
    to_call = state.to_call
    my_total = state.my_stack + state.street_bets[me]
    pid = state.player_at

    def raise_to(x):
        if not state.can_raise:
            return passive()
        x = int(max(state.min_raise_to, min(x, state.max_raise_to)))
        if x >= 0.45 * my_total:  # committing anyway: just jam
            return state.all_in()
        return state.raise_to(x)

    def passive():
        return state.call() if to_call > 0 else state.check()

    def fold():
        return state.check() if to_call == 0 else state.fold()

    # --- facing a jam or a raise big enough to be a call-off decision
    if to_call > 0 and to_call >= 0.4 * my_total and spot.raises:
        jammer = pid(spot.raises[-1][0])
        lvl = 0
        if mem.rate(jammer, "jam") >= 0.25 or mem.player_type(jammer) == "maniac":
            lvl = 2
        elif mem.rate(jammer, "jam") >= 0.08 or mem.rate(jammer, "pfr") >= 0.28:
            lvl = 1
        if mem.rate(jammer, "jam") >= 0.5:
            lvl = 3
        need = to_call / (state.pot + to_call)
        lvl += (need < 0.40) + (need < 0.30)
        lvl -= bool(spot.callers)  # someone already called the jam
        lvl -= _left_to_act(state, spot) >= 2
        return state.call() if hand in R.CALL_JAM[_clamp(lvl, R.CALL_JAM)] else fold()

    # --- nobody has raised yet
    if not spot.raises:
        if spot.limpers:
            return _limped(state, mem, spot, hand, pos, bb, raise_to, passive, fold)
        if pos == "BB":
            return state.check()
        lvl = R.OPEN_LEVEL[pos] + _steal_shift(state, mem)
        if hand in R.OPEN[_clamp(lvl, R.OPEN)]:
            size = 3.0 if pos == "SB" else 2.5
            if _station_behind(state, mem):
                size += 0.5
            return raise_to(size * bb)
        return fold()

    raiser_seat, raise_amt = spot.raises[-1]
    raiser = pid(raiser_seat)
    rpos = position(n, raiser_seat, btn)
    rtype = mem.player_type(raiser)
    my_raises = [s for s, _ in spot.raises if s == me]

    # --- one raise in front of us
    if len(spot.raises) == 1:
        shift = 0
        rfi = mem.rate(raiser, "rfi")
        shift += (rfi >= 0.40) + (rfi >= 0.60) - (rfi <= 0.12)
        if rtype == "maniac":
            shift = max(shift, 1)
        elif rtype == "nit":
            shift = min(shift, -1)
        base = R.VS_OPEN_LEVEL.get(rpos, 2) + shift
        squeeze = bool(spot.callers)
        tb = R.THREEBET[_clamp(base - squeeze + (pos == "SB"), R.THREEBET)]
        if not squeeze and rtype != "station":
            f3b = mem.rate(raiser, "fold_to_3bet")
            if f3b >= 0.70:
                tb = tb | R.THREEBET_BLUFF[1]
            elif f3b >= 0.60:
                tb = tb | R.THREEBET_BLUFF[0]
        if hand in tb:
            in_pos = pos not in ("SB", "BB")
            mult = (3.0 if in_pos else 4.0) + len(spot.callers)
            if rtype == "station":
                mult += 0.5
            return raise_to(mult * raise_amt)
        if pos == "BB":
            lvl = R.BB_DEFEND_LEVEL.get(rpos, 1) + max(shift, 0)
            lvl -= (raise_amt > 3 * bb) + (raise_amt > 5 * bb)
            call = R.BB_DEFEND[min(lvl, 2)] if lvl >= 0 else R.CALL[0]
        else:
            lvl = base - (pos == "SB") - (raise_amt > 4 * bb)
            call = R.CALL[_clamp(lvl, R.CALL)]
        return state.call() if hand in call else fold()

    # --- we opened and face a 3-bet
    if len(spot.raises) == 2 and my_raises:
        tb_rate = mem.rate(raiser, "threebet")
        lvl = 1 + (tb_rate >= 0.14) + (tb_rate >= 0.25) - (rtype == "nit")
        if rtype == "maniac":
            lvl = max(lvl, 2)
        in_pos = rpos in ("SB", "BB") and pos not in ("SB", "BB")
        if hand in R.FOURBET[_clamp(lvl, R.FOURBET)]:
            return raise_to((2.3 if in_pos else 2.6) * raise_amt)
        clvl = lvl - (not in_pos) - (raise_amt > 5 * spot.raises[0][1])
        return state.call() if hand in R.CALL_3BET[_clamp(clvl, R.CALL_3BET)] else fold()

    # --- cold facing a 3-bet (open + 3-bet in front, we have not raised)
    if len(spot.raises) == 2:
        lvl = (rtype == "maniac") - (rtype == "nit")
        four = R.FOURBET[_clamp(lvl + 1, R.FOURBET)] if lvl >= 0 else R.FOURBET[0]
        if hand in four:
            return state.all_in() if state.can_raise else passive()
        cold_call = R.COLD_CALL_3BET[lvl > 0]
        return state.call() if hand in cold_call and hand not in four else fold()

    # --- 4-bet or more: jam or fold
    lvl = 1 + (rtype == "maniac") - (rtype == "nit")
    if hand in R.FOURBET[_clamp(lvl, R.FOURBET)]:
        return state.all_in() if state.can_raise else passive()
    return fold()


# ------------------------------------------------------------ limped pots
def _limped(state, mem, spot, hand, pos, bb, raise_to, passive, fold):
    stations = sum(mem.player_type(state.player_at(s)) == "station" for s in spot.limpers)
    lvl = 1 + (pos in ("BTN", "CO", "HU")) - (pos in ("LJ", "SB"))
    lvl += stations == len(spot.limpers)  # value-raise wider vs pure callers
    if hand in R.ISO[_clamp(lvl, R.ISO)]:
        size = (4 + len(spot.limpers) + (stations > 0)) * bb
        if pos in ("SB", "BB"):
            size += bb
        return raise_to(size)
    if pos == "BB" or state.to_call == 0:
        return state.check()
    if hand in R.OVERLIMP and (pos in ("BTN", "CO", "SB") or len(spot.limpers) >= 2):
        return passive()
    return fold()


# ------------------------------------------------------------ opponent reads
def _behind(state) -> list[int]:
    """Player ids still to act after us preflop (unopened pot)."""
    order = preflop_order(state.num_players, state.button)
    i = order.index(state.seat)
    return [state.player_at(s) for s in order[i + 1:] if not state.folded[s]]


def _left_to_act(state, spot) -> int:
    order = preflop_order(state.num_players, state.button)
    acted = {s for s, _ in spot.raises} | set(spot.callers)
    i = order.index(state.seat)
    return sum(1 for s in order[i + 1:] if not state.folded[s] and s not in acted)


def _steal_shift(state, mem) -> int:
    """Open wider when everyone behind over-folds, tighter vs aggression."""
    behind = _behind(state)
    if not behind:
        return 0
    types = [mem.player_type(p) for p in behind]
    if "maniac" in types:
        return -1
    if "station" in types:
        return 0
    avg_fold = sum(mem.rate(p, "fold_to_open") for p in behind) / len(behind)
    return (avg_fold >= 0.80) + (avg_fold >= 0.90)


def _station_behind(state, mem) -> bool:
    return any(mem.player_type(p) == "station" for p in _behind(state))
