# Relative, not `from controllers.generic....` -- confirmed against the real
# lp_rebalancer/__init__.py shipped inside hummingbot/hummingbot:development, which
# uses the same pattern for the same reason: this package is imported under two
# different roots depending on context (`controllers.*` inside a bot container,
# `bots.controllers.*` by hummingbot-api, which mounts it one level deeper). An
# absolute import pins the module to one of them and breaks under the other.
#
# This re-export is not cosmetic -- Hummingbot's controller loader
# (strategy/strategy_v2_base.py's load_controller_configs) imports
# `controllers.<controller_type>.<controller_name>` (the *package*, not the file
# inside it) and inspects that module's top-level members for a ControllerConfigBase
# subclass. An empty __init__.py exposes nothing, so it fails with "No configuration
# class found" -- caught live in Phase 6 continuation, deploying this controller for
# real for the first time (see docs/live-dry-run-notes.md).
from .narrative_lp_agent import NarrativeLPAgent, NarrativeLPAgentConfig

__all__ = ["NarrativeLPAgent", "NarrativeLPAgentConfig"]
