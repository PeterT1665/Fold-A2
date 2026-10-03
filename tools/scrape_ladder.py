"""Download recent ladder games (hand histories + names) into games/.

  python tools/scrape_ladder.py            # all recent ladder games
  python tools/scrape_ladder.py --delay 2  # slower

Organisers OK'd scraping. Uses the same public queries as the website, one
request per --delay seconds. Writes games/<match id>.json (the hand history,
plus "names" and "result") and games/index.json. Already-downloaded games are
skipped. games/ is gitignored: never commit it.
"""
import argparse
import json
import os
import time
import urllib.request

API = "https://convex.poker.monashcoding.com/api/query"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "games")


def query(path, args):
    body = json.dumps({"path": path, "args": args, "format": "json"}).encode()
    req = urllib.request.Request(API, body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.load(r)
    if d.get("status") != "success":
        raise RuntimeError(f"{path}: {d}")
    return d["value"]


def get(url):
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.load(r)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--delay", type=float, default=1.0)
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    idx_path = os.path.join(OUT, "index.json")
    index = json.load(open(idx_path)) if os.path.exists(idx_path) else {}

    recent = [g for g in query("matches:recent", {}) if g.get("kind") == "ladder"]
    print(f"{len(recent)} recent ladder games, {sum(g['id'] in index for g in recent)} already saved")
    for g in recent:
        if g["id"] in index:
            continue
        time.sleep(a.delay)
        rep = query("tournament:replay", {"matchId": g["id"]})
        if not rep or not rep.get("historyUrl"):
            print(f"  {g['id']}: no history yet")
            continue
        time.sleep(a.delay)
        hist = get(rep["historyUrl"])
        hist["names"] = rep["names"]
        hist["result"] = rep.get("result")
        hist["elo"] = rep.get("elo")
        hist["at"] = g["at"]
        with open(os.path.join(OUT, g["id"] + ".json"), "w") as f:
            json.dump(hist, f)
        index[g["id"]] = {"at": g["at"], "names": rep["names"], "chips": g["chips"]}
        with open(idx_path, "w") as f:
            json.dump(index, f, indent=1)
        print(f"  saved {g['id']}  {len(hist['hands'])} hands")
    print(f"done: {len(index)} games in {OUT}")


if __name__ == "__main__":
    main()
