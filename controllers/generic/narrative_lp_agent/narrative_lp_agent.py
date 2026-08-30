"""
Narrative LP Agent — extends Hummingbot's stock `lp_rebalancer` generic controller.

Why extend instead of reimplement (see docs/research-phase1-notes.md): `lp_rebalancer`
already implements the DLMM position lifecycle (open/monitor/auto-close via LP executor
limit prices), BUY/SELL price-zone anchoring, and KEEP-vs-rebalance logic. This file adds
only what's specific to this hackathon submission on top of it:

1. A **directional behavior toggle**, independently configurable per direction:
   - `uptrend_behavior`: "follow_trend" (let the base class reopen higher, its default)
     or "hold" (stay flat in quote once price exits the range upward).
   - `downtrend_behavior`: "exit_to_stable" (convert the returned base token to quote
     instead of reopening lower — the "Zap Out" pattern, see docs/research-phase1-notes.md)
     or "reopen_lower" (let the base class reopen lower, its default — more fee income,
     more exposure).
2. A **cost-benefit gate** applied to every reopen (not the initial position): skips the
   rebalance for this tick if a trailing estimate of expected fee income doesn't clear a
   configurable multiple of the estimated rebalancing cost.
3. A **stop-loss**, measured from the entry price of the very first position, which
   overrides both toggles and forces a stable exit with a hard pause.
4. Config fields carrying the on-chain + narrative entry-funnel thresholds and the
   cross-venue hedge toggle, so one YAML per risk profile is the single source of truth
   for strategy.md's three presets — see the "What this controller does NOT do" section
   in this directory's README.md for exactly what is and isn't enforced at this layer.

IMPORTANT — untested: this repo has no Hummingbot runtime installed to run it against.
The code is written to compile against the real `lp_rebalancer.py` (verified by direct
download of the source, not paraphrased) and follows its own patterns, but it has not
been exercised end-to-end. Validation happens in Phase 6 (dry-run).
"""

import logging
from decimal import Decimal
from typing import List, Literal, Optional

from pydantic import Field

from controllers.generic.lp_rebalancer.lp_rebalancer import LPRebalancer, LPRebalancerConfig
from hummingbot.core.data_type.common import TradeType
from hummingbot.logger import HummingbotLogger
from hummingbot.strategy_v2.executors.lp_executor.data_types import LPExecutorConfig
from hummingbot.strategy_v2.executors.order_executor.data_types import ExecutionStrategy, OrderExecutorConfig
from hummingbot.strategy_v2.models.executor_actions import CreateExecutorAction, ExecutorAction


class NarrativeLPAgentConfig(LPRebalancerConfig):
    """
    Configuration for the Narrative LP Agent controller.

    Adds directional behavior toggles, a cost-benefit rebalance gate, a stop-loss, and
    the entry-funnel / hedge fields that make up one risk-profile bundle, on top of
    every field `LPRebalancerConfig` already provides (position sizing, price-zone
    anchoring, autoswap, etc. — see the parent class for those).
    """
    controller_name: str = "narrative_lp_agent"

    # --- Risk profile bookkeeping ---
    risk_profile: Literal["conservative", "moderate", "aggressive", "custom"] = Field(
        default="moderate",
        description="Informational label for which preset this config was built from. "
                    "Does not itself change runtime behavior — the fields below do."
    )

    # --- Entry funnel thresholds (Layer 1 on-chain + Layer 2 narrative) ---
    # NOT enforced by this controller at runtime — a controller instance is deployed
    # already targeting one specific pool_address, after a discovery routine (Phase 4)
    # has evaluated these thresholds and the narrative cross-check. They live here so a
    # single YAML per risk profile is the complete, self-documenting parameter bundle
    # strategy.md describes, and so the discovery routine can read the same file.
    min_volume_24h_quote: Decimal = Field(
        default=Decimal("10000"),
        description="[Enforced by the Phase 4 discovery routine, not this controller] "
                    "Minimum 24h volume in quote asset for a pool to be eligible."
    )
    min_tvl_quote: Decimal = Field(
        default=Decimal("1000"),
        description="[Enforced by the Phase 4 discovery routine, not this controller] "
                    "Minimum pool TVL — a sanity floor, not just a quality bar: without "
                    "it a near-zero-TVL pool can produce a Volume/TVL ratio in the "
                    "billions and dominate ranking by that metric (caught live in "
                    "Phase 6 — see docs/phase6-notes.md)."
    )
    min_volume_tvl_ratio: Decimal = Field(
        default=Decimal("0.1"),
        description="[Enforced by the Phase 4 discovery routine] Minimum 24h volume / TVL ratio."
    )
    market_cap_min: Optional[Decimal] = Field(
        default=None, description="[Enforced by the Phase 4 discovery routine] Minimum token market cap."
    )
    market_cap_max: Optional[Decimal] = Field(
        default=None, description="[Enforced by the Phase 4 discovery routine] Maximum token market cap."
    )
    min_dwell_time_seconds: int = Field(
        default=1800,
        description="[Enforced by the Phase 4 discovery routine] Minimum pool age before it's eligible."
    )

    # --- Directional behavior toggles ---
    uptrend_behavior: Literal["follow_trend", "hold"] = Field(
        default="follow_trend",
        json_schema_extra={"is_updatable": True},
        description="When price exits the range upward: 'follow_trend' reopens higher "
                    "(lp_rebalancer's default); 'hold' stays flat in quote instead."
    )
    downtrend_behavior: Literal["exit_to_stable", "reopen_lower"] = Field(
        default="exit_to_stable",
        json_schema_extra={"is_updatable": True},
        description="When price exits the range downward: 'exit_to_stable' converts the "
                    "returned base token to quote instead of reopening (avoids further IL); "
                    "'reopen_lower' lets lp_rebalancer reopen lower (more fee income, more "
                    "exposure) — its default."
    )

    # --- Cost-benefit gate (applied to every reopen, not the initial position) ---
    min_fee_to_cost_ratio: Decimal = Field(
        default=Decimal("1.5"),
        json_schema_extra={"is_updatable": True},
        description="A reopen only proceeds if the trailing expected-fee estimate is at "
                    "least this many times estimated_rebalance_cost_quote."
    )
    estimated_rebalance_cost_quote: Decimal = Field(
        default=Decimal("0.05"),
        json_schema_extra={"is_updatable": True},
        description="Rough fixed per-rebalance cost estimate in quote asset (slippage + "
                    "priority fee). A simple heuristic, not a live quote — refine with "
                    "real quote/priority-fee data in a later iteration."
    )

    # --- Stop-loss ---
    stop_loss_pct: Optional[Decimal] = Field(
        default=None,
        json_schema_extra={"is_updatable": True},
        description="If set, forces a stable exit and a hard pause (no auto-resume) once "
                    "price has dropped this % from the first position's entry price."
    )

    # --- Cross-venue hedge (bonus criterion; config surface only, see README) ---
    hedge_enabled: bool = Field(
        default=False,
        json_schema_extra={"is_updatable": True},
        description="Reserves config for hedging LP inventory on another venue. NOT YET "
                    "IMPLEMENTED — see this directory's README. Logs a warning if enabled."
    )
    hedge_venue: Optional[str] = Field(default=None, description="Target venue/connector for the hedge (future work).")
    hedge_ratio_pct: Decimal = Field(default=Decimal("100"), description="% of LP inventory value to hedge (future work).")


