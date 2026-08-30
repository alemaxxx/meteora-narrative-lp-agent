# Phase 1 research notes — reference conventions

Findings from inspecting the official Hummingbot / Condor / Gateway repos and docs
before scaffolding this repo. Read-only research, no code was run.

## Hummingbot V2 Controller

- Controllers live in `controllers/<category>/` (e.g. `market_making/`, `generic/`),
  each with a Pydantic `Config(ControllerConfigBase)` class and a `Controller` class.
- Flow: `create --controller-config <name>` generates a YAML in `conf/controllers/` →
  [`scripts/v2_with_controllers.py`](https://github.com/hummingbot/hummingbot/blob/master/scripts/v2_with_controllers.py)
  loads the controller → `start --v2 <config>.yml` runs it.
- Reference implementation inspected: [`dman_maker_v2.py`](https://github.com/hummingbot/hummingbot/blob/master/controllers/market_making/dman_maker_v2.py).

## `lp_rebalancer` — official generic controller for CLMM/DLMM LP (key finding)

Hummingbot already ships a controller built for exactly this use case:
`controllers/generic/lp_rebalancer/`, created via
`create --controller-config generic.lp_rebalancer.lp_rebalancer`.

Config fields: `connector_name`, `lp_provider` (e.g. `meteora/clmm`), `pool_address`,
`total_amount_quote`, `side` (BUY/SELL/RANGE), `position_width_pct`,
`position_offset_pct`, `rebalance_threshold_pct`, `buy_price_min/max`,
`sell_price_min/max`, `strategy_type` (0=Spot, 1=Curve, 2=Bid-Ask), `autoswap`.

It already implements price-zone anchoring (BUY/SELL zones) and **KEEP-vs-rebalance
logic** (skips rebalancing when the position is already optimally anchored) — which is
most of what Phase 3 needs for "follow the trend up / exit-or-relocate down" and the
cost-benefit gate.

**Decision (confirmed 2026-08-30): Phase 3 extends `lp_rebalancer` rather than
reimplementing the DLMM position lifecycle from scratch.** This is both less code and
more aligned with the official convention that Botcamp validates submissions against.

Sources: [lp_rebalancer_guide.md](https://raw.githubusercontent.com/hummingbot/skills/main/skills/lp-agent/references/lp_rebalancer_guide.md),
[controller README](https://github.com/hummingbot/hummingbot/blob/development/controllers/generic/lp_rebalancer/README.md),
[hummingbot-api PR #120](https://github.com/hummingbot/hummingbot-api/pull/120).

### Refinement to apply when implementing (from Meteora's own "Zap Out" LP tip, 2026-08-30)

Meteora's own UI promotes ["Zap Out"](https://x.com/MeteoraAG/status/2094085426630058344) —
closing a position and instantly swapping into SOL/USDC in the same flow, to avoid
holding the falling token between position close and swap. The Gateway `meteora/clmm`
connector doesn't expose a single atomic "zap-out" endpoint (remove/close-position and
execute-swap are separate calls), so **when implementing the "downtrend → exit to
stable" behavior (strategy.md §4), chain remove-liquidity/close-position immediately
into execute-swap**, minimizing the price-exposure window between the two calls, rather
than treating them as independent, loosely-sequenced steps. Not a new feature — an
execution-order refinement of a behavior already in the design.

## LP Executor (single position, manual)

Executor used internally by `lp_rebalancer`, also usable standalone for manual control
(`lower_price`/`upper_price` fixed, `auto_close_above/below_range_seconds`). States:
`NOT_ACTIVE → OPENING → IN_RANGE ↔ OUT_OF_RANGE → CLOSING → COMPLETE`. Must always be
driven through the executor, never by calling the Gateway CLMM endpoints directly
(breaks state tracking).

## Meteora Gateway endpoints

`/connectors/meteora/clmm/{fetch-pools, pool-info, open-position, close-position,
add-liquidity, remove-liquidity, quote-position, positions-owned, quote-swap,
execute-swap, collect-fees}`. Config at `conf/connectors/meteora.yml` (slippage,
`strategyType`). **DAMM v2 has no Gateway connector today** — DLMM only, hence this repo
targets DLMM (see the `damm-infinite-monitor` private project for DAMM v2, unrelated to
this hackathon build).

## Condor Agent routine convention

Routines live in `routines/`, auto-discovered. Each file needs a Pydantic
`Config(BaseModel)` class (with a docstring description) and
`async def run(config: Config, context) -> str` (or a structured `RoutineResult`).
Optional module flags: `CONTINUOUS = True`, `CATEGORY`, `handle_callback`/`handle_message`.

Reference routine inspected: [`solana_pool_scanner.py`](https://github.com/hummingbot/condor/blob/main/routines/solana_pool_scanner.py) —
already does volume/TVL/volume-TVL-ratio filtering via GeckoTerminal, i.e. most of our
Phase 3 on-chain filter (layer 1). We still need to add market-cap range and dwell time.

## `hummingbot/skills/lp-agent` — operational reference

An official "skill" bundle with ready scripts for Meteora pool discovery, deploying
`lp_rebalancer` (`manage_controller.py`), monitoring (`manage_executor.py`), and
performance visualization/export (`visualize_lp_positions.py`,
`export_lp_positions.py`). Useful as an operational template for Phases 3 and 6
(dry-run workflow, demo video prep).

## Minimal structure this repo follows

- `controllers/generic/<name>/` (config + controller + README) on the Hummingbot side.
- `routines/<name>.py` on the Condor side.
- Pydantic `BaseModel` / `ControllerConfigBase` for all config — no invented format.
- Standard entrypoints (`v2_with_controllers.py` + `start --v2`; Condor's routine
  auto-discovery) — no custom entrypoint.
