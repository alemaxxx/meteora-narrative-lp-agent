# Phase 6 notes — validation and dry-run

What was actually run (not just written), what it caught, and what's still left for the
user's own infrastructure. Written 2026-08-30.

## Test setup

A local, gitignored virtualenv (`.venv/`) with `requirements-dev.txt` installed
(`pydantic`, `pyyaml`, `httpx`, `pytest`, `pytest-asyncio`, `pytest-httpx`, and
`python-telegram-bot` — the last one a genuine Condor routine dependency, needed to
import `routines/*.py` at all, not a test-only fake). 37 tests, all passing:

```
python -m venv .venv
.venv/Scripts/pip install -r requirements-dev.txt   # .venv/bin/pip on macOS/Linux
.venv/Scripts/python -m pytest tests/ -v
```

## Finding #1 (before writing any tests): GeckoTerminal's Meteora DEX id was wrong

`meteora_pool_scanner.py` (Phase 4) used `DEX_IDS = ["meteora-dlmm", "meteora"]`, copied
from Condor's own reference `solana_pool_scanner.py`. Live-checking it: `GET
.../dexes/solana/dexes/meteora-dlmm/pools` returns **404** — that id doesn't exist.
GeckoTerminal's real Solana DEX id list only has `meteora`, `meteora-dbc`,
`meteora-damm-v2` — no dedicated DLMM id, and the plain `meteora` id doesn't reliably
separate DLMM from legacy pools.

Looked for a better source instead of patching around it: Meteora publishes its own
DLMM-specific pools API, verified live —

```
GET https://dlmm.datapi.meteora.ag/pools
    ?page=1&page_size=<n>&sort_by=volume_24h:desc
    &filter_by=is_blacklisted=false&&tvl>1000&&volume_24h>10000
```

— server-side filtering, guaranteed-DLMM pools, direct `token_x.market_cap` /
`token_y.market_cap` (no `fdv_usd` proxy needed), and `created_at` as epoch
milliseconds (not the ISO-string `pool_created_at` the GeckoTerminal version assumed).
`meteora_pool_scanner.py` was rewritten around this API rather than patched — cheaper
(one filtered request instead of fanning out across DEX ids × pages) and more correct
(DLMM guaranteed, no ambiguity).

## Finding #2 (live scan, before any filter tuning): degenerate Volume/TVL ratios

The very first live `scan()` call returned pools like `TVL: 0.0000135` with `Volume/TVL:
2,073,431,521x` — nonsense, and it was **winning** the ranking because the scanner
sorted by Volume/TVL descending with no TVL floor. Added `min_tvl_quote` (default 1000,
scaled per risk profile: 1000 / 5000 / 20000 for aggressive / moderate / conservative)
as a real filter, not just a "nice to have" — without it, a near-zero-TVL pool with
stale volume dominates the ranking by construction. Re-ran live: results became sane
(SOL-USDC, `Volume/TVL: 21.7x`, real numbers). Propagated the new field to
`NarrativeLPAgentConfig`, all three `conf/controllers/*.example.yml` templates, and
`narrative_lp_funnel.py`'s template-to-scanner-config wiring. Regression test:
`tests/test_meteora_pool_scanner.py::test_passes_filters_rejects_pool_below_min_tvl`,
built directly from the degenerate pool observed live.

## Finding #3 (writing tests/test_narrative_lp_funnel.py): pair parsing was broken for every real pool name

`_parse_pair_from_name`'s regex required whitespace around a hyphen
(`\s+-\s+`) to split a name like `"SOME - USDC"` — written for GeckoTerminal's
`"SOME / USDC 0.3%"` format. Meteora's own API (now the primary source, per Finding #1)
returns bare `"SOL-USDC"` — no spaces. **Every real candidate pool would have silently
returned `(None, None)` and been skipped** — the funnel would have approved nothing,
ever, without erroring or logging anything wrong-looking (it logs skips as expected
"unparseable pair" cases, which look routine, not alarming). Caught by a straightforward
unit test (`test_parse_pair_from_name_hyphenated`), not by inspection. Fixed the regex
to `\s*-\s*` (optional, not required, whitespace).

## What the 37 tests actually cover

- **`tests/test_meteora_pool_scanner.py` (9)** — real logic, real fixture
  (`tests/fixtures/meteora_pools_live_sample.json`, captured live 2026-08-30, not
  invented). High confidence.
- **`tests/test_narrative_check.py` (7)** — real cross-check logic, LunarCrush/CryptoPanic
  HTTP mocked (pytest-httpx) since this repo has no paid API keys. The 2-of-3 rule,
  missing-key handling, and lookback-window filtering are exercised for real; the mocked
  response *shapes* are still only as good as Finding #1's lesson applies here too —
  verified against each provider's docs (Phase 4), not against a live authenticated call.
- **`tests/test_narrative_lp_funnel.py` (9)** — pure functions plus a real read of the
  actual `conf/controllers/*.example.yml` files (not fixtures — the real templates this
  routine depends on). Deploy-to-a-live-API is explicitly out of scope here.
- **`tests/test_narrative_lp_agent.py` (12)** — see `tests/stubs.py`'s module docstring
  for the important caveat: `LPRebalancer` itself is a test double whose
  `determine_executor_actions()` returns whatever a test configures, rather than
  re-executing the real ~300-line upstream state machine. This validates NarrativeLPAgent's
  own post-filter logic (the 4 things Phase 3 added) in isolation, on the assumption that
  the real `LPRebalancer`/`ControllerBase` contract matches what `tests/stubs.py` models
  (field names, `executors_info`, `market_data_provider.get_balance`/`.time()`, etc. —
  all taken from reading the real downloaded `lp_rebalancer.py` source, not guessed). It
  does **not** prove compatibility with the real Hummingbot runtime, whose exact
  `ControllerBase` implementation isn't available outside a real install.

## What's still not validated, and can't be from here

- No real Hummingbot instance, Gateway, or Condor bot has run any of this code. Every
  finding above came from either (a) live calls to genuinely public, keyless APIs
  (GeckoTerminal, Meteora's pools API), or (b) tests against stubs built from reading
  real source, not from running the real target systems.
- LunarCrush and CryptoPanic were verified against documentation and mocked in tests,
  never called live (need paid/registered keys this repo doesn't have).
- The Hummingbot API deploy calls (`narrative_lp_funnel.py`'s `_register_and_deploy`,
  `frontend/index.html`'s deploy button) have never hit a real API.
- The demo video the hackathon requires needs the bot actually running, which needs a
  funded wallet and a live Docker/Gateway/API stack — outside what this environment can
  do. See [docs/dry-run-runbook.md](./dry-run-runbook.md) for the steps to do that
  yourself.
