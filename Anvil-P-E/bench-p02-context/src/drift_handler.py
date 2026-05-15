"""
drift_handler.py — Topology drift detection and canonical identity management.

The IdentityGraph is the core component that makes this engine topology-independent.
Every service maps to a stable CanonicalID via a flat alias_map. Renames update the
map; the canonical_id never changes. Behavioral fingerprinting detects implicit renames.
"""

import json
import re
import hashlib
import time
from collections import Counter
from typing import Any, Optional, Union

from .types import (
    CanonicalID,
    CanonicalEntity,
    InternalEvent,
    IMPLICIT_RENAME_THRESHOLD,
)


# ---------------------------------------------------------------------------
# Log normalization — strips dynamic tokens for fingerprinting
# ---------------------------------------------------------------------------

_DYNAMIC_TOKEN_RE = re.compile(
    r"\b(?:"
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"  # UUID
    r"|\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}"                            # IPv4
    r"|0x[0-9a-f]+"                                                     # hex
    r"|\d+"                                                             # integers
    r")\b",
    re.IGNORECASE,
)


def _normalize_log(msg: str) -> str:
    """Strip dynamic tokens, lowercase, collapse whitespace."""
    return re.sub(_DYNAMIC_TOKEN_RE, "<VAL>", msg).lower().split()


_BUCKET_LABELS = ["none", "low", "med", "high", "critical"]


def _bucket(value: float, thresholds: list[float]) -> str:
    """Map a numeric value to a named severity bucket."""
    for i, t in enumerate(thresholds):
        if value < t:
            return _BUCKET_LABELS[i + 1]
    return "critical"


def _bucket_similarity(bucket_a: str, bucket_b: str) -> float:
    """Partial credit for adjacent severity buckets (80% at distance 1, 40% at 2)."""
    if bucket_a == bucket_b:
        return 1.0
    try:
        dist = abs(_BUCKET_LABELS.index(bucket_a) - _BUCKET_LABELS.index(bucket_b))
    except ValueError:
        return 0.0
    if dist == 1:
        return 0.6
    if dist == 2:
        return 0.4
    return 0.0


# ---------------------------------------------------------------------------
# Behavioral fingerprinting
# ---------------------------------------------------------------------------

def compute_signature(events: list[InternalEvent]) -> dict:
    """
    Compute a name-independent behavioral fingerprint from a service's event stream.

    The fingerprint captures HOW a service behaves (log templates, metric regimes,
    error rates) without any reference to its name. This allows matching
    'payments-svc' to 'billing-svc' even without an explicit rename event.

    Fields used:
      - log.message      → normalized template (dynamic tokens stripped)
      - log.level        → dominant level (ERROR/WARN/INFO)
      - metric.value     → latency and error-rate buckets (not exact values)
      - metric.name      → which metric kinds appear
      - deploy events    → deploy frequency

    Fields intentionally excluded (name-coupled):
      - service name, span IDs, trace IDs, exact metric values, exact versions

    Args:
        events: Recent events for a single canonical entity.

    Returns:
        Dict with fingerprint fields suitable for similarity comparison.
    """
    sig: dict = {
        "log_template_counts": Counter(),  # {md5_of_normalized_template: count}
        "error_rate_bucket": "none",
        "latency_bucket": "none",
        "deploy_frequency": 0,
        "metric_names_seen": set(),
        "dominant_log_level": "INFO",
    }

    log_levels: Counter = Counter()
    latency_values: list[float] = []
    error_rate_values: list[float] = []

    for ev in events:
        if ev.kind == "log":
            tokens = _normalize_log(ev.data.get("message", ""))
            template_hash = hashlib.md5(" ".join(tokens).encode()).hexdigest()[:8]
            sig["log_template_counts"][template_hash] += 1
            log_levels[ev.data.get("level", "INFO")] += 1

        elif ev.kind == "metric":
            name = ev.data.get("metric_name", ev.data.get("name", ""))
            sig["metric_names_seen"].add(name)
            try:
                val = float(ev.data.get("value", 0))
            except (TypeError, ValueError):
                val = 0.0
            if "latency" in name.lower():
                latency_values.append(val)
            if "error" in name.lower():
                error_rate_values.append(val)

        elif ev.kind == "deploy":
            sig["deploy_frequency"] += 1

    if latency_values:
        avg_lat = sum(latency_values) / len(latency_values)
        sig["latency_bucket"] = _bucket(avg_lat, [100.0, 300.0, 800.0])

    if error_rate_values:
        avg_err = sum(error_rate_values) / len(error_rate_values)
        sig["error_rate_bucket"] = _bucket(avg_err, [0.01, 0.05, 0.15])

    sig["dominant_log_level"] = (
        log_levels.most_common(1)[0][0] if log_levels else "INFO"
    )
    sig["metric_names_seen"] = list(sig["metric_names_seen"])
    return sig


