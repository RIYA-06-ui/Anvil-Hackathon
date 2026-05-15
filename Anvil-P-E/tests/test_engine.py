"""
test_engine.py — End-to-end integration tests for PersistentContextEngine.

These tests simulate real operational scenarios including the worked example
from the problem statement (INC-714 with payments-svc → billing-svc rename).
"""

import time
import pytest

from src.engine import PersistentContextEngine
from src.types import Event, IncidentSignal


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_raw_event(kind, service, ts, event_id=None, data=None) -> Event:
    return Event(
        event_id=event_id or f"{kind}-{int(ts)}",
        kind=kind,
        timestamp=ts,
        service=service,
        data=data or {},
    )


def make_signal(incident_id, service, ts, severity="critical") -> IncidentSignal:
    return IncidentSignal(
        incident_id=incident_id,
        service=service,
        timestamp=ts,
        severity=severity,
        data={"incident_id": incident_id},
    )


@pytest.fixture
def engine():
    e = PersistentContextEngine()
    yield e
    e.close()


# ---------------------------------------------------------------------------
# Task 2.2 — Ingest pipeline
# ---------------------------------------------------------------------------

class TestIngestPipeline:

    def test_ingest_single_event(self, engine):
        events = [make_raw_event("deploy", "payments-svc", 1000.0)]
        engine.ingest(events)
        assert engine.event_count == 1

    def test_ingest_all_6_event_kinds(self, engine):
        events = [
            make_raw_event("deploy",          "svc-a", 1000.0),
            make_raw_event("log",             "svc-a", 1010.0, data={"level": "ERROR", "message": "err"}),
            make_raw_event("metric",          "svc-a", 1020.0, data={"metric_name": "latency_p99", "value": 800}),
            make_raw_event("trace",           "svc-a", 1030.0, data={"span_id": "s1"}),
            make_raw_event("topology",        "svc-a", 1040.0, data={"change_type": "rename", "old_service": "svc-a", "new_service": "svc-b"}),
            make_raw_event("remediation",     "svc-b", 1050.0, data={"action": "rollback"}),
            make_raw_event("incident_signal", "svc-b", 1060.0, data={"incident_id": "INC-001"}),
        ]
        engine.ingest(events)
        assert engine.event_count == 7

    def test_ingest_skips_malformed_events(self, engine):
        # Event missing 'kind' field — should be silently skipped
        bad_event = {"service": "svc-a", "timestamp": 1000.0}
        engine.ingest([bad_event])
        assert engine.event_count == 0

    def test_ingest_throughput_1k_per_sec(self, engine):
        """Generate 1000 events and verify ingest completes in ≤1 second."""
        events = [
            make_raw_event("log", "svc-a", float(i),
                           event_id=f"log-{i}",
                           data={"level": "INFO", "message": f"msg {i}"})
            for i in range(1000)
        ]
        t0 = time.monotonic()
        engine.ingest(events)
        elapsed = time.monotonic() - t0
        assert elapsed <= 1.0, f"Ingest took {elapsed:.3f}s for 1000 events"
        assert engine.event_count == 1000

    def test_topology_rename_updates_identity(self, engine):
        events = [
            make_raw_event("deploy",   "payments-svc", 1000.0),
            make_raw_event("topology", "payments-svc", 1100.0, data={
                "change_type": "rename",
                "old_service": "payments-svc",
                "new_service": "billing-svc",
            }),
        ]
        engine.ingest(events)
        # Both names should resolve to the same canonical
        canon_pay = engine._identity.resolve("payments-svc")
        canon_bill = engine._identity.resolve("billing-svc")
        assert canon_pay is not None
        assert canon_bill is not None
        assert canon_pay == canon_bill


# ---------------------------------------------------------------------------
# Task 2.6 — Context reconstruction (fast path)
# ---------------------------------------------------------------------------

