"""Fold-A2 v4: range-tracking, expected-value poker bot.

Every decision:
  1. Rebuild each live opponent's range (1326 combos) from this hand's actions, weighting every combo
     by how often the ladder field takes that action with that hand class (field_model.py), tempered by
     this opponent's own observed looseness and aggression.
  2. Monte-Carlo our showdown equity against those ranges (one joint sample set, reweighted per scenario).
  3. Score check / call / fold / each bet size by expected chips, using the field's fold/call/raise
     frequencies per hand class to predict how each opponent answers each size.
Preflop is a percentile-range strategy adjusted to the raiser's observed opening frequency.
"""
import bisect
import random
import time

from cards7 import ALL_COMBOS, bucket, evaluate, hand_class, parse
from field_model import FIELD
from keys import facing_bucket, pf_key, pf_pos, pf_sbucket, post_key
from pf_table import PF

OVERBET_CAP = 1.6
STREET_NO = {"preflop": 0, "flop": 1, "turn": 2, "river": 3}
NC = len(ALL_COMBOS)
COMBO_PCT = [PF[hand_class(a, b)][2] for a, b in ALL_COMBOS]
COMBO_SB = [pf_sbucket(p) for p in COMBO_PCT]
COMBO_MASK = [(1 << a) | (1 << b) for a, b in ALL_COMBOS]


# ------------------------------------------------------------------ field likelihood tables
def _probs(t):
    """counts (f, c, x, r0..r3) -> smoothed probabilities of the same shape."""
    f, c, x, *rb = t
    tot = f + c + x + sum(rb)
    k = 1.0
    return tuple((v + k * 0.15) / (tot + k) for v in (f, c, x, *rb))


_PROB = {k: _probs(v) for k, v in FIELD.items()}
_DEFAULT = (0.4, 0.3, 0.2, 0.025, 0.025, 0.025, 0.025)


def field_p(key):
    return _PROB.get(key, _DEFAULT)


def _field_avg(prefixes, idx_num, idx_den):
    num = den = 0
    for k, v in FIELD.items():
        if k[:2] in prefixes and k[2] != "0":
            num += sum(v[i] for i in idx_num)
            den += sum(v[i] for i in idx_den)
    return num / max(den, 1)


FIELD_FOLD = _field_avg(("s1", "s2", "s3"), (0,), (0, 1, 3, 4, 5, 6))  # fold rate facing a postflop bet


def _field_bet_rate():
    num = den = 0
    for k, v in FIELD.items():
        if k[0] == "s" and k[2] == "0":
            num += sum(v[3:]); den += sum(v[2:])
    return num / max(den, 1)


FIELD_BET = _field_bet_rate()  # bet rate when checked to


def _field_vpip():
    num = den = 0
    for k, v in FIELD.items():
        if k[0] == "p":
            num += v[1] + sum(v[3:]); den += sum(v)
    return num / max(den, 1)


FIELD_VPIP = _field_vpip()


def size_bin(size):
    if size >= 1.2:
        return 3
    return 0 if size < 0.45 else (1 if size < 0.8 else 2)


# ------------------------------------------------------------------ opponent stats (whole game)
class Stats:
    __slots__ = ("hands", "vpip", "pfr", "faced", "folded", "post_ops", "post_agg", "opens", "open_ops")

    def __init__(self):
        self.hands = self.vpip = self.pfr = 0
        self.faced = self.folded = 0
        self.post_ops = self.post_agg = 0
        self.opens = self.open_ops = 0

    def fold_mult(self):
        r = (self.folded + FIELD_FOLD * 8) / (self.faced + 8)
        return max(0.03, min(1.7, r / FIELD_FOLD))

    def aggr(self):
        r = (self.post_agg + FIELD_BET * 10) / (self.post_ops + 10)
        return max(0.5, min(2.6, r / FIELD_BET))

    def loose(self):
        r = (self.vpip + FIELD_VPIP * 10) / (self.hands + 10)
        return max(0.5, min(2.5, r / FIELD_VPIP))

    def open_rate(self):
        return (self.opens + 0.2 * 8) / (self.open_ops + 8)


