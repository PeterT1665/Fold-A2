"""In-process privacy test: the private seed and seat tokens never reach any client view, other humans' hole cards
never appear during a live hand, and closing a room stops its threads.

  python play/tests/privacy.py        (needs the macpoker SDK; starts no server)
"""
import importlib.util, json, os, re, sys, threading, time
from macpoker.actions import Action
spec = importlib.util.spec_from_file_location("srv", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server.py"))
srv = importlib.util.module_from_spec(spec); spec.loader.exec_module(srv)
RES = []
def check(n, ok, d=""): RES.append(bool(ok)); print(("PASS  " if ok else "FAIL  ") + n + (f"   [{d}]" if d else ""))
base = threading.active_count()
def scope(v):
    """everything a client could use to learn a hidden card during a live hand: seats, board, and THIS hand's log lines"""
    log = v["log"]; start = max((i for i, l in enumerate(log) if l.startswith("—")), default=0)
    return json.dumps({"table": v["table"], "board": v["board"], "log": log[start:], "my_turn": v["my_turn"]})
def hits(text, card): return re.search(rf"(?<![A-Za-z0-9]){card}(?![A-Za-z0-9])", text) is not None
# positive control: the detector must fire if a hidden card really were exposed
_fake = {"table": [{"cards": ["Ah", "Kd"]}], "board": [], "log": ["— Hand 1 —", "x checks"], "my_turn": None}
check("detector self-test: flags an exposed card", hits(scope(_fake), "Kd") and not hits(scope(_fake), "2c"))
_fake["log"] = ["— Hand 1 —", "Flop: 2c 3c 4c", "— Hand 2 —", "x checks"]
check("detector self-test: ignores cards from earlier hands in the log", not hits(scope(_fake), "2c"))
def run(mode, humans):
    room = srv.Room(6, 25, ["house:call"] * 5, humans, {0: "Host"}, 0.0, 0, 1, mode=mode, start_stack=500, level_hands=4)
    srv.ROOMS[room.id] = room
    for i in range(1, humans): room.join(f"Friend{i}")
    room.start(); t0 = time.time(); leaks = secret_hits = token_hits = snaps = 0
    while time.time() - t0 < 240 and room.status not in ("finished", "error"):
        for pid, tx in list(room.human_tx.items()):
            with room.lock:     # one consistent snapshot: the view and the real hole cards come from the same instant
                v = room.view(pid); js = json.dumps(v)
                hl = room.hand_list(pid); js2 = json.dumps(hl)
                if hl: js2 += json.dumps(room.replay(pid, hl[-1]["hand"]))
                live = (not v["between_hands"]) and room.table is not None and v["status"] == "playing"
                holes = {o: list(h) for o, h in room.table["holes"].items()} if live else {}
            secret_hits += room.secret in js + js2
            token_hits += any(p.get("token") and p["token"] in js + js2 for p in room.players)
            if live:
                snaps += 1
                for other, h in holes.items():
                    if other != pid and room.players[other]["kind"] == "human":
                        for c in h:
                            if hits(scope(v), c): leaks += 1
                        for seat in v["table"]:       # and directly: the card fields of every other seat must be empty
                            if seat["pid"] == other and seat.get("cards"): leaks += 1
            if tx.pending is not None: tx.submit(Action.call() if tx.pending["to_call"] else Action.check())
        if room.last_result and room.status == "playing": room.ack.set()
        time.sleep(0.002)
    check(f"{mode}, {humans} human(s): game finished", room.status == "finished", room.status)
    check(f"{mode}, {humans} human(s): private seed never appears in any view/history/replay", secret_hits == 0, secret_hits)
    check(f"{mode}, {humans} human(s): nobody's seat token appears in anyone's view", token_hits == 0, token_hits)
    if humans > 1: check(f"{mode}, {humans} humans: opponents' hole cards never visible during live hands ({snaps} snapshots)", leaks == 0 and snaps > 10, leaks)
    return room
a = run("knockout", 1); b = run("tournament", 3); c = run("knockout", 2)
check("each room has its own private seed, different from its public id", len({r.secret for r in (a, b, c)}) == 3 and all(r.secret != r.id for r in (a, b, c)))
# abandoned game: the engine thread must stop when the room is closed
room = srv.Room(6, 100, ["house:call"] * 5, 1, {0: "Quitter"}, 0.0, 0, 1, mode="tournament"); room.start()
t0 = time.time()
while time.time() - t0 < 20 and not room.human_tx: time.sleep(0.01)
time.sleep(0.5); room.close(); t0 = time.time()
while time.time() - t0 < 30 and threading.active_count() > base: time.sleep(0.1)
check(f"closing a room stops its threads ({threading.active_count()} alive vs {base} before)", threading.active_count() <= base + 0)
print(f"\n{sum(RES)}/{len(RES)} checks passed"); sys.exit(0 if all(RES) else 1)
