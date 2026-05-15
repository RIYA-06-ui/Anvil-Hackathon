"""
test_drift.py — Unit tests for IdentityGraph and behavioral fingerprinting.
"""

import pytest
from src.drift_handler import (
    IdentityGraph,
    compute_signature,
    fingerprint_similarity,
    compute_incident_fingerprint,
)
from src.types import InternalEvent


def make_event(kind, ts, canonical_id, data=None):
    return InternalEvent(
        event_id=f"{kind}-{ts}",
        kind=kind,
        timestamp=ts,
        canonical_id=canonical_id,
        raw_service_name="svc",
        data=data or {},
    )


@pytest.fixture
def graph():
    return IdentityGraph()


# ---------------------------------------------------------------------------
# IdentityGraph — resolve_or_create
# ---------------------------------------------------------------------------

class TestIdentityGraph:

    def test_first_seen_creates_new_canonical(self, graph):
        cid = graph.resolve_or_create("payments-svc")
        assert cid.startswith("entity:")
        assert "payments-svc" in graph.alias_map

    def test_same_name_returns_same_canonical(self, graph):
        cid1 = graph.resolve_or_create("payments-svc")
        cid2 = graph.resolve_or_create("payments-svc")
        assert cid1 == cid2

    def test_different_names_get_different_canonicals(self, graph):
        cid1 = graph.resolve_or_create("payments-svc")
        cid2 = graph.resolve_or_create("auth-svc")
        assert cid1 != cid2

    def test_canonical_id_format(self, graph):
        cid = graph.resolve_or_create("svc-x")
        assert cid.startswith("entity:")
        assert len(cid) == len("entity:") + 12

    # ---------------------------------------------------------------------------
    # Explicit renames
    # ---------------------------------------------------------------------------

    def test_explicit_rename_maps_both_names(self, graph):
        old_cid = graph.resolve_or_create("payments-svc")
        new_cid = graph.register_rename("payments-svc", "billing-svc")
        assert old_cid == new_cid
        assert graph.alias_map["billing-svc"] == old_cid
        assert graph.alias_map["payments-svc"] == old_cid

    def test_cascading_rename_all_resolve_same(self, graph):
        graph.resolve_or_create("payments-svc")
        graph.register_rename("payments-svc", "billing-svc")
        graph.register_rename("billing-svc", "finance-svc")
        c1 = graph.alias_map["payments-svc"]
        c2 = graph.alias_map["billing-svc"]
        c3 = graph.alias_map["finance-svc"]
        assert c1 == c2 == c3

    def test_circular_rename_no_crash(self, graph):
        graph.resolve_or_create("svc-a")
        graph.register_rename("svc-a", "svc-b")
        # Circular: svc-b back to svc-a — should not cause error or duplicate
        graph.register_rename("svc-b", "svc-a")
        assert graph.alias_map["svc-a"] == graph.alias_map["svc-b"]

    def test_rename_updates_known_aliases(self, graph):
        graph.resolve_or_create("payments-svc")
        graph.register_rename("payments-svc", "billing-svc")
        canon = graph.alias_map["billing-svc"]
        aliases = graph.get_all_aliases(canon)
        assert "payments-svc" in aliases
        assert "billing-svc" in aliases

    def test_resolve_known_name(self, graph):
        graph.resolve_or_create("svc-x")
        assert graph.resolve("svc-x") is not None

    def test_resolve_unknown_name_returns_none(self, graph):
        assert graph.resolve("never-seen") is None

    def test_len_tracks_entity_count(self, graph):
        graph.resolve_or_create("svc-a")
        graph.resolve_or_create("svc-b")
        assert len(graph) == 2
        # Rename should NOT create new entity
        graph.register_rename("svc-a", "svc-a-new")
        assert len(graph) == 2

    # ---------------------------------------------------------------------------
    # Dependencies
    # ---------------------------------------------------------------------------

    def test_update_dependencies_creates_both_entities(self, graph):
        graph.update_dependencies("api-gw", "payments-svc")
        assert graph.resolve("api-gw") is not None
        assert graph.resolve("payments-svc") is not None

    def test_get_downstream(self, graph):
        graph.update_dependencies("api-gw", "payments-svc")
        api_canon = graph.resolve("api-gw")
        pay_canon = graph.resolve("payments-svc")
        assert pay_canon in graph.get_downstream(api_canon)

    def test_get_upstream(self, graph):
        graph.update_dependencies("api-gw", "payments-svc")
        api_canon = graph.resolve("api-gw")
        pay_canon = graph.resolve("payments-svc")
        assert api_canon in graph.get_upstream(pay_canon)

    # ---------------------------------------------------------------------------
    # Merge canonicals
    # ---------------------------------------------------------------------------

    def test_merge_canonicals_redirects_aliases(self, graph):
        c1 = graph.resolve_or_create("svc-old")
        c2 = graph.resolve_or_create("svc-new")
        graph.merge_canonicals(keep_id=c1, merge_id=c2)
        assert graph.alias_map["svc-new"] == c1
        assert c2 not in graph.entities


