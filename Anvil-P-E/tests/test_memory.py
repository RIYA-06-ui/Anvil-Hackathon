"""
test_memory.py — Unit tests for EventStore and IncidentMemory.
"""

import time
import pytest

from src.memory import EventStore, IncidentMemory
from src.types import InternalEvent, HistoricalIncident, CausalEdgeDict


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def make_event(
    event_id: str,
    kind: str,
    timestamp: float,
    canonical_id: str = "entity:abc",
    service: str = "svc-a",
    data: dict = None,
) -> InternalEvent:
    return InternalEvent(
        event_id=event_id,
        kind=kind,
        timestamp=timestamp,
        canonical_id=canonical_id,
        raw_service_name=service,
        data=data or {},
    )


@pytest.fixture
def store():
    return EventStore()


@pytest.fixture
def memory():
    return IncidentMemory()


# ---------------------------------------------------------------------------
# EventStore tests
# ---------------------------------------------------------------------------

class TestEventStore:

    def test_add_and_get_by_id(self, store):
        ev = make_event("e1", "deploy", 1000.0)
        store.add_event(ev)
        assert store.get_by_id("e1") == ev

    def test_get_missing_event_returns_none(self, store):
        assert store.get_by_id("nonexistent") is None

    def test_total_events_count(self, store):
        store.add_event(make_event("e1", "deploy", 1000.0))
        store.add_event(make_event("e2", "metric", 1100.0))
        assert store.total_events == 2
        assert store.unique_events == 2

    def test_query_by_canonical_returns_all(self, store):
        store.add_event(make_event("e1", "deploy", 1000.0, canonical_id="entity:abc"))
        store.add_event(make_event("e2", "metric", 1100.0, canonical_id="entity:abc"))
        store.add_event(make_event("e3", "log",    1200.0, canonical_id="entity:xyz"))
        results = store.query_by_canonical("entity:abc")
        assert len(results) == 2
        assert all(e.canonical_id == "entity:abc" for e in results)

    def test_query_window_temporal_bounds(self, store):
        # Event at T=500, T=1000, T=1500, T=2000
        for i, ts in enumerate([500.0, 1000.0, 1500.0, 2000.0]):
            store.add_event(make_event(f"e{i}", "log", ts))
        # Query ±600s around T=1000 → should get T=500 and T=1000 and T=1500
        results = store.query_window("entity:abc", center_ts=1000.0, window_seconds=600.0)
        timestamps = {e.timestamp for e in results}
        assert 500.0 in timestamps
        assert 1000.0 in timestamps
        assert 1500.0 in timestamps
        assert 2000.0 not in timestamps  # outside window

    def test_query_window_canonical_isolation(self, store):
        store.add_event(make_event("e1", "deploy", 1000.0, canonical_id="entity:abc"))
        store.add_event(make_event("e2", "metric", 1050.0, canonical_id="entity:xyz"))
        results = store.query_window("entity:abc", center_ts=1000.0, window_seconds=300.0)
        assert len(results) == 1
        assert results[0].event_id == "e1"

    def test_query_window_includes_related_canonicals(self, store):
        store.add_event(make_event("e1", "deploy", 1000.0, canonical_id="entity:abc"))
        store.add_event(make_event("e2", "metric", 1050.0, canonical_id="entity:dep"))
        results = store.query_window(
            "entity:abc", center_ts=1000.0, window_seconds=300.0,
            include_related_canonicals={"entity:dep"}
        )
        assert len(results) == 2

    def test_query_window_sorted_by_timestamp(self, store):
        for ts in [1200.0, 1000.0, 1100.0]:
            store.add_event(make_event(f"e{int(ts)}", "log", ts))
        results = store.query_window("entity:abc", center_ts=1100.0, window_seconds=300.0)
        timestamps = [e.timestamp for e in results]
        assert timestamps == sorted(timestamps)

    def test_query_kind_for_canonical(self, store):
        store.add_event(make_event("e1", "deploy", 1000.0))
        store.add_event(make_event("e2", "metric", 1100.0))
        store.add_event(make_event("e3", "deploy", 1200.0))
        deploys = store.query_kind_for_canonical("deploy", "entity:abc")
        assert len(deploys) == 2
        assert all(e.kind == "deploy" for e in deploys)

    def test_get_recent_events_limit(self, store):
        for i in range(20):
            store.add_event(make_event(f"e{i}", "log", float(i * 100)))
        recent = store.get_recent_events("entity:abc", n=5)
        assert len(recent) == 5
        # Should be the 5 most recent
        assert recent[0].timestamp > recent[1].timestamp

    def test_canonical_ids_property(self, store):
        store.add_event(make_event("e1", "log", 1000.0, canonical_id="entity:abc"))
        store.add_event(make_event("e2", "log", 1000.0, canonical_id="entity:xyz"))
        assert store.canonical_ids == {"entity:abc", "entity:xyz"}

    def test_clear_resets_all_indexes(self, store):
        store.add_event(make_event("e1", "log", 1000.0))
        store.clear()
        assert store.total_events == 0
        assert store.get_by_id("e1") is None


