"""
Adversarial rename scenarios for drift detection.

Tests edge cases and corner cases in topology drift handling:
  - Long cascading rename chains (A→B→C→D→E)
  - Circular renames (A→B→A)
  - Complex service topology (diamond dependencies)
  - Implicit rename inference via behavioral fingerprinting
  - Merge conflicts and entity consolidation
"""

import pytest
from src.drift_handler import (
    IdentityGraph,
    compute_signature,
    fingerprint_similarity,
)
from src.types import InternalEvent, IMPLICIT_RENAME_THRESHOLD


def make_event(kind, ts, canonical_id, data=None):
    """Helper to create test events."""
    return InternalEvent(
        event_id=f"{kind}-{ts}",
        kind=kind,
        timestamp=ts,
        canonical_id=canonical_id,
        raw_service_name="svc",
        data=data or {},
    )


class TestAdversarialRenames:
    """Adversarial test cases for IdentityGraph rename handling."""

    def test_long_cascading_rename_chain_5_steps(self):
        """
        Test a long rename chain: svc-v1 → v2 → v3 → v4 → v5.
        All names should resolve to the same canonical_id.
        All aliases should be tracked.
        """
        graph = IdentityGraph()
        original = graph.resolve_or_create("svc-v1")
        
        # Chain of renames
        names = ["svc-v2", "svc-v3", "svc-v4", "svc-v5"]
        for new_name in names:
            old_name = names[names.index(new_name) - 1] if new_name != "svc-v2" else "svc-v1"
            canon = graph.register_rename(old_name, new_name)
            assert canon == original, f"Rename {old_name} → {new_name} broke chain"
        
        # All names resolve to same canonical
        for name in ["svc-v1", "svc-v2", "svc-v3", "svc-v4", "svc-v5"]:
            assert graph.resolve(name) == original
        
        # All aliases are tracked
        aliases = graph.get_all_aliases(original)
        assert len(aliases) == 5
        assert set(aliases) == {"svc-v1", "svc-v2", "svc-v3", "svc-v4", "svc-v5"}

    def test_circular_rename_triple_cycle(self):
        """
        Test circular rename: A → B → C → A.
        The flat map should handle this gracefully with no duplicates or errors.
        """
        graph = IdentityGraph()
        graph.resolve_or_create("svc-a")
        graph.register_rename("svc-a", "svc-b")
        graph.register_rename("svc-b", "svc-c")
        graph.register_rename("svc-c", "svc-a")
        
        # All three resolve to the same canonical
        canon_a = graph.resolve("svc-a")
        canon_b = graph.resolve("svc-b")
        canon_c = graph.resolve("svc-c")
        assert canon_a == canon_b == canon_c
        
        # Exactly 3 aliases (no duplicates)
        aliases = graph.get_all_aliases(canon_a)
        assert len(aliases) == 3
        assert set(aliases) == {"svc-a", "svc-b", "svc-c"}

    def test_diamond_topology_with_renames(self):
        """
        Test complex dependency topology with renames:
          gw → [api, db]
          api → auth
          db → cache
        Then rename: api → api-v2, cache → cache-v2.
        Dependencies should remain consistent.
        """
        graph = IdentityGraph()
        
        # Build diamond
        gw = graph.resolve_or_create("gw")
        api = graph.resolve_or_create("api")
        db = graph.resolve_or_create("db")
        auth = graph.resolve_or_create("auth")
        cache = graph.resolve_or_create("cache")
        
        graph.update_dependencies("gw", "api")
        graph.update_dependencies("gw", "db")
        graph.update_dependencies("api", "auth")
        graph.update_dependencies("db", "cache")
        
        # Check downstream before rename
        assert auth in graph.get_downstream(api)
        assert cache in graph.get_downstream(db)
        
        # Rename api and cache
        graph.register_rename("api", "api-v2")
        graph.register_rename("cache", "cache-v2")
        
        # Dependencies should still work (resolved via canonical)
        assert auth in graph.get_downstream(api)  # Still works
        assert cache in graph.get_downstream(db)  # Still works
        
        # New names resolve to same canonicals
        assert graph.resolve("api-v2") == api
        assert graph.resolve("cache-v2") == cache

    def test_interleaved_explicit_and_implicit_renames(self):
        """
        Test mixed scenario: explicit rename + implicit rename inference.
        Create two behavioral twins and merge them, then explicitly rename one.
        """
        graph = IdentityGraph()
        
        # Create two services with identical behavior
        svc_a = graph.resolve_or_create("payments-svc")
        svc_b = graph.resolve_or_create("billing-svc")
        
        # Build identical event streams
        common_logs = [
            make_event("log", float(i * 50), svc_a,
                       data={"message": "timeout in database query", "level": "ERROR"})
            for i in range(10)
        ]
        common_metrics = [
            make_event("metric", float(i * 50), svc_a,
                       data={"metric_name": "latency_p99", "value": 750.0})
            for i in range(5)
        ]
        
        # Create identical events for svc_b
        events_for_b = []
        for ev in common_logs + common_metrics:
            new_ev = make_event(ev.kind, ev.timestamp, svc_b, data=ev.data)
            events_for_b.append(new_ev)
        
        # Compute signatures
        sig_a = compute_signature(common_logs + common_metrics)
        sig_b = compute_signature(events_for_b)
        similarity = fingerprint_similarity(sig_a, sig_b)
        
        # Should be high similarity (above threshold)
        assert similarity >= IMPLICIT_RENAME_THRESHOLD
        
        # Merge the canonicals
        graph.merge_canonicals(keep_id=svc_a, merge_id=svc_b)
        
        # Both old names should now resolve to svc_a
        assert graph.resolve("payments-svc") == svc_a
        assert graph.resolve("billing-svc") == svc_a
        
        # Now explicitly rename
        graph.register_rename("payments-svc", "finance-svc")
        
        # All three names resolve to same canonical
        assert graph.resolve("payments-svc") == svc_a
        assert graph.resolve("billing-svc") == svc_a
        assert graph.resolve("finance-svc") == svc_a

    def test_many_renames_same_canonical(self):
        """
        Stress test: 50 renames of the same service.
        Ensures O(1) flat map doesn't degrade with chain length.
        """
        graph = IdentityGraph()
        original = graph.resolve_or_create("initial-name")
        
        # Rename many times
        for i in range(50):
            old_name = f"name-{i}" if i > 0 else "initial-name"
            new_name = f"name-{i + 1}"
            canon = graph.register_rename(old_name, new_name)
            assert canon == original
        
        # All 51 names resolve to original
        assert len(graph.get_all_aliases(original)) == 51
        for i in range(51):
            name = "initial-name" if i == 0 else f"name-{i}"
            assert graph.resolve(name) == original

    def test_three_way_merge_consolidation(self):
        """
        Test merging three canonical entities into one:
        Merge svc_b and svc_c into svc_a.
        """
        graph = IdentityGraph()
        svc_a = graph.resolve_or_create("service-a")
        svc_b = graph.resolve_or_create("service-b")
        svc_c = graph.resolve_or_create("service-c")
        
        assert len(graph) == 3
        
        # Merge b into a
        graph.merge_canonicals(keep_id=svc_a, merge_id=svc_b)
        assert len(graph) == 2
        
        # Merge c into a
        graph.merge_canonicals(keep_id=svc_a, merge_id=svc_c)
        assert len(graph) == 1
        
        # All three original names resolve to svc_a
        assert graph.resolve("service-a") == svc_a
        assert graph.resolve("service-b") == svc_a
        assert graph.resolve("service-c") == svc_a
        
        # All aliases tracked
        aliases = graph.get_all_aliases(svc_a)
        assert set(aliases) == {"service-a", "service-b", "service-c"}

    def test_rename_nonexistent_service_creates_it(self):
        """
        Edge case: renaming a service that doesn't yet exist should create it.
        """
        graph = IdentityGraph()
        
        # Register rename for a service we haven't seen yet
        canon = graph.register_rename("never-seen-old", "never-seen-new")
        
        # Both names now resolve to the same canonical
        assert graph.resolve("never-seen-old") == canon
        assert graph.resolve("never-seen-new") == canon
        
        # Entity should exist
        assert len(graph) == 1

    def test_identical_rename_is_idempotent(self):
        """
        Renaming a service to itself should be a no-op.
        """
        graph = IdentityGraph()
        canon = graph.resolve_or_create("svc-stable")
        aliases_before = graph.get_all_aliases(canon)
        
        # "Rename" to same name
        result_canon = graph.register_rename("svc-stable", "svc-stable")
        
        # Should return same canonical, no alias duplication
        assert result_canon == canon
        aliases_after = graph.get_all_aliases(canon)
        assert len(aliases_before) == len(aliases_after)

    def test_behavioral_signature_with_mixed_event_types(self):
        """
        Test fingerprinting with all 7 event kinds present.
        Signature should handle each type gracefully.
        """
        graph = IdentityGraph()
        svc = graph.resolve_or_create("mixed-svc")
        
        # Generate events of all kinds
        events = [
            make_event("deploy", 0.0, svc, data={"version": "1.0.0"}),
            make_event("log", 100.0, svc, data={"message": "startup complete", "level": "INFO"}),
            make_event("metric", 200.0, svc, data={"metric_name": "latency_p99", "value": 120.0}),
            make_event("trace", 300.0, svc, data={"span_id": "abc123", "parent_span_id": None}),
            make_event("topology", 400.0, svc, data={"dependency": "database"}),
            make_event("incident_signal", 500.0, svc, data={"severity": "high"}),
            make_event("remediation", 600.0, svc, data={"action": "rollback"}),
        ]
        
        # Compute signature — should not crash
        sig = compute_signature(events)
        
        # Should have computed fields
        assert "log_template_counts" in sig
        assert "metric_names_seen" in sig
        assert "latency_bucket" in sig
        assert "error_rate_bucket" in sig
        assert "deploy_frequency" in sig
        assert sig["deploy_frequency"] == 1

    def test_upstream_downstream_tracking_after_merges(self):
        """
        Test that dependency tracking is preserved after merging canonicals.
        """
        graph = IdentityGraph()
        
        # Create a simple chain: api → db
        api1 = graph.resolve_or_create("api-svc")
        db = graph.resolve_or_create("db-svc")
        graph.update_dependencies("api-svc", "db-svc")
        
        # Create a duplicate api with different name
        api2 = graph.resolve_or_create("api-v2")
        
        # Merge api2 into api1
        graph.merge_canonicals(keep_id=api1, merge_id=api2)
        
        # Dependencies should still work
        downstream = graph.get_downstream(api1)
        assert db in downstream


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