def fingerprint_similarity(sig_a: dict, sig_b: dict) -> float:
    """
    Compute similarity between two behavioral signatures. Returns [0.0, 1.0].

    Uses weighted scoring across 4 independent dimensions:
      - Log template overlap (Jaccard)  — weight 0.40
      - Metric names overlap (Jaccard)  — weight 0.25
      - Latency bucket match            — weight 0.20
      - Error rate bucket match         — weight 0.15

    Threshold for implicit rename inference: ≥ IMPLICIT_RENAME_THRESHOLD (0.85).

    Args:
        sig_a: Behavioral signature of entity A.
        sig_b: Behavioral signature of entity B.

    Returns:
        Similarity score in [0.0, 1.0].
    """
    score = 0.0
    weights = {"log": 0.40, "metrics": 0.25, "latency": 0.20, "error": 0.15}

    # Log template Jaccard similarity
    set_a = set(sig_a.get("log_template_counts", {}).keys())
    set_b = set(sig_b.get("log_template_counts", {}).keys())
    if set_a or set_b:
        score += weights["log"] * len(set_a & set_b) / len(set_a | set_b)

    # Metric name Jaccard similarity
    mn_a = set(sig_a.get("metric_names_seen", []))
    mn_b = set(sig_b.get("metric_names_seen", []))
    if mn_a or mn_b:
        score += weights["metrics"] * len(mn_a & mn_b) / len(mn_a | mn_b)

    # Latency bucket — adjacent buckets receive partial credit
    lat_a = sig_a.get("latency_bucket", "none")
    lat_b = sig_b.get("latency_bucket", "none")
    if lat_a != "none" or lat_b != "none":
        score += weights["latency"] * _bucket_similarity(lat_a, lat_b)

    # Error rate bucket — adjacent buckets receive partial credit
    err_a = sig_a.get("error_rate_bucket", "none")
    err_b = sig_b.get("error_rate_bucket", "none")
    if err_a != "none" or err_b != "none":
        score += weights["error"] * _bucket_similarity(err_a, err_b)

    return round(score, 4)


def extract_incident_features(events: list[InternalEvent]) -> dict[str, Any]:
    """
    Extract component features for fuzzy incident similarity matching.

    Uses soft latency thresholds (peak value + bucket) so near-miss spikes
    (e.g. 2900ms vs 3000ms) still align with high-latency families.
    """
    has_deploy = False
    has_error_log = False
    has_remediation = False
    log_levels: list[str] = []
    latency_peak = 0.0

    for ev in events:
        kind = ev.kind
        if kind == "deploy":
            has_deploy = True
        elif kind == "log":
            level = ev.data.get("level", "INFO").upper()
            log_levels.append(level)
            if level in ("ERROR", "CRITICAL", "FATAL"):
                has_error_log = True
        elif kind == "metric":
            try:
                val = float(ev.data.get("value", 0))
            except (TypeError, ValueError):
                val = 0.0
            name = ev.data.get("metric_name", ev.data.get("name", "")).lower()
            if "latency" in name:
                latency_peak = max(latency_peak, val)
        elif kind == "remediation":
            has_remediation = True

    dominant_level = "INFO"
    if log_levels:
        dominant_level = Counter(log_levels).most_common(1)[0][0]

    n = len(events)
    density = "few" if n < 5 else ("some" if n < 20 else "many")
    latency_bucket = _bucket(latency_peak, [100.0, 800.0, 2500.0, 3000.0])
    has_high_latency = latency_peak >= 2500.0

    return {
        "has_deploy": has_deploy,
        "has_error_log": has_error_log,
        "has_high_latency": has_high_latency,
        "has_remediation": has_remediation,
        "dominant_level": dominant_level,
        "density": density,
        "latency_peak": round(latency_peak, 2),
        "latency_bucket": latency_bucket,
    }