# ------------------------------------------------------------------ hand replay
class Replay:
    """Walks a hand's action list, yielding the situation before each action."""

    def __init__(self, n, sb, bb):
        self.n = n
        self.contrib = [0] * n
        self.sbet = [0] * n
        self.folded = [False] * n
        if n == 2:
            sbs, bbs = 0, 1
        else:
            sbs, bbs = 1, 2
        self.contrib[sbs] = self.sbet[sbs] = sb
        self.contrib[bbs] = self.sbet[bbs] = bb
        self.street = 0
        self.nr = 0
        self.stack0 = None

    def new_street(self, st):
        self.street = st
        self.sbet = [0] * self.n
        self.nr = 0

    def apply(self, seat, kind, amt):
        if kind == "fold":
            self.folded[seat] = True
        elif kind == "call":
            self.contrib[seat] += amt; self.sbet[seat] += amt
        elif kind == "raise":
            add = amt - self.sbet[seat]
            self.contrib[seat] += add; self.sbet[seat] = amt
            self.nr += 1


# ------------------------------------------------------------------ the bot logic
class Brain:
    def __init__(self):
        self.stats = {}
        self.n = 0
        self.sb, self.bb, self.stack = 1, 2, 200
        self.num_hands = 100
        self.rng = random.Random(20261004)
        self._bcache = {}
        self.hand_events = []
        self.hand_boards = {}
        self.cur_hand = -1

    # ---- game events ----
    def on_hello(self, msg):
        self.n = msg.get("num_players", 0)
        bl = msg.get("blinds") or [1, 2]
        self.sb, self.bb = bl[0], bl[1]
        self.stack = msg.get("stack", 200)
        self.num_hands = msg.get("num_hands", 100)

    def st(self, pid):
        s = self.stats.get(pid)
        if s is None:
            s = self.stats[pid] = Stats()
        return s

    def on_hand_start(self, msg):
        self.hand_events = []
        self.cur_hand = msg.get("hand", -1)
        self.players = msg.get("players")
        self._bcache = {}

    def on_action(self, ev):
        self.hand_events.append(ev)
        if ev.get("players"):
            self.players = ev["players"]

    def on_hand_end(self, msg):
        try:
            self._learn(self.hand_events, msg.get("players") or self.players)
        except Exception:
            pass

    def _learn(self, events, players):
        if not players:
            return
        n = len(players)
        rp = Replay(n, self.sb, self.bb)
        seen = set()
        vp = set(); pr = set()
        opened = False
        for ev in events:
            st = STREET_NO.get(ev.get("street"), 0)
            if st != rp.street:
                rp.new_street(st)
            s = ev["seat"]; kind = ev["action"]; amt = ev["amount"]
            pid = players[s]
            S = self.st(pid)
            seen.add(pid)
            cur = max(rp.sbet)
            to_call = cur - rp.sbet[s]
            if st == 0:
                if kind in ("call", "raise"):
                    vp.add(pid)
                if kind == "raise":
                    pr.add(pid)
                if not opened and rp.nr == 0 and pf_pos(s, n) != 2:
                    S.open_ops += 1
                    if kind == "raise":
                        S.opens += 1
                if kind == "raise":
                    opened = True
            else:
                S.post_ops += 1 if to_call == 0 else 0
                if to_call == 0 and kind == "raise":
                    S.post_agg += 1
                if to_call > 0:
                    S.faced += 1
                    if kind == "fold":
                        S.folded += 1
            rp.apply(s, kind, amt)
        for pid in players:
            S = self.st(pid)
            S.hands += 1
            if pid in vp:
                S.vpip += 1
            if pid in pr:
                S.pfr += 1

    # ---- buckets per board, cached ----
    def buckets(self, board):
        key = tuple(board)
        b = self._bcache.get(key)
        if b is None:
            bm = 0
            for c in board:
                bm |= 1 << c
            b = [-1] * NC
            for i, (x, y) in enumerate(ALL_COMBOS):
                if COMBO_MASK[i] & bm:
                    continue
                b[i] = bucket([x, y], board)
            self._bcache[key] = b
        return b

    # ---- ranges ----
    def ranges(self, s, hole, board):
        """Weights over all combos for every live opponent seat, from this hand's history."""
        n = len(s.stacks)
        dead = 0
        for c in hole + board:
            dead |= 1 << c
        base = [0.0 if COMBO_MASK[i] & dead else 1.0 for i in range(NC)]
        W = {}
        for seat in range(n):
            if seat != s.seat and not s.folded[seat]:
                W[seat] = list(base)
        rp = Replay(n, self.sb, self.bb)
        boards = {1: board[:3], 2: board[:4], 3: board[:5]}
        for street, seat, kind, amt in s.history:
            st = STREET_NO[street]
            if st != rp.street:
                rp.new_street(st)
            if seat in W and kind != "fold":
                pid = s.players[seat]
                S = self.st(pid)
                w = W[seat]
                cur = max(rp.sbet)
                to_call = cur - rp.sbet[seat]
                pot = sum(rp.contrib)
                if st == 0:
                    pos = pf_pos(seat, n)
                    loose = S.loose()
                    col = 1 if kind == "call" else (2 if kind == "check" else None)
                    tab = []
                    for sbk in range(10):
                        p = field_p(pf_key(rp.nr, pos, sbk))
                        v = sum(p[3:]) if col is None else p[col]
                        tab.append(v)
                    if kind == "raise" and rp.nr >= 1:
                        # big re-raises are strong: sharpen with raise size (bb)
                        pass
                    ex = 1.0 / loose
                    tab = [v ** ex for v in tab]
                    for i in range(NC):
                        if w[i]:
                            w[i] *= tab[COMBO_SB[i]]
                else:
                    bd = boards[st]
                    bk = self.buckets(bd)
                    fb = facing_bucket(to_call, pot, rp.nr)
                    if kind == "raise":
                        if to_call == 0:
                            size = (amt - rp.sbet[seat]) / max(pot, 1)
                        else:
                            size = (amt - cur) / max(pot + to_call, 1)
                        sb_ = size_bin(size if amt < self.stack else 9)
                        ex = 1.0 / S.aggr()
                        tab = []
                        for b in range(7):
                            p = field_p(post_key(st, fb, b))
                            rtot = sum(p[3:])
                            v = 0.9 * p[3 + sb_] + 0.1 * rtot / 4  # size-specific, smoothed
                            tab.append(v ** ex)
                    else:  # call / check
                        col = 1 if kind == "call" else 2
                        stick = (1 - min(0.9, FIELD_FOLD * S.fold_mult())) / (1 - FIELD_FOLD)
                        ex = 1.0 / max(0.5, min(3.0, stick)) if kind == "call" else 1.0
                        tab = []
                        for b in range(7):
                            p = field_p(post_key(st, fb, b))
                            tot = p[0] + p[1] + p[2] + sum(p[3:])
                            tab.append((p[col] / tot) ** ex)
                    for i in range(NC):
                        if w[i]:
                            bi = bk[i]
                            w[i] = w[i] * tab[bi] if bi >= 0 else 0.0
            rp.apply(seat, kind, amt)
        for seat, w in W.items():
            if sum(w) <= 0:
                W[seat] = list(base)
        return W

    # ---- Monte Carlo ----
    def simulate(self, hole, board, W, nsamp):
        seats = list(W)
        cums = {}
        for seat in seats:
            w = W[seat]
            cum = []
            t = 0.0
            for v in w:
                t += v
                cum.append(t)
            cums[seat] = (cum, t)
        dead0 = 0
        for c in hole + board:
            dead0 |= 1 << c
        need = 5 - len(board)
        deck = [c for c in range(52) if not dead0 >> c & 1]
        rng = self.rng
        samples = []
        for _ in range(nsamp):
            dead = dead0
            picks = []
            ok = True
            for seat in seats:
                cum, t = cums[seat]
                for _try in range(6):
                    i = bisect.bisect_right(cum, rng.random() * t)
                    if i >= NC:
                        i = NC - 1
                    m = COMBO_MASK[i]
                    if not m & dead:
                        break
                else:
                    ok = False
                    break
                dead |= m
                picks.append(i)
            if not ok:
                continue
            run = []
            while len(run) < need:
                c = deck[int(rng.random() * len(deck))]
                if not dead >> c & 1:
                    dead |= 1 << c
                    run.append(c)
            full = board + run
            me = evaluate(hole + full)
            best = -1
            nb = 0
            for i in picks:
                a, b = ALL_COMBOS[i]
                v = evaluate([a, b] + full)
                if v > best:
                    best, nb = v, 1
                elif v == best:
                    nb += 1
            r = 1.0 if me > best else (1.0 / (nb + 1) if me == best else 0.0)
            samples.append((picks, r))
        return seats, samples

    @staticmethod
    def eq(samples, factors=None):
        """Equity, optionally with per-opponent combo factors (list per opponent index)."""
        if not samples:
            return 0.0
        if factors is None:
            return sum(r for _, r in samples) / len(samples)
        num = den = 0.0
        for picks, r in samples:
            w = 1.0
            for k, i in enumerate(picks):
                w *= factors[k][i]
            num += w * r
            den += w
        return num / den if den > 1e-12 else 0.0

    # ---- response model to our bet ----
    def response(self, s, seat, w, bk, st, raise_to, pot_after, nr_after):
        """Per-combo fold / raise probability of `seat` facing our bet, and their averages."""
        S = self.st(s.players[seat])
        tc = max(0, min(raise_to - s.street_bets[seat], s.stacks[seat]))
        fb = facing_bucket(tc, pot_after, nr_after)
        fm = S.fold_mult()
        pf_b = []
        pr_b = []
        for b in range(7):
            p = field_p(post_key(st, fb, b))
            f, c, r = p[0], p[1], sum(p[3:])
            tot = f + c + r
            f, r = f / tot, r / tot
            f2 = min(0.97, f * fm)
            pf_b.append(f2)
            pr_b.append(r * (1 - f2) / max(1 - f, 1e-6))
        pf = [0.0] * NC
        pr = [0.0] * NC
        tw = fsum = rsum = 0.0
        for i in range(NC):
            wi = w[i]
            if wi:
                b = bk[i]
                if b < 0:
                    continue
                pf[i] = pf_b[b]; pr[i] = pr_b[b]
                tw += wi; fsum += wi * pf_b[b]; rsum += wi * pr_b[b]
        return pf, pr, (fsum / tw if tw else 0.5), (rsum / tw if tw else 0.1), tc

    # ---- main decision ----
    def act(self, s):
        hole = [parse(c) for c in s.hole]
        board = [parse(c) for c in s.board]
        if not board:
            return self.preflop(s, hole)
        return self.postflop(s, hole, board)

    # ---------------------------------------------------------------- preflop
    def preflop(self, s, hole):
        n = len(s.stacks)
        seat = s.seat
        pct = PF[hand_class(*hole)][2]
        hist = s.history
        raises = [h for h in hist if h[2] == "raise"]
        nr = len(raises)
        bb = self.bb
        pos = pf_pos(seat, n)
        # players still to act after us preflop (BB acts last)
        order = [(3 + i) % n for i in range(n)] if n > 2 else [0, 1]
        idx = order.index(seat)
        behind = sum(1 for x in order[idx + 1:] if not s.folded[x])
        limpers = sum(1 for h in hist if h[2] == "call") if nr == 0 else 0
        to_call = s.to_call
        stack = s.my_stack + s.street_bets[seat]

        if nr == 0:
            thr = {0: 0.0, 1: 0.40, 2: 0.30, 3: 0.21, 4: 0.16, 5: 0.13, 6: 0.11}.get(behind, 0.10)
            if limpers:
                thr *= 0.75
            if to_call == 0:  # big blind option
                if pct < 0.12 and s.can_raise:
                    return self._raise(s, (4 + limpers) * bb)
                return s.check()
            if pct < thr and s.can_raise:
                size = (2.5 if behind > 1 else 3.0) * bb + limpers * bb
                return self._raise(s, int(round(size)))
            # complete / limp behind only with cheap, playable hands in position
            if limpers and pct < 0.32 and to_call <= bb and pos != 0:
                return s.call()
            if seat == 1 and n > 2 and pct < 0.22 and to_call <= bb // 2 + 1:
                return s.call()
            return s.fold()

        # facing raises
        raiser_seat = raises[-1][1]
        rpid = s.players[raiser_seat]
        R = self.st(rpid)
        last_to = raises[-1][3]
        callers_after = sum(1 for h in hist[hist.index(raises[-1]) + 1:] if h[2] == "call")
        pot = s.pot
        odds = to_call / max(pot + to_call, 1)
        if to_call > 0.25 * stack:
            # big raise / jam: hands above the middle of the raiser's range are favourites
            pfr = (R.pfr + 0.12 * 10) / (R.hands + 10)
            width = max(0.03, min(1.0, pfr * (0.6 if nr >= 2 else 1.0)))
            if pct < 0.025 or pct < 0.42 * width:
                return s.call() if not s.can_raise or to_call >= s.my_stack else s.all_in()
            return s.fold()
        if nr == 1:
            open_r = R.open_rate() if pf_pos(raiser_seat, n) != 2 else 0.25
            # opener's range width; late-position openers are wider
            rng_w = max(0.06, min(0.6, open_r * (1.3 if pf_pos(raiser_seat, n) == 1 else 1.0)))
            size_bb = last_to / bb
            tight = 3.0 / max(size_bb, 2.5)  # bigger opens = stronger, call less
            t3 = max(0.025, min(0.12, 0.22 * rng_w)) * min(1.0, tight * 1.2)
            if pct < t3 and s.can_raise:
                mult = 3.0 if pos != 2 else 3.6
                return self._raise(s, int(last_to * mult + callers_after * last_to))
            tcall = min(0.30, 0.55 * rng_w) * tight
            if pos == 2 and seat == 2:
                tcall = min(0.40, tcall * 1.35 + 0.03)
            if pos == 1:
                tcall *= 1.15
            if callers_after:
                tcall *= 0.85
            if to_call > 0.12 * stack:
                tcall = min(tcall, 0.07)
            if pct < tcall:
                return s.call()
            return s.fold()
        # facing a 3-bet or more
        if nr == 2:
            jam_t = 0.025
            call_t = 0.065
        else:
            jam_t = 0.018
            call_t = 0.025
        if R.loose() > 1.5 or R.pfr > 0.3 * max(R.hands, 1):
            jam_t *= 1.6; call_t *= 1.5
        if pct < jam_t:
            if s.can_raise and last_to < 0.35 * stack:
                return self._raise(s, int(last_to * 2.4))
            return s.all_in() if s.can_raise else s.call()
        if pct < call_t and to_call <= 0.3 * stack:
            return s.call()
        if odds < 0.2 and pct < 0.2:
            return s.call()
        return s.fold()

    def _raise(self, s, to):
        to = max(s.min_raise_to, min(int(to), s.max_raise_to))
        if to >= 0.85 * s.max_raise_to:
            return s.all_in()
        return s.raise_to(to)

    # ---------------------------------------------------------------- postflop
    def postflop(self, s, hole, board):
        t0 = time.time()
        st = STREET_NO[s.street]
        W = self.ranges(s, hole, board)
        if not W:
            return s.check() if s.to_call == 0 else s.call()
        clock = s.clock_ms
        nsamp = 700 if clock > 15000 else (350 if clock > 6000 else 120)
        if len(W) >= 3:
            nsamp = int(nsamp * 0.7)
        seats, samples = self.simulate(hole, board, W, nsamp)
        if len(samples) < 20:
            return s.check() if s.to_call == 0 else s.fold()
        eq0 = self.eq(samples)
        bk = self.buckets(board)
        pot = s.pot
        to_call = s.to_call
        my_sbet = s.street_bets[s.seat]
        my_stack = s.my_stack
        n = len(s.stacks)
        # position: are we last to act on this street among live players?
        live = [x for x in range(n) if not s.folded[x] and s.stacks[x] > 0]
        ip = self._in_position(s, live)
        R = 1.0 if st == 3 else ((1.0 if ip else 0.92) if st == 1 else (1.0 if ip else 0.95))
        if len(W) >= 2:
            R *= 0.95

        options = []  # (ev, action)
        if to_call == 0:
            options.append((eq0 * pot * R, s.check()))
        else:
            allin_call = to_call >= my_stack
            Rc = 1.0 if (allin_call or st == 3) else R
            options.append((0.0, s.fold()))
            big = to_call >= 0.9 * (pot - to_call)  # pot-size+ bets: ladder data says call a bit tighter
            options.append((eq0 * (pot + to_call) * Rc - to_call - (0.04 * pot if big else 0.0), s.call()))

        if s.can_raise:
            cur = max(s.street_bets)
            nr_now = sum(1 for h in s.history if h[0] == s.street and h[2] == "raise")
            cands = set()
            if to_call == 0:
                fracs = (0.33, 0.6, 0.9, 1.3) if st < 3 else (0.4, 0.7, 1.0, 1.5)
                for f in fracs:
                    cands.add(int(round(my_sbet + f * pot)))
            else:
                for k in (0.6, 1.0):
                    cands.add(int(round(cur + k * (pot + to_call))))
            # field response data covers bets up to ~2x pot; beyond that it overstates folds
            # ...except against proven callers, where big value bets are what they pay off
            cap = OVERBET_CAP
            if all(self.st(s.players[x]).fold_mult() < 0.45 for x in W):
                cap = 5.0
                for f in (2.0, 3.0):
                    cands.add(int(round(my_sbet + to_call + f * (pot + to_call))))
            if s.max_raise_to - my_sbet <= cap * (pot + to_call):
                cands.add(s.max_raise_to)
            for T in sorted(cands):
                T = max(s.min_raise_to, min(T, s.max_raise_to))
                if T >= 0.8 * s.max_raise_to:
                    T = s.max_raise_to
                a = T - my_sbet
                if a <= to_call:
                    continue
                ev = self._bet_ev(s, seats, W, samples, bk, st, T, a, pot, R, nr_now + 1)
                act = s.all_in() if T == s.max_raise_to else s.raise_to(T)
                options.append((ev, act))
        best = max(options, key=lambda o: o[0])
        # tie-break toward passive: a bet must beat checking by a small margin
        if best[1].kind == "raise":
            passive = options[0] if to_call == 0 else max(options[:2], key=lambda o: o[0])
            margin = 0.02 if eq0 >= 0.4 else 0.10  # bluffs lean hardest on the fold model
            if best[0] < passive[0] + margin * pot:
                best = passive
        self.last_debug = (round(eq0, 3), [(round(e, 1), a.kind, a.amount) for e, a in options], round((time.time() - t0) * 1000))
        return best[1]

    def _in_position(self, s, live):
        n = len(s.stacks)
        # postflop order starts left of the button (seat 1); last live seat in that order is in position
        order = [(1 + i) % n for i in range(n)]
        last = [x for x in order if x in live]
        return bool(last) and last[-1] == s.seat

    def _bet_ev(self, s, seats, W, samples, bk, st, T, a, pot, R, nr_after):
        pot_after = pot + a
        factors = []
        p_all_fold = 1.0
        p_raise_any = 0.0
        tcs = []
        rf = []
        for seat in seats:
            pf, pr, pfm, prm, tc = self.response(s, seat, W[seat], bk, st, T, pot_after, nr_after)
            p_all_fold *= pfm
            p_raise_any = 1 - (1 - p_raise_any) * (1 - prm)
            factors.append([1.0 - x for x in pf])
            rf.append(pr)
            tcs.append((1 - pfm, tc))
        if p_all_fold >= 0.999:
            return pot
        eq_c = self.eq(samples, factors)
        exp_callers = sum(p for p, _ in tcs) / max(1 - p_all_fold, 1e-6)
        add = sum(p * tc for p, tc in tcs) / max(sum(p for p, _ in tcs), 1e-6)
        final_pot = pot_after + max(1.0, exp_callers) * add
        all_in = T >= s.max_raise_to
        Rb = 1.0 if (all_in or st == 3) else R
        ev_called = eq_c * final_pot * Rb - a
        # being raised: fold our weak hands, continue with strong ones
        q = min(0.9, p_raise_any / max(1 - p_all_fold, 1e-6))
        if q > 0.01 and not all_in:
            eq_r = self.eq(samples, rf)
            ev_raised = ev_called if eq_r > 0.5 else -a
        else:
            ev_raised = ev_called
        return p_all_fold * pot + (1 - p_all_fold) * ((1 - q) * ev_called + q * ev_raised)
