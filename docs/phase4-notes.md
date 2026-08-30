# Phase 4 notes — Condor narrative layer

Three routines, following Condor's real routine convention exactly (Config +
`async def run(config, context) -> RoutineResult`, discovered from `routines/`) —
verified against the actual downloaded source of `solana_pool_scanner.py`,
`base.py`, and `manage_controller.py` (not paraphrased), per
[docs/research-phase1-notes.md](./research-phase1-notes.md).

## routines/meteora_pool_scanner.py — Layer 1 (on-chain)

Same GeckoTerminal data source and fetch pattern as Condor's own reference
`solana_pool_scanner.py`, narrowed to Meteora's DEX ids (`meteora-dlmm`, `meteora`) and
extended with the two filters that routine didn't have: market-cap range and minimum
dwell time (pool age).

**Known caveat, disclosed in the code:** market cap uses `market_cap_usd` when
GeckoTerminal provides it, falling back to `fdv_usd` (fully diluted valuation) — a
reasonable proxy for brand-new tokens where GeckoTerminal hasn't verified circulating
supply, but a proxy nonetheless. Needs a live-response check in Phase 6 before trusting
it for real capital decisions.

## routines/narrative_check.py — Layer 2 (narrative)

LunarCrush (Galaxy Score) + CryptoPanic (recent news), combined with the Layer 1 verdict
passed in as `onchain_signal_passed` into strategy.md §3's 2-of-3 cross-check. Both
endpoints were verified directly against each provider's own docs before writing this
file (see the module docstring for the exact URLs/auth — not assumed from memory).

**Known caveat, disclosed in the code:** LunarCrush tracks an established coin list, not
every freshly-launched token. A brand-new pool's token may simply return 404 — handled as
"signal unavailable" (counts as not-passed), the conservative default for a 2-of-3 gate
rather than a special case that needs its own branch.

## routines/narrative_lp_funnel.py — the bridge to the Phase 3 Controller

Runs Layer 1 → Layer 2 for each survivor → for pools that pass both, fills in
`trading_pair`/`pool_address` on the chosen risk profile's
`conf/controllers/narrative_lp_agent_<profile>.example.yml` template and, if
`dry_run=False`, registers + deploys it via the Hummingbot API. This is strategy.md §7's
"Condor supervises the Controller's entry decision" made concrete: one risk-profile YAML
is the single source of truth for every parameter except the per-pool pair/address this
routine fills in — exactly the design decided in Phase 3.

**`dry_run=True` is the default on purpose.** The routine always reports what it would
deploy; actually spending capital (`dry_run=False`) is a deliberate action by whoever
runs it. This is deliberately *not* "the LLM decides and trades unsupervised on day one" —
it's the routine doing the mechanical 2-of-3 cross-check and a human (or later, a trusted
scheduled cycle) reviewing before committing.

**Deploy API contract verified against real source, not summary.** The first version of
this file was drafted from an AI-paraphrased summary of `manage_controller.py`, which
described `deploy-v2-controllers` as taking full config dicts. That was wrong — the real
contract is two calls: `POST /controllers/configs/{name}` to register a named config,
then `POST /bot-orchestration/deploy-v2-controllers` with `controllers_config` as a list
of those *names*, not dicts. Caught by downloading and reading the actual script before
finalizing this file — a reminder that AI-generated summaries of source code are a
starting point for what to go verify, not a citable fact on their own.

## What's still not real end-to-end

- No Hummingbot API, Gateway, or Condor runtime is running anywhere near this repo —
  none of these three routines have executed. `python -m py_compile` confirms syntax
  only.
- `_parse_pair_from_name` is a best-effort regex against GeckoTerminal's pool-name
  string format observed in the reference routine's code; pools with unusual naming will
  be skipped (logged as `[skipped]`) rather than mis-parsed into a wrong trading pair.
- The LunarCrush/CryptoPanic response field names (`galaxy_score`, `results[].title`,
  `results[].published_at`) come from each provider's public docs, not a live test call —
  worth a real API call with a funded key before Phase 6.

Full validation is still Phase 6 (dry-run), same as Phase 3.
