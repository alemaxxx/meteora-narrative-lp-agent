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
    narrative_lp_agent/   # our Controller: extends Hummingbot's lp_rebalancer
                           # with the on-chain + narrative entry funnel and the
                           # 3 risk-profile presets (Phase 3)
conf/
  controllers/            # generated YAML configs (git-ignored; *.example.yml tracked)
routines/
  ...                      # Condor routines: narrative/social signal checks (Phase 4)
scripts/
  ...                      # operational scripts: dry-run, deploy, monitor (Phase 6)
docs/
  ...                      # research notes, design decisions
strategy.md                # strategy write-up required by the hackathon submission
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
2. ✅ Repository scaffold (this commit)
3. ⬜ Hummingbot V2 Controller — on-chain filter, `lp_rebalancer` extension, 3 risk
   profiles
4. ⬜ Narrative layer (Condor Agent — LunarCrush + CryptoPanic, 2-of-3 cross-check)
5. ⬜ Multi-user / connect-wallet layer
6. ⬜ Dry-run / simulation mode + demo video

## Disclaimer

Experimental hackathon software. Not financial advice. Use at your own risk; test in
dry-run / testnet before connecting a funded wallet.
