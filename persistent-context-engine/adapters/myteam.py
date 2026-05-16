"""
adapters/myteam.py — Benchmark harness adapter shim.

Thin wrapper over PersistentContextEngine that satisfies the Adapter interface
expected by the benchmark harness (run.py / self_check.py).

The harness calls:
    engine = Engine()
    engine.ingest(events)
    context = engine.reconstruct_context(signal, mode="fast")
    engine.close()
"""

import os
import sys
from typing import Iterable, Literal

# Automatically resolve the persistent-context-engine directory
# so that python can find 'src' even if PYTHONPATH is not set.
import os
import sys

_curr = os.path.abspath(os.path.dirname(__file__))
_engine_root = None
while _curr != os.path.dirname(_curr):
    if os.path.exists(os.path.join(_curr, "persistent-context-engine", "src")):
        _engine_root = os.path.join(_curr, "persistent-context-engine")
        break
    elif os.path.basename(_curr) == "persistent-context-engine" and os.path.exists(os.path.join(_curr, "src")):
        _engine_root = _curr
        break
    _curr = os.path.dirname(_curr)

if _engine_root and _engine_root not in sys.path:
    sys.path.insert(0, _engine_root)

from src.engine import PersistentContextEngine
from src.types import Event, IncidentSignal, Context


class Engine:
    """
    Benchmark adapter for PersistentContextEngine.

    Implements the Adapter interface required by the Anvil benchmark harness.
    This class is intentionally minimal — all logic lives in PersistentContextEngine.
    """

    def __init__(self) -> None:
        """Initialize the underlying engine with default configuration."""
        self._engine = PersistentContextEngine()

    def ingest(self, events: Iterable[Event]) -> None:
        """
        Ingest a stream of telemetry events.

        Delegates directly to PersistentContextEngine.ingest().
        Throughput: ≥1,000 events/sec.

        Args:
            events: Iterable of Event TypedDicts (all 7 kinds supported).
        """
        self._engine.ingest(events)

    def reconstruct_context(
        self,
        signal: IncidentSignal,
        mode: Literal["fast", "deep"] = "fast",
    ) -> Context:
        """
        Reconstruct operational context for an incident signal.

        Args:
            signal: The IncidentSignal TypedDict from the harness.
            mode:   "fast" (p95 ≤2s) or "deep" (p95 ≤6s).

        Returns:
            Context TypedDict with all required fields.
        """
        return self._engine.reconstruct_context(signal, mode=mode)

    def close(self) -> None:
        """Release all resources held by the engine."""
        self._engine.close()
