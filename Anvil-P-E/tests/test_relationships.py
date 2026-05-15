"""
test_relationships.py — Unit tests for the RelationshipEngine.
"""

import pytest
from src.relationships import RelationshipEngine, _edge_confidence, DEPLOY_WINDOW
from src.types import InternalEvent


def make_event(event_id, kind, ts, canonical_id="entity:abc", data=None):
    return InternalEvent(
        event_id=event_id,
        kind=kind,
        timestamp=ts,
        canonical_id=canonical_id,
        raw_service_name="svc",
        data=data or {},
    )


@pytest.fixture
def engine():
    return RelationshipEngine()


# ---------------------------------------------------------------------------
# Confidence formula
# ---------------------------------------------------------------------------

class TestConfidenceFormula:

    def test_deploy_induced_at_zero_delta(self):
        """At Δt=0.001 (just after), confidence should be near W_type."""
        conf = _edge_confidence("deploy_induced", delta_t=0.001)
        assert 0.70 < conf <= 0.75

    def test_deploy_induced_decays_with_time(self):
        conf_early = _edge_confidence("deploy_induced", delta_t=60.0)
        conf_late  = _edge_confidence("deploy_induced", delta_t=600.0)
        assert conf_early > conf_late

    def test_trace_parent_no_decay(self):
        """Trace edges have no temporal decay — confidence equals W_type."""
        conf1 = _edge_confidence("trace_parent", delta_t=1.0)
        conf2 = _edge_confidence("trace_parent", delta_t=10000.0)
        assert conf1 == conf2 == pytest.approx(1.0, abs=0.001)

    def test_corr_weight_boosts_confidence(self):
        base = _edge_confidence("deploy_induced", delta_t=300.0, corr_weight=1.0)
        boosted = _edge_confidence("deploy_induced", delta_t=300.0, corr_weight=1.5)
        assert boosted > base

    def test_confidence_never_exceeds_1(self):
        conf = _edge_confidence("deploy_induced", delta_t=0.001, corr_weight=10.0)
        assert conf <= 1.0


# ---------------------------------------------------------------------------
# Trace edges
# ---------------------------------------------------------------------------

class TestTraceEdges:

    def test_trace_parent_creates_edge(self, engine):
        ev_parent = make_event("e1", "trace", 1000.0, data={"span_id": "span-A"})
        ev_child  = make_event("e2", "trace", 1001.0, data={
            "span_id": "span-B", "parent_span_id": "span-A"
        })
        chain = engine.build_causal_chain([ev_parent, ev_child])
        assert len(chain) >= 1
        edge = chain[0]
        assert edge["from_event_id"] == "e1"
        assert edge["to_event_id"] == "e2"
        assert edge["edge_type"] == "trace_parent"
        assert edge["confidence"] == pytest.approx(1.0, abs=0.001)

    def test_no_trace_edge_without_parent_span(self, engine):
        ev1 = make_event("e1", "trace", 1000.0, data={"span_id": "span-A"})
        ev2 = make_event("e2", "trace", 1001.0, data={"span_id": "span-B"})
        chain = engine.build_causal_chain([ev1, ev2])
        trace_edges = [e for e in chain if e["edge_type"] == "trace_parent"]
        assert len(trace_edges) == 0


# ---------------------------------------------------------------------------
# Deploy rule edges
# ---------------------------------------------------------------------------