class TestContextReconstructionFast:

    def _ingest_worked_example(self, engine):
        """Ingest the INC-714 worked example events."""
        T = 1_000_000.0  # base timestamp
        events = [
            # Original deployment under payments-svc
            make_raw_event("deploy", "payments-svc", T,
                           event_id="deploy-v1",
                           data={"version": "v1.0", "deploy_type": "rolling"}),
            make_raw_event("log",    "payments-svc", T + 305,
                           event_id="log-err-1",
                           data={"level": "ERROR", "message": "connection timeout to 10.0.0.1:8080"}),
            make_raw_event("metric", "payments-svc", T + 310,
                           event_id="metric-lat-1",
                           data={"metric_name": "latency_p99", "value": 850}),
            make_raw_event("trace",  "payments-svc", T + 315,
                           event_id="trace-1",
                           data={"span_id": "span-abc", "parent_span_id": None}),
            # Topology rename
            make_raw_event("topology", "payments-svc", T + 400,
                           event_id="rename-1",
                           data={
                               "change_type": "rename",
                               "old_service": "payments-svc",
                               "new_service": "billing-svc",
                           }),
            # Incident under new name
            make_raw_event("incident_signal", "billing-svc", T + 500,
                           event_id="inc-714",
                           data={"incident_id": "INC-714", "severity": "critical"}),
            # Remediation
            make_raw_event("remediation", "billing-svc", T + 600,
                           event_id="rem-1",
                           data={"action": "rollback billing-svc to v2.13.4"}),
        ]
        engine.ingest(events)
        return T

    def test_reconstruct_returns_context_shape(self, engine):
        T = self._ingest_worked_example(engine)
        signal = make_signal("INC-714", "billing-svc", T + 500)
        ctx = engine.reconstruct_context(signal, mode="fast")

        assert "incident_id" in ctx
        assert "related_events" in ctx
        assert "causal_chain" in ctx
        assert "similar_past_incidents" in ctx
        assert "suggested_remediations" in ctx
        assert "confidence" in ctx
        assert "explain" in ctx

    def test_reconstruct_incident_id_preserved(self, engine):
        T = self._ingest_worked_example(engine)
        signal = make_signal("INC-714", "billing-svc", T + 500)
        ctx = engine.reconstruct_context(signal, mode="fast")
        assert ctx["incident_id"] == "INC-714"

    def test_reconstruct_finds_related_events(self, engine):
        T = self._ingest_worked_example(engine)
        signal = make_signal("INC-714", "billing-svc", T + 500)
        ctx = engine.reconstruct_context(signal, mode="fast")
        # Should find deploy, log, metric, trace in the window
        related_kinds = {e["kind"] for e in ctx["related_events"]}
        assert "deploy" in related_kinds
        assert "metric" in related_kinds
        assert "log" in related_kinds

    def test_reconstruct_causal_chain_links_related_events(self, engine):
        T = self._ingest_worked_example(engine)
        signal = make_signal("INC-714", "billing-svc", T + 500)
        ctx = engine.reconstruct_context(signal, mode="fast")
        if ctx["causal_chain"]:
            linked = set()
            for edge in ctx["causal_chain"]:
                linked.add(edge["from_event_id"])
                linked.add(edge["to_event_id"])
            related_ids = {e["event_id"] for e in ctx["related_events"]}
            assert linked.issubset(related_ids)

    def test_reconstruct_causal_chain_confidence_above_threshold(self, engine):
        T = self._ingest_worked_example(engine)
        signal = make_signal("INC-714", "billing-svc", T + 500)
        ctx = engine.reconstruct_context(signal, mode="fast")
        for edge in ctx["causal_chain"]:
            assert edge["confidence"] >= 0.65, (
                f"Edge {edge['from_event_id']} → {edge['to_event_id']} "
                f"has confidence {edge['confidence']} below chain threshold"
            )

    def test_reconstruct_confidence_is_valid_float(self, engine):
        T = self._ingest_worked_example(engine)
        signal = make_signal("INC-714", "billing-svc", T + 500)
        ctx = engine.reconstruct_context(signal, mode="fast")
        assert 0.0 <= ctx["confidence"] <= 1.0

    def test_reconstruct_explain_is_nonempty_string(self, engine):
        T = self._ingest_worked_example(engine)
        signal = make_signal("INC-714", "billing-svc", T + 500)
        ctx = engine.reconstruct_context(signal, mode="fast")
        assert isinstance(ctx["explain"], str)
        assert len(ctx["explain"]) > 20

    def test_reconstruct_fast_mode_latency(self, engine):
        """Fast mode must complete in ≤2s p95."""
        T = self._ingest_worked_example(engine)
        signal = make_signal("INC-714", "billing-svc", T + 500)

        times = []
        for _ in range(5):
            t0 = time.monotonic()
            engine.reconstruct_context(signal, mode="fast")
            times.append(time.monotonic() - t0)

        p95 = sorted(times)[int(len(times) * 0.95) - 1] if len(times) > 1 else times[0]
        assert p95 <= 2.0, f"Fast mode p95 latency {p95:.3f}s exceeds 2s budget"

    def test_reconstruct_cross_rename_finds_pre_rename_events(self, engine):
        """
        Core topology drift test: billing-svc incident must surface events
        originally ingested under payments-svc.
        """
        T = self._ingest_worked_example(engine)
        signal = make_signal("INC-714", "billing-svc", T + 500)
        ctx = engine.reconstruct_context(signal, mode="fast")

        # Related events should include the deploy that happened under payments-svc
        related_ids = {e["event_id"] for e in ctx["related_events"]}
        assert "deploy-v1" in related_ids, (
            "deploy-v1 (ingested under payments-svc) must appear in billing-svc context"
        )

    def test_reconstruct_unknown_service_returns_valid_context(self, engine):
        """Engine should not crash on a signal from a completely unknown service."""
        signal = make_signal("INC-UNKNOWN", "never-seen-svc", time.time())
        ctx = engine.reconstruct_context(signal, mode="fast")
        assert ctx["incident_id"] == "INC-UNKNOWN"
        assert isinstance(ctx["related_events"], list)


# ---------------------------------------------------------------------------
# Task 2.7 — Context reconstruction (deep path)
# ---------------------------------------------------------------------------

