"""
relationships.py — Relationship synthesis engine for the Persistent Context Engine.

Builds causal edges between events using three complementary strategies:
  1. Rule-based:   Heuristic patterns (deploy → metric spike → error, trace links).
  2. Statistical:  Co-occurrence frequency across historical events.
  3. Behavioral:   Fingerprint matching for cross-entity similarity.

Confidence formula: W_type × exp(-Δt / τ) × W_corr
"""

import math
from collections import defaultdict
from typing import Optional

from .types import (
    InternalEvent,
    CausalEdge,
    CausalEdgeDict,
    CanonicalID,
    CONFIDENCE_NOISE_FLOOR,
    CONFIDENCE_CHAIN_THRESHOLD,
)


# ---------------------------------------------------------------------------
# Type weights and temporal half-lives (τ in seconds)
# ---------------------------------------------------------------------------

EDGE_CONFIG: dict[str, dict] = {
    "deploy_induced": {"weight": 0.75, "tau": 600.0},   # 10-min half-life
    "trace_parent":   {"weight": 1.00, "tau": None},    # no decay — exact linkage
    "temporal_prox":  {"weight": 0.40, "tau": 300.0},   # 5-min half-life
    "statistical":    {"weight": 0.60, "tau": None},    # P(B|A) based, no decay
    "behavioral":     {"weight": 0.55, "tau": None},    # cross-entity pattern match
}

# Maximum temporal gap for rule-based causal edges (seconds)
DEPLOY_WINDOW = 900.0        # 15 minutes
TEMPORAL_PROX_WINDOW = 300.0  # 5 minutes
# Half-life for |t_event - t_signal| proximity multiplier
SIGNAL_PROXIMITY_TAU = 900.0  # 15 minutes


def _temporal_decay(delta_t: float, tau: Optional[float]) -> float:
    """Compute exponential decay weight. Returns 1.0 if tau is None (no decay)."""
    if tau is None or tau <= 0:
        return 1.0
    return math.exp(-delta_t / tau)


def _edge_confidence(
    edge_type: str,
    delta_t: float,
    corr_weight: float = 1.0,
) -> float:
    """
    Compute confidence for a causal edge.

    Formula: W_type × exp(-Δt / τ) × W_corr

    Args:
        edge_type:    One of the keys in EDGE_CONFIG.
        delta_t:      B.timestamp - A.timestamp (seconds, must be > 0).
        corr_weight:  Co-occurrence reinforcement (1.0 baseline; boosted by history).

    Returns:
        Confidence in [0.0, 1.0].
    """
    config = EDGE_CONFIG.get(edge_type, {"weight": 0.3, "tau": 300.0})
    w = config["weight"]
    decay = _temporal_decay(delta_t, config["tau"])
    raw = w * decay * corr_weight
    return round(min(1.0, raw), 4)


def _signal_proximity_multiplier(
    event_ts: float,
    incident_ts: Optional[float],
) -> float:
    """
    Boost edges whose source events are temporally close to the incident signal.

    Returns multiplier in (0.35, 1.0]; 1.0 when incident_ts is unknown.
    """
    if incident_ts is None:
        return 1.0
    delta = abs(event_ts - incident_ts)
    proximity = math.exp(-delta / SIGNAL_PROXIMITY_TAU)
    return 0.35 + 0.65 * proximity


def _finalize_confidence(
    edge_type: str,
    delta_t: float,
    source_ts: float,
    incident_ts: Optional[float] = None,
    corr_weight: float = 1.0,
    scale: float = 1.0,
) -> float:
    """Apply edge-type decay, optional correlation boost, and signal proximity."""
    base = _edge_confidence(edge_type, delta_t, corr_weight) * scale
    boosted = base * _signal_proximity_multiplier(source_ts, incident_ts)
    return round(min(1.0, boosted), 4)


# ---------------------------------------------------------------------------
# Relationship Engine
# ---------------------------------------------------------------------------

