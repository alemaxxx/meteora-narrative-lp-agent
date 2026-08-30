"""
Minimal stand-ins for the Hummingbot modules `narrative_lp_agent.py` imports, installed
into `sys.modules` before that module is imported for testing.

IMPORTANT — what this does and doesn't prove (see docs/phase6-notes.md): this stubs
`LPRebalancer` itself as a test double whose `determine_executor_actions()` returns
whatever a test tells it to (simulating "here's what the real lp_rebalancer decided this
tick"), rather than re-executing lp_rebalancer's real ~300-line state machine. That's a
deliberate choice, not a shortcut: it lets these tests target exactly what Phase 3 added
(the post-filter behavior in NarrativeLPAgent) in isolation, without re-verifying
lp_rebalancer's own correctness — that's Hummingbot's tested code, not ours. It does NOT
prove NarrativeLPAgent is compatible with the real ControllerBase/LPRebalancer runtime
contract (whose exact shape isn't available outside a real Hummingbot install) — that
still needs Phase 6's live dry-run.

Field sets on the stubbed Pydantic models (LPExecutorConfig, OrderExecutorConfig,
LPRebalancerConfig) match what the real downloaded lp_rebalancer.py source is observed
to construct/read (see docs/research-phase1-notes.md and docs/phase3-notes.md) — not
guessed from scratch.
"""

import sys
import types
from decimal import Decimal
from enum import Enum
from typing import Any, List, Optional

from pydantic import BaseModel, Field


class TradeType(Enum):
    BUY = 1
    SELL = 2
    RANGE = 3


class MarketDict(dict):
    def add_or_update(self, connector_name, trading_pair):
        self[connector_name] = trading_pair
        return self


class CandlesConfig:
    pass


class HummingbotLogger:
    pass


class ControllerConfigBase(BaseModel):
    id: str = "test_controller"


class ExecutorAction:
    pass


class CreateExecutorAction(ExecutorAction):
    def __init__(self, controller_id: str, executor_config: Any):
        self.controller_id = controller_id
        self.executor_config = executor_config


class CloseType(Enum):
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    EARLY_STOP = "EARLY_STOP"


class RunnableStatus(Enum):
    RUNNING = "RUNNING"
    TERMINATED = "TERMINATED"


class ConnectorPair(BaseModel):
    connector_name: str
    trading_pair: str


def parse_provider(lp_provider: str):
    """Matches the real gateway_utils.parse_provider contract inferred from usage:
    'meteora/clmm' -> ('meteora', 'clmm')."""
    dex, _, trading_type = lp_provider.partition("/")
    return dex, trading_type


class LPExecutorConfig(BaseModel):
    type: str = "lp_executor"
    timestamp: float = 0
    connector_name: str
    lp_provider: str
    trading_pair: str
    pool_address: str
    lower_price: Decimal
    upper_price: Decimal
    base_amount: Decimal
    quote_amount: Decimal
    side: TradeType
    slippage_pct: Decimal = Field(default=Decimal("0.05"))
    max_slippage_pct: Decimal = Field(default=Decimal("5"))
    extra_params: Optional[dict] = None
    upper_limit_price: Optional[Decimal] = None
    lower_limit_price: Optional[Decimal] = None
    keep_position: bool = False


