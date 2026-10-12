# Putting the poker room online

## Why not Vercel

Vercel (and Netlify, Cloudflare Pages) run each request in a short-lived function with no memory shared between
requests. This server keeps live tables, game threads and timers in memory for as long as people are playing, so it
needs a host that runs one ordinary process all the time. A static page on Vercel plus the server somewhere else
would work, but adds CORS and two deployments for no benefit. Use a host that runs a container.

## What you need

A host that runs a Docker container 24/7, gives you HTTPS, and lets you pin the service to **one instance** (tables
live in memory, so two instances would not see each other's games). The repo's `Dockerfile` is the entire setup:
Python 3.12, the vendored SDK, the web server, our two bots and the house bots. No scraped data is in the image.

### Option A: Render (simplest)

1. Push the repo to GitHub (already on `v4-fresh`).
2. Render dashboard: **New → Web Service**, connect the repo, choose the branch. It should detect the Dockerfile
   (pick **Docker** as the runtime if asked).
3. Health check path: `/healthz`.
4. Instance: at least 0.5 CPU and 512 MB (that is what the numbers below were measured on; check the current plans
   and prices). A free instance that sleeps when idle makes the first visitor wait for a cold start, which is a poor
   first impression for a post, and its CPU may be smaller than the test box, so lower `MAX_ROOMS` to match.
5. Environment variables are optional (see below). Keep it at one instance and leave autoscaling off.
6. Open the URL it gives you, then run the tests against it (below).

### Option B: Fly.io

`fly launch` from the repo root will find the Dockerfile. Set the internal port to 8000, keep a single machine running
(disable auto-stop and auto-scale to zero), and set env vars with `fly secrets set` or `[env]` in `fly.toml`.

## Settings (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `PORT` | 8000 | The platform normally sets this itself |
| `MAX_ROOMS` | 40 | Most tables hosted at once; beyond this, "create" answers 503 and the page shows "The server is full right now" |
| `IDLE_MINUTES` | 5 | A table nobody has talked to for this long is closed and its thread freed |
| `PUBLIC_URL` | (auto) | Your site's address, used for the link-preview image. Normally detected from the request headers behind the platform's HTTPS proxy; set it if the preview shows a wrong or relative address |

## How much it holds (measured)

Container limited to 0.5 CPU and 512 MB, worst case: every opponent is Fold-A2 v4.2 (our heaviest bot), every player
acts instantly, and each page polls every 0.3 s.

| Tables playing at once | CPU used (cap is 50%) | State latency, median / 95th pct | Hands per table per minute | Errors |
|---|---|---|---|---|
| 5 | 9% | 4 ms / 13 ms | 9.0 | 0 |
| 10 | 17% | 5 ms / 18 ms | 9.0 | 0 |
| 20 | 26% | 4 ms / 39 ms | 9.0 | 0 |
| 40 | 43% | 11 ms / 264 ms | 8.2 | 0 |

Memory stayed under 50 MB. Each active table costs roughly 1% of a CPU; real visitors think and pause, so real load is
lower. A bigger instance should scale roughly in proportion (not measured): raise `MAX_ROOMS` with it.

## Before you post

- Run `python play/tests/suite.py https://your-site` and `python play/tests/attack.py https://your-site` (the second
  must print 0/18 for both modes). They create many throwaway tables, so do this before the post, not during it.
- Open it on a phone, and try an invite link in a second browser.
- LinkedIn caches link previews. After deploying, paste the URL into LinkedIn's Post Inspector to refresh the card.
  The preview image is `play/static/og.png`, a real screenshot; replace it if you want a different one (1200x630).

## What this does not cover

- **Abuse:** there is no per-visitor rate limiting. The table cap protects the server, but one script could fill every
  slot until its tables go idle. A proxy or CDN in front (Cloudflare, for example) can rate-limit if that matters.
- **Restarts:** a restart or redeploy ends every game in progress. There are no accounts or saved games.
- **Moderation:** player names are escaped (no code injection) but not filtered.
