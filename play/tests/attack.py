"""Can someone who only knows the room code predict the deal?

  python play/tests/attack.py [http://127.0.0.1:8000]

Needs the macpoker SDK. Replays the old, insecure seeding (room code -> deck) against a running server and counts how
many players' hole cards it guesses. A secure server prints 0/18 for both game types."""
import json, random, sys, time, urllib.request
from macpoker.cards import shuffled_deck, cards_str
B = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")
def get(p): return json.load(urllib.request.urlopen(B + p))
def post(p, b): return json.load(urllib.request.urlopen(urllib.request.Request(B + p, json.dumps(b).encode(), {"Content-Type": "application/json"})))
def play_hands(s, want):
    for _ in range(20000):
        st = get(f"/api/state?room={s['room']}&token={s['token']}")
        if st["status"] in ("finished", "error") or len(get(f"/api/history?room={s['room']}&token={s['token']}")) >= want: return st
        t = st["my_turn"]
        if t: post("/api/act", {**s, "action": "check" if t["to_call"] == 0 else "call"})
        elif st["between_hands"]: post("/api/next", s)
        time.sleep(0.003)
def attack(mode, n=6, hands=3):
    extra = {"hands": 50} if mode == "tournament" else {"start_stack": 1000, "level_hands": 0}
    r = post("/api/create", {"name": "Eve", "seats": n, "mode": mode, "bot_delay": 0, "auto_next": 1, "lineup": ["house:call"] * (n - 1), **extra})
    s = {"room": r["room"], "token": r["token"]}
    play_hands(s, hands)
    st = get(f"/api/state?room={s['room']}&token={s['token']}")
    hit = tot = 0
    if mode == "tournament":
        for h in range(1, hands + 1):
            rep = get(f"/api/replay?room={s['room']}&token={s['token']}&hand={h}")
            deck = shuffled_deck(random.Random(f"{r['room']}:{h - 1}"))
            for pid, hole in rep["holes"].items():
                seat = (int(pid) + (h - 1)) % n
                tot += 1; hit += cards_str([deck[2 * seat], deck[2 * seat + 1]]) == hole
    else:
        order = list(range(n)); rng = random.Random(r["room"]); rng.shuffle(order)
        for h in range(1, hands + 1):
            rep = get(f"/api/replay?room={s['room']}&token={s['token']}&hand={h}")
            deck = shuffled_deck(rng)
            k = h - 1                                   # button moves one player per hand while everyone is alive
            seat_map = order[k:] + order[:k]
            for i, pid in enumerate(seat_map):
                hole = rep["holes"].get(str(pid))
                if hole is not None:
                    tot += 1; hit += cards_str([deck[2 * i], deck[2 * i + 1]]) == hole
    post("/api/leave", s)
    return hit, tot
for mode in ("tournament", "knockout"):
    hit, tot = attack(mode)
    print(f"  {mode:10}: attacker predicted {hit}/{tot} players' hole cards")