class RelationshipEngine:
    """
    Synthesizes causal edges between events using rule-based and statistical signals.

    The engine operates in two modes:
      - Incremental: called at ingest time to update running co-occurrence counts.
      - On-demand:   called at reconstruct_context to build the causal chain
                     for a specific window of events.
    """

    def __init__(self) -> None:
        # Co-occurrence counter: (canonical_id_A, kind_A, canonical_id_B, kind_B) → count
        self._cooccurrence: defaultdict[tuple, int] = defaultdict(int)
        # Total observations per (canonical_id, kind) — denominator for P(B|A)
        self._kind_counts: defaultdict[tuple, int] = defaultdict(int)
        # Remediation reinforcement weights: (canonical_id, remediation_action) → boost
        self._remediation_weights: defaultdict[tuple, float] = defaultdict(lambda: 1.0)

    # ------------------------------------------------------------------
    # Incremental update (called at ingest)
    # ------------------------------------------------------------------

    def observe_event(self, event: InternalEvent) -> None:
        """
        Record a new event for statistical edge learning.

        Updates kind counts used to compute P(B|A) co-occurrence probabilities.

        Args:
            event: Freshly ingested InternalEvent.
        """
        key = (event.canonical_id, event.kind)
        self._kind_counts[key] += 1

    def observe_pair(
        self,
        event_a: InternalEvent,
        event_b: InternalEvent,
    ) -> None:
        """
        Record a temporal co-occurrence pair (A precedes B within DEPLOY_WINDOW).

        Args:
            event_a: Earlier event.
            event_b: Later event.
        """
        key = (
            event_a.canonical_id, event_a.kind,
            event_b.canonical_id, event_b.kind,
        )
        self._cooccurrence[key] += 1

    def cooccurrence_probability(
        self,
        canonical_a: CanonicalID,
        kind_a: str,
        canonical_b: CanonicalID,
        kind_b: str,
    ) -> float:
        """
        Compute P(event_b | event_a) from historical co-occurrence counts.

        Returns a probability in [0.0, 1.0]. Returns 0.0 if no history.

        Args:
            canonical_a: Source canonical entity.
            kind_a:      Source event kind.
            canonical_b: Target canonical entity.
            kind_b:      Target event kind.
        """
        pair_key = (canonical_a, kind_a, canonical_b, kind_b)
        count = self._cooccurrence.get(pair_key, 0)
        total = self._kind_counts.get((canonical_a, kind_a), 0)
        if total == 0:
            return 0.0
        return min(1.0, count / total)

    # ------------------------------------------------------------------
    # On-demand causal chain construction
    # ------------------------------------------------------------------

    def build_causal_chain(
        self,
        events: list[InternalEvent],
        topology_neighbors: Optional[set[CanonicalID]] = None,
        incident_ts: Optional[float] = None,
    ) -> list[CausalEdgeDict]:
        """
        Build a directed causal chain from a window of events.

        Applies three edge-building strategies in priority order:
          1. Trace parent links (highest confidence — exact span linkage).
          2. Deploy-induced rules (temporal heuristics for known causal patterns).
          3. Statistical co-occurrence (learned correlations from history).
          4. Temporal proximity (weak default for co-located events).

        Edges below CONFIDENCE_NOISE_FLOOR (0.25) are discarded.
        The returned chain is sorted: root causes first, terminal effects last.

        Args:
            events:             Events in the incident window, any order.
            topology_neighbors: Set of canonical_ids known to be related
                                (upstream/downstream) — relaxes same-entity checks.

        Returns:
            List of CausalEdgeDict sorted by timestamp of source event.
        """
        if len(events) < 2:
            return []

        sorted_events = sorted(events, key=lambda e: e.timestamp)
        edges: list[CausalEdge] = []
        event_by_id = {ev.event_id: ev for ev in sorted_events}

        # Strategy 1: Exact trace parent links
        edges.extend(self._trace_edges(sorted_events, event_by_id, incident_ts))

        # Strategy 2: Deploy-induced causal rules
        edges.extend(
            self._deploy_rule_edges(sorted_events, topology_neighbors, incident_ts)
        )

        # Strategy 3: Statistical co-occurrence edges
        edges.extend(self._statistical_edges(sorted_events, incident_ts))

        # Strategy 4: Temporal proximity edges (only if no better edge exists)
        existing_pairs = {(e.source_id, e.target_id) for e in edges}
        edges.extend(
            self._temporal_prox_edges(sorted_events, existing_pairs, incident_ts)
        )

        # Deduplicate: keep highest-confidence edge per (source, target) pair
        best: dict[tuple, CausalEdge] = {}
        for edge in edges:
            key = (edge.source_id, edge.target_id)
            if key not in best or edge.confidence > best[key].confidence:
                best[key] = edge

        # Filter noise floor
        filtered = [e for e in best.values() if e.confidence >= CONFIDENCE_NOISE_FLOOR]

        # Sort by source event timestamp (root causes first)
        filtered.sort(
            key=lambda e: event_by_id.get(e.source_id, sorted_events[0]).timestamp
        )

        return [e.to_dict() for e in filtered]

    def _trace_edges(
        self,
        events: list[InternalEvent],
        event_by_id: dict[str, InternalEvent],
        incident_ts: Optional[float] = None,
    ) -> list[CausalEdge]:
        """Build edges from exact trace parent_span_id → span_id linkage."""
        edges = []
        span_to_event: dict[str, str] = {}  # span_id → event_id

        for ev in events:
            span_id = ev.data.get("span_id")
            if span_id:
                span_to_event[span_id] = ev.event_id

        for ev in events:
            parent_span = ev.data.get("parent_span_id")
            if parent_span and parent_span in span_to_event:
                source_id = span_to_event[parent_span]
                source_ev = event_by_id.get(source_id)
                if source_ev:
                    delta_t = max(0.001, ev.timestamp - source_ev.timestamp)
                    edges.append(CausalEdge(
                        source_id=source_id,
                        target_id=ev.event_id,
                        edge_type="trace_parent",
                        confidence=_finalize_confidence(
                            "trace_parent", delta_t, source_ev.timestamp, incident_ts
                        ),
                        rationale=f"Exact trace parent: span {parent_span} → {ev.data.get('span_id')}",
                    ))
        return edges

    def _deploy_rule_edges(
        self,
        events: list[InternalEvent],
        topology_neighbors: Optional[set[CanonicalID]],
        incident_ts: Optional[float] = None,
    ) -> list[CausalEdge]:
        """
        Build rule-based causal edges for known SRE patterns:
          - deploy → metric spike
          - deploy → error logs
          - metric degradation → error logs
        """
        edges = []
        deploys = [e for e in events if e.kind == "deploy"]
        metrics = [e for e in events if e.kind == "metric"]
        logs = [e for e in events if e.kind == "log"]

        def _same_scope(a: InternalEvent, b: InternalEvent) -> bool:
            if a.canonical_id == b.canonical_id:
                return True
            if topology_neighbors:
                return (
                    a.canonical_id in topology_neighbors
                    or b.canonical_id in topology_neighbors
                )
            return False

        # Rule A: deploy → metric spike
        for deploy in deploys:
            for metric in metrics:
                if not _same_scope(deploy, metric):
                    continue
                delta_t = metric.timestamp - deploy.timestamp
                if 0 < delta_t <= DEPLOY_WINDOW:
                    p_corr = self.cooccurrence_probability(
                        deploy.canonical_id, "deploy",
                        metric.canonical_id, "metric",
                    )
                    w_corr = 1.0 + p_corr * 0.5  # history boosts up to 1.5×
                    conf = _finalize_confidence(
                        "deploy_induced", delta_t, deploy.timestamp,
                        incident_ts, w_corr,
                    )
                    edges.append(CausalEdge(
                        source_id=deploy.event_id,
                        target_id=metric.event_id,
                        edge_type="deploy_induced",
                        confidence=conf,
                        rationale=(
                            f"Deploy preceded metric event by {delta_t:.0f}s "
                            f"(within {DEPLOY_WINDOW}s window)"
                        ),
                    ))

        # Rule B: deploy → error logs
        for deploy in deploys:
            for log in logs:
                if not _same_scope(deploy, log):
                    continue
                if log.data.get("level", "").upper() not in ("ERROR", "CRITICAL", "FATAL"):
                    continue
                delta_t = log.timestamp - deploy.timestamp
                if 0 < delta_t <= DEPLOY_WINDOW:
                    conf = _finalize_confidence(
                        "deploy_induced", delta_t, deploy.timestamp,
                        incident_ts, scale=0.85,
                    )
                    edges.append(CausalEdge(
                        source_id=deploy.event_id,
                        target_id=log.event_id,
                        edge_type="deploy_induced",
                        confidence=conf,
                        rationale=(
                            f"Deploy preceded {log.data.get('level')} log by {delta_t:.0f}s"
                        ),
                    ))

        # Rule C: metric degradation → error logs (cascading failure pattern)
        for metric in metrics:
            for log in logs:
                if not _same_scope(metric, log):
                    continue
                if log.data.get("level", "").upper() not in ("ERROR", "CRITICAL"):
                    continue
                delta_t = log.timestamp - metric.timestamp
                if 0 < delta_t <= TEMPORAL_PROX_WINDOW:
                    conf = _finalize_confidence(
                        "temporal_prox", delta_t, metric.timestamp,
                        incident_ts, corr_weight=1.1,
                    )
                    edges.append(CausalEdge(
                        source_id=metric.event_id,
                        target_id=log.event_id,
                        edge_type="temporal_prox",
                        confidence=conf,
                        rationale=f"Metric degradation preceded error log by {delta_t:.0f}s",
                    ))

        return edges

    def _statistical_edges(
        self,
        events: list[InternalEvent],
        incident_ts: Optional[float] = None,
    ) -> list[CausalEdge]:
        """
        Build edges where P(B|A) from historical data exceeds threshold (0.5).
        """
        edges = []
        threshold = 0.5

        for i, ev_a in enumerate(events):
            for ev_b in events[i + 1:]:
                delta_t = ev_b.timestamp - ev_a.timestamp
                if delta_t <= 0 or delta_t > DEPLOY_WINDOW:
                    continue
                p = self.cooccurrence_probability(
                    ev_a.canonical_id, ev_a.kind,
                    ev_b.canonical_id, ev_b.kind,
                )
                if p >= threshold:
                    conf = EDGE_CONFIG["statistical"]["weight"] * p
                    conf *= _signal_proximity_multiplier(ev_a.timestamp, incident_ts)
                    conf = round(min(1.0, conf), 4)
                    if conf >= CONFIDENCE_NOISE_FLOOR:
                        edges.append(CausalEdge(
                            source_id=ev_a.event_id,
                            target_id=ev_b.event_id,
                            edge_type="statistical",
                            confidence=conf,
                            rationale=f"Historical co-occurrence P(B|A)={p:.2f}",
                        ))
        return edges

    def _temporal_prox_edges(
        self,
        events: list[InternalEvent],
        existing_pairs: set[tuple],
        incident_ts: Optional[float] = None,
    ) -> list[CausalEdge]:
        """
        Build weak temporal proximity edges for event pairs with no better edge.
        Only fires for ERROR/CRITICAL events within TEMPORAL_PROX_WINDOW.
        """
        edges = []
        error_events = [
            e for e in events
            if e.kind == "log" and e.data.get("level", "").upper() in ("ERROR", "CRITICAL")
        ]

        for i, ev_a in enumerate(error_events):
            for ev_b in error_events[i + 1:]:
                pair = (ev_a.event_id, ev_b.event_id)
                if pair in existing_pairs:
                    continue
                delta_t = ev_b.timestamp - ev_a.timestamp
                if 0 < delta_t <= TEMPORAL_PROX_WINDOW:
                    conf = _finalize_confidence(
                        "temporal_prox", delta_t, ev_a.timestamp, incident_ts
                    )
                    if conf >= CONFIDENCE_NOISE_FLOOR:
                        edges.append(CausalEdge(
                            source_id=ev_a.event_id,
                            target_id=ev_b.event_id,
                            edge_type="temporal_prox",
                            confidence=conf,
                            rationale=f"Co-located error events within {delta_t:.0f}s",
                        ))
        return edges

    def reinforce_remediation(
        self,
        canonical_id: CanonicalID,
        remediation_action: str,
        success: bool,
    ) -> None:
        """
        Adjust co-occurrence weights based on remediation outcomes.

        Args:
            canonical_id:       Entity the remediation was applied to.
            remediation_action: Action string.
            success:            Whether metrics recovered after remediation.
        """
        key = (canonical_id, remediation_action)
        if success:
            self._remediation_weights[key] = min(2.0, self._remediation_weights[key] + 0.1)
        else:
            self._remediation_weights[key] = max(0.1, self._remediation_weights[key] - 0.05)
