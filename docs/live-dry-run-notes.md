# Live dry-run notes

Findings from actually running the full stack (Docker Desktop + WSL2 Ubuntu + Hummingbot
API + Postgres + EMQX + Gateway + Condor) for the first time, live, on 2026-08-30 — the
step `docs/dry-run-runbook.md` describes doing on the user's own machine. This is the
next layer of validation after Phase 6's local, no-runtime tests: things only a real
running stack can surface.

## Setup: two more upstream/environment bugs found and worked around

1. **`hummingbot/deploy`'s `setup.sh` silently exits on Windows/Git Bash.**
   `check_disk_space()`'s non-Linux/non-macOS branch is a bare `return` with no explicit
   status — under `set -e`, that inherits the exit code of the last failed `[[ ]]` test
   (1), aborting the whole installer immediately with no error message. Patched locally
   to `return 0`. Real upstream bug, not specific to this project.
2. **Windows/Git Bash lacks `make`/`tmux` with no way for the installer to self-install
   them** (it only knows `apt`/`dnf`/`yum`/`apk`/`pacman`). Installed `make` via
   `winget install ezwinports.make`, but `tmux` has no clean native-Windows equivalent —
   switched to running the installer inside WSL2 Ubuntu instead, which is what the
   installer actually targets. Needed: enabling Docker Desktop's WSL integration for the
   Ubuntu distro (Settings → Resources → WSL Integration), a one-time GUI step.

