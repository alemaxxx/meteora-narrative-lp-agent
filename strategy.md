# Strategy: Meteora Narrative LP Agent

**Track:** Meteora (DLMM) — Agent Builders Cup
**Format:** Hummingbot V2 Controller (deterministic execution) supervised by a Condor
Agent (LLM judgment)

## 1. Overview

Meteora Narrative LP Agent is an automated liquidity-provision bot for **Meteora DLMM
pools on Solana**, executed through the Hummingbot Gateway `meteora/clmm` connector. It
actively manages bin ranges and rebalances positions rather than taking a static range,
and it only enters a pool once two independent layers of evidence agree that the pool is
worth the risk: cheap on-chain metrics first, then a narrative/social confirmation check
supervised by an LLM (Condor Agent).

The Controller side extends Hummingbot's own `lp_rebalancer` generic controller (rather
than reimplementing DLMM position management from scratch), adding the entry funnel and
the three risk-profile presets described below.

## 2. Meteora track compliance

> "Strategies must provide liquidity or trade on Meteora pools (DLMM or DAMM v2) on
> Solana via the Hummingbot Gateway connector. Preference for automated LP strategies
> that actively manage bin ranges and rebalance positions. Bonus points for hedging LP
> inventory on another eligible venue."

- **LP via Hummingbot Gateway:** `meteora/clmm` connector, DLMM pools. (DAMM v2 has no
  Gateway connector as of this writing, so DLMM is the only viable venue for this
  submission.)
- **Active bin range management / rebalancing:** built on `lp_rebalancer`'s price-zone
  anchoring and KEEP-vs-rebalance logic (Section 4).
- **Bonus — cross-venue hedge:** optional toggle to hedge LP inventory on another
  eligible venue; on by default in the Conservative profile, off in Aggressive
  (Section 5).

## 3. Entry funnel (2 layers)

Every newly created DLMM pool is evaluated before any capital is committed. A pool must
clear **both** layers, and within them at least **2 of 3 independent signals**, before
the Controller is allowed to open a position.

### Layer 1 — on-chain filter (cheap, runs on every new pool)

- Minimum 24h volume
- Minimum Volume/TVL ratio
- Market-cap range (min/max)
- Minimum dwell time (pool age) before it's eligible at all

Only pools that pass Layer 1 are forwarded to Layer 2 — this keeps the expensive
narrative check off pools that are obviously too thin or too young.

### Layer 2 — narrative filter (only for pools that survive Layer 1)

The Condor Agent queries:

- **LunarCrush** — social score (a proxy for X/hype without needing the paid X API)
- **CryptoPanic** — real news coverage

**Cross-check rule:** entry requires at least **2 of 3** independent signals to agree
(on-chain volume, social score, real news) — this is what prevents entering on a single
manipulated signal (e.g. wash-traded volume with no real social backing, or a fake
news-adjacent pump).

## 4. Position management

Both behaviors below are **user-configurable**, not hardcoded — the risk profile picks a
default, advanced mode lets the user override either one independently.

- **Price exits the range upward:** either follow the trend (open a new position higher)
  or hold — user's choice.
- **Price exits the range downward:** either exit to the stable pair (avoids
  impermanent loss) or close-and-reopen lower (more fee exposure, more risk) — user's
  choice, both behaviors implemented and available.
- **Cost-benefit gate on every rebalance:** a rebalance only executes if expected fee
  income exceeds the cost of doing it (slippage + priority fee). This wraps
  `lp_rebalancer`'s existing KEEP-vs-rebalance logic with our own expected-fee estimate.

## 5. Risk profiles

Three ready-made presets bundle every parameter above (minimum volume, market-cap range,
dwell time, up/down-trend behavior, stop-loss, hedge on/off, check interval, position
width, rebalance threshold, cost-benefit margin), plus an **advanced mode** to override
any single field. The UI is a 3-button profile picker with an optional "advanced"
accordion — no wall of parameters up front.

| Profile | Entry filters | Rebalance cadence | Hedge |
|---|---|---|---|
| **Conservative** | Strictest volume/mcap/dwell-time thresholds | Wider bins, wider cost-benefit margin | On |
| **Moderate** | Balanced | Balanced | Configurable |
| **Aggressive** | Looser thresholds, faster reaction | Tighter bins, more frequent rebalancing | Off |

## 6. Multi-user

Any user connects their own wallet (client-side signing) and picks a profile — no
private key is ever held server-side.

## 7. Architecture

```
                 ┌──────────────────────────┐
 new DLMM pool → │ Layer 1: on-chain filter  │  (Controller, cheap, every pool)
                 └────────────┬─────────────┘
                               │ passes
                 ┌────────────▼─────────────┐
                 │ Layer 2: narrative filter │  (Condor: LunarCrush + CryptoPanic,
                 │  (2-of-3 cross-check)     │   2-of-3 cross-check)
                 └────────────┬─────────────┘
                               │ passes
                 ┌────────────▼─────────────┐
                 │ lp_rebalancer (extended)  │  (Controller: open/rebalance/close
                 │  + risk-profile preset    │   DLMM position via Gateway meteora/clmm,
                 │  + cost-benefit gate      │   cost-benefit gate on every rebalance)
                 └───────────────────────────┘
```

## 8. Status

Build phases are tracked in [README.md](./README.md).

**Phase 3 (Controller) is written, not yet run.** [`narrative_lp_agent`](./controllers/generic/narrative_lp_agent)
extends `lp_rebalancer` with the directional toggles, cost-benefit gate, and stop-loss
described in Sections 4–5 above, and the three profiles in Section 5 exist as config
templates in `conf/controllers/`. What it does *not* do yet: enforce the entry funnel
itself (that's Phase 4's job — a controller instance is bound to one pool from
deployment, so pool discovery/filtering has to happen before deployment, not inside it)
and execute the cross-venue hedge (config field exists, execution doesn't). See
[docs/phase3-notes.md](./docs/phase3-notes.md) for the reasoning and known limitations,
and [docs/research-phase1-notes.md](./docs/research-phase1-notes.md) for why extending
`lp_rebalancer` was the right call. Validation happens in Phase 6 (dry-run) — this repo
has no Hummingbot runtime installed to run it against yet.

**Phase 4 (narrative layer) is written, not yet run.** [`routines/`](./routines)
implements Layer 1 (`meteora_pool_scanner.py`), Layer 2 (`narrative_check.py`, LunarCrush
+ CryptoPanic 2-of-3 cross-check), and the bridge that fills in a risk profile's
Controller config per approved pool and deploys it (`narrative_lp_funnel.py`,
`dry_run=True` by default — deploying real capital is a deliberate, reviewed action, not
automatic). See [docs/phase4-notes.md](./docs/phase4-notes.md), including one correction
worth flagging: the Hummingbot API deploy contract was initially drafted from an
AI-paraphrased summary and was wrong (full config dicts vs. registered names) until
checked against the real source — a reminder that summaries are a lead to verify, not a
citable fact.
