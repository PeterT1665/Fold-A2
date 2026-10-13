"""End-to-end test of a running poker room (dealing integrity, split pots, privacy, bad input, 16-ish simultaneous
tables, busting, heads-up, turn timer, leaving).

  python play/tests/suite.py [http://127.0.0.1:8000]

It creates several dozen throwaway tables, so point it at your own server only (a deployment with a low
--max-rooms may answer 503 to part of it). Needs the macpoker SDK installed? No: it only talks HTTP.
"""
import collections, json, random, re, sys, threading, time, urllib.error, urllib.request
B = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")
RES = []
def check(name, ok, detail=""):
    RES.append(bool(ok)); print(("PASS  " if ok else "FAIL  ") + name + (f"   [{detail}]" if detail else ""), flush=True)
def req(method, path, body=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    r = urllib.request.Request(B + path, data, {"Content-Type": "application/json"}, method=method)
    try:
        with urllib.request.urlopen(r, timeout=30) as f: return f.status, f.read()
    except urllib.error.HTTPError as e: return e.code, e.read()
    except Exception as e: return -1, repr(e).encode()
def J(b):
    try: return json.loads(b)
    except Exception: return None
def get(p): c, b = req("GET", p); return c, J(b)
def post(p, body=None, raw=None): c, b = req("POST", p, body, raw); return c, J(b)
def create(**kw):
    c, j = post("/api/create", kw); assert c == 200, (c, j); return {"room": j["room"], "token": j["token"]}
def state(s): return get(f"/api/state?room={s['room']}&token={s['token']}")
def policy(t, pol, rng):
    if pol == "shove" and t["can_raise"]: return "raise", t["max_raise_to"]
    if pol == "rand":
        r = rng.random()
        if t["can_raise"] and r < 0.3: return "raise", rng.randint(t["min_raise_to"], t["max_raise_to"])
        if t["to_call"] and r > 0.8: return "fold", 0
    if pol == "fold" and t["to_call"]: return "fold", 0
    return ("check", 0) if t["to_call"] == 0 else ("call", 0)
def drive(sessions, pols, timeout=400, seed=1, stop=None):
    rng = random.Random(seed); t0 = time.time(); last = [None] * len(sessions)
    while time.time() - t0 < timeout:
        done = True
        for i, (s, pol) in enumerate(zip(sessions, pols)):
            c, st = state(s)
            if c != 200: return None
            last[i] = st
            if st["status"] not in ("finished", "error"): done = False
            if stop and stop(st): return last
            if pol == "idle": continue
            t = st["my_turn"]
            if t:
                a, amt = policy(t, pol, rng); post("/api/act", {**s, "action": a, "amount": amt})
            elif st["between_hands"]: post("/api/next", s)
        if done: return last
        time.sleep(0.002)
    return last
def replays(s):
    c, hist = get(f"/api/history?room={s['room']}&token={s['token']}")
    return [get(f"/api/replay?room={s['room']}&token={s['token']}&hand={h['hand']}")[1] for h in hist]
def parse_winners(lines):
    names = set()
    for l in lines:
        if " wins " in l: names.add(l.split(" wins ")[0])
        elif " split " in l: names.update(re.split(r", | and ", l.split(" split ")[0]))
    return names

print("== 1. dealing integrity, split pots, chip conservation (3 games per mode, all-calling table)")
allholes = []; firsts = collections.defaultdict(list); bad_dupe = bad_win = bad_cons = hands_n = 0; split_n = 0
for mode, kw in (("tournament", {"hands": 100}), ("knockout", {"start_stack": 1000, "level_hands": 6})) * 3:
    s = create(name="T", seats=6, mode=mode, bot_delay=0, auto_next=1, lineup=["house:call"] * 5, **kw)
    last = drive([s], ["call"])[0]
    tot = sum(x["chips"] for x in last["scores"])
    if last["status"] != "finished" or tot != (0 if mode == "tournament" else 6000): bad_cons += 1
    reps = replays(s)
    for k, rep in enumerate(reps):
        hands_n += 1
        fin = rep["frames"][-1]
        cards = [c for h in rep["holes"].values() for c in h] + fin["board"]
        if len(set(cards)) != len(cards) or any(not re.fullmatch(r"[2-9TJQKA][cdhs]", c) for c in cards): bad_dupe += 1
        allholes += [c for h in rep["holes"].values() for c in h]
        pos = {p["name"] for p in fin["seats"] if (p.get("result") or 0) > 0}
        if not pos <= parse_winners(rep["lines"]): bad_win += 1
        if sum(p["result"] for p in fin["seats"]) != 0: bad_cons += 1
        split_n += any(" split " in l for l in rep["lines"])
        if k == 0: firsts[mode].append(json.dumps(rep["holes"], sort_keys=True))
    post("/api/leave", s)
check("every game finished and chips are conserved", bad_cons == 0, f"{bad_cons} problems")
check(f"{hands_n} hands: no duplicate or invalid cards", bad_dupe == 0, f"{bad_dupe} bad")
check(f"every player who gained chips is named as a winner/split winner ({split_n} split pots seen)", bad_win == 0, f"{bad_win} bad")
rc = collections.Counter(c[0] for c in allholes); sc = collections.Counter(c[1] for c in allholes); n = len(allholes)
chi_r = sum((rc[r] - n / 13) ** 2 / (n / 13) for r in "23456789TJQKA")
chi_s = sum((sc[x] - n / 4) ** 2 / (n / 4) for x in "cdhs")
check(f"hole-card ranks look uniform over {n} cards (chi2 {chi_r:.1f}, limit 32.9)", chi_r < 32.9)
check(f"hole-card suits look uniform (chi2 {chi_s:.1f}, limit 16.3)", chi_s < 16.3)
check("identical games deal different cards", all(len(set(v)) == len(v) for v in firsts.values()))

print("== 2. accounts and privacy over HTTP")
host = create(name="Host", seats=5, humans=2, mode="knockout", start_stack=500, bot_delay=0, auto_next=1, lineup=["house:call"] * 3)
c, j = post("/api/join", {"room": host["room"], "name": "Friend"}); fr = {"room": host["room"], "token": j["token"]}
c3, _ = post("/api/join", {"room": host["room"], "name": "Third"})
check("a full room refuses a third player (409)", c3 == 409, c3)
c, _ = state({"room": host["room"], "token": "nope"}); check("wrong token -> 404", c == 404, c)
other = create(name="Other", seats=5, bot_delay=0, lineup=["house:call"] * 4)
c, _ = state({"room": other["room"], "token": host["token"]}); check("a token from another room -> 404", c == 404, c)
c, _ = post("/api/start", fr); check("only the host can start (friend gets 403)", c == 403, c)
post("/api/start", host)
c, _ = post("/api/join", {"room": host["room"], "name": "Late"}); check("joining after the start is refused (409)", c == 409, c)
leak = 0; checked = 0
for _ in range(400):
    cA, a = state(host); cB, b = state(fr)
    if a["status"] == "playing" and not a["between_hands"] and (a["my_turn"] or b["my_turn"]):
        for me, st in ((host, a), (fr, b)):
            for p in st["table"]:
                if p["pid"] != st["me"] and not p.get("out") and p.get("cards"): leak += 1
        checked += 1
        for s_, st in ((host, a), (fr, b)):
            if st["my_turn"]: post("/api/act", {**s_, "action": "call" if st["my_turn"]["to_call"] else "check"})
        if checked >= 25: break
    elif a["between_hands"]: post("/api/next", host)
    time.sleep(0.01)
check(f"other players' hole cards are never in your state during a live hand ({checked} snapshots)", leak == 0 and checked > 5, f"{leak} leaks")
c, ok = post("/api/act", {**host, "action": "call"}); check("acting out of turn is ignored, not an error", c == 200 and ok.get("ok") in (True, False))
post("/api/leave", host)

print("== 3. bad input (the server must answer, never hang up, and stay alive)")
rooms = []
cases = [("/api/create", b) for b in ({}, {"seats": "x"}, {"seats": None}, {"seats": -5}, {"seats": 999}, {"hands": "abc"}, {"humans": "q"},
          {"lineup": "v4"}, {"lineup": [1, 2, {}]}, {"mode": "evil"}, {"name": "A" * 5000}, {"bot_delay": "slow"}, {"start_stack": -1}, {"level_hands": "x"})]
for path, b in cases:
    c, j = post(path, b)
    check(f"POST {path} {json.dumps(b)[:50]}", c in (200, 400), f"status {c}")
    if c == 200 and j and "token" in j: rooms.append({"room": j["room"], "token": j["token"]})
for raw in (b"{not json", b"", b"[1,2,3]", b"null", b"x" * 200000):
    c, _ = post("/api/create", raw=raw); check(f"POST raw body {raw[:12]!r}...", c in (200, 400), f"status {c}")
    if c == 200: pass
live = create(name="F", seats=5, bot_delay=0, lineup=["house:call"] * 4)
t0 = time.time()
while time.time() - t0 < 30:
    c, st = state(live)
    if st["my_turn"]: break
    time.sleep(0.02)
for body in ({"action": "raise", "amount": "abc"}, {"action": "raise", "amount": None}, {"action": "raise", "amount": -5}, {"action": "bogus"},
             {"action": None}, {"amount": 5}, {"action": "raise", "amount": 10 ** 15}, {"action": "raise", "amount": 1.5}):
    c, _ = post("/api/act", {**live, **body}); check(f"POST /api/act {json.dumps(body)}", c in (200, 400), f"status {c}")
for path in ("/api/replay?room=x&token=y&hand=abc", f"/api/replay?room={live['room']}&token={live['token']}&hand=abc", "/api/state", "/api/history?room=%00&token=%00",
             "/api/room_info", "/nope", "/api/bots?x=" + "a" * 20000):
    c, _ = get(path); check(f"GET {path[:60]}", c in (200, 400, 404), f"status {c}")
for path in ("/../server.py", "/..%2fserver.py", "/%2e%2e/server.py", "//etc/passwd", "/static/../server.py", "/../README.md", "/./../server.py"):
    c, b = req("GET", path); check(f"path traversal {path} is refused", c in (400, 404) and b"class Room" not in b and b"def main" not in b, f"status {c}")
for path in ("/", "/app.js", "/style.css", "/api/bots"):
    c, _ = get(path) if path.startswith("/api") else req("GET", path); check(f"GET {path} still works", c == 200, c)
res = drive([live], ["call"])
check("a game still plays to the end after all that abuse", res and res[0]["status"] in ("playing", "finished") and res[0]["hand"] >= 1)
for r in rooms + [live]: post("/api/leave", r)

print("== 4. eight rooms at once (cross-talk and chip conservation)")
outs = {}
def worker(i):
    mode = "knockout" if i % 2 else "tournament"
    lineup = random.Random(i).sample(["house:call", "house:random", "house:allin", "house:checkfold", "v4", "v35"], 5)
    kw = {"hands": 40} if mode == "tournament" else {"start_stack": 400, "level_hands": 4}
    s = create(name=f"P{i}", seats=6, mode=mode, bot_delay=0, auto_next=1, lineup=lineup, **kw)
    last = drive([s], ["rand"], seed=i, timeout=500)
    outs[i] = (mode, last[0] if last else None)
ths = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
[t.start() for t in ths]; [t.join() for t in ths]
for i, (mode, st) in sorted(outs.items()):
    ok = st and st["status"] == "finished" and sum(x["chips"] for x in st["scores"]) == (0 if mode == "tournament" else 2400) and all(f"P{i}" == x["name"] or not x["name"].startswith("P") for x in st["scores"])
    check(f"room {i} ({mode}) finished with chips conserved and no foreign players", ok, st and st["status"])

print("== 5. game flows")
s = create(name="Shover", seats=5, mode="knockout", start_stack=200, level_hands=5, bot_delay=0, auto_next=1, lineup=["house:call"] * 4)
st = drive([s], ["shove"], timeout=240)[0]
mine = [x for x in st["scores"] if x["name"] == "Shover"][0]["chips"]
check(f"all-in every hand: game ends (I {'won' if mine else 'busted'}) and bookkeeping agrees", st["status"] == "finished" and ((mine == 1000) or (mine == 0 and st["my_place"])), f"{st['status']} chips {mine} place {st.get('my_place')}")
for seats in (2, 3):
    s = create(name="HU", seats=seats, mode="knockout", start_stack=200, level_hands=3, bot_delay=0, auto_next=1, lineup=["house:call"] * (seats - 1))
    st = drive([s], ["shove"], timeout=240)[0]
    check(f"{seats}-handed knockout finishes with chips conserved", st["status"] == "finished" and sum(x["chips"] for x in st["scores"]) == 200 * seats, st["status"])
h = create(name="Host", seats=5, humans=2, mode="tournament", hands=6, turn_limit=2, bot_delay=0, auto_next=1, lineup=["house:call"] * 3)
c, j = post("/api/join", {"room": h["room"], "name": "Sleeper"}); f = {"room": h["room"], "token": j["token"]}
post("/api/start", h); t0 = time.time()
res = drive([h, f], ["call", "idle"], timeout=180)
check(f"a player who never acts is auto-folded after the {2}s limit and the game finishes ({time.time() - t0:.0f}s)", res and res[0]["status"] == "finished" and res[0]["hand"] == 6)
m = create(name="Leaver", seats=5, bot_delay=0.3, lineup=["house:call"] * 4)
t0 = time.time()
while time.time() - t0 < 20 and not state(m)[1]["my_turn"]: time.sleep(0.02)
c, _ = post("/api/leave", m); c2, _ = state(m); c3, _ = post("/api/leave", m)
check("leaving mid-hand removes the room (later requests 404)", c == 200 and c2 == 404 and c3 == 404, (c, c2, c3))
c, b = get("/api/bots"); check("server is still healthy at the end", c == 200 and len(b) > 5)
print(f"\n{sum(RES)}/{len(RES)} checks passed"); sys.exit(0 if all(RES) else 1)