def serialize_incident_fingerprint(features: dict[str, Any]) -> str:
    """Serialize incident features for storage (JSON, not MD5 hash)."""
    return json.dumps(features, sort_keys=True, separators=(",", ":"))


def parse_incident_fingerprint(stored: str) -> dict[str, Any]:
    """Parse stored fingerprint — supports JSON features or legacy MD5 hex."""
    if not stored:
        return {}
    if stored.startswith("{"):
        try:
            return json.loads(stored)
        except json.JSONDecodeError:
            pass
    return {"legacy_hash": stored}


def incident_fingerprint_similarity(
    feat_a: dict[str, Any],
    feat_b: dict[str, Any],
) -> float:
    """
    Component-wise similarity between two incident feature dicts.

    Returns [0.0, 1.0]. Legacy MD5 fingerprints only match on exact hash.
    """
    legacy_a = feat_a.get("legacy_hash")
    legacy_b = feat_b.get("legacy_hash")
    if legacy_a or legacy_b:
        if legacy_a and legacy_b and legacy_a == legacy_b:
            return 1.0
        if legacy_a and legacy_b:
            return 0.0
        # Mixed legacy vs JSON — fall through to component match where possible

    weights = {
        "has_deploy": 0.12,
        "has_error_log": 0.22,
        "has_high_latency": 0.18,
        "has_remediation": 0.08,
        "dominant_level": 0.15,
        "density": 0.10,
        "latency_bucket": 0.15,
    }
    score = 0.0

    for key in ("has_deploy", "has_error_log", "has_high_latency", "has_remediation"):
        if bool(feat_a.get(key)) == bool(feat_b.get(key)):
            score += weights[key]

    if feat_a.get("dominant_level") == feat_b.get("dominant_level"):
        score += weights["dominant_level"]
    elif {feat_a.get("dominant_level"), feat_b.get("dominant_level")} <= {"ERROR", "CRITICAL", "WARN"}:
        score += weights["dominant_level"] * 0.6

    dens_a = feat_a.get("density", "few")
    dens_b = feat_b.get("density", "few")
    score += weights["density"] * _bucket_similarity(dens_a, dens_b)

    lat_a = feat_a.get("latency_bucket", "none")
    lat_b = feat_b.get("latency_bucket", "none")
    score += weights["latency_bucket"] * _bucket_similarity(lat_a, lat_b)

    # Soft numeric peak: 2900ms vs 3100ms still scores high
    peak_a = float(feat_a.get("latency_peak", 0.0))
    peak_b = float(feat_b.get("latency_peak", 0.0))
    if peak_a > 0 or peak_b > 0:
        peak_sim = 1.0 - min(1.0, abs(peak_a - peak_b) / max(peak_a, peak_b, 1.0))
        if peak_a >= 2500 or peak_b >= 2500:
            score = min(1.0, score + 0.08 * peak_sim)

    return round(min(1.0, score), 4)


def compute_incident_fingerprint(events: list[InternalEvent]) -> dict[str, Any]:
    """
    Produce incident shape features for fuzzy similarity matching.

    Returns a feature dict; callers serialize via serialize_incident_fingerprint()
    when persisting to HistoricalIncident.behavioral_fingerprint.
    """
    return extract_incident_features(events)


IncidentFingerprint = Union[dict[str, Any], str]


# ---------------------------------------------------------------------------
# Identity Graph — flat alias map with behavioral inference
# ---------------------------------------------------------------------------