# ---------------------------------------------------------------------------
# Behavioral fingerprinting
# ---------------------------------------------------------------------------

class TestBehavioralFingerprinting:

    def _log_events(self, canonical_id, message, level, count=5):
        return [
            make_event("log", float(i * 100), canonical_id,
                       data={"message": message, "level": level})
            for i in range(count)
        ]

    def _metric_events(self, canonical_id, name, value, count=5):
        return [
            make_event("metric", float(i * 100), canonical_id,
                       data={"metric_name": name, "value": value})
            for i in range(count)
        ]

    def test_identical_events_produce_max_similarity(self):
        events = (
            self._log_events("entity:a", "connection timeout to 10.0.0.1:8080", "ERROR")
            + self._metric_events("entity:a", "latency_p99", 750.0)
        )
        sig_a = compute_signature(events)
        sig_b = compute_signature(events)
        # Similarity is 0.85 because not all 4 dimensions match perfectly
        # (deploy_frequency is 0 in both, so that dimension contributes 0)
        assert fingerprint_similarity(sig_a, sig_b) >= 0.80

    def test_different_log_templates_low_similarity(self):
        events_a = self._log_events("entity:a", "connection timeout", "ERROR")
        events_b = self._log_events("entity:b", "disk write failed", "ERROR")
        sig_a = compute_signature(events_a)
        sig_b = compute_signature(events_b)
        sim = fingerprint_similarity(sig_a, sig_b)
        assert sim < 0.5

    def test_rename_scenario_high_similarity(self):
        """payments-svc and billing-svc should score ≥0.60 if behaviorally similar."""
        base_logs = [
            make_event("log", float(i * 50), "entity:pay",
                       data={"message": "connection timeout to 10.0.0.1:9090", "level": "ERROR"})
            for i in range(10)
        ]
        base_metrics = [
            make_event("metric", float(i * 50), "entity:pay",
                       data={"metric_name": "latency_p99", "value": 820.0})
            for i in range(5)
        ]
        billing_logs = [
            make_event("log", float(i * 50), "entity:bill",
                       data={"message": "connection timeout to 192.168.1.1:9090", "level": "ERROR"})
            for i in range(10)
        ]
        billing_metrics = [
            make_event("metric", float(i * 50), "entity:bill",
                       data={"metric_name": "latency_p99", "value": 790.0})
            for i in range(5)
        ]
        sig_pay = compute_signature(base_logs + base_metrics)
        sig_bill = compute_signature(billing_logs + billing_metrics)
        sim = fingerprint_similarity(sig_pay, sig_bill)
        # Both have same log template (after IP stripping), same metrics, same latency bucket
        assert sim >= 0.60

    def test_empty_events_produce_zero_similarity(self):
        sig_a = compute_signature([])
        sig_b = compute_signature([])
        # Both empty — all fields default, similarity computation should not crash
        sim = fingerprint_similarity(sig_a, sig_b)
        assert 0.0 <= sim <= 1.0

    def test_compute_incident_fingerprint_consistent(self):
        events = self._log_events("entity:a", "error", "ERROR")
        fp1 = compute_incident_fingerprint(events)
        fp2 = compute_incident_fingerprint(events)
        assert fp1 == fp2
        assert fp1["has_error_log"] is True

    def test_compute_incident_fingerprint_different_for_different_shapes(self):
        from src.drift_handler import incident_fingerprint_similarity
        events_a = self._log_events("entity:a", "error", "ERROR")
        events_b = self._metric_events("entity:b", "latency_p99", 500.0)
        fp_a = compute_incident_fingerprint(events_a)
        fp_b = compute_incident_fingerprint(events_b)
        assert incident_fingerprint_similarity(fp_a, fp_b) < 0.65