# ---------------------------------------------------------------------------
# IncidentMemory tests
# ---------------------------------------------------------------------------

def make_incident(
    incident_id: str,
    canonical_id: str = "entity:abc",
    timestamp: float = 1000.0,
    fingerprint: str = "fp:abc123",
    remediation: str = None,
) -> HistoricalIncident:
    return HistoricalIncident(
        incident_id=incident_id,
        canonical_id=canonical_id,
        timestamp=timestamp,
        causal_chain=[],
        behavioral_fingerprint=fingerprint,
        resolved_remediation=remediation,
    )


class TestIncidentMemory:

    def test_store_and_find_by_canonical(self, memory):
        inc = make_incident("INC-001")
        memory.store_incident(inc)
        results = memory.find_by_canonical("entity:abc")
        assert len(results) == 1
        assert results[0].incident_id == "INC-001"

    def test_find_similar_by_canonical(self, memory):
        memory.store_incident(make_incident("INC-001", canonical_id="entity:abc"))
        memory.store_incident(make_incident("INC-002", canonical_id="entity:abc"))
        memory.store_incident(make_incident("INC-003", canonical_id="entity:xyz", fingerprint="fp:xyz999"))
        results = memory.find_similar("entity:abc", "fp:abc123", top_k=5)
        ids = [r.incident_id for r in results]
        assert "INC-001" in ids
        assert "INC-002" in ids
        assert "INC-003" not in ids  # different entity AND different fingerprint

    def test_find_similar_by_fingerprint_cross_entity(self, memory):
        """Incidents with same fingerprint on different entity are found via fingerprint index."""
        memory.store_incident(make_incident("INC-001", canonical_id="entity:abc", fingerprint="fp:shared"))
        memory.store_incident(make_incident("INC-002", canonical_id="entity:xyz", fingerprint="fp:shared"))
        # Query for entity:abc with fingerprint fp:shared — should find INC-002 via fingerprint
        results = memory.find_similar("entity:abc", "fp:shared", top_k=5)
        ids = [r.incident_id for r in results]
        assert "INC-001" in ids
        assert "INC-002" in ids

    def test_find_similar_top_k_limit(self, memory):
        for i in range(10):
            memory.store_incident(make_incident(f"INC-{i:03d}", timestamp=float(i * 100)))
        results = memory.find_similar("entity:abc", "fp:abc123", top_k=3)
        assert len(results) <= 3

    def test_find_similar_returns_empty_for_unknown(self, memory):
        results = memory.find_similar("entity:never_seen", "fp:none", top_k=5)
        assert results == []

    def test_remediation_outcome_boost(self, memory):
        inc = make_incident("INC-001", remediation="rollback")
        memory.store_incident(inc)
        assert inc.confidence_weight == 1.0
        memory.record_remediation_outcome("entity:abc", "rollback", success=True)
        assert inc.confidence_weight > 1.0
        assert inc.outcome_confirmed is True

    def test_remediation_outcome_penalty(self, memory):
        memory.record_remediation_outcome("entity:abc", "restart", success=False)
        remediations = memory.get_best_remediations("entity:abc")
        # After a penalty, "restart" score should be negative — not surfaced
        assert "restart" not in remediations

    def test_get_best_remediations_ordering(self, memory):
        memory.record_remediation_outcome("entity:abc", "rollback", success=True)
        memory.record_remediation_outcome("entity:abc", "rollback", success=True)
        memory.record_remediation_outcome("entity:abc", "restart", success=True)
        rems = memory.get_best_remediations("entity:abc", top_k=2)
        assert rems[0] == "rollback"  # rollback has 2 successes vs restart's 1

    def test_age_decay_on_old_incidents(self, memory):
        """Old incidents should score lower than recent ones."""
        old_ts = time.time() - (100 * 86400)  # 100 days ago (past horizon)
        new_ts = time.time() - 3600           # 1 hour ago
        memory.store_incident(make_incident("INC-OLD", timestamp=old_ts, fingerprint="fp:x"))
        memory.store_incident(make_incident("INC-NEW", timestamp=new_ts, fingerprint="fp:x"))
        results = memory.find_similar("entity:abc", "fp:x", top_k=2)
        # INC-NEW should rank first (more recent)
        assert results[0].incident_id == "INC-NEW"

    def test_total_incidents_count(self, memory):
        memory.store_incident(make_incident("INC-001"))
        memory.store_incident(make_incident("INC-002"))
        assert memory.total_incidents == 2

    def test_clear_resets_all(self, memory):
        memory.store_incident(make_incident("INC-001"))
        memory.clear()
        assert memory.total_incidents == 0
        assert memory.find_by_canonical("entity:abc") == []
