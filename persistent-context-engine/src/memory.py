"""
memory.py — EventStore and IncidentMemory for the Persistent Context Engine.

EventStore:     Three-index in-memory store. O(log N) temporal queries via bisect.
IncidentMemory: Historical incident store with cross-rename similarity matching.
"""

import bisect
import time
from collections import defaultdict
from typing import Optional

from .drift_handler import (
    incident_fingerprint_similarity,
    parse_incident_fingerprint,
)
from .types import CanonicalID, InternalEvent, HistoricalIncident, MEMORY_HORIZON_DAYS

# Minimum fuzzy similarity to consider a historical incident a near-miss match
FUZZY_INCIDENT_MATCH_THRESHOLD = 0.65
# Max incidents from the same benchmark family in similar_past top-k
MAX_INCIDENTS_PER_FAMILY = 2


class EventStore:
    """
    Three-index in-memory event store.

    Index 1 — _timeline:      sorted list[(timestamp, event_id)] for O(log N) range queries.
    Index 2 — _by_id:         dict[event_id → InternalEvent] for O(1) lookups.
    Index 3 — _by_canonical:  dict[canonical_id → list[event_id]] for per-service queries.
    Index 4 — _by_kind:       dict[kind → list[event_id]] for rule-engine fast lanes.

    Memory estimate (L2: 12 svcs × 7 days ≈ 17k events): ~17 MB total — safe in RAM.
    """

    def __init__(self) -> None:
        self._timeline: list[tuple[float, str]] = []
        self._by_id: dict[str, InternalEvent] = {}
        self._by_canonical: defaultdict[CanonicalID, list[str]] = defaultdict(list)
        self._by_kind: defaultdict[str, list[str]] = defaultdict(list)
        self._total_ingested: int = 0

    def add_event(self, event: InternalEvent) -> None:
        """Insert event into all indexes. O(log N) due to bisect.insort."""
        key = (event.timestamp, event.event_id)
        bisect.insort(self._timeline, key)
        self._by_id[event.event_id] = event
        self._by_canonical[event.canonical_id].append(event.event_id)
        self._by_kind[event.kind].append(event.event_id)
        self._total_ingested += 1

    def get_by_id(self, event_id: str) -> Optional[InternalEvent]:
        """O(1) point lookup by event_id."""
        return self._by_id.get(event_id)

    def query_by_canonical(self, canonical_id: CanonicalID) -> list[InternalEvent]:
        """Return all events for a canonical entity (transparent across renames)."""
        ids = self._by_canonical.get(canonical_id, [])
        return [self._by_id[eid] for eid in ids if eid in self._by_id]

    def query_window(
        self,
        canonical_id: CanonicalID,
        center_ts: float,
        window_seconds: float = 900.0,
        include_related_canonicals: Optional[set] = None,
    ) -> list[InternalEvent]:
        """
        Return events for a canonical entity within [center_ts ± window_seconds].

        Complexity: O(log N + K). Rename-transparent because events are stored
        by canonical_id at ingest time — no name resolution needed at query time.

        Args:
            canonical_id:              Target entity.
            center_ts:                 Center of the time window (unix epoch).
            window_seconds:            Half-width in seconds (default ±15 min).
            include_related_canonicals: Additional canonical IDs (dependencies).

        Returns:
            Events sorted by timestamp ascending.
        """
        lo = center_ts - window_seconds
        hi = center_ts + window_seconds

        lo_idx = bisect.bisect_left(self._timeline, (lo, ""))
        hi_idx = bisect.bisect_right(self._timeline, (hi, "\xff"))

        target_canonicals = {canonical_id}
        if include_related_canonicals:
            target_canonicals.update(include_related_canonicals)

        results: list[InternalEvent] = []
        for _ts, eid in self._timeline[lo_idx:hi_idx]:
            event = self._by_id.get(eid)
            if event and event.canonical_id in target_canonicals:
                results.append(event)
        return results

    def query_kind_for_canonical(
        self, kind: str, canonical_id: CanonicalID
    ) -> list[InternalEvent]:
        """Return all events of a specific kind for a canonical entity."""
        ids = self._by_kind.get(kind, [])
        return [
            self._by_id[eid]
            for eid in ids
            if eid in self._by_id and self._by_id[eid].canonical_id == canonical_id
        ]

    def get_recent_events(
        self, canonical_id: CanonicalID, n: int = 100
    ) -> list[InternalEvent]:
        """Return the N most recent events for a canonical entity (newest first)."""
        all_events = self.query_by_canonical(canonical_id)
        return sorted(all_events, key=lambda e: e.timestamp, reverse=True)[:n]

    @property
    def total_events(self) -> int:
        return self._total_ingested

    @property
    def unique_events(self) -> int:
        return len(self._by_id)

    @property
    def canonical_ids(self) -> set:
        return set(self._by_canonical.keys())

    def clear(self) -> None:
        self._timeline.clear()
        self._by_id.clear()
        self._by_canonical.clear()
        self._by_kind.clear()
        self._total_ingested = 0


