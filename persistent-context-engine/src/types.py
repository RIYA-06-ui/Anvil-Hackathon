"""
types.py — All TypedDicts, Dataclasses, and type aliases for the Persistent Context Engine.

This module contains ONLY data structures — no logic.
All types fall into two categories:
  - Public API types (Event, IncidentSignal, Context, CausalEdgeDict): exposed to callers.
  - Internal types (InternalEvent, CanonicalEntity, HistoricalIncident): used only inside engine.
"""

import uuid
import time
from dataclasses import dataclass, field
from typing import TypedDict, Optional, Literal, Any

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

CanonicalID = str  # e.g., "entity:3f8a9b2c1d4e"

EventKind = Literal[
    "deploy",
    "log",
    "metric",
    "trace",
    "topology",
    "incident_signal",
    "remediation",
]

# ---------------------------------------------------------------------------
# Public API types (exposed to benchmark harness)
# ---------------------------------------------------------------------------


class Event(TypedDict, total=False):
    """
    Raw JSONL event from the telemetry stream.

    All fields are optional at the TypedDict level because different event kinds
    use different subsets. Validation happens in the ingest pipeline.

    Fields:
        event_id:  Unique identifier for this event.
        kind:      One of the 7 event kinds.
        timestamp: Unix epoch seconds (float for sub-second precision).
        service:   Raw service name at time of emission (may change via rename).
        data:      Kind-specific payload dict.
    """

    event_id: str
    kind: EventKind
    timestamp: float
    service: str
    data: dict[str, Any]


class IncidentSignal(TypedDict, total=False):
    """
    Incident signal triggering context reconstruction.

    Fields:
        incident_id: Unique incident identifier (e.g., "INC-714").
        service:     Raw service name emitting the signal.
        timestamp:   Unix epoch seconds.
        severity:    Severity level: "critical" | "warning" | "info".
        data:        Additional signal metadata.
    """

    incident_id: str
    service: str
    timestamp: float
    severity: str
    data: dict[str, Any]


class CausalEdgeDict(TypedDict):
    """
    A directed causal relationship between two events.

    Fields:
        from_event_id: Source event identifier.
        to_event_id:   Target (caused) event identifier.
        edge_type:     How this edge was inferred.
        confidence:    Probability [0.0, 1.0] that this edge represents true causality.
        rationale:     Human-readable reason for this edge.
    """

    from_event_id: str
    to_event_id: str
    edge_type: str          # "deploy_induced" | "trace" | "statistical" | "temporal"
    confidence: float
    rationale: str


class Context(TypedDict):
    """
    Output of reconstruct_context(). The primary deliverable of the engine.

    Fields:
        incident_id:            The incident being reconstructed.
        related_events:         All events temporally and causally connected to the incident.
        causal_chain:           Ordered list of causal edges tracing the incident root cause.
        similar_past_incidents: Historical incidents behaviorally matching this one.
        suggested_remediations: Ordered list of recommended actions (highest confidence first).
        confidence:             Aggregate confidence [0.0, 1.0] in the context reconstruction.
        explain:                Human-readable narrative explaining the incident and recommendation.
    """

    incident_id: str
    related_events: list[Event]
    causal_chain: list[CausalEdgeDict]
    similar_past_incidents: list[dict]
    suggested_remediations: list[str]
    confidence: float
    explain: str


# ---------------------------------------------------------------------------
# Internal types (not exposed to callers)
# ---------------------------------------------------------------------------


