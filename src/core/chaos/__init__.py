"""Chaos substrate for stress benchmarks.

Public surface:
- ProviderKillSwitch: force a provider to fail after N successful calls
- LatencyInjector: sample sleep before each provider call
- chaos_scenario: named composition of primitives via ExitStack
- ProviderKilledError, ChaosPreconditionError: typed faults
"""

from src.core.chaos.primitives import (
    ChaosPreconditionError,
    LatencyInjector,
    ProviderKilledError,
    ProviderKillSwitch,
)
from src.core.chaos.scenarios import chaos_scenario, list_scenarios

__all__ = [
    "ChaosPreconditionError",
    "LatencyInjector",
    "ProviderKilledError",
    "ProviderKillSwitch",
    "chaos_scenario",
    "list_scenarios",
]