class NarrativeLPAgent(LPRebalancer):
    """
    Adds directional toggles, a cost-benefit rebalance gate, and a stop-loss on top of
    `LPRebalancer`, by post-filtering the actions it would take rather than duplicating
    its ~300-line stateful `determine_executor_actions`. See module docstring.
    """

    _logger: Optional[HummingbotLogger] = None

    @classmethod
    def logger(cls) -> HummingbotLogger:
        if cls._logger is None:
            cls._logger = logging.getLogger(__name__)
        return cls._logger

    def __init__(self, config: NarrativeLPAgentConfig, *args, **kwargs):
        super().__init__(config, *args, **kwargs)
        self.config: NarrativeLPAgentConfig = config

        # True once a directional-hold, downtrend-exit, or stop-loss has fired. While
        # True, no new position is opened — same "manual recovery" spirit as the base
        # class's _orphaned_position_address halt. Cleared only by an operator/Condor
        # config update (e.g. flipping downtrend_behavior, or a redeploy).
        self._paused: bool = False
        self._pause_reason: Optional[str] = None

        # Entry price of the very first position, used by the stop-loss check.
        self._entry_price: Optional[Decimal] = None

        if self.config.hedge_enabled:
            self.logger().warning(
                "hedge_enabled=True but cross-venue hedge execution is not implemented "
                "yet (config surface reserved for a follow-up phase). LP inventory will "
                "NOT be hedged by this controller."
            )

    def determine_executor_actions(self) -> List[ExecutorAction]:
        if self._paused:
            return []

        was_already_running = self._initial_position_created
        actions = super().determine_executor_actions()

        # The very first position was just created this tick — record its entry price
        # for the stop-loss check. Never gated: it already passed the Phase 4 discovery
        # routine's on-chain + narrative funnel before this controller was deployed.
        if not was_already_running and self._initial_position_created and self._entry_price is None:
            self._entry_price = self._pool_price
            return actions

        if not was_already_running or not actions:
            return actions

        lp_action = next(
            (a for a in actions
             if isinstance(a, CreateExecutorAction) and isinstance(a.executor_config, LPExecutorConfig)),
            None,
        )
        if lp_action is None:
            return actions

        side = lp_action.executor_config.side

        if self._stop_loss_breached():
            self.logger().warning(
                f"Stop-loss ({self.config.stop_loss_pct}%) breached from entry "
                f"{self._entry_price} — forcing stable exit and pausing."
            )
            return self._veto_with_stable_exit(reason="stop_loss")

        if side == TradeType.BUY and self.config.uptrend_behavior == "hold":
            self.logger().info("uptrend_behavior=hold: skipping reopen, staying in quote asset.")
            self._paused = True
            self._pause_reason = "uptrend_hold"
            return []

        if side == TradeType.SELL and self.config.downtrend_behavior == "exit_to_stable":
            self.logger().info(
                "downtrend_behavior=exit_to_stable: converting returned base token to "
                "quote instead of reopening lower."
            )
            return self._veto_with_stable_exit(reason="downtrend_exit_to_stable")

        # Cost-benefit gate: applies to every remaining reopen (BUY/follow_trend,
        # SELL/reopen_lower, or RANGE). Transient — no pause, just skip this tick.
        expected_fee = self._expected_fee_quote_estimate()
        if expected_fee is not None:
            min_required = self.config.estimated_rebalance_cost_quote * self.config.min_fee_to_cost_ratio
            if expected_fee < min_required:
                self.logger().info(
                    f"Cost-benefit gate: expected fee ~{expected_fee:.6f} {self._quote_token} "
                    f"< required {min_required:.6f} {self._quote_token} "
                    f"({self.config.min_fee_to_cost_ratio}x {self.config.estimated_rebalance_cost_quote}) "
                    "— skipping rebalance this tick."
                )
                return []

        return actions

    def _stop_loss_breached(self) -> bool:
        if not self.config.stop_loss_pct or self._entry_price is None or self._pool_price is None:
            return False
        drawdown_pct = (self._entry_price - self._pool_price) / self._entry_price * Decimal("100")
        return drawdown_pct >= self.config.stop_loss_pct

    def _expected_fee_quote_estimate(self, window: int = 5) -> Optional[Decimal]:
        """
        Trailing average fee value (in quote) realized by the last `window` closed LP
        positions. Returns None with no closed-position history yet, which lets the
        first reopen through uncontested (nothing to compare against).

        This is a simple heuristic, not a live simulation of the next position's actual
        fee income — refine with real volume/fee-tier data in a later iteration.
        """
        closed = [e for e in self.executors_info
                  if e.is_done and getattr(e.config, "type", None) == "lp_executor"]
        if not closed:
            return None
        pool_price = self._pool_price or Decimal("0")
        recent = closed[-window:]
        fee_values = [
            Decimal(str(e.custom_info.get("base_fee", 0))) * pool_price
            + Decimal(str(e.custom_info.get("quote_fee", 0)))
            for e in recent
        ]
        return sum(fee_values) / len(fee_values) if fee_values else None

    def _veto_with_stable_exit(self, reason: str) -> List[ExecutorAction]:
        """
        Replace a reopen the base class wanted with a market SELL of the current base
        balance into quote — the "Zap Out" pattern (see docs/research-phase1-notes.md):
        chain the exit into an immediate stable conversion instead of leaving the base
        token sitting exposed between the position close and a later, separate swap.

        Assumes this wallet is dedicated to this controller (true under the Phase 5
        one-wallet-per-user design) — it swaps the full base balance, not just this
        position's share.
        """
        self._paused = True
        self._pause_reason = reason
        try:
            base_balance = self.market_data_provider.get_balance(self.config.connector_name, self._base_token)
        except Exception as e:
            self.logger().warning(f"Stable exit: could not read {self._base_token} balance: {e}")
            return []
        if base_balance <= 0:
            return []
        swap_config = OrderExecutorConfig(
            timestamp=self.market_data_provider.time(),
            connector_name=self.config.connector_name,
            trading_pair=self.config.trading_pair,
            side=TradeType.SELL,
            amount=base_balance,
            execution_strategy=ExecutionStrategy.MARKET,
        )
        return [CreateExecutorAction(controller_id=self.config.id, executor_config=swap_config)]

    def to_format_status(self) -> List[str]:
        status = super().to_format_status()
        box_width = 100
        extra = []
        extra.append("|" + " " * box_width + "|")
        line = f"| Risk profile: {self.config.risk_profile}  |  Uptrend: {self.config.uptrend_behavior}  |  Downtrend: {self.config.downtrend_behavior}"
        extra.append(line + " " * (box_width - len(line) + 1) + "|")
        line = (f"| Cost-benefit gate: min_fee_to_cost_ratio={self.config.min_fee_to_cost_ratio}x, "
                f"est_cost={self.config.estimated_rebalance_cost_quote} {self._quote_token}")
        extra.append(line + " " * (box_width - len(line) + 1) + "|")
        if self.config.stop_loss_pct:
            entry = f"{self._entry_price:.6f}" if self._entry_price else "N/A"
            line = f"| Stop-loss: {self.config.stop_loss_pct}% from entry {entry}"
            extra.append(line + " " * (box_width - len(line) + 1) + "|")
        line = f"| Hedge: {'ENABLED (not implemented)' if self.config.hedge_enabled else 'off'}"
        extra.append(line + " " * (box_width - len(line) + 1) + "|")
        if self._paused:
            line = f"| PAUSED — reason: {self._pause_reason} (requires config update or redeploy to resume)"
            extra.append(line + " " * (box_width - len(line) + 1) + "|")
        extra.append("+" + "-" * box_width + "+")
        return status[:-1] + extra  # replace base's closing border with ours after the extra lines
