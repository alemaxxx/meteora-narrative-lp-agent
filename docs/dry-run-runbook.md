# Dry-run runbook (you run this — see docs/phase6-notes.md for why)

Everything up to here (Phases 1–6's automated part) was validated as far as this
environment allows: real source code read directly, live calls to public/keyless APIs,
and a 37-test suite exercising the logic this repo added. What's left needs your own
machine — Docker, a funded (small!) Solana wallet, and API keys. This is that checklist,
in the order to run it, ending with what the hackathon's required demo video needs to
show.

## 1. Run the tests yourself first

Confirms your machine reproduces what's documented in `docs/phase6-notes.md` before you
touch anything live:

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements-dev.txt   # .venv/bin/pip on macOS/Linux
.venv/Scripts/python -m pytest tests/ -v
```

Expect 37 passed.

## 2. Stand up Gateway + Hummingbot API

Follow Hummingbot's own install docs (this repo doesn't bundle either):

- Gateway: https://hummingbot.org/gateway/installation/
- Hummingbot API: https://hummingbot.org/hummingbot-api/installation/

Use the `hummingbot/hummingbot:development` image (the lp-agent skill's own guidance,
see `docs/research-phase1-notes.md`) — `latest` may lag the LP executor / `lp_rebalancer`
features this repo builds on.

## 3. Import a wallet and fund it (small amount — this is a dry-run, not production)

Follow [docs/wallet-setup.md](./wallet-setup.md). Fund with a small amount of SOL (rent +
fees) and enough of your chosen pair's quote asset to cover one risk profile's
`total_amount_quote` (see `conf/controllers/*.example.yml` — $50 by default in all
three).

## 4. Drop this repo's controller and routines into your instance

- Copy `controllers/generic/narrative_lp_agent/` into your Hummingbot instance's
  `controllers/generic/` directory (alongside the stock `lp_rebalancer/` it extends).
- Copy `routines/*.py` into your Condor instance's `routines/` directory.
- Set the environment variables from `.env.example` (LunarCrush/CryptoPanic keys,
  Hummingbot API URL/credentials) in your Condor/API environment.

## 5. Run the discovery funnel in dry-run mode first

From Condor (chat or scheduled), run `narrative_lp_funnel` with `dry_run=True` (the
default) for each risk profile you want to demo. Confirm:

- Layer 1 (`meteora_pool_scanner`) returns real, sane candidates (TVL/volume/ratio that
  make sense — this is what Finding #2 in `docs/phase6-notes.md` was about; if you see
  absurd ratios again, something regressed).
- Layer 2 (`narrative_check`) returns real LunarCrush/CryptoPanic signals for at least
  one candidate (requires your own API keys — this repo's automated tests only mock
  these calls, see `docs/phase6-notes.md`).
- Approved pools get a written config in `conf/controllers/` (git-ignored, real file on
  disk) — inspect it before ever setting `dry_run=False`.

## 6. Deploy one controller for real, small amount

Either flip `dry_run=False` on `narrative_lp_funnel` for one approved pool, or deploy
manually via `frontend/index.html` (point it at your own API URL — see
`docs/wallet-setup.md` for the CORS note) or `manage_controller.py`-style calls. Watch
it for at least one full open → in-range/out-of-range → rebalance-or-not cycle so the
behaviors Phase 3 added actually get exercised, not just position opening:

- Does it correctly follow-or-hold on an upward exit per `uptrend_behavior`?
- Does it correctly exit-to-stable-or-reopen-lower on a downward exit per
  `downtrend_behavior`? If `exit_to_stable`, confirm the swap actually happens and the
  controller pauses (see `docs/phase3-notes.md`'s pause/resume model — it will NOT
  auto-resume, that's intentional).
- Does the cost-benefit gate log a skip on a low-fee tick, if you can catch one?

## 7. Record the demo video

The hackathon's own rule (see the original project summary): a video showing the bot
**running for real**, not a pitch. Suggested shape, given everything above:

1. Show `conf/controllers/<your-deployed-config>.yml` — a real, filled-in config from
   step 5/6, not a hand-edited example.
2. Show the controller's live status (`to_format_status()`'s output — includes risk
   profile, the cost-benefit gate's numbers, pause state if applicable — see
   `controllers/generic/narrative_lp_agent/README.md`).
3. Show at least one real on-chain transaction (position open, or the rebalance/exit
   you caught in step 6) on a Solana explorer.
4. Optionally, show `frontend/index.html` doing a real deploy against your own API, to
   demonstrate the multi-user flow from Phase 5.

## If something here contradicts what's in the code

Trust the code and file an issue/note in `docs/` — this runbook describes intent, not a
guarantee; it hasn't been executed by anyone yet as of this writing.
