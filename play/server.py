"""Fold A2 poker room: play no-limit hold'em in the browser against our bots.

  python play/server.py                 # http://localhost:8000
  python play/server.py --port 9000 --host 0.0.0.0   # let friends on your network join

Uses the official macpoker engine (same rules as the tournament: 200-chip stacks reset every hand,
blinds 1/2, everyone moves one seat each hand). A human seat is just another transport: when the
engine asks it to act, it waits for your click. Rooms can have several human seats, so friends can
join the same table with the room link.

Standard library only (plus macpoker). The browser polls /api/state; no websockets needed.
"""
import argparse
import importlib.util
import json
import os
import random
import secrets
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
sys.path.insert(0, os.path.join(ROOT, "opponents"))
sys.path.insert(0, os.path.join(ROOT, "v4"))

from macpoker import Bot
from macpoker.actions import Action
from macpoker.bots import BUILTINS
from macpoker.cards import parse_cards
from macpoker.evaluator import evaluate, hand_name
from macpoker.match import MatchConfig, MatchRunner
from macpoker.transport import InProcessTransport, Transport


# ------------------------------------------------------------------ bots
_LOADED = {}


def _load_class(path):
    if path not in _LOADED:
        d = os.path.dirname(path)
        sys.path.insert(0, d)
        spec = importlib.util.spec_from_file_location(f"botmod_{len(_LOADED)}", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        subs = [v for v in vars(mod).values()
                if isinstance(v, type) and issubclass(v, Bot) and v is not Bot and v.__module__ == mod.__name__]
        _LOADED[path] = subs[0]
    return _LOADED[path]


def bot_catalog():
    """id -> (label, factory). Ladder clones appear only if opponents/clone_data.json exists."""
    cat = {
        "v4": ("Fold-A2 v4.2 (tournament entry)", lambda seed: _load_class(os.path.join(ROOT, "v4", "main.py"))()),
        "v35": ("Fold-A2 v3.5 (old bot)", lambda seed: _load_class(os.path.join(ROOT, "macpoker-scaffold", "main.py"))()),
    }
    data = os.path.join(ROOT, "opponents", "clone_data.json")
    if os.path.exists(data):
        hands = json.load(open(data))["hands"]
        top = sorted((n for n, h in hands.items() if h >= 1500 and n != "love-of-da-game"), key=str.lower)
        for name in top:
            cat["clone:" + name] = (f"Ladder copy: {name}",
                                    (lambda nm: lambda seed: __import__("clone").CloneBot(nm, seed))(name))
    for b in sorted(BUILTINS):
        cat["house:" + b] = (f"House bot: {b}", (lambda nm: lambda seed: BUILTINS[nm]())(b))
    return cat


CATALOG = bot_catalog()


# ------------------------------------------------------------------ transports
class HumanTransport(Transport):
    """Blocks the engine on this seat's turn until the browser posts an action."""

    def __init__(self, room, pid):
        self.room, self.pid = room, pid
        self.cv = threading.Condition()
        self.pending = None
        self.reply = None

    def send(self, msg):
        self.room.observe(self.pid, msg)

    def act(self, view, timeout_ms):
        with self.cv:
            self.pending, self.reply = view, None
            self.room.set_actor(view["seat"], view)
            limit = self.room.turn_limit
            deadline = time.time() + limit if limit else None
            while self.reply is None and not self.room.closed:
                left = None if deadline is None else deadline - time.time()
                if left is not None and left <= 0:
                    break
                self.cv.wait(timeout=1 if left is None else min(1, left))
            a = self.reply or (Action.check() if view["to_call"] == 0 else Action.fold())
            self.pending = None
            self.room.set_actor(None, None)
            return a, 0.0  # humans are not charged against the chess clock

    def submit(self, action):
        with self.cv:
            if self.pending is None:
                return False
            self.reply = action
            self.cv.notify_all()
            return True


class PacedBot(Transport):
    """In-process bot with a short think pause so the table is watchable."""

    def __init__(self, room, pid, bot):
        self.room, self.pid = room, pid
        self.inner = InProcessTransport(bot)

    def send(self, msg):
        self.room.observe(self.pid, msg)
        self.inner.send(msg)

    def act(self, view, timeout_ms):
        self.room.set_actor(view["seat"], None)
        t0 = time.time()
        a, ms = self.inner.act(view, timeout_ms)
        pause = self.room.bot_delay - (time.time() - t0)
        if pause > 0 and not self.room.closed:
            time.sleep(pause)
        self.room.set_actor(None, None)
        return a, ms


# ------------------------------------------------------------------ room
class Room:
    def __init__(self, seats, hands, lineup, humans, names, bot_delay, turn_limit, auto_next):
        self.id = secrets.token_urlsafe(5)
        self.n = seats
        self.num_hands = hands
        self.bot_delay = bot_delay
        self.turn_limit = turn_limit
        self.auto_next = auto_next
        self.closed = False
        self.lock = threading.RLock()
        self.version = 0
        self.status = "lobby"
        # player ids 0..n-1; the first `humans` are human slots
        self.players = []
        for pid in range(seats):
            if pid < humans:
                self.players.append({"kind": "human", "name": names.get(pid, f"Player {pid + 1}"),
                                     "token": secrets.token_urlsafe(12), "joined": pid == 0})
            else:
                bid = lineup[pid - humans] if pid - humans < len(lineup) else "v4"
                if bid not in CATALOG:
                    bid = "v4"
                self.players.append({"kind": "bot", "bot": bid, "name": self._bot_name(bid, pid)})
        self.totals = [0] * seats
        self.hand_no = -1
        self.events = []        # human-readable log
        self.table = None       # current hand model
        self.last_result = None
        self.actor_seat = None
        self.human_tx = {}
        self.ack = threading.Event()
        self.final = None

    def _bot_name(self, bid, pid):
        short = {"v4": "Fold-A2 v4.2", "v35": "Fold-A2 v3.5"}.get(bid)
        if short is None:
            short = bid.split(":", 1)[1]
        taken = sum(1 for p in getattr(self, "players", []) if p.get("bot") == bid)
        return short if taken == 0 else f"{short} #{taken + 1}"

    # ---- lifecycle ----
    def token_pid(self, token):
        for pid, p in enumerate(self.players):
            if p.get("token") and secrets.compare_digest(p["token"], token or ""):
                return pid
        return None

    def join(self, name):
        with self.lock:
            if self.status != "lobby":
                return None
            for pid, p in enumerate(self.players):
                if p["kind"] == "human" and not p["joined"]:
                    p["joined"] = True
                    p["name"] = (name or p["name"])[:20]
                    self.bump()
                    return pid, p["token"]
            return None

    def start(self):
        with self.lock:
            if self.status != "lobby":
                return
            # unclaimed human seats become our bot
            for pid, p in enumerate(self.players):
                if p["kind"] == "human" and not p["joined"]:
                    self.players[pid] = {"kind": "bot", "bot": "v4", "name": self._bot_name("v4", pid)}
            self.status = "playing"
            self.bump()
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        transports = []
        for pid, p in enumerate(self.players):
            if p["kind"] == "human":
                t = HumanTransport(self, pid)
                self.human_tx[pid] = t
            else:
                t = PacedBot(self, pid, CATALOG[p["bot"]][1](f"{self.id}:{pid}"))
            transports.append(t)
        cfg = MatchConfig(seats=self.n, deals=self.num_hands, seed=self.id, base_time_ms=10**12, increment_ms=0)
        try:
            res = MatchRunner(cfg, transports).run()
            with self.lock:
                self.final = {"chips": res.chips, "verdicts": res.verdicts}
                self.status = "finished"
                self.bump()
        except Exception as exc:  # never leave the browser hanging
            with self.lock:
                self.status = "error"
                self.events.append(f"Table error: {exc}")
                self.bump()

    def close(self):
        self.closed = True
        for t in self.human_tx.values():
            with t.cv:
                t.cv.notify_all()
        self.ack.set()

    # ---- engine callbacks ----
    def bump(self):
        self.version += 1

    def set_actor(self, seat, view):
        with self.lock:
            self.actor_seat = seat
            self.bump()

    def observe(self, pid, msg):
        t = msg.get("type")
        with self.lock:
            if t == "hand_start":
                if self.table is None or self.table["hand"] != msg["hand"]:
                    self.hand_no = msg["hand"]
                    n = self.n
                    self.table = {"hand": msg["hand"], "players": msg["players"], "button": msg["button"],
                                  "stacks": list(msg["stacks"]), "bets": [0] * n, "folded": [False] * n,
                                  "allin": [False] * n, "holes": {}, "board": [], "street": "preflop",
                                  "pot": 0, "last": {}, "sb": None, "bb": None}
                    self.last_result = None
                    self.events.append(f"— Hand {msg['hand'] + 1} —")
                self.table["holes"][pid] = msg["hole"]
                self.bump()
                return
            if pid != 0 or self.table is None:
                return  # broadcast messages are processed once, from player 0's copy
            T = self.table
            players = msg.get("players") or T["players"]
            name = lambda seat: self.players[players[seat]]["name"]
            if t == "blinds":
                for key, s, a in (("sb", msg["sb_seat"], msg["sb"]), ("bb", msg["bb_seat"], msg["bb"])):
                    T[key] = s
                    T["stacks"][s] -= a; T["bets"][s] += a; T["pot"] += a
            elif t == "action":
                s, kind, amt = msg["seat"], msg["action"], msg["amount"]
                if kind == "fold":
                    T["folded"][s] = True
                    label = "folds"
                elif kind == "check":
                    label = "checks"
                elif kind == "call":
                    T["stacks"][s] -= amt; T["bets"][s] += amt
                    label = f"calls {amt}"
                else:
                    add = amt - T["bets"][s]
                    T["stacks"][s] -= add; T["bets"][s] = amt
                    label = f"raises to {amt}" if T["street"] == "preflop" or max(
                        b for i, b in enumerate(T["bets"]) if i != s) > 0 else f"bets {amt}"
                if T["stacks"][s] == 0 and kind in ("call", "raise"):
                    T["allin"][s] = True
                    label += " (all-in)"
                T["pot"] = msg["pot"]
                T["last"][s] = label
                self.events.append(f"{name(s)} {label}")
            elif t == "street":
                T["street"] = msg["street"]; T["board"] = msg["board"]
                T["bets"] = [0] * self.n
                T["last"] = {s: v for s, v in T["last"].items() if v.startswith("folds")}
                self.events.append(f"{msg['street'].capitalize()}: {' '.join(msg['board'])}")
            elif t == "hand_end":
                board = msg["board"]
                shown = {}
                for s, hole in msg["revealed"].items():
                    s = int(s)
                    val = evaluate(parse_cards(hole + board)) if len(board) == 5 else None
                    shown[s] = {"cards": hole, "hand": hand_name(val) if val else ""}
                winners = []
                for p in msg["pots"]:
                    for w in p["winners"]:
                        winners.append(w)
                for s, d in enumerate(msg["deltas"]):
                    self.totals[players[s]] += d
                won = {s: d for s, d in enumerate(msg["deltas"]) if d > 0}
                for s, d in won.items():
                    how = f" with {shown[s]['hand']}" if s in shown and shown[s]["hand"] else ""
                    self.events.append(f"{name(s)} wins +{d}{how}")
                T["board"] = board
                self.last_result = {"deltas": msg["deltas"], "shown": shown, "winners": sorted(set(winners)),
                                    "pots": msg["pots"]}
                self.events = self.events[-200:]
                self.bump()
                self._pause_between_hands()
                return
            self.events = self.events[-200:]
            self.bump()

    def _pause_between_hands(self):
        if self.closed or not any(p["kind"] == "human" for p in self.players):
            return
        self.ack.clear()
        self.lock.release()
        try:
            self.ack.wait(timeout=self.auto_next if self.auto_next > 0 else 600)
        finally:
            self.lock.acquire()

    # ---- views ----
    def view(self, pid):
        with self.lock:
            T = self.table
            seats = []
            my_seat = None
            if T:
                for seat, p_id in enumerate(T["players"]):
                    p = self.players[p_id]
                    if p_id == pid:
                        my_seat = seat
                    cards = None
                    if p_id == pid and pid in T["holes"]:
                        cards = T["holes"][pid]
                    elif self.last_result and seat in self.last_result["shown"]:
                        cards = self.last_result["shown"][seat]["cards"]
                    seats.append({
                        "seat": seat, "pid": p_id, "name": p["name"], "kind": p["kind"],
                        "stack": T["stacks"][seat], "bet": T["bets"][seat], "folded": T["folded"][seat],
                        "allin": T["allin"][seat], "button": seat == T["button"], "sb": seat == T["sb"],
                        "bb": seat == T["bb"], "last": T["last"].get(seat, ""), "cards": cards,
                        "has_cards": not T["folded"][seat], "total": self.totals[p_id],
                        "acting": seat == self.actor_seat,
                        "result": (self.last_result["deltas"][seat] if self.last_result else None),
                        "shown_hand": (self.last_result["shown"].get(seat, {}).get("hand") if self.last_result else None),
                    })
            my_turn = None
            tx = self.human_tx.get(pid)
            if tx is not None and tx.pending is not None:
                v = tx.pending
                my_turn = {k: v[k] for k in ("to_call", "min_raise_to", "max_raise_to", "can_raise", "pot")}
                my_turn["my_bet"] = v["street_bets"][v["seat"]]
                my_turn["stack"] = v["stacks"][v["seat"]]
            board_scores = sorted(((self.totals[i], self.players[i]["name"], i) for i in range(self.n)), reverse=True)
            return {
                "room": self.id, "version": self.version, "status": self.status,
                "hand": self.hand_no + 1, "num_hands": self.num_hands, "seats_n": self.n,
                "me": pid, "my_seat": my_seat, "table": seats,
                "board": T["board"] if T else [], "pot": T["pot"] if T else 0,
                "street": T["street"] if T else None, "my_turn": my_turn,
                "between_hands": bool(self.last_result) and self.status == "playing",
                "auto_next": self.auto_next, "turn_limit": self.turn_limit,
                "log": self.events[-60:],
                "lobby": [{"pid": i, "name": p["name"], "kind": p["kind"], "joined": p.get("joined", True)}
                          for i, p in enumerate(self.players)],
                "scores": [{"pid": i, "name": nm, "chips": c} for c, nm, i in board_scores],
                "final": self.final,
            }


ROOMS = {}


# ------------------------------------------------------------------ http
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 100_000:
            return {}
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            return {}

    def _room(self, q):
        room = ROOMS.get((q.get("room") or [""])[0])
        pid = room.token_pid((q.get("token") or [""])[0]) if room else None
        return room, pid

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/api/bots":
            return self._json([{"id": k, "label": v[0]} for k, v in CATALOG.items()])
        if u.path == "/api/state":
            room, pid = self._room(q)
            if room is None or pid is None:
                return self._json({"error": "unknown room or token"}, 404)
            return self._json(room.view(pid))
        if u.path == "/api/room_info":
            room = ROOMS.get((q.get("room") or [""])[0])
            if room is None:
                return self._json({"error": "unknown room"}, 404)
            with room.lock:
                return self._json({"room": room.id, "status": room.status, "seats_n": room.n,
                                   "open": sum(1 for p in room.players if p["kind"] == "human" and not p["joined"])})
        path = "index.html" if u.path in ("/", "/index.html") else u.path.lstrip("/")
        full = os.path.normpath(os.path.join(STATIC, path))
        if not full.startswith(STATIC) or not os.path.isfile(full):
            self.send_error(404)
            return
        ctype = {"html": "text/html", "js": "text/javascript", "css": "text/css", "svg": "image/svg+xml"}.get(
            full.rsplit(".", 1)[-1], "application/octet-stream")
        data = open(full, "rb").read()
        self.send_response(200)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        u = urlparse(self.path)
        b = self._body()
        if u.path == "/api/create":
            seats = max(2, min(10, int(b.get("seats", 6))))
            humans = max(1, min(seats - 1, int(b.get("humans", 1))))
            hands = max(1, min(1000, int(b.get("hands", 50))))
            lineup = [x for x in b.get("lineup", []) if isinstance(x, str)]
            room = Room(seats, hands, lineup, humans, {0: str(b.get("name") or "You")[:20]},
                        bot_delay=max(0.0, min(3.0, float(b.get("bot_delay", 0.7)))),
                        turn_limit=max(0, min(600, int(b.get("turn_limit", 0)))),
                        auto_next=max(0, min(60, int(b.get("auto_next", 4)))))
            ROOMS[room.id] = room
            if humans == 1:
                room.start()
            return self._json({"room": room.id, "token": room.players[0]["token"], "pid": 0})
        if u.path == "/api/join":
            room = ROOMS.get(b.get("room", ""))
            if room is None:
                return self._json({"error": "unknown room"}, 404)
            got = room.join(str(b.get("name") or ""))
            if got is None:
                return self._json({"error": "room is full or already started"}, 409)
            return self._json({"room": room.id, "token": got[1], "pid": got[0]})
        q = {"room": [b.get("room", "")], "token": [b.get("token", "")]}
        room, pid = self._room(q)
        if room is None or pid is None:
            return self._json({"error": "unknown room or token"}, 404)
        if u.path == "/api/start":
            if pid != 0:
                return self._json({"error": "only the host can start"}, 403)
            room.start()
            return self._json({"ok": True})
        if u.path == "/api/act":
            tx = room.human_tx.get(pid)
            kind = b.get("action")
            if kind == "raise":
                act = Action.raise_to(int(b.get("amount", 0)))
            elif kind in ("fold", "check", "call"):
                act = Action(kind)
            else:
                return self._json({"error": "bad action"}, 400)
            ok = tx.submit(act) if tx else False
            return self._json({"ok": ok})
        if u.path == "/api/next":
            room.ack.set()
            return self._json({"ok": True})
        if u.path == "/api/leave":
            room.close()
            ROOMS.pop(room.id, None)
            return self._json({"ok": True})
        return self._json({"error": "not found"}, 404)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    a = ap.parse_args()
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    print(f"Fold A2 poker room on http://{'localhost' if a.host in ('127.0.0.1', '0.0.0.0') else a.host}:{a.port}")
    print(f"{len(CATALOG)} opponents available. Ctrl+C to stop.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
