"""
Tests for routines/meteora_pool_scanner.py's pure logic, using a real response captured
live from https://dlmm.datapi.meteora.ag/pools on 2026-08-30 (tests/fixtures/
meteora_pools_live_sample.json) rather than an invented shape — see docs/phase6-notes.md
for the live-testing pass this scanner was rewritten from (GeckoTerminal -> Meteora's own
API) and the min_tvl_quote bug it caught.
"""

import json
from pathlib import Path

from routines.meteora_pool_scanner import Config, _build_filter, _dwell_seconds, _parse_pool, _passes_filters

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "meteora_pools_live_sample.json").read_text())


def test_parse_pool_reads_real_response_shape():
    raw = FIXTURE["data"][0]  # SOL-USDC, high volume/TVL pool
    p = _parse_pool(raw)

    assert p["name"] == "SOL-USDC"
    assert p["address"] == raw["address"]
    assert p["volume_24h"] == raw["volume"]["24h"]
    assert p["tvl"] == raw["tvl"]
    assert p["vol_tvl_ratio"] == raw["volume"]["24h"] / raw["tvl"]
    assert p["market_cap"] == raw["token_x"]["market_cap"]
    assert p["dwell_seconds"] > 0  # pool_created_at is in the past


def test_parse_pool_handles_zero_tvl_without_dividing_by_zero():
    raw = dict(FIXTURE["data"][0])
    raw["tvl"] = 0
    p = _parse_pool(raw)
    assert p["vol_tvl_ratio"] == 0


def test_dwell_seconds_uses_epoch_milliseconds_not_iso_string():
    # created_at in the real API is epoch ms (confirmed live) -- a naive ISO-string
    # parse (this scanner's Phase-4 GeckoTerminal predecessor's convention) would raise
    # or silently misparse here.
    now_ms = FIXTURE["data"][0]["created_at"]
    seconds = _dwell_seconds(now_ms)
    assert seconds is not None
    assert seconds > 0


def test_dwell_seconds_none_when_missing():
    assert _dwell_seconds(None) is None


def test_passes_filters_rejects_pool_below_min_tvl():
    # Regression test for the Phase 6 bug: a near-zero-TVL pool must never pass, even
    # with high volume and a high vol/tvl ratio, because that ratio is meaningless noise.
    config = Config(min_volume_24h_quote=0, min_tvl_quote=1000, min_volume_tvl_ratio=0, min_dwell_time_seconds=0)
    p = {
        "volume_24h": 27_898.0,
        "tvl": 0.0000135,  # matches the degenerate real pool observed live
        "vol_tvl_ratio": 27_898.0 / 0.0000135,
        "dwell_seconds": 10_000,
        "market_cap": 100,
    }
    assert _passes_filters(p, config) is False


def test_passes_filters_accepts_healthy_pool_from_fixture():
    config = Config(min_volume_24h_quote=1000, min_tvl_quote=1000, min_volume_tvl_ratio=0.01, min_dwell_time_seconds=0)
    p = _parse_pool(FIXTURE["data"][0])
    assert _passes_filters(p, config) is True


def test_passes_filters_enforces_market_cap_range():
    config = Config(
        min_volume_24h_quote=0, min_tvl_quote=0, min_volume_tvl_ratio=0, min_dwell_time_seconds=0,
        market_cap_min=1_000_000_000, market_cap_max=2_000_000_000,
    )
    p = _parse_pool(FIXTURE["data"][1])  # ANTFUN-USDT, mcap ~482M -- below the floor
    assert _passes_filters(p, config) is False


def test_passes_filters_rejects_dwell_time_below_minimum():
    config = Config(min_volume_24h_quote=0, min_tvl_quote=0, min_volume_tvl_ratio=0, min_dwell_time_seconds=999_999_999)
    p = _parse_pool(FIXTURE["data"][0])
    assert _passes_filters(p, config) is False


def test_build_filter_includes_volume_and_tvl_floors():
    config = Config(min_volume_24h_quote=5000, min_tvl_quote=1000)
    filter_str = _build_filter(config)
    assert "volume_24h>5000" in filter_str
    assert "tvl>1000" in filter_str
    assert "is_blacklisted=false" in filter_str