Once inside WSL2 Ubuntu, the installer ran clean: Condor + Hummingbot API + Postgres +
EMQX all came up, `curl http://localhost:8000/` matched Hummingbot's own docs exactly.
Gateway itself is not part of that installer — started separately via
`POST /gateway/start` on the API (confirmed simpler than expected: the current
hummingbot-api README says Gateway auto-generates its own mTLS certs on first start, no
manual cert step, protected by the API's own `CONFIG_PASSWORD`).

## Wallet import: real endpoint confirmed, one thing to say plainly

`POST /accounts/gateway/add-wallet` with `{"chain": "solana", "private_key": "...", "set_default": true}`
worked exactly as the OpenAPI schema describes, returning `{"address": "..."}`. Real
finding worth stating plainly: the private key for this test wallet was pasted into a
chat screenshot during setup. It's a dedicated test wallet (not a primary one), so
treated as "keep it to trivial test amounts only" going forward rather than something
requiring immediate rotation — but it's the kind of exposure this project's whole
Phase 5 design (self-hosted signer, key never leaves the user's own Gateway) exists to
prevent, and it happened anyway through a side channel (a screenshot) the design can't
cover. Worth remembering for the demo video: never show a `add-wallet` call on screen.

## Layer 1 (`meteora_pool_scanner`): confirmed working end-to-end with live data

Run from Condor's web dashboard (`/web` from the Telegram bot → routine UI at
`localhost:8088`) against the real Meteora pools API: **"Fetched 200 Meteora DLMM
pools. 15 passed the on-chain filter"**, with sane Volume/TVL ratios (14x–88x) and
real pool names/addresses. This is the same rewrite validated locally in Phase 6, now
confirmed inside the actual Condor runtime — the routine's Config fields, docstring, and
table output all rendered in the dashboard exactly as written.

## Layer 2 (`narrative_check`): logic confirmed correct, but neither data provider is
## actually free to call

Ran against `SOL` (a token definitely tracked by both providers, to isolate "no data for
this token" from "can't reach the provider at all"). Result: **both LunarCrush and
CryptoPanic returned 401/blocked** — not because of a wrong key or wrong endpoint (the
LunarCrush call reached the real endpoint and got a real 401, not a 404), but because
**both providers require a paid plan for API access**, contradicting what Phase 4's
research assumed (verified against each provider's docs, but not against their current
pricing pages). CryptoPanic's minimum is $50/week; LunarCrush's account dashboard shows
the same "upgrade to unlock" gate on its API section.

**What this confirms working correctly:** with both signals unavailable, the routine
did not crash — it logged the failures, correctly treated both as "not passed" (the
conservative default the code was designed around), and returned a correct `FAIL
(<2/3 signals)` verdict (1/3, on-chain only). This is the 2-of-3 cross-check logic
behaving exactly as designed under a real failure condition, not a mocked one.

**What this means for the submission:** strategy.md's Layer 2 description is accurate
as a design — it does not currently produce a real PASS verdict without paying for at
least one of the two providers, since on-chain alone is only 1 of 3 signals. Decision
(2026-08-30): document this rather than pay for either provider right now. Revisit
before the final demo video if a genuine 2-of-3 PASS needs to be shown on camera.

## Frontend: confirmed working end-to-end, including a real deploy attempt

Tested against this live API for the first time (Phase 5 only tested it against a local
static server with no real backend). `Test connection` and `Preview config` both worked
cleanly — CORS was not an issue against a stock `hummingbot-api` install. UX was also
reworked mid-session after actually using it live (see phase5-notes.md's "UX
simplification" section): the technical API-connection step moved from first to last,
a plain-language summary replaced the raw JSON as the default Deploy view, and the pool
filter inputs got tucked behind a toggle.

## First real deploy attempt: two findings, one from each side of the stack

Deployed for real (US$8 target, small test wallet, user's own click) against a live
pool. Two things surfaced that no amount of local/mocked testing could have caught:

**1. `controllers/generic/narrative_lp_agent/__init__.py` was empty — controller
wouldn't load at all.** First deploy attempt: container came up, then exited
immediately with `Failed to start strategy v2_with_controllers: No configuration class
found in the module narrative_lp_agent.` Traced it into the real Hummingbot source
inside the `hummingbot/hummingbot:development` image itself
(`strategy/strategy_v2_base.py`'s `load_controller_configs`): the loader imports
`controllers.<controller_type>.<controller_name>` — the **package** (the directory),
not the `.py` file inside it — then inspects that module's top-level members for a
`ControllerConfigBase` subclass. An empty `__init__.py` exposes nothing to inspect.
Confirmed the fix by reading the real `lp_rebalancer/__init__.py` shipped in the same
image: it re-exports from the file with a relative import (`from .lp_rebalancer import
LPRebalancer, LPRebalancerConfig`), specifically because this same package tree gets
imported under two different root paths depending on context (`controllers.*` inside a
bot container vs. `bots.controllers.*` inside hummingbot-api itself). Applied the same
pattern. Second attempt: container stayed up.

**2. `total_amount_quote` is denominated in the pair's quote token, never literally
dollars — and the bot correctly refused rather than silently doing something wrong.**
With the loader fixed, the bot started, read `total_amount_quote: 8` for a `PINK-SOL`
pair, and understood it as **8 SOL** (~$800+ at the time) — not $8 — because SOL is
that pair's quote token (the second symbol in the pair, same convention `lp_rebalancer`
documents: "amount always in quote asset"). The wallet only had 0.2 SOL, so every
attempt failed with `INSUFFICIENT_BALANCE` from Gateway, confirmed via `docker logs` —
**no transaction was ever submitted on-chain, no funds moved** (verified against
`/portfolio/state` before and after: 0.2 SOL + 10.5 USDC, unchanged). What did need
manual intervention: `lp_rebalancer`'s inherited retry-on-failure logic kept trying
every ~5 seconds with no backoff or attempt cap, so the bot was stopped by hand
(`/bot-orchestration/stop-bot`, then a direct `docker stop` since the API call didn't
take effect immediately) rather than left to keep hammering Gateway/RPC indefinitely.
Fixed in the frontend, not the controller: the deploy summary now shows the amount in
the pair's actual quote token, and shows an explicit warning when that token isn't a
recognized stablecoin, including the sharper point that "convert to stable" on a
non-stablecoin quote still leaves the position holding a volatile asset, not cash.

Both fixes are pushed. Third attempt (COT-SOL, 0.03 SOL, a deliberately small amount
after the warning above did its job): **succeeded**. Confirmed independently on Solscan,
outside this project's own stack entirely — signer matched the test wallet, "Position:
Open" + "Liquidity: Add" on the real Meteora DLMM Program
(`LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo`), `Initialize_position` +
`Add_liquidity_by_strategy2` instructions, timestamp matching the bot's own log. This is
the Meteora track's core requirement — "provide liquidity... on Meteora pools (DLMM)...
via the Hummingbot Gateway connector" — demonstrated for real, not simulated.

## Finding #4 (the important one): closing a position on Meteora's site does NOT stop the bot

After the COT-SOL position above, the user closed it manually on Meteora's own website
(app.meteora.ag) rather than through this project's tooling. **The bot container kept
running.** Following `lp_rebalancer`'s inherited retry-on-close logic (see
`docs/phase3-notes.md`), it detected the out-of-band close and spent roughly the next
hour trying to reopen: repeatedly running `autoswap` to buy more of the base token
(COT) with the wallet's SOL whenever it computed a shortfall, retrying through Gateway/RPC
failures (rate limits, slippage tolerance, transaction simulation failures, an expired
blockhash), and — twice — **succeeding**: opening a brand-new real position with no user
action at all, each time funded partly by the SOL the autoswap loop had spent buying COT
along the way. The second one was caught and stopped (`docker stop`) only because the
user happened to check their wallet balance and noticed an unfamiliar token; confirmed
independently via Solscan (a "Position: Open" transaction ~50 seconds before the
container was actually killed) and via `docker ps` (the container had been `Up` for over
an hour since the very first deploy).

**The lesson, stated plainly: "close the position on the site" and "stop the bot" are
two different actions, and only killing the container actually stops the automation.**
This is not a bug in the sense of doing something wrong per its own logic — `lp_rebalancer`
is designed to treat any closed position as something to recover from, which is exactly
right when *it* closed the position and wrong when a human closed it on purpose out of
band. Both positions were eventually closed and funds recovered (verified: `positions_owned`
returns `[]`, final balance confirmed against Solscan), but this is a real gap, not just
a caveat:

- **Not yet built:** a way to tell a running bot "the human closed this on purpose, don't
  reopen" short of killing the container — e.g. detecting the position's on-chain closer
  wasn't the bot's own executor, or a simple external "pause" signal the frontend could
  send.
- **Not yet built:** a cap on how much the autoswap-driven retry loop can spend chasing a
  reopen — it kept buying more base token in small increments across many failed
  attempts with no overall budget, only the existing per-position-open retry counter.
- **Operational takeaway for the demo video and for real use:** always stop the bot
  container explicitly, never assume closing a position elsewhere is sufficient. Worth a
  loud warning in `docs/wallet-setup.md` and the frontend itself.

## Finding #5: position width has no relationship to a specific pool's bin coarseness

The opened position looked wrong in Meteora's own UI: "Total Bins: 2" — the practical
minimum. Root cause: `position_width_pct` (0.5%, the Moderate profile default) and
COT-SOL's `bin_step` (100) combine to just under 1 bin's worth of width per side, so
Meteora rounded up to the minimum viable range. The same width % lands on wildly
different bin counts depending on each pool's `bin_step`, which a risk-profile preset
has no way to anticipate. Fixed in the frontend: a "Number of bins" control appears once
a pool is selected (the Meteora pools API already returns `pool_config.bin_step`, it
just wasn't being read), computing `position_width_pct = numBins * bin_step / 100` —
labeled as a linear approximation, not an exact match to DLMM's actual compounding bin
pricing. Verified live against a real pool's real bin_step before pushing.
