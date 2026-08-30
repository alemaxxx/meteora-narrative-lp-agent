"""
Layer 2 of the entry funnel (strategy.md §3): narrative/social confirmation for pools
that already passed Layer 1 (meteora_pool_scanner.py). Queries LunarCrush (social score)
and CryptoPanic (news), and combines them with the Layer 1 verdict into the 2-of-3
cross-check that prevents entering on a single manipulated signal.

Endpoints verified directly against each provider's own docs before writing this file
(not assumed from memory):
- LunarCrush v4: GET https://lunarcrush.com/api4/public/coins/{symbol}/v1,
  Authorization: Bearer <key> — https://github.com/lunarcrush/api
- CryptoPanic v1: GET https://cryptopanic.com/api/v1/posts/?auth_token=<key>&public=true&currencies=<symbol>

Known caveat: LunarCrush tracks an established coin list, not every freshly-launched
token — a brand-new pool's token may simply not be tracked yet. That's handled as
"signal unavailable" (counts as not-passed), which is the conservative, safe default
for the 2-of-3 rule rather than a special case.

Exposes `check_narrative()` as a plain importable function for narrative_lp_funnel.py,
separate from `run()`.
"""

CATEGORY = "Meteora LP Agent"

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from pydantic import BaseModel, Field
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

LUNARCRUSH_URL = "https://lunarcrush.com/api4/public/coins/{symbol}/v1"
CRYPTOPANIC_URL = "https://cryptopanic.com/api/v1/posts/"
HTTP_TIMEOUT = 10.0


class Config(BaseModel):
    """Layer 2 narrative cross-check: LunarCrush social score + CryptoPanic news,
    combined with the Layer 1 on-chain verdict into a 2-of-3 signal gate."""

    token_symbol: str = Field(description="Token symbol as tracked by LunarCrush/CryptoPanic, e.g. 'SOME' — NOT the pool address")
    onchain_signal_passed: bool = Field(default=True, description="Layer 1 verdict for this pool (from meteora_pool_scanner) — the 3rd signal")
    min_galaxy_score: float = Field(default=50.0, description="Minimum LunarCrush Galaxy Score to count the social signal as passed")
    min_news_count: int = Field(default=1, description="Minimum CryptoPanic news posts in the lookback window to count the news signal as passed")
    news_lookback_hours: int = Field(default=48, description="Lookback window for counting CryptoPanic posts")


async def _fetch_lunarcrush(symbol: str) -> Optional[dict]:
    api_key = os.environ.get("LUNARCRUSH_API_KEY")
    if not api_key:
        logger.warning("LUNARCRUSH_API_KEY not set — social signal will be treated as unavailable.")
        return None
    url = LUNARCRUSH_URL.format(symbol=symbol.upper())
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {api_key}"})
        if resp.status_code == 404:
            logger.info(f"LunarCrush has no data for {symbol} (not tracked, likely too new).")
            return None
        resp.raise_for_status()
        return resp.json().get("data")
    except Exception as e:
        logger.warning(f"LunarCrush request failed for {symbol}: {e}")
        return None


async def _fetch_cryptopanic(symbol: str, lookback_hours: int) -> list[dict]:
    api_key = os.environ.get("CRYPTOPANIC_API_KEY")
    if not api_key:
        logger.warning("CRYPTOPANIC_API_KEY not set — news signal will be treated as unavailable.")
        return []
    params = {"auth_token": api_key, "public": "true", "currencies": symbol.upper(), "kind": "news"}
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.get(CRYPTOPANIC_URL, params=params)
        resp.raise_for_status()
        results = resp.json().get("results", [])
    except Exception as e:
        logger.warning(f"CryptoPanic request failed for {symbol}: {e}")
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    recent = []
    for post in results:
        published = post.get("published_at")
        try:
            ts = datetime.fromisoformat(published.replace("Z", "+00:00")) if published else None
        except (ValueError, TypeError):
            ts = None
        if ts is None or ts >= cutoff:
            recent.append(post)
    return recent


async def check_narrative(config: Config) -> dict:
    """Pure signal-gathering + cross-check, importable by narrative_lp_funnel.py."""
    social_data = await _fetch_lunarcrush(config.token_symbol)
    news_posts = await _fetch_cryptopanic(config.token_symbol, config.news_lookback_hours)

    galaxy_score = social_data.get("galaxy_score") if social_data else None
    social_passed = galaxy_score is not None and galaxy_score >= config.min_galaxy_score
    news_passed = len(news_posts) >= config.min_news_count

    signals = {
        "onchain_volume": config.onchain_signal_passed,
        "social_score": social_passed,
        "news_coverage": news_passed,
    }
    passed_count = sum(1 for v in signals.values() if v)

    return {
        "token_symbol": config.token_symbol.upper(),
        "signals": signals,
        "passed_count": passed_count,
        "verdict": passed_count >= 2,
        "galaxy_score": galaxy_score,
        "news_count": len(news_posts),
        "news_headlines": [p.get("title", "") for p in news_posts[:5]],
    }


async def run(config: Config, context: ContextTypes.DEFAULT_TYPE) -> str:
    from routines.base import RoutineResult

    result = await check_narrative(config)

    verdict_str = "PASS (>=2/3 signals)" if result["verdict"] else "FAIL (<2/3 signals)"
    lines = [
        f"Narrative Check — {result['token_symbol']}: {verdict_str}\n",
        f"On-chain volume:  {'PASS' if result['signals']['onchain_volume'] else 'fail'}",
        f"Social score:     {'PASS' if result['signals']['social_score'] else 'fail'} "
        f"(Galaxy Score: {result['galaxy_score'] if result['galaxy_score'] is not None else 'unavailable'}, "
        f"threshold: {config.min_galaxy_score})",
        f"News coverage:    {'PASS' if result['signals']['news_coverage'] else 'fail'} "
        f"({result['news_count']} posts in last {config.news_lookback_hours}h, threshold: {config.min_news_count})",
    ]
    if result["news_headlines"]:
        lines.append("\nRecent headlines:")
        lines.extend(f"  - {h}" for h in result["news_headlines"])

    report_text = "\n".join(lines)

    try:
        from condor.reports import ReportBuilder

        builder = ReportBuilder(f"Narrative Check — {result['token_symbol']}")
        builder.source("routine", "narrative_check").tags(["meteora", "narrative", "narrative-lp-agent"])
        builder.markdown(report_text)
        await builder.save()
    except Exception as e:
        logger.debug(f"ReportBuilder unavailable or failed, skipping dashboard report: {e}")

    return RoutineResult(text=report_text, table_data=[
        {"Signal": k.replace("_", " ").title(), "Result": "PASS" if v else "fail"}
        for k, v in result["signals"].items()
    ], table_columns=["Signal", "Result"])