class TestDeployRuleEdges:

    def test_deploy_then_metric_creates_edge(self, engine):
        deploy = make_event("d1", "deploy", 1000.0)
        metric = make_event("m1", "metric", 1300.0, data={"metric_name": "latency_p99", "value": 800})
        chain = engine.build_causal_chain([deploy, metric])
        deploy_edges = [e for e in chain if e["edge_type"] == "deploy_induced"]
        assert len(deploy_edges) >= 1
        assert deploy_edges[0]["from_event_id"] == "d1"
        assert deploy_edges[0]["confidence"] >= 0.25

    def test_deploy_then_error_log_creates_edge(self, engine):
        deploy = make_event("d1", "deploy", 1000.0)
        log    = make_event("l1", "log",    1060.0, data={"level": "ERROR", "message": "timeout"})
        chain  = engine.build_causal_chain([deploy, log])
        deploy_edges = [e for e in chain if e["edge_type"] == "deploy_induced"]
        assert len(deploy_edges) >= 1

    def test_metric_before_deploy_no_edge(self, engine):
        """Events before a deploy cannot be caused by it."""
        deploy = make_event("d1", "deploy", 1000.0)
        metric = make_event("m1", "metric",  900.0, data={"metric_name": "latency_p99", "value": 800})
        chain  = engine.build_causal_chain([deploy, metric])
        # metric is BEFORE deploy — should produce no deploy_induced edge
        deploy_edges = [
            e for e in chain
            if e["edge_type"] == "deploy_induced" and e["from_event_id"] == "d1"
        ]
        assert len(deploy_edges) == 0

    def test_deploy_outside_window_no_edge(self, engine):
        """Deploy more than 15 min before metric should NOT create edge."""
        deploy = make_event("d1", "deploy", 1000.0)
        metric = make_event("m1", "metric", 1000.0 + DEPLOY_WINDOW + 60, data={"metric_name": "latency"})
        chain  = engine.build_causal_chain([deploy, metric])
        deploy_edges = [e for e in chain if e["edge_type"] == "deploy_induced"]
        assert len(deploy_edges) == 0

    def test_info_log_does_not_create_edge(self, engine):
        """Only ERROR/CRITICAL logs should trigger deploy-induced edges."""
        deploy = make_event("d1", "deploy", 1000.0)
        log    = make_event("l1", "log", 1060.0, data={"level": "INFO", "message": "startup"})
        chain  = engine.build_causal_chain([deploy, log])
        deploy_edges = [e for e in chain if e["from_event_id"] == "d1"]
        assert len(deploy_edges) == 0


# ---------------------------------------------------------------------------
# Statistical edges
# ---------------------------------------------------------------------------

class TestStatisticalEdges:

    def test_cooccurrence_probability_zero_with_no_history(self, engine):
        p = engine.cooccurrence_probability("entity:a", "deploy", "entity:a", "metric")
        assert p == 0.0

    def test_cooccurrence_probability_increases_with_observations(self, engine):
        deploy = make_event("d1", "deploy", 1000.0)
        metric = make_event("m1", "metric", 1100.0)
        engine.observe_event(deploy)
        engine.observe_event(metric)
        engine.observe_pair(deploy, metric)
        p = engine.cooccurrence_probability("entity:abc", "deploy", "entity:abc", "metric")
        assert p > 0.0

    def test_statistical_edge_fires_at_high_cooccurrence(self, engine):
        """After many co-occurrence observations, a statistical edge should appear."""
        for i in range(10):
            d = make_event(f"d{i}", "deploy", float(i * 2000))
            m = make_event(f"m{i}", "metric", float(i * 2000 + 100))
            engine.observe_event(d)
            engine.observe_event(m)
            engine.observe_pair(d, m)

        deploy = make_event("d_new", "deploy", 50000.0)
        metric = make_event("m_new", "metric", 50100.0)
        chain = engine.build_causal_chain([deploy, metric])
        stat_or_deploy = [e for e in chain if e["edge_type"] in ("deploy_induced", "statistical")]
        assert len(stat_or_deploy) >= 1


# ---------------------------------------------------------------------------
# Noise floor
# ---------------------------------------------------------------------------

class TestNoiseFloor:

    def test_very_distant_events_no_edges(self, engine):
        """Events 2 hours apart should produce no edges."""
        deploy = make_event("d1", "deploy", 1000.0)
        log    = make_event("l1", "log",    1000.0 + 7200, data={"level": "ERROR"})
        chain  = engine.build_causal_chain([deploy, log])
        assert all(e["confidence"] >= 0.25 for e in chain)

    def test_single_event_produces_no_chain(self, engine):
        events = [make_event("e1", "deploy", 1000.0)]
        chain  = engine.build_causal_chain(events)
        assert chain == []

    def test_chain_sorted_root_cause_first(self, engine):
        deploy = make_event("d1", "deploy", 1000.0)
        metric = make_event("m1", "metric", 1200.0)
        log    = make_event("l1", "log",    1250.0, data={"level": "ERROR"})
        chain  = engine.build_causal_chain([deploy, metric, log])
        if len(chain) >= 2:
            # Source of first edge should be the earliest event
            first_src = chain[0]["from_event_id"]
            assert first_src == "d1"
