"""Starts its own server with tiny limits (12 tables, 12 s idle) and checks: the table cap answers 503, abandoned tables
are closed, an actively polled table survives, threads come back down, and creating works again afterwards.

  python play/tests/hardening.py      (needs the macpoker SDK; takes about 1 minute)
"""
import json, subprocess, sys, time, urllib.request, urllib.error, os
import tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOG = os.path.join(tempfile.gettempdir(), "poker-hardening.log")
PORT = 8990; B = f"http://127.0.0.1:{PORT}"
proc = subprocess.Popen([sys.executable, f"{ROOT}/play/server.py", "--port", str(PORT), "--max-rooms", "12", "--idle-minutes", "0.2"],
                        stdout=open(LOG, "w"), stderr=subprocess.STDOUT)
time.sleep(3)
RES = []
def check(n, ok, d=""): RES.append(bool(ok)); print(("PASS  " if ok else "FAIL  ") + n + (f"   [{d}]" if d else ""), flush=True)
def req(method, path, body=None):
    r = urllib.request.Request(B + path, json.dumps(body).encode() if body is not None else None, {"Content-Type": "application/json"}, method=method)
    try:
        with urllib.request.urlopen(r, timeout=30) as f: return f.status, json.loads(f.read())
    except urllib.error.HTTPError as e: return e.code, json.loads(e.read() or b"{}")
def threads(): return len(subprocess.run(["ps", "-M", "-p", str(proc.pid)], capture_output=True, text=True).stdout.strip().splitlines()) - 1
try:
    base = threads()
    rooms = []
    for i in range(12):
        c, j = req("POST", "/api/create", {"name": f"x{i}", "seats": 8, "mode": "knockout", "lineup": ["v4"] * 7, "bot_delay": 0, "auto_next": 1})
        assert c == 200, (c, j); rooms.append({"room": j["room"], "token": j["token"]})
    c, j = req("POST", "/api/create", {"name": "late"})
    check("the 13th table is refused with a friendly message (503)", c == 503 and "full" in j.get("error", ""), (c, j))
    check(f"12 tables = 12 extra threads ({threads()} vs {base} before)", threads() >= base + 12)
    live = rooms[0]; t0 = time.time(); hands = 0
    while time.time() - t0 < 45:     # one player keeps playing and polling; the other 11 are abandoned
        c, st = req("GET", f"/api/state?room={live['room']}&token={live['token']}")
        if c != 200: break
        hands = st["hand"]
        if st["my_turn"]: req("POST", "/api/act", {**live, "action": "check" if st["my_turn"]["to_call"] == 0 else "call"})
        elif st["between_hands"]: req("POST", "/api/next", live)
        time.sleep(0.3)
    gone = sum(req("GET", f"/api/state?room={r['room']}&token={r['token']}")[0] == 404 for r in rooms[1:])
    c, st = req("GET", f"/api/state?room={live['room']}&token={live['token']}")
    check(f"the 11 abandoned tables were closed after the idle limit ({gone}/11)", gone == 11)
    check(f"the table that kept polling was NOT closed and kept playing (reached hand {hands})", c == 200 and hands >= 3, (c, hands))
    time.sleep(2)
    check(f"threads came back down ({threads()} now, {base} at start, +1 for the live game)", threads() <= base + 2, threads())
    c, j = req("POST", "/api/create", {"name": "again"})
    check("after the cleanup, new tables can be created again", c == 200, (c, j))
    time.sleep(25)     # silence: no requests at all, so the idle timer (12 s here) can run out
    check("a table that stops being polled is closed too", req("GET", f"/api/state?room={live['room']}&token={live['token']}")[0] == 404)
    log = open(LOG).read()
    check("no tracebacks in the server log", "Traceback" not in log, log[-300:] if "Traceback" in log else "")
finally:
    proc.terminate(); proc.wait(timeout=10)
print(f"\n{sum(RES)}/{len(RES)} checks passed"); sys.exit(0 if all(RES) else 1)
