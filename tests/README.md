# Tests

```bash
python -m venv .venv
.venv/Scripts/pip install -r ../requirements-dev.txt   # .venv/bin/pip on macOS/Linux
.venv/Scripts/python -m pytest . -v
```

37 tests, no network access required (LunarCrush/CryptoPanic are mocked, GeckoTerminal/
Meteora calls use a captured fixture) except `tests/test_meteora_pool_scanner.py` does
not itself make live calls either — the live check that validated its rewrite was a
manual, throwaway script, not part of this suite (see `docs/phase6-notes.md`).

- `stubs.py` — minimal stand-ins for the Hummingbot modules `narrative_lp_agent.py`
  imports. **Read its module docstring before trusting `test_narrative_lp_agent.py`'s
  results** — it explains exactly what is and isn't proven by stubbing `LPRebalancer`.
- `fixtures/meteora_pools_live_sample.json` — a real response captured live from
  Meteora's own DLMM pools API on 2026-08-30, not an invented shape.
- Everything else tests real, unstubbed logic (routine helper functions, config
  templating, real YAML files) with mocked HTTP where an external paid API is involved.

See [docs/phase6-notes.md](../docs/phase6-notes.md) for what running this suite caught
(two real bugs) and what it still doesn't prove (needs a live Hummingbot/Condor runtime
— see [docs/dry-run-runbook.md](../docs/dry-run-runbook.md)).
