# Phase 3 notes — Hummingbot V2 Controller

What was built, the key design decisions, and their known limitations. Written
2026-08-30, against the real `lp_rebalancer.py` source (downloaded from
`hummingbot/hummingbot` at the `development` branch and read directly — not
paraphrased) — see [docs/research-phase1-notes.md](./research-phase1-notes.md) for why
we extend it instead of reimplementing the DLMM position lifecycle.

## Extension strategy: post-filter, don't fork

`LPRebalancer.determine_executor_actions()` is a single ~280-line stateful method with
no factored-out hook for "which side should the next reopen use." Rather than fork and
maintain a parallel copy of that method (drift risk against upstream), `NarrativeLPAgent`
calls `super().determine_executor_actions()` to get the action the base class *would*
take, then inspects and — only for reopens, never the initial position — vetoes or lets
it through. This keeps 100% of the base class's position-lifecycle correctness (auto-close
via limit prices, KEEP logic, autoswap, orphaned-position halt, slippage ramp-carry) and
adds exactly four things on top: directional hold/exit toggles, a cost-benefit gate, a
stop-loss, and status reporting.

## Why the entry funnel isn't enforced inside this controller

A Hummingbot V2 Controller is deployed already bound to one `pool_address` — it has no
mechanism to scan many candidate pools and pick one. So "Layer 1 on-chain filter" +
"Layer 2 narrative cross-check" (strategy.md §3) can't live as runtime logic *inside*
this controller; they have to run *before* it's deployed, to decide both *whether* to
deploy and *which* `pool_address`/`trading_pair` to deploy it against. That's Phase 4's
job (a Condor routine, modeled on `solana_pool_scanner.py` per the Phase 1 research).

The entry-funnel threshold fields (`min_volume_24h_quote`, `min_volume_tvl_ratio`,
`market_cap_min/max`, `min_dwell_time_seconds`) are still declared on
`NarrativeLPAgentConfig` — not because this controller checks them, but so one YAML per
risk profile is the complete, self-documenting bundle strategy.md §5 describes, and so
the Phase 4 routine can read the exact same file as its source of thresholds instead of
duplicating them.

## The downtrend "exit to stable" is the Zap Out pattern, chained

When `downtrend_behavior=exit_to_stable` vetoes a SELL-side reopen, the replacement
action is a market SELL of the *entire current base-token wallet balance* into quote —
not a swap sized from the closed position's specific returned amount. Reason: by the
time our post-filter runs, `LPRebalancer` has already cleared `_last_closed_base_amount`
(it clears those fields right after building the reopen action it hands back). Reading
live wallet balance instead is simpler, doesn't depend on scraping fields the base class
manages for its own bookkeeping, and matches the "Zap Out" intent (see the Meteora tip
noted in `docs/research-phase1-notes.md`) of converting everything currently exposed —
at the cost of assuming a dedicated wallet (true under the Phase 5 one-wallet-per-user
design; documented as a caveat in the controller's README).

## Cost-benefit gate is a heuristic, not a simulation

`_expected_fee_quote_estimate()` averages the realized fees of the last 5 closed LP
positions. It is a trailing indicator, not a forecast of the *next* position's fee
income — a pool that just went quiet after being busy will overestimate; a pool
recovering after being quiet will underestimate. Good enough to stop obviously
unprofitable rapid-fire rebalancing on a still/dead pool; not precise. Marked as a
refinement target in the controller's README rather than treated as accurate.

## Pause/resume has no auto-resume, deliberately

Directional hold, downtrend exit, and stop-loss all set a pause flag that blocks all
further action until an operator (or a later Condor routine) updates the running config
or redeploys. We considered auto-resuming when price re-enters the configured buy/sell
zone, but that requires trusting a heuristic re-entry signal for exactly the situations
(a stop-loss, a deliberate "stay out") where a wrong guess is most costly. Matches the
base class's own precedent: an orphaned position also halts and requires manual recovery.

## Hedge is a config stub, not a feature

`hedge_enabled` / `hedge_venue` / `hedge_ratio_pct` exist on the config so the risk-profile
YAMLs match strategy.md's table (hedge on for Conservative, off for Aggressive), but no
hedge order is ever placed — the controller only logs a warning when `hedge_enabled=true`.
Implementing this needs a second connector/venue and its own execution logic; explicitly
out of scope for this pass, called out here and in the controller's README so it isn't
mistaken for working functionality.

## Verification status

Syntax-checked with `python -m py_compile` (catches typos, not import correctness — this
repo has no Hummingbot package installed to import-check or run against). Full validation
is Phase 6's dry-run.
