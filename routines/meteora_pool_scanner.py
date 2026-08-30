"""
Layer 1 of the entry funnel (strategy.md §3): cheap on-chain filter, run against
every new Meteora DLMM pool before the expensive narrative check (narrative_check.py)
ever runs.

REWRITTEN in Phase 6 after live-testing the original GeckoTerminal-based version
(see docs/phase6-notes.md for the full story): GeckoTerminal's Solana DEX id list has
no "meteora-dlmm" id (confirmed live — 404; the ids that actually exist are "meteora",
"meteora-dbc", "meteora-damm-v2"), and the plain "meteora" id doesn't reliably
distinguish DLMM from legacy pools. Meteora publishes its own DLMM-specific pools API
with server-side filtering — verified live, response shape confirmed by inspecting a
real request, not assumed:

    GET https://dlmm.datapi.meteora.ag/pools
    ?page=1&page_size=<n>&sort_by=volume_24h:desc
    &filter_by=is_blacklisted=false&&tvl><n>&&volume_24h><n>

This is both more correct (DLMM only, no ambiguity) and cheaper (server-side volume/TVL
filtering means far fewer pools to fetch and filter client-side, vs. fanning out
GeckoTerminal page requests per DEX id).

Exposes `scan()` as a plain importable function, separate from `run()`, so
narrative_lp_funnel.py can call it directly without going through the Telegram-report
side effects `run()` produces when used standalone from chat.
"""

CATEGORY = "Meteora LP Agent"

import logging
from datetime import datetime, timezone
from typing import Optional

import httpx
from pydantic import BaseModel, Field
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

POOLS_URL = "https://dlmm.datapi.meteora.ag/pools"
HTTP_TIMEOUT = 15.0
MAX_PAGE_SIZE = 1000  # API-documented ceiling


class Config(BaseModel):
    """Scan new Meteora DLMM pools via Meteora's own pools API and apply the Layer 1
    on-chain filter (volume, Volume/TVL ratio, market-cap range, minimum dwell time)."""

    min_volume_24h_quote: float = Field(default=10_000, description="Min 24h volume (USD)")
    min_tvl_quote: float = Field(
        default=1_000,
        description="Min TVL (USD) — a sanity floor, not just a quality bar: without it, "
                    "a near-zero-TVL pool with stale/leftover volume produces a Volume/TVL "
                    "ratio in the billions and dominates the ranking (caught live in Phase 6 "
                    "— see docs/phase6-notes.md).",
    )
    min_volume_tvl_ratio: float = Field(default=0.1, description="Min 24h volume / TVL ratio")
    market_cap_min: Optional[float] = Field(default=None, description="Min base-token market cap (USD), null = no floor")
    market_cap_max: Optional[float] = Field(default=None, description="Max base-token market cap (USD), null = no ceiling")
    min_dwell_time_seconds: int = Field(default=1800, description="Minimum pool age before it's eligible")
    top_n: int = Field(default=15, description="Number of pools to return")
    search_token: Optional[str] = Field(default=None, description="Filter pools containing this token symbol")
    fetch_page_size: int = Field(default=200, description="Pools to fetch server-side per request (max 1000)")


def _build_filter(config: Config) -> str:
    """Server-side pre-filter (volume/TVL floor only — ratio and market cap need the
    raw numbers and are applied client-side after fetch)."""
    parts = ["is_blacklisted=false"]
    if config.min_volume_24h_quote > 0:
        parts.append(f"volume_24h>{config.min_volume_24h_quote}")
    if config.min_tvl_quote > 0:
        parts.append(f"tvl>{config.min_tvl_quote}")
    return "&&".join(parts)


async def _fetch_pools(config: Config) -> list[dict]:
    params = {
        "page": "1",
        "page_size": str(min(config.fetch_page_size, MAX_PAGE_SIZE)),
        "sort_by": "volume_24h:desc",
        "filter_by": _build_filter(config),
    }
    if config.search_token:
        params["query"] = config.search_token
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.get(POOLS_URL, params=params)
        resp.raise_for_status()
        return resp.json().get("data", [])
    except Exception as e:
        logger.warning(f"Meteora pools API request failed: {e}")
        return []


def _dwell_seconds(created_at_ms: Optional[int]) -> Optional[float]:
    """Seconds since `created_at` (epoch milliseconds — confirmed by inspecting a live
    response; NOT an ISO string). None if missing."""
    if not created_at_ms:
        return None
    try:
        created = datetime.fromtimestamp(created_at_ms / 1000, tz=timezone.utc)
        return (datetime.now(timezone.utc) - created).total_seconds()
    except (ValueError, TypeError, OSError):
        return None


