"""
Tests for routines/narrative_check.py's 2-of-3 cross-check, with LunarCrush/CryptoPanic
HTTP calls mocked (pytest-httpx) rather than hitting the real APIs (which need paid
keys this repo doesn't have — see docs/phase6-notes.md).
"""

import re
from datetime import datetime, timedelta, timezone

import pytest

from routines.narrative_check import Config, check_narrative

LUNARCRUSH_URL = "https://lunarcrush.com/api4/public/coins/SOME/v1"
CRYPTOPANIC_URL = re.compile(r"^https://cryptopanic\.com/api/v1/posts/")


@pytest.fixture(autouse=True)
def api_keys(monkeypatch):
    monkeypatch.setenv("LUNARCRUSH_API_KEY", "test-lc-key")
    monkeypatch.setenv("CRYPTOPANIC_API_KEY", "test-cp-key")


def _news_post(hours_ago: float, title: str = "Some headline"):
    ts = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return {"title": title, "published_at": ts.isoformat().replace("+00:00", "Z")}


@pytest.mark.asyncio
async def test_all_three_signals_pass_gives_verdict_true(httpx_mock):
    httpx_mock.add_response(url=LUNARCRUSH_URL, json={"data": {"galaxy_score": 75}})
    httpx_mock.add_response(url=CRYPTOPANIC_URL, json={"results": [_news_post(1), _news_post(5)]})

    result = await check_narrative(Config(token_symbol="SOME", onchain_signal_passed=True))

    assert result["verdict"] is True
    assert result["passed_count"] == 3
    assert result["signals"] == {"onchain_volume": True, "social_score": True, "news_coverage": True}


@pytest.mark.asyncio
async def test_lunarcrush_404_treated_as_unavailable_not_passed(httpx_mock):
    httpx_mock.add_response(url=LUNARCRUSH_URL, status_code=404)
    httpx_mock.add_response(url=CRYPTOPANIC_URL, json={"results": [_news_post(1)]})

    result = await check_narrative(Config(token_symbol="SOME", onchain_signal_passed=True))

    assert result["signals"]["social_score"] is False
    assert result["galaxy_score"] is None
    # onchain (True) + news (True) = 2/3 -> still passes despite social being unavailable
    assert result["verdict"] is True


@pytest.mark.asyncio
async def test_two_of_three_rule_fails_with_only_one_signal(httpx_mock):
    httpx_mock.add_response(url=LUNARCRUSH_URL, status_code=404)
    httpx_mock.add_response(url=CRYPTOPANIC_URL, json={"results": []})

    result = await check_narrative(Config(token_symbol="SOME", onchain_signal_passed=True))

    assert result["passed_count"] == 1
    assert result["verdict"] is False


@pytest.mark.asyncio
async def test_onchain_failing_pool_still_passes_on_social_plus_news(httpx_mock):
    httpx_mock.add_response(url=LUNARCRUSH_URL, json={"data": {"galaxy_score": 80}})
    httpx_mock.add_response(url=CRYPTOPANIC_URL, json={"results": [_news_post(1)]})

    result = await check_narrative(Config(token_symbol="SOME", onchain_signal_passed=False))

    assert result["passed_count"] == 2
    assert result["verdict"] is True


@pytest.mark.asyncio
async def test_galaxy_score_below_threshold_fails_social_signal(httpx_mock):
    httpx_mock.add_response(url=LUNARCRUSH_URL, json={"data": {"galaxy_score": 30}})
    httpx_mock.add_response(url=CRYPTOPANIC_URL, json={"results": []})

    result = await check_narrative(
        Config(token_symbol="SOME", onchain_signal_passed=True, min_galaxy_score=50)
    )

    assert result["signals"]["social_score"] is False
    assert result["passed_count"] == 1


@pytest.mark.asyncio
async def test_news_lookback_window_excludes_old_posts(httpx_mock):
    httpx_mock.add_response(url=LUNARCRUSH_URL, json={"data": {"galaxy_score": 90}})
    httpx_mock.add_response(
        url=CRYPTOPANIC_URL,
        json={"results": [_news_post(hours_ago=200, title="old news")]},  # outside 48h default window
    )

    result = await check_narrative(Config(token_symbol="SOME", onchain_signal_passed=True, min_news_count=1))

    assert result["news_count"] == 0
    assert result["signals"]["news_coverage"] is False


@pytest.mark.asyncio
async def test_missing_api_keys_treated_as_unavailable_not_a_crash(monkeypatch):
    monkeypatch.delenv("LUNARCRUSH_API_KEY", raising=False)
    monkeypatch.delenv("CRYPTOPANIC_API_KEY", raising=False)

    result = await check_narrative(Config(token_symbol="SOME", onchain_signal_passed=True))

    assert result["signals"]["social_score"] is False
    assert result["signals"]["news_coverage"] is False
    assert result["signals"]["onchain_volume"] is True
    assert result["passed_count"] == 1
    assert result["verdict"] is False
