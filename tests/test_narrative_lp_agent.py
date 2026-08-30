"""
Tests for the 4 behaviors NarrativeLPAgent adds on top of the (stubbed) LPRebalancer —
see tests/stubs.py's module docstring for exactly what is and isn't proven by these
tests, and docs/phase6-notes.md for the full picture.
"""

import types
from decimal import Decimal

from tests.stubs import (
    CreateExecutorAction,
    ExecutorInfo,
    FakeMarketDataProvider,
    LPExecutorConfig,
    OrderExecutorConfig,
    TradeType,
)

from controllers.generic.narrative_lp_agent.narrative_lp_agent import NarrativeLPAgent, NarrativeLPAgentConfig


def make_config(**overrides):
    defaults = dict(trading_pair="SOME-USDC", pool_address="Pool111")
    defaults.update(overrides)
    return NarrativeLPAgentConfig(**defaults)


def make_agent(config, balances=None):
    mdp = FakeMarketDataProvider(balances=balances or {})
    return NarrativeLPAgent(config, market_data_provider=mdp)


def lp_action(side, trading_pair="SOME-USDC", pool_address="Pool111"):
    return CreateExecutorAction(
        controller_id="test_controller",
        executor_config=LPExecutorConfig(
            connector_name="solana-mainnet-beta",
            lp_provider="meteora/clmm",
            trading_pair=trading_pair,
            pool_address=pool_address,
            lower_price=Decimal("1"),
            upper_price=Decimal("2"),
            base_amount=Decimal("10"),
            quote_amount=Decimal("0"),
            side=side,
        ),
    )


def test_initial_position_is_never_gated_and_captures_entry_price():
    agent = make_agent(make_config())
    agent._pool_price = Decimal("1.5")
    agent.queued_actions = [[lp_action(TradeType.BUY)]]

    actions = agent.determine_executor_actions()

    assert len(actions) == 1
    assert agent._entry_price == Decimal("1.5")
    assert agent._paused is False


def test_uptrend_hold_vetoes_buy_reopen():
    agent = make_agent(make_config(uptrend_behavior="hold"))
    agent._initial_position_created = True  # simulate: already past the first position
    agent.queued_actions = [[lp_action(TradeType.BUY)]]
    result = agent.determine_executor_actions()

    assert result == []
    assert agent._paused is True
    assert agent._pause_reason == "uptrend_hold"


def test_uptrend_follow_trend_passes_buy_reopen_through():
    agent = make_agent(make_config(uptrend_behavior="follow_trend"))
    agent._initial_position_created = True
    agent.queued_actions = [[lp_action(TradeType.BUY)]]

    result = agent.determine_executor_actions()

    assert len(result) == 1
    assert agent._paused is False


def test_downtrend_exit_to_stable_vetoes_sell_reopen_and_swaps_full_base_balance():
    agent = make_agent(
        make_config(downtrend_behavior="exit_to_stable"),
        balances={"SOME": Decimal("42")},
    )
    agent._initial_position_created = True
    agent.queued_actions = [[lp_action(TradeType.SELL)]]

    result = agent.determine_executor_actions()

    assert agent._paused is True
    assert agent._pause_reason == "downtrend_exit_to_stable"
    assert len(result) == 1
    swap_config = result[0].executor_config
    assert isinstance(swap_config, OrderExecutorConfig)
    assert swap_config.side == TradeType.SELL
    assert swap_config.amount == Decimal("42")


def test_downtrend_exit_to_stable_with_zero_balance_issues_no_swap_but_still_pauses():
    agent = make_agent(make_config(downtrend_behavior="exit_to_stable"), balances={})
    agent._initial_position_created = True
    agent.queued_actions = [[lp_action(TradeType.SELL)]]

    result = agent.determine_executor_actions()

    assert result == []
    assert agent._paused is True