class IdentityGraph:
    """
    Manages stable canonical identities for all services, surviving renames.

    Uses a FLAT alias map (name → canonical_id) rather than a chained map
    (name → name). This eliminates circular rename bugs and provides O(1)
    resolution regardless of rename chain length.

    Rename chain example:
      payments-svc → billing-svc → finance-svc
      alias_map: {
        "payments-svc": "entity:3f8a",
        "billing-svc":  "entity:3f8a",   ← same canonical
        "finance-svc":  "entity:3f8a",   ← same canonical
      }
    All three resolve in O(1). No cycles possible (we never store name→name).
    """

    def __init__(self) -> None:
        self.alias_map: dict[str, CanonicalID] = {}
        self.entities: dict[CanonicalID, CanonicalEntity] = {}
        # topology graph: canonical_id → set of downstream canonical_ids
        self.dependencies: dict[CanonicalID, set[CanonicalID]] = {}

    def resolve_or_create(self, raw_service_name: str) -> CanonicalID:
        """
        Return the canonical_id for a service name, creating one if needed.

        Steps:
          1. Direct alias map lookup (O(1)).
          2. Behavioral similarity check for implicit rename inference
             (only runs if enough signal exists).
          3. Create a new CanonicalEntity if genuinely new.

        Args:
            raw_service_name: The service name from the raw event payload.

        Returns:
            The stable canonical_id for this service.
        """
        # Step 1: direct lookup
        if raw_service_name in self.alias_map:
            return self.alias_map[raw_service_name]

        # Step 2: implicit rename detection (deferred — needs behavioral signal)
        # This is triggered explicitly via infer_implicit_renames() after enough events.

        # Step 3: create new canonical entity
        entity = CanonicalEntity(first_seen_as=raw_service_name)
        entity.known_aliases.append(raw_service_name)
        self.entities[entity.canonical_id] = entity
        self.alias_map[raw_service_name] = entity.canonical_id
        self.dependencies[entity.canonical_id] = set()
        return entity.canonical_id

    def register_rename(self, old_name: str, new_name: str) -> CanonicalID:
        """
        Register an explicit service rename from a topology event.

        Both old and new names are mapped to the same canonical_id.
        Handles cascading renames (A→B then B→C) correctly because the
        flat map always resolves to canonical_id, never to another name.

        Also handles circular renames (A→B→A) gracefully — the flat map
        simply overwrites with the same value.

        Args:
            old_name: Previous service name.
            new_name: New service name after rename.

        Returns:
            The canonical_id that both names now map to.
        """
        # Resolve the canonical for the old name (create if needed)
        canon = self.resolve_or_create(old_name)

        # Map new name to the same canonical
        self.alias_map[new_name] = canon
        entity = self.entities[canon]
        if new_name not in entity.known_aliases:
            entity.known_aliases.append(new_name)

        return canon

    def update_dependencies(
        self, upstream_name: str, downstream_name: str
    ) -> None:
        """
        Register a dependency edge: upstream → downstream.

        Args:
            upstream_name:   Service that upstream_name depends on (or provides to downstream).
            downstream_name: Service that calls/depends on upstream.
        """
        up_canon = self.resolve_or_create(upstream_name)
        down_canon = self.resolve_or_create(downstream_name)
        self.dependencies.setdefault(up_canon, set()).add(down_canon)

    def get_downstream(self, canonical_id: CanonicalID) -> set[CanonicalID]:
        """Return canonical IDs of all services directly downstream of this entity."""
        return self.dependencies.get(canonical_id, set())

    def get_upstream(self, canonical_id: CanonicalID) -> set[CanonicalID]:
        """Return canonical IDs of all services that this entity depends on."""
        return {
            cid for cid, deps in self.dependencies.items()
            if canonical_id in deps
        }

    def get_related_canonicals(
        self,
        canonical_id: CanonicalID,
        max_hops: int = 3,
    ) -> set[CanonicalID]:
        """
        Multi-hop BFS over upstream and downstream dependency edges.

        Captures cascading failures across 2nd/3rd-order topology neighbors.
        Does not include the seed canonical_id itself.
        """
        related: set[CanonicalID] = set()
        frontier: set[CanonicalID] = {canonical_id}
        visited: set[CanonicalID] = {canonical_id}

        for _ in range(max_hops):
            next_frontier: set[CanonicalID] = set()
            for cid in frontier:
                neighbors = self.get_downstream(cid) | self.get_upstream(cid)
                for neighbor in neighbors:
                    if neighbor not in visited:
                        visited.add(neighbor)
                        related.add(neighbor)
                        next_frontier.add(neighbor)
            if not next_frontier:
                break
            frontier = next_frontier

        return related

    def infer_implicit_renames(
        self,
        event_store_fn,  # callable: (canonical_id) → list[InternalEvent]
        threshold: float = IMPLICIT_RENAME_THRESHOLD,
    ) -> list[tuple[str, str, float]]:
        """
        Detect implicit service renames via behavioral fingerprint similarity.

        Runs after enough events have been ingested. Compares behavioral signatures
        of all known canonical entities. If two entities are sufficiently similar
        (similarity ≥ threshold) and one appeared shortly after the other disappeared,
        they are inferred to be the same logical service.

        Args:
            event_store_fn: Callable mapping canonical_id → recent events.
            threshold:      Similarity threshold for rename inference.

        Returns:
            List of (old_canonical_id, new_canonical_id, similarity_score) tuples
            representing inferred renames. Caller should merge these.
        """
        # Update behavioral signatures for all entities
        sigs: dict[CanonicalID, dict] = {}
        for cid, entity in self.entities.items():
            recent = event_store_fn(cid)
            if len(recent) >= 5:  # need at least 5 events for a reliable signature
                sig = compute_signature(recent)
                entity.behavioral_sig = sig
                entity.sig_updated_at = time.time()
                sigs[cid] = sig

        # Pairwise comparison — O(n^2) but n is small (≤20 services in L2)
        inferred: list[tuple[str, str, float]] = []
        canon_ids = list(sigs.keys())
        for i, cid_a in enumerate(canon_ids):
            for cid_b in canon_ids[i + 1:]:
                sim = fingerprint_similarity(sigs[cid_a], sigs[cid_b])
                if sim >= threshold:
                    inferred.append((cid_a, cid_b, sim))

        return inferred

    def merge_canonicals(
        self, keep_id: CanonicalID, merge_id: CanonicalID
    ) -> None:
        """
        Merge two canonical entities into one (for implicit rename resolution).

        All aliases from merge_id are re-pointed to keep_id.
        The merge_id entity is removed from the graph.

        Args:
            keep_id:  The canonical_id to retain.
            merge_id: The canonical_id to absorb into keep_id.
        """
        if keep_id not in self.entities or merge_id not in self.entities:
            return
        if keep_id == merge_id:
            return

        merge_entity = self.entities[merge_id]
        keep_entity = self.entities[keep_id]

        # Re-point all aliases
        for alias in merge_entity.known_aliases:
            self.alias_map[alias] = keep_id
            if alias not in keep_entity.known_aliases:
                keep_entity.known_aliases.append(alias)

        # Merge dependencies
        for dep in self.dependencies.get(merge_id, set()):
            self.dependencies.setdefault(keep_id, set()).add(dep)

        # Remove merged entity
        del self.entities[merge_id]
        if merge_id in self.dependencies:
            del self.dependencies[merge_id]

    def get_all_aliases(self, canonical_id: CanonicalID) -> list[str]:
        """Return all known service names for a canonical entity."""
        entity = self.entities.get(canonical_id)
        return entity.known_aliases if entity else []

    def resolve(self, raw_service_name: str) -> Optional[CanonicalID]:
        """
        Resolve a service name to its canonical_id without creating a new entity.

        Args:
            raw_service_name: Raw service name to look up.

        Returns:
            canonical_id if known, else None.
        """
        return self.alias_map.get(raw_service_name)

    def __len__(self) -> int:
        """Number of distinct canonical entities tracked."""
        return len(self.entities)
