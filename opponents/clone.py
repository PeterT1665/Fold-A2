"""Behavioural clones of real ladder bots, fitted by tools/v4/fit.py (opponents/clone_data.json).

Each decision: same situation key the fit used (street, facing size, hand-strength bucket), then sample
fold / call / raise / check from that bot's own counts, smoothed toward the whole field, and a raise
size the bot really used in that spot. Not shipped.
"""
import json, os, random, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "v4"))
from macpoker import Bot
from cards7 import parse, bucket, hand_class
from keys import pf_sbucket, pf_pos, pf_key, facing_bucket, post_key
from pf_table import PF

_DATA = None
PRIOR = 4.0  # pseudo-counts of field behaviour mixed into each bot's table


def data():
    global _DATA
    if _DATA is None:
        _DATA = json.load(open(os.path.join(ROOT, "opponents", "clone_data.json")))
    return _DATA


class CloneBot(Bot):
    def __init__(self, name="*", seed="0"):
        self.cname = name
        self.rng = random.Random(f"{name}:{seed}")
        d = data()["tables"]
        self.mine = d.get(name, {})
        self.field = d["*"]

    def _dist(self, key, legal):
        m = self.mine.get(key)
        f = self.field.get(key)
        w = {}
        fn = sum(f[a] for a in legal) if f else 0
        for a in legal:
            v = (m[a] if m else 0) + (PRIOR * f[a] / fn if fn else 0)
            w[a] = v
        if sum(w.values()) <= 0:
            return None
        return w

    def _size(self, key):
        m = self.mine.get(key)
        szs = (m or {}).get("sz") or (self.field.get(key) or {}).get("sz") or []
        if m and len(m.get("sz", [])) < 3 and self.field.get(key) and self.rng.random() < 0.3:
            szs = self.field[key]["sz"] or szs
        return self.rng.choice(szs) if szs else None

    def act(self, s):
        hole = [parse(c) for c in s.hole]
        board = [parse(c) for c in s.board]
        n = len(s.stacks)
        hist = [h for h in s.history if h[0] == s.street]
        nr = sum(1 for h in hist if h[2] == "raise")
        if not board:
            key = pf_key(nr, pf_pos(s.seat, n), pf_sbucket(PF[hand_class(*hole)][2]))
        else:
            st = {"flop": 1, "turn": 2, "river": 3}[s.street]
            key = post_key(st, facing_bucket(s.to_call, s.pot, nr), bucket(hole, board))
        if s.to_call > 0:
            legal = ["f", "c"] + (["r"] if s.can_raise else [])
        else:
            legal = ["x"] + (["r"] if s.can_raise else [])
            if not board:
                # preflop with nothing to call (big blind option): the fit logs that as check
                pass
        w = self._dist(key, legal)
        if not w:
            return s.check() if s.to_call == 0 else s.fold()
        r = self.rng.random() * sum(w.values())
        a = legal[-1]
        for k in legal:
            r -= w[k]
            if r <= 0:
                a = k
                break
        if a == "f":
            return s.fold()
        if a in ("x", "c"):
            return s.check() if s.to_call == 0 else s.call()
        sz = self._size(key)
        if sz is None:
            return s.call() if s.to_call else s.check()
        if sz < 0:
            return s.all_in()
        if not board:
            to = int(round(sz * 2))
        else:
            cur = max(s.street_bets)
            if s.to_call == 0:
                to = s.street_bets[s.seat] + int(round(sz * s.pot))
            else:
                to = cur + int(round(sz * (s.pot + s.to_call)))
        to = max(s.min_raise_to, min(to, s.max_raise_to))
        return s.raise_to(to)
