"""How do the top bots play the flop compared with us and the field, by hand strength?

  python tools/flop_policy_compare.py            # uses ../Fold-A2/games or ./games (whichever has the games)

Buckets are the bot's own PostFlopEvaluator classes on the flop. Postflop profit = hand result + chips put in preflop
(so only chips won or lost from the flop on). 'top' = best average place among regulars.
"""
import glob, json, os, statistics, sys
from collections import defaultdict
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "macpoker-scaffold"))
from postflop_evaluator import PostFlopEvaluator
GAMES = [d for d in (os.path.join(ROOT, "games"), os.path.join(os.path.dirname(ROOT), "Fold-A2", "games")) if glob.glob(os.path.join(d, "j9*.json"))][0]
TOP = {"Gladiators", "catherine", "merch where", "pocket-nuts", "wicked wings combo", "성진우", "tungbot", "MAC Projects Team Testing Bot 3"}
US = "love-of-da-game"; EV = PostFlopEvaluator()
ORDER = ["NUT_HAND", "STRONG_MADE", "MEDIUM_MADE", "STRONG_DRAW", "WEAK_DRAW", "TRASH"]
rows = []
for f in glob.glob(os.path.join(GAMES, "*.json")):
    if f.endswith(("index.json", "_decisions.json", "_calib.json", "game1.json")): continue
    g = json.load(open(f)); names = g.get("names")
    if not names: continue
    for h in g["hands"]:
        n = len(h["seat_map"]); sm = h["seat_map"]; ev = h["events"]
        bl = next(e for e in ev if e["type"] == "blinds")
        inv = [0] * n; inv[bl["sb_seat"]] += bl["sb"]; inv[bl["bb_seat"]] += bl["bb"]
        sbet = [0] * n; sbet[bl["sb_seat"]], sbet[bl["bb_seat"]] = bl["sb"], bl["bb"]
        street, cur, board = "preflop", bl["bb"], []; alive = set(range(n)); pre_inv = None; seen = {}
        flop_alive = None; first = {}
        for e in ev:
            if e["type"] == "street":
                if e["street"] == "flop": pre_inv = list(inv); flop_alive = set(alive)
                street, board, cur, sbet = e["street"], e["board"], 0, [0] * n; continue
            if e["type"] != "action": continue
            s, k, a = e["seat"], e["action"], e["amount"]
            if street == "flop" and s not in first:
                first[s] = (k, cur - sbet[s] > 0, cur)       # (action, facing a bet?, bet level)
            if k == "fold": alive.discard(s)
            if k == "raise": inv[s] += a - sbet[s]; sbet[s] = a; cur = a
            elif k == "call": inv[s] += a; sbet[s] += a
        if pre_inv is None: continue
        for s in flop_alive:
            nm = names[sm[s]]; grp = "us" if nm == US else "top" if nm in TOP else "rest"
            hc = EV.evaluate(h["holes"][str(s)], board_flop := [x for x in next(e for e in ev if e["type"] == "street" and e["street"] == "flop")["board"]]).hc.name
            act = first.get(s)
            rows.append((grp, hc, h["deltas_by_bot"][sm[s]] + pre_inv[s], act, len(flop_alive)))
print(f"{len(rows)} flop hands ({sum(1 for r in rows if r[0]=='top')} by top bots, {sum(1 for r in rows if r[0]=='us')} by us)\n")
def table(title, sel, fmt):
    print(title); print(f"   {'':<14}" + "".join(f"{g:>20}" for g in ("top bots", "us", "rest")))
    for hc in ORDER:
        line = f"   {hc[:13]:<14}"
        for g in ("top", "us", "rest"):
            R = [r for r in rows if r[0] == g and r[1] == hc]; line += f"{fmt(R, sel):>20}"
        print(line)
    print()
share = lambda R, sel: f"{100*len(R)/max(1,sum(1 for r in rows if r[0]==R[0][0])):.0f}% of flops" if R else "-"
profit = lambda R, sel: f"{statistics.mean(r[2] for r in R):+.1f} (n={len(R)})" if len(R) >= 15 else "-"
def betrate(R, _):
    Q = [r for r in R if r[3] and not r[3][1]]            # checked to us / first to act: option to bet
    return f"{100*sum(1 for r in Q if r[3][0]=='raise')/len(Q):.0f}% (n={len(Q)})" if len(Q) >= 15 else "-"
def facing(act):
    def f(R, _):
        Q = [r for r in R if r[3] and r[3][1]]
        return f"{100*sum(1 for r in Q if r[3][0]==act)/len(Q):.0f}% (n={len(Q)})" if len(Q) >= 15 else "-"
    return f
table("1) How often each hand class shows up (share of all flops seen)", None, share)
table("2) Chips won/lost from the flop on, per flop hand", None, profit)
table("3) When it is our turn with no bet to face: how often does the bot BET?", None, betrate)
table("4) Facing a flop bet: how often does it FOLD?", None, facing("fold"))
table("5) Facing a flop bet: how often does it RAISE?", None, facing("raise"))