def test_downtrend_reopen_lower_passes_sell_reopen_through_with_no_fee_history():
    agent = make_agent(make_config(downtrend_behavior="reopen_lower"))
    agent._initial_position_created = True
    agent.queued_actions = [[lp_action(TradeType.SELL)]]

    result = agent.determine_executor_actions()

    assert len(result) == 1
    assert agent._paused is False


def _closed_lp_executor(base_fee, quote_fee):
    return ExecutorInfo(
        id="closed-1",
        config=types.SimpleNamespace(type="lp_executor"),
        custom_info={"base_fee": base_fee, "quote_fee": quote_fee},
        is_done=True,
    )


def test_cost_benefit_gate_blocks_reopen_when_trailing_fees_are_low():
    agent = make_agent(
        make_config(
            downtrend_behavior="reopen_lower",
            min_fee_to_cost_ratio=Decimal("2"),
            estimated_rebalance_cost_quote=Decimal("1"),
        )
    )
    agent._initial_position_created = True
    agent._pool_price = Decimal("1")
    agent.executors_info = [_closed_lp_executor(Decimal("0"), Decimal("0.5"))]  # avg fee = 0.5 < 2*1
    agent.queued_actions = [[lp_action(TradeType.SELL)]]

    result = agent.determine_executor_actions()

    assert result == []
    assert agent._paused is False  # transient skip, not a hard pause


def test_cost_benefit_gate_allows_reopen_when_trailing_fees_are_high():
    agent = make_agent(
        make_config(
            downtrend_behavior="reopen_lower",
            min_fee_to_cost_ratio=Decimal("2"),
            estimated_rebalance_cost_quote=Decimal("1"),
        )
    )
    agent._initial_position_created = True
    agent._pool_price = Decimal("1")
    agent.executors_info = [_closed_lp_executor(Decimal("0"), Decimal("5"))]  # avg fee = 5 >= 2*1
    agent.queued_actions = [[lp_action(TradeType.SELL)]]

    result = agent.determine_executor_actions()

    assert len(result) == 1


def test_stop_loss_forces_stable_exit_even_when_downtrend_behavior_is_reopen_lower():
    agent = make_agent(
        make_config(downtrend_behavior="reopen_lower", stop_loss_pct=Decimal("10")),
        balances={"SOME": Decimal("7")},
    )
    agent._initial_position_created = True
    agent._entry_price = Decimal("100")
    agent._pool_price = Decimal("85")  # 15% drawdown >= 10% stop-loss
    agent.queued_actions = [[lp_action(TradeType.SELL)]]

    result = agent.determine_executor_actions()

    assert agent._paused is True
    assert agent._pause_reason == "stop_loss"
    assert len(result) == 1
    assert result[0].executor_config.amount == Decimal("7")


def test_stop_loss_not_triggered_below_threshold():
    agent = make_agent(make_config(downtrend_behavior="reopen_lower", stop_loss_pct=Decimal("10")))
    agent._initial_position_created = True
    agent._entry_price = Decimal("100")
    agent._pool_price = Decimal("95")  # 5% drawdown < 10%
    agent.queued_actions = [[lp_action(TradeType.SELL)]]

    result = agent.determine_executor_actions()

    assert agent._paused is False
    assert len(result) == 1


def test_paused_short_circuits_without_calling_super():
    agent = make_agent(make_config(uptrend_behavior="hold"))
    agent._initial_position_created = True
    agent.queued_actions = [[lp_action(TradeType.BUY)]]
    agent.determine_executor_actions()  # triggers the pause, consumes the queued action
    assert agent._paused is True
    assert agent.queued_actions == []  # the one queued action was consumed by this call

    sentinel = [[lp_action(TradeType.BUY)]]
    agent.queued_actions = sentinel
    result = agent.determine_executor_actions()

    assert result == []
    assert agent.queued_actions == sentinel  # untouched -- proves super() was never called


def test_hedge_enabled_does_not_raise():
    # Smoke test: constructing with hedge_enabled=True should only log a warning,
    # never raise or attempt to place an order (hedge execution isn't implemented).
    agent = make_agent(make_config(hedge_enabled=True))
    assert agent.config.hedge_enabled is True