def _parse_pool(raw: dict) -> Optional[dict]:
    volume_24h = float((raw.get("volume") or {}).get("24h", 0) or 0)
    tvl = float(raw.get("tvl", 0) or 0)
    vol_tvl_ratio = (volume_24h / tvl) if tvl > 0 else 0

    # token_x is the base token in this API's `name` ("BASE-QUOTE") and market_cap
    # convention, confirmed on live SOL-USDC / TRUMP-USDC responses.
    token_x = raw.get("token_x") or {}
    market_cap = token_x.get("market_cap")
    market_cap = float(market_cap) if market_cap is not None else None

    return {
        "name": raw.get("name", ""),
        "volume_24h": volume_24h,
        "tvl": tvl,
        "vol_tvl_ratio": vol_tvl_ratio,
        "market_cap": market_cap,
        "dwell_seconds": _dwell_seconds(raw.get("created_at")),
        "base_price": raw.get("current_price", "?"),
        "address": raw.get("address", ""),
    }


def _passes_filters(p: dict, config: Config) -> bool:
    if p["volume_24h"] < config.min_volume_24h_quote:
        return False
    if p["tvl"] < config.min_tvl_quote:
        return False
    if p["vol_tvl_ratio"] < config.min_volume_tvl_ratio:
        return False
    if p["dwell_seconds"] is None or p["dwell_seconds"] < config.min_dwell_time_seconds:
        return False
    if config.market_cap_min is not None:
        if p["market_cap"] is None or p["market_cap"] < config.market_cap_min:
            return False
    if config.market_cap_max is not None:
        if p["market_cap"] is None or p["market_cap"] > config.market_cap_max:
            return False
    return True


async def scan(config: Config) -> list[dict]:
    """Fetch (server-side pre-filtered by volume) and apply the remaining client-side
    filters. Importable by narrative_lp_funnel.py. Returns candidates sorted by
    Volume/TVL ratio (highest first), deduplicated by address."""
    raw_pools = await _fetch_pools(config)
    all_pools = [p for raw in raw_pools if (p := _parse_pool(raw))]

    seen = set()
    unique = []
    for p in all_pools:
        if p["address"] and p["address"] not in seen:
            seen.add(p["address"])
            unique.append(p)

    passed = [p for p in unique if _passes_filters(p, config)]
    passed.sort(key=lambda p: p["vol_tvl_ratio"], reverse=True)
    return passed[: config.top_n]


def _fmt_usd(val: Optional[float]) -> str:
    if val is None:
        return "?"
    if val >= 1_000_000:
        return f"${val / 1_000_000:.1f}M"
    if val >= 1_000:
        return f"${val / 1_000:.1f}K"
    return f"${val:.0f}"


async def run(config: Config, context: ContextTypes.DEFAULT_TYPE) -> str:
    from routines.base import RoutineResult

    raw_pools = await _fetch_pools(config)
    total_fetched = len({p["address"] for raw in raw_pools if (p := _parse_pool(raw)) and p["address"]})

    top = await scan(config)

    if not top:
        return "No Meteora DLMM pools passed the Layer 1 on-chain filter."

    lines = [f"Meteora Pool Scanner (Layer 1) — {len(top)} pools passed filters (of {total_fetched} fetched)\n"]
    for i, p in enumerate(top, 1):
        dwell_h = (p["dwell_seconds"] or 0) / 3600
        lines.append(
            f"{i}. {p['name']}\n"
            f"   Vol: {_fmt_usd(p['volume_24h'])} | TVL: {_fmt_usd(p['tvl'])} | "
            f"V/T: {p['vol_tvl_ratio']:.2f}x | MCap: {_fmt_usd(p['market_cap'])} | "
            f"Age: {dwell_h:.1f}h\n"
            f"   Pool: {p['address']}"
        )
    report_text = "\n".join(lines)

    try:
        from condor.reports import ReportBuilder

        builder = ReportBuilder("Meteora Pool Scanner (Layer 1)")
        builder.source("routine", "meteora_pool_scanner").tags(["meteora", "solana", "dlmm", "narrative-lp-agent"])
        builder.markdown(
            f"Fetched {total_fetched} Meteora DLMM pools. {len(top)} passed the on-chain "
            f"filter (vol >= {_fmt_usd(config.min_volume_24h_quote)}, V/T >= "
            f"{config.min_volume_tvl_ratio}x, dwell >= {config.min_dwell_time_seconds}s)."
        )
        builder.table(
            [
                {
                    "#": i,
                    "Pool": p["name"],
                    "Vol 24h": _fmt_usd(p["volume_24h"]),
                    "TVL": _fmt_usd(p["tvl"]),
                    "V/T": f"{p['vol_tvl_ratio']:.2f}x",
                    "MCap": _fmt_usd(p["market_cap"]),
                    "Age (h)": f"{(p['dwell_seconds'] or 0) / 3600:.1f}",
                    "Address": p["address"],
                }
                for i, p in enumerate(top, 1)
            ]
        )
        builder.manual_order()
        await builder.save()
    except Exception as e:
        logger.debug(f"ReportBuilder unavailable or failed, skipping dashboard report: {e}")

    return RoutineResult(text=report_text)
