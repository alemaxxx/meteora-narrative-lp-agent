"""
The bridge between Condor's judgment and the Controller's entry decision
(strategy.md §7): runs Layer 1 (meteora_pool_scanner) then Layer 2 (narrative_check)
for each survivor, and — only for pools that pass both — registers and deploys the
Phase 3 `narrative_lp_agent` controller via the Hummingbot API, using the chosen risk
profile's `conf/controllers/narrative_lp_agent_<profile>.example.yml` as the single
source of truth for every parameter except `trading_pair`/`pool_address`, which this
routine fills in per pool.

`dry_run=True` is the default deliberately: this routine reports what it WOULD deploy
without spending real capital. Setting `dry_run=False` is a reviewed, deliberate action
by whoever runs it (a human via Condor chat, or a later scheduled cycle once the
strategy is trusted) — matching strategy.md's framing of Condor as *supervising*
judgment, not acting unattended from day one.

Hummingbot API contract (POST /controllers/configs/{name}, then POST
/bot-orchestration/deploy-v2-controllers with controllers_config as a list of those
registered *names*) verified directly against the real `manage_controller.py` source
(downloaded, not paraphrased) — see docs/research-phase1-notes.md.
"""

CATEGORY = "Meteora LP Agent"

import base64
import logging
import os
import re
from pathlib import Path
from typing import Literal, Optional

import httpx
import yaml
from pydantic import BaseModel, Field
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent
HTTP_TIMEOUT = 30.0


class Config(BaseModel):
    """Layer 1 -> Layer 2 -> (optional) Controller deployment pipeline for one risk profile."""

    risk_profile: Literal["conservative", "moderate", "aggressive"] = Field(
        default="moderate",
        description="Which conf/controllers/narrative_lp_agent_<profile>.example.yml to read parameters from",
    )
    max_candidates_to_check: int = Field(
        default=5, description="Max Layer 1 survivors to run the narrative check on (rate/cost control)"
    )
    dry_run: bool = Field(
        default=True,
        description="If True (default), only reports what would be deployed. If False, actually "
                    "registers + deploys the controller for pools that pass both layers.",
    )


def _load_profile_template(risk_profile: str) -> dict:
    path = _REPO_ROOT / "conf" / "controllers" / f"narrative_lp_agent_{risk_profile}.example.yml"
    with open(path) as f:
        return yaml.safe_load(f)


def _parse_pair_from_name(name: str) -> tuple[Optional[str], Optional[str]]:
    """Meteora's own pools API (routines/meteora_pool_scanner.py, since the Phase 6
    rewrite) returns plain 'BASE-QUOTE' names, e.g. 'SOL-USDC' — no spaces around the
    hyphen and no trailing fee percentage. The fee-suffix strip and '/'-delimiter
    handling are kept for robustness against other sources, but the hyphen pattern
    below must NOT require surrounding whitespace, or every real pool name from the
    current data source fails to parse (caught live in Phase 6 — every candidate was
    silently skipped until this was fixed; see docs/phase6-notes.md and the regression
    test in tests/test_narrative_lp_funnel.py).

    Best-effort split into (base, quote) — returns (None, None) if the shape doesn't
    match, so the caller can skip a pool it can't confidently parse rather than build a
    bad trading pair."""
    cleaned = re.sub(r"\s*\d+(\.\d+)?%\s*$", "", name).strip()
    parts = re.split(r"\s*/\s*|\s*-\s*", cleaned)
    if len(parts) != 2:
        return None, None
    return parts[0].strip(), parts[1].strip()


def _prepare_controller_config(template: dict, risk_profile: str, pool: dict, base_symbol: str, quote_symbol: str) -> dict:
    config = dict(template)
    trading_pair = f"{base_symbol}-{quote_symbol}"
    config["id"] = f"narrative_lp_agent_{risk_profile}_{pool['address'][:8]}"
    config["trading_pair"] = trading_pair
    config["pool_address"] = pool["address"]
    return config


def _write_deploy_config(config: dict) -> Path:
    out_path = _REPO_ROOT / "conf" / "controllers" / f"{config['id']}.yml"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        yaml.safe_dump(config, f, sort_keys=False)
    return out_path


def _api_config() -> dict:
    return {
        "url": os.environ.get("HUMMINGBOT_API_URL", "http://localhost:8000"),
        "user": os.environ.get("API_USER", "admin"),
        "password": os.environ.get("API_PASS", "admin"),
    }


