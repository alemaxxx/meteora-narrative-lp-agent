# Meteora Narrative LP Agent

Automated liquidity provision agent for **Meteora DLMM pools on Solana**, built for the
[Agent Builders Cup](https://botcamp.xyz) hackathon (racing for **Meteora**).

> Status: early build. See [strategy.md](./strategy.md) for the full strategy write-up
> and the phase log below for what's implemented so far.

## What it does

The agent watches newly created Meteora DLMM pools, filters them through a two-layer
funnel (on-chain metrics, then social/news narrative confirmation), and — once a pool
clears both layers — deploys and actively manages a concentrated liquidity position:
opening, rebalancing, and closing bins as price moves, according to a risk profile the
end user picks (Conservative / Moderate / Aggressive), with an optional advanced mode
for field-level tuning.

It is built as two cooperating layers, matching the two accepted submission formats for
this hackathon rather than inventing a third:

- **Hummingbot V2 Controller** (`controllers/`) — deterministic execution: position
  sizing, bin range management, rebalancing, on-chain filtering.
- **Condor Agent** (`routines/`) — LLM-supervised judgment: narrative/social signal
  checks (LunarCrush + CryptoPanic) that gate entries the Controller is allowed to take.

This split follows the official convention (see [docs/research-phase1-notes.md](./docs/research-phase1-notes.md)):
Botcamp validates submitted strategy code against the real Hummingbot Controller /
Condor Routine structure, so this repo builds directly on top of it — most notably by
**extending Hummingbot's own `lp_rebalancer` generic controller** (BUY/SELL price-zone
anchoring, KEEP-vs-rebalance logic, `meteora/clmm` support) instead of reimplementing
DLMM position management from scratch.

## Repository layout

```
controllers/
  generic/
    narrative_lp_agent/   # our Controller: extends Hummingbot's lp_rebalancer with
                           # directional toggles, a cost-benefit gate, and a stop-loss
                           # (Phase 3 — see its own README.md for what it does and
                           # does not enforce)
conf/
  controllers/            # risk-profile templates (*.example.yml, tracked); filled-in
                           # per-deployment configs are git-ignored
routines/
  meteora_pool_scanner.py  # Layer 1: on-chain filter (GeckoTerminal)
  narrative_check.py       # Layer 2: LunarCrush + CryptoPanic 2-of-3 cross-check
  narrative_lp_funnel.py   # bridges Layer 1+2 into a Controller deployment
scripts/
  ...                      # operational scripts: dry-run, deploy, monitor (Phase 6)
frontend/
  index.html                # static, no build step — risk-profile picker + deploy UI
                             # against the user's OWN Hummingbot API (see docs/wallet-setup.md)
tests/
  ...                      # 37 tests covering the logic this repo added — see tests/README.md
docs/
  ...                      # research notes, design decisions
strategy.md                # strategy write-up required by the hackathon submission
requirements.txt / requirements-dev.txt
```

## Compliance with the Meteora track criteria

> "Strategies must provide liquidity or trade on Meteora pools (DLMM or DAMM v2) on
> Solana via the Hummingbot Gateway connector. Preference for automated LP strategies
> that actively manage bin ranges and rebalance positions. Bonus points for hedging LP
> inventory on another eligible venue."

This agent targets **Meteora DLMM** via the Hummingbot Gateway `meteora/clmm` connector
(DAMM v2 has no Gateway connector today — see research notes), actively manages bin
ranges through automated rebalancing, and includes an optional cross-venue hedge toggle
for the LP inventory.

## Build phases

1. ✅ Reference research (official Hummingbot V2 Controller / Condor Routine / Meteora
   Gateway conventions) — see [docs/research-phase1-notes.md](./docs/research-phase1-notes.md)
2. ✅ Repository scaffold
3. 🟡 Hummingbot V2 Controller — [`narrative_lp_agent`](./controllers/generic/narrative_lp_agent)
   extends `lp_rebalancer` with directional toggles, a cost-benefit rebalance gate, a
   stop-loss, and the 3 risk-profile presets. **Written, not yet run** — see
   [docs/phase3-notes.md](./docs/phase3-notes.md); validation is Phase 6. The on-chain
   filter itself (pool discovery) is Phase 4's job, not this controller's.
4. 🟡 Narrative layer ([routines/](./routines)) — `meteora_pool_scanner.py` (Layer 1,
   on-chain), `narrative_check.py` (Layer 2, LunarCrush + CryptoPanic 2-of-3
   cross-check), `narrative_lp_funnel.py` (bridges both into a Phase 3 Controller
   deployment, `dry_run=True` by default). **Written, not yet run** — see
   [docs/phase4-notes.md](./docs/phase4-notes.md)
5. 🟡 Multi-user / connect-wallet layer ([frontend/](./frontend), [docs/wallet-setup.md](./docs/wallet-setup.md)) —
   **custody model corrected before building anything**, see
   [docs/phase5-notes.md](./docs/phase5-notes.md): Hummingbot Gateway signs
   autonomously from a key it holds (encrypted), not via live browser co-signing, so
   "non-custodial" here means each user self-hosts their own Gateway/API — the
   frontend never asks for a private key and never sends anything to a server this
   project runs. Verified working locally (profile selection, advanced fields, config
   preview, graceful connection-failure handling) — not yet tested against a live
   Hummingbot API. New pools now surface automatically: the frontend polls Meteora's own
   DLMM pools API directly from the browser every 30s (Layer 1 only, filtered by the
   selected risk profile), click a row to fill in the deploy fields — verified live in a
   real browser, see [docs/phase5-notes.md](./docs/phase5-notes.md).
6. 🟡 Dry-run / simulation mode ([tests/](./tests), [docs/phase6-notes.md](./docs/phase6-notes.md)) —
   37 tests passing, 2 real bugs found and fixed by actually running things (a dead
   GeckoTerminal DEX id + a missing TVL floor letting degenerate ratios dominate the
   scanner; a pair-parsing regex that silently skipped every real pool name). Demo
   video and full live-API validation are yours to do — see
   [docs/dry-run-runbook.md](./docs/dry-run-runbook.md).

## Running the tests

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements-dev.txt   # .venv/bin/pip on macOS/Linux
.venv/Scripts/python -m pytest tests/ -v
```

37 tests, no live Hummingbot/Condor runtime required — see [tests/README.md](./tests/README.md)
for what they do and don't cover, and [docs/phase6-notes.md](./docs/phase6-notes.md) for
two real bugs this suite (and the live checks that led to it) caught.

## Disclaimer

Experimental hackathon software. Not financial advice. Use at your own risk; test in
dry-run / testnet before connecting a funded wallet.