@dataclass
class CanonicalEntity:
    """
    Immutable identity node for a logical service.

    Created ONCE when a service name is first seen, and never deleted.
    Survives all service renames and dependency shifts — the canonical_id
    is the stable identity anchor throughout the engine's lifetime.

    Attributes:
        canonical_id:   Stable unique identifier (format: "entity:{12-char hex}").
        first_seen_as:  Raw service name at creation time.
        first_seen_at:  Unix timestamp of first observation.
        known_aliases:  All service names ever associated with this entity.
        behavioral_sig: Computed behavioral fingerprint dict (see drift_handler.py).
        sig_updated_at: Timestamp of last signature computation.
    """

    canonical_id: CanonicalID = field(
        default_factory=lambda: f"entity:{uuid.uuid4().hex[:12]}"
    )
    first_seen_as: str = ""
    first_seen_at: float = field(default_factory=time.time)
    known_aliases: list[str] = field(default_factory=list)
    behavioral_sig: dict = field(default_factory=dict)
    sig_updated_at: float = 0.0


@dataclass
class InternalEvent:
    """
    Enriched event stored in the memory substrate.

    Wraps a raw Event with canonical resolution applied at ingest time.
    After ingest, the canonical_id never changes even if the service is renamed.

    Attributes:
        event_id:               Unique event identifier.
        kind:                   Event kind string.
        timestamp:              Unix epoch float.
        canonical_id:           Resolved at ingest time; immutable thereafter.
        raw_service_name:       Original service name in the payload.
        data:                   Full kind-specific payload.
        behavioral_fingerprint: Hash of normalized content (for similarity matching).
    """

    event_id: str
    kind: str
    timestamp: float
    canonical_id: CanonicalID
    raw_service_name: str
    data: dict[str, Any]
    behavioral_fingerprint: str = ""


@dataclass
class HistoricalIncident:
    """
    Stored record of a resolved incident for future similarity matching.

    Indexed by canonical_id so cross-rename lookups work transparently.

    Attributes:
        incident_id:          Original incident identifier.
        canonical_id:         Canonical entity involved.
        timestamp:            When the incident occurred.
        causal_chain:         The causal edges reconstructed for this incident.
        behavioral_fingerprint: Fingerprint of the incident's behavioral shape.
        resolved_remediation: The action taken to resolve (if known).
        outcome_confirmed:    True if metrics recovered after remediation.
        confidence_weight:    Decays with age; boosted by confirmed outcomes.
    """

    incident_id: str
    canonical_id: CanonicalID
    timestamp: float
    causal_chain: list[CausalEdgeDict]
    behavioral_fingerprint: str
    resolved_remediation: Optional[str] = None
    outcome_confirmed: bool = False
    confidence_weight: float = 1.0


@dataclass
class CausalEdge:
    """
    Internal (non-dict) causal edge for use within the relationship engine.

    Converted to CausalEdgeDict before being placed in Context output.

    Attributes:
        source_id:   Source event_id.
        target_id:   Target event_id.
        edge_type:   How this edge was inferred.
        confidence:  [0.0, 1.0].
        rationale:   Human-readable explanation.
    """

    source_id: str
    target_id: str
    edge_type: str
    confidence: float
    rationale: str = ""

    def to_dict(self) -> CausalEdgeDict:
        """Convert to the public CausalEdgeDict TypedDict format."""
        return CausalEdgeDict(
            from_event_id=self.source_id,
            to_event_id=self.target_id,
            edge_type=self.edge_type,
            confidence=round(self.confidence, 4),
            rationale=self.rationale,
        )


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FAST_WINDOW_SECONDS = 1800.0      # ±30 minutes for fast mode context window (temporarily widened)
DEEP_WINDOW_SECONDS = 3600.0     # ±60 minutes for deep mode context window
# Relaxed thresholds for debugging (set to 0.0 to expose plumbing issues)
CONFIDENCE_NOISE_FLOOR = 0.25     # edges below this are discarded
CONFIDENCE_CHAIN_THRESHOLD = 0.65  # edges below this are low-confidence in chain
IMPLICIT_RENAME_THRESHOLD = 0.75   # fingerprint similarity for inferred rename (lowered for better fuzzy coverage)
MEMORY_HORIZON_DAYS = 90.0       # incidents older than this get confidence decay
REMEDIATION_CONFIRM_WINDOW = 600.0  # 10 min to confirm metric recovery after remediation