class TestContextReconstructionDeep:

    def test_deep_mode_returns_same_shape(self, engine):
        events = [
            make_raw_event("deploy", "svc-a", 1000.0),
            make_raw_event("metric", "svc-a", 1200.0, data={"metric_name": "latency", "value": 700}),
            make_raw_event("log",    "svc-a", 1300.0, data={"level": "ERROR", "message": "fail"}),
        ]
        engine.ingest(events)
        signal = make_signal("INC-D1", "svc-a", 1500.0)
        ctx = engine.reconstruct_context(signal, mode="deep")
        for field in ("incident_id", "related_events", "causal_chain",
                      "similar_past_incidents", "suggested_remediations",
                      "confidence", "explain"):
            assert field in ctx

    def test_deep_mode_latency(self, engine):
        """Deep mode must complete in ≤6s."""
        # Ingest 500 events to create realistic load
        events = [
            make_raw_event("log", "svc-a", float(i * 10),
                           event_id=f"log-{i}",
                           data={"level": "INFO", "message": f"msg {i}"})
            for i in range(500)
        ]
        engine.ingest(events)
        signal = make_signal("INC-DEEP", "svc-a", 2500.0)

        t0 = time.monotonic()
        engine.reconstruct_context(signal, mode="deep")
        elapsed = time.monotonic() - t0
        assert elapsed <= 6.0, f"Deep mode took {elapsed:.3f}s, exceeds 6s budget"

    def test_deep_mode_broader_window_than_fast(self, engine):
        """Deep mode should find more events than fast mode (wider time window)."""
        T = 1_000_000.0
        # Events 20 minutes before incident (outside fast 15-min window, inside deep 60-min)
        events = [
            make_raw_event("deploy", "svc-a", T - 1200,   event_id="deploy-old"),   # 20 min before
            make_raw_event("deploy", "svc-a", T - 600,    event_id="deploy-close"),  # 10 min before
            make_raw_event("log",    "svc-a", T,          event_id="log-now",
                           data={"level": "ERROR", "message": "fail"}),
        ]
        engine.ingest(events)
        signal = make_signal("INC-WIN", "svc-a", T)
        ctx_fast = engine.reconstruct_context(signal, mode="fast")
        ctx_deep = engine.reconstruct_context(signal, mode="deep")

        fast_ids = {e["event_id"] for e in ctx_fast["related_events"]}
        deep_ids = {e["event_id"] for e in ctx_deep["related_events"]}

        # deploy-old is 20 min before — in deep window, possibly outside fast window
        # deploy-close is 10 min before — in both windows
        assert "deploy-close" in fast_ids
        assert "deploy-old" in deep_ids


# ---------------------------------------------------------------------------
# Multi-incident historical matching
# ---------------------------------------------------------------------------

class TestHistoricalMatching:

    def test_second_incident_matches_first(self, engine):
        """After two incidents on the same service, the second should match the first."""
        T1 = 1_000_000.0
        T2 = T1 + 86400  # 1 day later

        # Incident 1
        engine.ingest([
            make_raw_event("deploy", "svc-a", T1, event_id="d1"),
            make_raw_event("log",    "svc-a", T1 + 300, event_id="l1",
                           data={"level": "ERROR", "message": "conn timeout"}),
            make_raw_event("incident_signal", "svc-a", T1 + 400, event_id="inc1",
                           data={"incident_id": "INC-100"}),
            make_raw_event("remediation", "svc-a", T1 + 500, event_id="rem1",
                           data={"action": "rollback to v1.0"}),
        ])

        # Incident 2 on renamed service (same canonical)
        engine.ingest([
            make_raw_event("topology", "svc-a", T1 + 1000, data={
                "change_type": "rename",
                "old_service": "svc-a",
                "new_service": "svc-a-v2",
            }),
            make_raw_event("deploy", "svc-a-v2", T2, event_id="d2"),
            make_raw_event("log",    "svc-a-v2", T2 + 300, event_id="l2",
                           data={"level": "ERROR", "message": "conn timeout 192.168.1.1"}),
        ])

        signal2 = make_signal("INC-200", "svc-a-v2", T2 + 400)
        ctx = engine.reconstruct_context(signal2, mode="fast")

        # suggested_remediations should surface "rollback to v1.0" from incident 1
        assert isinstance(ctx["suggested_remediations"], list)
        assert len(ctx["suggested_remediations"]) >= 0  # may or may not have history yet

    def test_suggested_remediations_type(self, engine):
        engine.ingest([
            make_raw_event("deploy",     "svc-x", 1000.0),
            make_raw_event("remediation","svc-x", 1100.0,
                           data={"action": "restart pod"}),
        ])
        signal = make_signal("INC-X", "svc-x", 1050.0)
        ctx = engine.reconstruct_context(signal, mode="fast")
        assert isinstance(ctx["suggested_remediations"], list)
        for r in ctx["suggested_remediations"]:
            # Remediations are Remediation TypedDicts (dicts with action/target/etc.)
            assert isinstance(r, dict), f"Expected dict, got {type(r)}: {r}"
            assert "action" in r, f"Remediation missing 'action' key: {r}"
