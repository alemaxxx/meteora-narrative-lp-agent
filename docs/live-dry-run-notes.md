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

## Frontend: next up

Not yet tested against this live API (Phase 5 only tested it against a local static
server with no real backend). This stack now provides exactly what was missing —
tracked as the next step in this same live session.
