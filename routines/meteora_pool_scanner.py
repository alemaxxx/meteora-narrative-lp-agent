"""
Layer 1 of the entry funnel (strategy.md §3): cheap on-chain filter, run against
every new Meteora DLMM pool before the expensive narrative check (narrative_check.py)
ever runs. Modeled directly on Condor's own `solana_pool_scanner.py` reference routine
(see docs/research-phase1-notes.md) — same GeckoTerminal data source and DEX id list,
narrowed to Meteora and extended with the two filters that routine didn't have: market
cap range and minimum pool age (dwell time).

Exposes `scan()` as a plain importable function, separate from `run()`, so
narrative_lp_funnel.py can call it directly without going through the Telegram-report
side effects `run()` produces when used standalone from chat.
"""

CATEGORY = "Meteora LP Agent"

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

NETWORK = "solana"
DEX_IDS = ["meteora-dlmm", "meteora"]
PAGES_DEFAULT = 3


class Config(BaseModel):
    """Scan new Meteora DLMM pools on Solana via GeckoTerminal and apply the Layer 1
    on-chain filter (volume, Volume/TVL ratio, market-cap range, minimum dwell time)."""

    min_volume_24h_quote: float = Field(default=10_000, description="Min 24h volume (USD)")
    min_volume_tvl_ratio: float = Field(default=0.1, description="Min 24h volume / TVL ratio")
    market_cap_min: Optional[float] = Field(default=None, description="Min token market cap / FDV (USD), null = no floor")
    market_cap_max: Optional[float] = Field(default=None, description="Max token market cap / FDV (USD), null = no ceiling")
    min_dwell_time_seconds: int = Field(default=1800, description="Minimum pool age before it's eligible")
    top_n: int = Field(default=15, description="Number of pools to return")
    search_token: Optional[str] = Field(default=None, description="Filter pools containing this token symbol")
    pages: int = Field(default=PAGES_DEFAULT, description="Pages to fetch per DEX id (20 pools/page)")


async def _fetch_pools_page(dex_id: str, page: int) -> list[dict]:
    from condor.pool_data import gecko_request

    try:
        body = await gecko_request(
            "GET",
            f"networks/{NETWORK}/dexes/{dex_id}/pools",
            params={"page": str(page)},
        )
        return body.get("data", [])
    except Exception as e:
        logger.warning(f"GeckoTerminal {dex_id} p{page} failed: {e}")
        return []


async def _fetch_all_pools(pages: int) -> list[dict]:
    tasks = [_fetch_pools_page(dex_id, page) for dex_id in DEX_IDS for page in range(1, pages + 1)]
    results = await asyncio.gather(*tasks)
    pools = []
    for batch in results:
        pools.extend(batch)
    return pools


def _dwell_seconds(created_at: Optional[str]) -> Optional[float]:
    """Seconds since `pool_created_at`. None if GeckoTerminal didn't return one for
    this pool — treated as "age unknown", not as "brand new", by the caller."""
    if not created_at:
        return None
    try:
        created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - created).total_seconds()
    except (ValueError, TypeError):
        return None


def _parse_pool(raw: dict) -> Optional[dict]:
    attr = raw.get("attributes", {})
    name = attr.get("name", "")
    volume_24h = float(attr.get("volume_usd", {}).get("h24", 0) or 0)
    tvl = float(attr.get("reserve_in_usd", 0) or 0)
    vol_tvl_ratio = (volume_24h / tvl) if tvl > 0 else 0

    # GeckoTerminal reports market_cap_usd only for tokens it has verified as
    # circulating-supply-accurate; fdv_usd (fully diluted valuation) is far more
    # consistently populated for brand-new tokens, so it's the fallback proxy.
    # NOTE: this proxy is best-effort — verify against live GeckoTerminal responses
    # in Phase 6 before trusting it for real capital decisions.
    market_cap = attr.get("market_cap_usd")
    market_cap = float(market_cap) if market_cap else None
    if market_cap is None:
        fdv = attr.get("fdv_usd")
        market_cap = float(fdv) if fdv else None

    dwell = _dwell_seconds(attr.get("pool_created_at"))

    dex_rel = raw.get("relationships", {}).get("dex", {}).get("data", {})
    dex_id = dex_rel.get("id", "unknown") if dex_rel else "unknown"

    return {
        "name": name,
        "dex_id": dex_id,
        "volume_24h": volume_24h,
        "tvl": tvl,
        "vol_tvl_ratio": vol_tvl_ratio,
        "market_cap": market_cap,
        "dwell_seconds": dwell,
        "base_price": attr.get("base_token_price_usd", "?"),
        "address": attr.get("address", ""),
    }


def _passes_filters(p: dict, config: Config) -> bool:
    if p["volume_24h"] < config.min_volume_24h_quote:
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
    """Pure fetch-and-filter, importable by narrative_lp_funnel.py. Returns candidate
    pools sorted by Volume/TVL ratio (highest first), already deduplicated by address."""
    raw_pools = await _fetch_all_pools(config.pages)
    all_pools = [p for raw in raw_pools if (p := _parse_pool(raw))]

    if config.search_token:
        token = config.search_token.upper()
        all_pools = [p for p in all_pools if token in p["name"].upper()]

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

    raw_pools = await _fetch_all_pools(config.pages)
    total_scanned = len({p["address"] for raw in raw_pools if (p := _parse_pool(raw)) and p["address"]})

    top = await scan(config)

    if not top:
        return "No Meteora DLMM pools passed the Layer 1 on-chain filter."

    lines = [f"Meteora Pool Scanner (Layer 1) — {len(top)} pools passed filters (of {total_scanned} scanned)\n"]
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
            f"Scanned {total_scanned} Meteora DLMM pools. {len(top)} passed the on-chain "
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
