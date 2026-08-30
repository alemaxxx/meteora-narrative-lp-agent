# narrative_lp_agent

Extends Hummingbot's stock [`lp_rebalancer`](https://github.com/hummingbot/hummingbot/blob/development/controllers/generic/lp_rebalancer/README.md)
generic controller (see `docs/research-phase1-notes.md` at the repo root for why we
extend rather than reimplement). Requires `lp_rebalancer.py` to be present at
`controllers/generic/lp_rebalancer/` in the same Hummingbot instance — it ships with
Hummingbot core, so this is true of any standard install/Docker image.

## What it adds on top of `lp_rebalancer`

- **`uptrend_behavior`** (`follow_trend` | `hold`) — what to do when price exits the
  range upward.
- **`downtrend_behavior`** (`exit_to_stable` | `reopen_lower`) — what to do when price
  exits the range downward. `exit_to_stable` converts the returned base token to quote
  immediately (the "Zap Out" pattern) instead of reopening lower.
- **Cost-benefit gate** (`min_fee_to_cost_ratio`, `estimated_rebalance_cost_quote`) —
  every reopen is skipped unless a trailing estimate of expected fee income clears this
  bar.
- **Stop-loss** (`stop_loss_pct`) — measured from the first position's entry price;
  overrides both toggles and forces a stable exit with a hard pause.
- **Entry-funnel and hedge fields** — carried here so one YAML per risk profile is a
  complete, self-documenting bundle (see "What this controller does NOT do" below).

## How the pause/resume model works

A directional hold, a downtrend exit, or a stop-loss all set an internal pause flag —
the controller then takes no further action, same as the base class's own handling of
an orphaned position (manual recovery, no silent auto-resume). To resume, update the
running config (e.g. flip `downtrend_behavior`, adjust `stop_loss_pct`) via Hummingbot's
live config-update mechanism, or redeploy the controller. This is a deliberate choice:
auto-resuming a stop-loss or a manually-configured "stay out" decision without a signal
we can actually validate would be worse than requiring an explicit restart.

## What this controller does NOT do

- **It does not scan for or select pools.** A controller instance targets one
  `pool_address` from the moment it's deployed. The on-chain filter fields
  (`min_volume_24h_quote`, `min_volume_tvl_ratio`, `market_cap_min/max`,
  `min_dwell_time_seconds`) and the narrative cross-check happen in the Phase 4 Condor
  routine, *before* this controller is deployed for a given pool — they're carried in
  this config only so the risk-profile YAML is one complete bundle.
- **It does not execute a cross-venue hedge.** `hedge_enabled` reserves the config field;
  when true, the controller only logs a warning that hedging is not implemented. Actual
  hedge order placement is future work.
- **The cost-benefit gate is a heuristic, not a live quote.** `estimated_rebalance_cost_quote`
  is a flat, user-set number; the "expected fee" side is a trailing average of the last
  few closed positions' realized fees, not a simulation of the next position's fee
  income. Good enough to stop obviously-unprofitable thrashing; not a precise estimate.
- **The stable-exit swap assumes a dedicated wallet.** It swaps the full current base
  balance, consistent with the Phase 5 one-wallet-per-user design — if the same wallet
  holds unrelated base-token balance, that gets swapped too.

## Status

Written against the real `lp_rebalancer.py` source (downloaded and read directly, not
paraphrased) and syntax-checked, but **not yet run** — this repo has no Hummingbot
runtime installed. End-to-end validation is Phase 6 (dry-run).
