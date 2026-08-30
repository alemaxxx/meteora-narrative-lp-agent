"""
Tests for routines/narrative_lp_funnel.py's pure functions: pair parsing, config
templating, and reading the real conf/controllers/*.example.yml files this routine
depends on as its single source of truth (see docs/phase3-notes.md).

NOT covered here (needs a live Hummingbot API — see docs/phase6-notes.md /
docs/dry-run-runbook.md): _register_and_deploy / the full run() pipeline.
"""

import routines.narrative_lp_funnel as funnel


def test_parse_pair_from_name_hyphenated():
    assert funnel._parse_pair_from_name("SOME-USDC") == ("SOME", "USDC")


def test_parse_pair_from_name_slash_with_fee_suffix():
    assert funnel._parse_pair_from_name("SOME / USDC 0.3%") == ("SOME", "USDC")


def test_parse_pair_from_name_unparseable_returns_none_none():
    assert funnel._parse_pair_from_name("not a pair at all") == (None, None)


def test_load_profile_template_reads_real_conservative_yaml():
    template = funnel._load_profile_template("conservative")
    assert template["controller_name"] == "narrative_lp_agent"
    assert template["risk_profile"] == "conservative"
    assert template["downtrend_behavior"] == "exit_to_stable"
    assert "min_tvl_quote" in template  # Phase 6 fix must be present in all 3 profiles


def test_load_profile_template_reads_all_three_profiles():
    for profile in ("conservative", "moderate", "aggressive"):
        template = funnel._load_profile_template(profile)
        assert template["risk_profile"] == profile
        assert template["min_volume_24h_quote"]
        assert template["min_tvl_quote"]


def test_prepare_controller_config_fills_pool_and_pair():
    template = funnel._load_profile_template("moderate")
    pool = {"address": "PoolAddress12345678", "name": "SOME-USDC"}

    config = funnel._prepare_controller_config(template, "moderate", pool, "SOME", "USDC")

    assert config["trading_pair"] == "SOME-USDC"
    assert config["pool_address"] == "PoolAddress12345678"
    assert config["id"] == "narrative_lp_agent_moderate_PoolAddr"
    # Every other field from the template must survive untouched
    assert config["downtrend_behavior"] == template["downtrend_behavior"]
    assert config["min_fee_to_cost_ratio"] == template["min_fee_to_cost_ratio"]


def test_write_deploy_config_writes_yaml_to_given_root(tmp_path, monkeypatch):
    monkeypatch.setattr(funnel, "_REPO_ROOT", tmp_path)
    config = {"id": "narrative_lp_agent_moderate_test1234", "trading_pair": "SOME-USDC"}

    out_path = funnel._write_deploy_config(config)

    assert out_path.exists()
    assert out_path.parent == tmp_path / "conf" / "controllers"
    written = out_path.read_text()
    assert "trading_pair: SOME-USDC" in written


def test_api_config_reads_env_vars(monkeypatch):
    monkeypatch.setenv("HUMMINGBOT_API_URL", "http://example.test:9000")
    monkeypatch.setenv("API_USER", "someone")
    monkeypatch.setenv("API_PASS", "secret")

    api = funnel._api_config()

    assert api == {"url": "http://example.test:9000", "user": "someone", "password": "secret"}


def test_api_config_defaults_when_unset(monkeypatch):
    monkeypatch.delenv("HUMMINGBOT_API_URL", raising=False)
    monkeypatch.delenv("API_USER", raising=False)
    monkeypatch.delenv("API_PASS", raising=False)

    api = funnel._api_config()

    assert api == {"url": "http://localhost:8000", "user": "admin", "password": "admin"}