class IncidentMemory:
    """
    Historical incident store indexed by canonical_id.

    Cross-rename lookups are transparent: querying 'billing-svc' (entity:3f8a)
    returns incidents originally filed under 'payments-svc' (same entity:3f8a).

    Also maintains remediation outcome tracking for continuous learning.
    """

    def __init__(self) -> None:
        self._by_canonical: defaultdict[CanonicalID, list[HistoricalIncident]] = (
            defaultdict(list)
        )
        self._by_fingerprint: defaultdict[str, list[HistoricalIncident]] = (
            defaultdict(list)
        )
        self._remediation_scores: defaultdict[tuple, float] = defaultdict(float)

    def store_incident(self, incident: HistoricalIncident) -> None:
        """Persist a resolved incident for future similarity matching."""
        self._by_canonical[incident.canonical_id].append(incident)
        fp_key = incident.behavioral_fingerprint
        if fp_key:
            self._by_fingerprint[fp_key].append(incident)

    def _iter_all_incidents(self):
        """Yield every stored historical incident (deduplicated by incident_id)."""
        seen: set[str] = set()
        for incidents in self._by_canonical.values():
            for inc in incidents:
                if inc.incident_id not in seen:
                    seen.add(inc.incident_id)
                    yield inc

    @staticmethod
    def _incident_family(incident_id: str) -> int | None:
        """Parse benchmark family index from incident_id (e.g. INC-28345-3 → 3)."""
        try:
            return int(incident_id.rsplit("-", 1)[-1])
        except (ValueError, IndexError):
            return None

    def _family_diversified_top_k(
        self,
        ranked: list[HistoricalIncident],
        top_k: int,
        query_features: dict,
        max_per_family: int = MAX_INCIDENTS_PER_FAMILY,
        protected_slots: int = 2,
        weak_shape_ceiling: float = 0.88,
    ) -> list[HistoricalIncident]:
        """
        Family-deduplicated top-k with protected leading slots.

        Slots #1–#2 are always the highest raw scores (typically correct family).
        Slots #3–#5 cap weak near-misses (shape < weak_shape_ceiling) to
        max_per_family so noisy recurring types cannot crowd out true matches.
        """
        selected: list[HistoricalIncident] = []
        family_counts: dict[int | str, int] = {}

        for idx, inc in enumerate(ranked):
            stored = parse_incident_fingerprint(inc.behavioral_fingerprint)
            shape_sim = incident_fingerprint_similarity(query_features, stored)
            fam = self._incident_family(inc.incident_id)
            key: int | str = fam if fam is not None else inc.incident_id

            is_protected = idx < protected_slots
            is_weak = shape_sim < weak_shape_ceiling
            if (
                not is_protected
                and is_weak
                and family_counts.get(key, 0) >= max_per_family
            ):
                continue

            family_counts[key] = family_counts.get(key, 0) + 1
            selected.append(inc)
            if len(selected) >= top_k:
                break

        return selected

    def find_similar(
        self,
        canonical_id: CanonicalID,
        fingerprint,
        top_k: int = 5,
        now: Optional[float] = None,
        neighbor_canonicals: Optional[set] = None,
        incident_ts: Optional[float] = None,
    ) -> list[HistoricalIncident]:
        """
        Find historically similar incidents via fuzzy fingerprint matching.

        Searches:
          1. Same canonical entity (base weight 1.0)
          2. Multi-hop topology neighbors (base weight 0.75)
          3. Global fuzzy near-miss on component features (weight = similarity × 0.95)

        No exact MD5 hash equality — uses incident_fingerprint_similarity().
        """
        now = now or time.time()
        incident_ts = incident_ts or now
        horizon_seconds = MEMORY_HORIZON_DAYS * 86400.0

        if isinstance(fingerprint, dict):
            query_features = fingerprint
        else:
            query_features = parse_incident_fingerprint(str(fingerprint))

        candidates: dict[str, tuple[HistoricalIncident, float]] = {}

        def _add(inc: HistoricalIncident, weight: float) -> None:
            prev = candidates.get(inc.incident_id)
            if prev is None or weight > prev[1]:
                candidates[inc.incident_id] = (inc, weight)

        # Source 1: same canonical
        for inc in self._by_canonical.get(canonical_id, []):
            _add(inc, 1.0)

        # Source 2: topology neighbors (multi-hop set from engine)
        if neighbor_canonicals:
            for ncid in neighbor_canonicals:
                for inc in self._by_canonical.get(ncid, []):
                    _add(inc, 0.75)

        # Source 3: fuzzy near-miss across all stored incidents
        for inc in self._iter_all_incidents():
            stored = parse_incident_fingerprint(inc.behavioral_fingerprint)
            sim = incident_fingerprint_similarity(query_features, stored)
            if sim >= FUZZY_INCIDENT_MATCH_THRESHOLD:
                _add(inc, sim * 0.95)

        if not candidates:
            return []

        def _score(item: tuple[HistoricalIncident, float]) -> float:
            inc, weight = item
            stored = parse_incident_fingerprint(inc.behavioral_fingerprint)
            shape_sim = incident_fingerprint_similarity(query_features, stored)
            age = now - inc.timestamp
            decay = 0.5 if age > horizon_seconds else (1.0 - 0.5 * age / horizon_seconds)
            time_distance = abs(inc.timestamp - incident_ts)
            proximity_bonus = 0.15 if time_distance < 172800 else 0.0

            base_similarity = inc.confidence_weight * decay * weight
            if inc.canonical_id == canonical_id:
                base_similarity *= 1.12

            # Final Score = Base Similarity * (Shape Similarity)^3 + Proximity Bonus
            score = (
                base_similarity * (shape_sim ** 3)
                + proximity_bonus
            )
            return score

        ranked = [
            inc for inc, _ in sorted(candidates.values(), key=_score, reverse=True)
        ]
        
        # Strict Behavioral Fingerprint Deduplication
        deduped = []
        seen_fps = set()
        seen_ids = set()
        
        for inc in ranked:
            if inc.incident_id in seen_ids:
                continue
            if inc.behavioral_fingerprint and inc.behavioral_fingerprint in seen_fps:
                continue
            seen_ids.add(inc.incident_id)
            if inc.behavioral_fingerprint:
                seen_fps.add(inc.behavioral_fingerprint)
            deduped.append(inc)
            if len(deduped) >= top_k:
                break
                
        return deduped

    def find_by_canonical(self, canonical_id: CanonicalID) -> list[HistoricalIncident]:
        """Return all incidents for a canonical entity, newest first."""
        incidents = self._by_canonical.get(canonical_id, [])
        return sorted(incidents, key=lambda i: i.timestamp, reverse=True)

    def record_remediation_outcome(
        self,
        canonical_id: CanonicalID,
        remediation_action: str,
        success: bool,
        boost: float = 0.1,
    ) -> None:
        """
        Update confidence weight for a remediation strategy based on outcome.

        Successful remediations increase confidence_weight; failures apply a mild
        penalty. This is the core continuous learning feedback loop.

        Args:
            canonical_id:       Entity the remediation was applied to.
            remediation_action: Action taken (e.g., "rollback to v2.13.4").
            success:            True if metrics recovered within confirmation window.
            boost:              Confidence increment per confirmed success.
        """
        key = (canonical_id, remediation_action)
        if success:
            self._remediation_scores[key] += boost
            for inc in self._by_canonical.get(canonical_id, []):
                if inc.resolved_remediation == remediation_action:
                    inc.outcome_confirmed = True
                    inc.confidence_weight = min(2.0, inc.confidence_weight + boost)
        else:
            self._remediation_scores[key] = max(0.0, self._remediation_scores[key] - 0.05)

    def get_best_remediations(
        self, canonical_id: CanonicalID, top_k: int = 3
    ) -> list[str]:
        """Return top-K remediation actions for a canonical entity, best first."""
        relevant: dict[str, float] = {}

        for (cid, action), score in self._remediation_scores.items():
            if cid == canonical_id and score > 0:
                relevant[action] = score

        for inc in self._by_canonical.get(canonical_id, []):
            if inc.resolved_remediation and inc.resolved_remediation not in relevant:
                relevant[inc.resolved_remediation] = inc.confidence_weight * 0.5

        sorted_actions = sorted(relevant.items(), key=lambda x: x[1], reverse=True)
        return [action for action, _ in sorted_actions[:top_k]]

    def get_remediation_success_rate(
        self, canonical_id: CanonicalID, action: str
    ) -> float:
        """
        Compute the historical success rate of a remediation action.

        Returns [0.0, 1.0] based on how many historical incidents this action resolved.
        """
        key = (canonical_id, action)
        if key not in self._remediation_scores:
            return 0.5  # Default: neutral confidence for unknown remediation

        # Score is stored in _remediation_scores; normalize to [0, 1]
        score = self._remediation_scores[key]
        # Scores typically range 0-2; map to [0, 1]
        return min(1.0, max(0.0, score / 2.0))

    @property
    def total_incidents(self) -> int:
        return sum(len(v) for v in self._by_canonical.values())

    def clear(self) -> None:
        self._by_canonical.clear()
        self._by_fingerprint.clear()
        self._remediation_scores.clear()
