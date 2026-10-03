"""Per-opponent preflop stats, keyed by stable player id.

Each rate is shrunk toward a population prior, so a few hands of evidence
move it a little and a lot of evidence moves it a lot:

    rate = (hits + PRIOR_WEIGHT * prior) / (opportunities + PRIOR_WEIGHT)

Only behaviour is recorded, never cards.
"""

from __future__ import annotations

from collections import defaultdict

PRIOR_WEIGHT = 8.0

# stat -> (prior rate, opportunity counter it is divided by)
PRIORS = {
    "vpip": (0.30, "hands"),
    "pfr": (0.18, "hands"),
    "jam": (0.02, "hands"),           # preflop all-in raises
    "rfi": (0.25, "rfi_opp"),         # opens when folded to
    "limp": (0.10, "rfi_opp"),        # limps when folded to
    "fold_to_open": (0.70, "open_opp"),
    "threebet": (0.08, "open_opp"),
    "fold_to_3bet": (0.55, "f3b_opp"),
}


class PreflopMemory:
    def __init__(self):
        self.me: int | None = None
        self.n: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    def set_me(self, pid: int) -> None:
        self.me = pid

    # ------------------------------------------------------------ observe
    def observe_hand(self, events, players, button, start_stacks):
        """Digest one finished hand. `events` are SDK action messages in order
        (street, seat, action, amount); raise amounts are raise-to totals."""
        n = len(players)
        if n < 2:
            return
        for pid in players:
            self.n[pid]["hands"] += 1
        raises = 0
        limpers = 0
        opener = None
        vpip: set[int] = set()
        pfr: set[int] = set()
        jam: set[int] = set()
        for ev in events:
            if ev.get("street") != "preflop":
                break
            s = ev.get("seat", -1)
            if not 0 <= s < n:
                continue
            c = self.n[players[s]]
            k = ev.get("action")
            if raises == 0 and limpers == 0:
                c["rfi_opp"] += 1
                c["rfi"] += k == "raise"
                c["limp"] += k == "call"
            elif raises == 1 and s != opener:
                c["open_opp"] += 1
                c["fold_to_open"] += k == "fold"
                c["threebet"] += k == "raise"
            elif raises == 2 and s == opener:
                c["f3b_opp"] += 1
                c["fold_to_3bet"] += k == "fold"
            if k in ("call", "raise"):
                vpip.add(s)
            if k == "raise":
                pfr.add(s)
                raises += 1
                if raises == 1:
                    opener = s
                if start_stacks and s < len(start_stacks) and ev.get("amount", 0) >= start_stacks[s]:
                    jam.add(s)
            elif k == "call" and raises == 0:
                limpers += 1
        for name, seats in (("vpip", vpip), ("pfr", pfr), ("jam", jam)):
            for s in seats:
                self.n[players[s]][name] += 1

    # ------------------------------------------------------------ query
    def hands(self, pid) -> int:
        return self.n[pid]["hands"] if pid in self.n else 0

    def rate(self, pid, stat: str) -> float:
        prior, opp = PRIORS[stat]
        c = self.n.get(pid)
        if c is None:
            return prior
        return (c[stat] + PRIOR_WEIGHT * prior) / (c[opp] + PRIOR_WEIGHT)

    def confidence(self, pid, stat: str) -> float:
        """0..1: share of rate() that comes from observed play, not the prior."""
        c = self.n.get(pid)
        k = c[PRIORS[stat][1]] if c is not None else 0
        return k / (k + PRIOR_WEIGHT)

    def player_type(self, pid) -> str:
        """maniac / station / nit / regular."""
        r = lambda s: self.rate(pid, s)
        if r("pfr") >= 0.35 or r("jam") >= 0.12 or r("threebet") >= 0.22:
            return "maniac"
        if r("vpip") >= 0.45 and r("pfr") < 0.5 * r("vpip"):
            return "station"
        if r("fold_to_open") <= 0.40:
            return "station"
        if r("vpip") <= 0.15:
            return "nit"
        return "regular"