class ExecutionStrategy(Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class OrderExecutorConfig(BaseModel):
    type: str = "order_executor"
    timestamp: float = 0
    connector_name: str
    trading_pair: str
    side: TradeType
    amount: Decimal
    execution_strategy: ExecutionStrategy


class ExecutorInfo:
    """Matches the attributes narrative_lp_agent.py / lp_rebalancer.py read off
    executors_info entries: id, is_active, is_done, status, config, custom_info."""

    def __init__(self, id, config, custom_info=None, is_active=False, is_done=False,
                 status=RunnableStatus.RUNNING, close_type=None):
        self.id = id
        self.config = config
        self.custom_info = custom_info or {}
        self.is_active = is_active
        self.is_done = is_done
        self.status = status
        self.close_type = close_type


class FakeMarketDataProvider:
    """Test-controllable stand-in for ControllerBase's market_data_provider."""

    def __init__(self, balances=None, now=1_700_000_000.0):
        self._balances = balances or {}
        self._now = now

    def initialize_rate_sources(self, *_a, **_kw):
        pass

    def get_balance(self, connector_name, token):
        return self._balances.get(token, Decimal("0"))

    def get_connector(self, connector_name):
        return types.SimpleNamespace(native_currency="SOL", get_native_currency_buffer=lambda: Decimal("0.005"))

    def time(self):
        return self._now


class FakeLPRebalancerConfig(ControllerConfigBase):
    """Stand-in for the real LPRebalancerConfig (see module docstring)."""

    controller_type: str = "generic"
    controller_name: str = "lp_rebalancer"
    connector_name: str = "solana-mainnet-beta"
    lp_provider: str = "meteora/clmm"
    trading_pair: str
    pool_address: str
    total_amount_quote: Decimal = Decimal("50")
    side: TradeType = TradeType.BUY
    position_width_pct: Decimal = Decimal("0.5")
    position_offset_pct: Decimal = Decimal("0.01")
    rebalance_threshold_pct: Decimal = Decimal("1")
    sell_price_max: Optional[Decimal] = None
    sell_price_min: Optional[Decimal] = None
    buy_price_max: Optional[Decimal] = None
    buy_price_min: Optional[Decimal] = None
    strategy_type: Optional[int] = None
    autoswap: bool = False
    swap_buffer_pct: Decimal = Decimal("0.01")


class FakeLPRebalancer:
    """Test double for LPRebalancer — see module docstring for what this does and
    doesn't prove. Tests drive it by appending to `queued_actions` (a list of action
    lists, one per call to determine_executor_actions)."""

    def __init__(self, config, *args, **kwargs):
        self.config = config
        self.market_data_provider = kwargs.get("market_data_provider") or FakeMarketDataProvider()
        self.executors_info: List[ExecutorInfo] = []
        self._base_token, self._quote_token = (config.trading_pair.split("-") + [""])[:2]
        self._pool_price: Optional[Decimal] = None
        self._initial_position_created = False
        self.queued_actions: List[list] = []

    def determine_executor_actions(self):
        if not self.queued_actions:
            return []
        actions = self.queued_actions.pop(0)
        self._initial_position_created = True
        return actions

    def logger(self):
        import logging
        return logging.getLogger("test")


def install():
    """Register the fake module tree in sys.modules. Call before importing
    controllers.generic.narrative_lp_agent.narrative_lp_agent."""

    def mod(name, **attrs):
        m = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(m, k, v)
        sys.modules[name] = m
        return m

    mod("hummingbot")
    mod("hummingbot.core")
    mod("hummingbot.core.data_type")
    mod("hummingbot.core.data_type.common", TradeType=TradeType, MarketDict=MarketDict)
    mod("hummingbot.core.utils")
    mod("hummingbot.core.utils.async_utils", safe_ensure_future=lambda coro: None)
    mod("hummingbot.data_feed")
    mod("hummingbot.data_feed.candles_feed")
    mod("hummingbot.data_feed.candles_feed.data_types", CandlesConfig=CandlesConfig)
    mod("hummingbot.logger", HummingbotLogger=HummingbotLogger)
    mod("hummingbot.strategy_v2")
    mod("hummingbot.strategy_v2.controllers", ControllerBase=FakeLPRebalancer, ControllerConfigBase=ControllerConfigBase)
    mod("hummingbot.strategy_v2.executors")
    mod("hummingbot.strategy_v2.executors.data_types", ConnectorPair=ConnectorPair)
    mod("hummingbot.strategy_v2.executors.gateway_utils", parse_provider=parse_provider)
    mod("hummingbot.strategy_v2.executors.lp_executor")
    mod("hummingbot.strategy_v2.executors.lp_executor.data_types", LPExecutorConfig=LPExecutorConfig)
    mod("hummingbot.strategy_v2.executors.order_executor")
    mod("hummingbot.strategy_v2.executors.order_executor.data_types",
        ExecutionStrategy=ExecutionStrategy, OrderExecutorConfig=OrderExecutorConfig)
    mod("hummingbot.strategy_v2.models")
    mod("hummingbot.strategy_v2.models.executor_actions",
        CreateExecutorAction=CreateExecutorAction, ExecutorAction=ExecutorAction)
    mod("hummingbot.strategy_v2.models.executors", CloseType=CloseType)
    mod("hummingbot.strategy_v2.models.executors_info", ExecutorInfo=ExecutorInfo)
    mod("hummingbot.strategy_v2.models.base", RunnableStatus=RunnableStatus)

    # NOTE: deliberately NOT stubbing "controllers" / "controllers.generic" themselves —
    # those are real namespace packages on disk (controllers/generic/narrative_lp_agent/
    # is what we're testing), and pre-registering fake modules for them would shadow
    # normal filesystem package resolution and break importing narrative_lp_agent.py.
    # Only the lp_rebalancer leaf — which doesn't exist in this repo, only inside a real
    # Hummingbot install — needs to be faked. Python resolves "controllers" and
    # "controllers.generic" from disk first, then finds these two already in
    # sys.modules and stops there without touching the filesystem for them.
    mod("controllers.generic.lp_rebalancer")
    mod("controllers.generic.lp_rebalancer.lp_rebalancer",
        LPRebalancer=FakeLPRebalancer, LPRebalancerConfig=FakeLPRebalancerConfig)