async def _api_request(method: str, endpoint: str, data: Optional[dict] = None) -> dict:
    api = _api_config()
    credentials = base64.b64encode(f"{api['user']}:{api['password']}".encode()).decode()
    headers = {"Authorization": f"Basic {credentials}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        resp = await client.request(method, f"{api['url']}{endpoint}", headers=headers, json=data)
        resp.raise_for_status()
        return resp.json()


async def _register_and_deploy(config: dict, bot_name: str) -> dict:
    """Two-step deploy matching the real Hummingbot API contract: register the named
    controller config, then reference it by name in the deploy call."""
    await _api_request("POST", f"/controllers/configs/{config['id']}", config)
    return await _api_request(
        "POST",
        "/bot-orchestration/deploy-v2-controllers",
        {
            "instance_name": bot_name,
            "controllers_config": [config["id"]],
            "credentials_profile": os.environ.get("HUMMINGBOT_CREDENTIALS_PROFILE", "master_account"),
            "image": os.environ.get("HUMMINGBOT_IMAGE", "hummingbot/hummingbot:development"),
            "headless": True,
        },
    )


async def run(config: Config, context: ContextTypes.DEFAULT_TYPE) -> str:
    from routines.base import RoutineResult
    from routines.meteora_pool_scanner import Config as ScannerConfig
    from routines.meteora_pool_scanner import scan
    from routines.narrative_check import Config as NarrativeConfig
    from routines.narrative_check import check_narrative

    template = _load_profile_template(config.risk_profile)

    scanner_config = ScannerConfig(
        min_volume_24h_quote=float(template["min_volume_24h_quote"]),
        min_tvl_quote=float(template.get("min_tvl_quote", 1000)),
        min_volume_tvl_ratio=float(template["min_volume_tvl_ratio"]),
        market_cap_min=float(template["market_cap_min"]) if template.get("market_cap_min") else None,
        market_cap_max=float(template["market_cap_max"]) if template.get("market_cap_max") else None,
        min_dwell_time_seconds=int(template["min_dwell_time_seconds"]),
    )
    candidates = await scan(scanner_config)

    lines = [
        f"Narrative LP Funnel — risk profile: {config.risk_profile} "
        f"({'DRY RUN' if config.dry_run else 'LIVE DEPLOY'})\n",
        f"Layer 1: {len(candidates)} pools passed the on-chain filter.\n",
    ]

    approved, rejected, skipped = [], [], []

    for pool in candidates[: config.max_candidates_to_check]:
        base_symbol, quote_symbol = _parse_pair_from_name(pool["name"])
        if not base_symbol:
            skipped.append(pool["name"])
            continue

        narrative = await check_narrative(NarrativeConfig(token_symbol=base_symbol, onchain_signal_passed=True))

        if not narrative["verdict"]:
            rejected.append((pool, narrative))
            continue

        deploy_config = _prepare_controller_config(template, config.risk_profile, pool, base_symbol, quote_symbol)
        deploy_path = _write_deploy_config(deploy_config)

        deploy_result = None
        deploy_error = None
        if not config.dry_run:
            try:
                bot_name = f"narrative_lp_agent_{config.risk_profile}_{pool['address'][:8]}"
                deploy_result = await _register_and_deploy(deploy_config, bot_name)
            except Exception as e:
                deploy_error = str(e)
                logger.error(f"Deploy failed for {deploy_config['id']}: {e}")

        approved.append((pool, narrative, deploy_config, deploy_path, deploy_result, deploy_error))

    lines.append(f"Layer 2: {len(approved)} approved (>=2/3 signals), {len(rejected)} rejected, {len(skipped)} skipped (unparseable pair).\n")

    for pool, narrative, deploy_config, deploy_path, deploy_result, deploy_error in approved:
        status = "DRY RUN — config written" if config.dry_run else ("DEPLOYED" if deploy_result else f"DEPLOY FAILED: {deploy_error}")
        lines.append(
            f"[APPROVED] {pool['name']} (pool {pool['address']})\n"
            f"  Signals: {narrative['signals']}\n"
            f"  Config: {deploy_path.relative_to(_REPO_ROOT)}\n"
            f"  {status}"
        )

    for pool, narrative in rejected:
        lines.append(f"[rejected] {pool['name']} — signals: {narrative['signals']}")

    if skipped:
        lines.append(f"[skipped] Could not parse trading pair for: {', '.join(skipped)}")

    report_text = "\n".join(lines)

    try:
        from condor.reports import ReportBuilder

        builder = ReportBuilder(f"Narrative LP Funnel — {config.risk_profile}")
        builder.source("routine", "narrative_lp_funnel").tags(["meteora", "narrative-lp-agent", config.risk_profile])
        builder.markdown(report_text)
        await builder.save()
    except Exception as e:
        logger.debug(f"ReportBuilder unavailable or failed, skipping dashboard report: {e}")

    return RoutineResult(text=report_text)
