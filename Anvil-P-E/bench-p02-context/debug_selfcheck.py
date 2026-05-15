"""
debug_selfcheck.py - Plumbing & Identity Debug Flow
Run from: persistent-context-engine/  via  python debug_selfcheck.py
"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

print("=" * 60)
print("STEP 1 -- Import sanity check")
print("=" * 60)
try:
    from src.engine import PersistentContextEngine
    from src.types import Event, IncidentSignal
    from adapters.myteam import Engine
    print("[OK] All imports succeeded")
except ImportError as e:
    print(f"[FAIL] Import error: {e}")
    sys.exit(1)

# -------------------------------------------------------
# STEP 2 -- Ingestion integrity
# -------------------------------------------------------
print()
print("=" * 60)
print("STEP 2 -- Ingestion integrity")
print("=" * 60)

T = 1_700_000_000.0   # realistic unix timestamp

raw_events = [
    {"event_id": "deploy-v1", "kind": "deploy",  "service": "payments-svc",
     "timestamp": T,       "data": {"version": "v2.1", "deploy_type": "rolling"}},
    {"event_id": "log-err1", "kind": "log",    "service": "payments-svc",
     "timestamp": T + 310, "data": {"level": "ERROR", "message": "connection timeout to db"}},
    {"event_id": "metric-1", "kind": "metric", "service": "payments-svc",
     "timestamp": T + 320, "data": {"metric_name": "latency_p99", "value": 850}},
    {"event_id": "topo-rename", "kind": "topology", "service": "payments-svc",
     "timestamp": T + 400, "data": {
         "change_type": "rename",
         "old_service": "payments-svc",
         "new_service": "billing-svc",
     }},
    {"event_id": "log-err2", "kind": "log",    "service": "billing-svc",
     "timestamp": T + 500, "data": {"level": "ERROR", "message": "payment gateway timeout"}},
    {"event_id": "rem-1",    "kind": "remediation", "service": "billing-svc",
     "timestamp": T + 600, "data": {"action": "rollback to v2.0", "outcome": "resolved"}},
]

engine = PersistentContextEngine()
engine.ingest(raw_events)

print(f"[CHECK] engine.event_count = {engine.event_count}")
print(f"[CHECK] engine.unique_services = {engine.unique_services}")

if engine.event_count == 0:
    print("[FAIL] EventStore is EMPTY after ingest -- data never reached memory!")
else:
    print(f"[OK] EventStore has {engine.event_count} events")

# -------------------------------------------------------
# STEP 3 -- Identity mapping
# -------------------------------------------------------
print()
print("=" * 60)
print("STEP 3 -- Identity (IdentityGraph) mapping")
print("=" * 60)

ig = engine._identity
for name in ["payments-svc", "billing-svc"]:
    cid = ig.resolve(name)
    print(f"  '{name}'  ->  canonical_id = {cid}")

canon_pay  = ig.resolve("payments-svc")
canon_bill = ig.resolve("billing-svc")

if canon_pay is None:
    print("[FAIL] 'payments-svc' not in alias_map!")
if canon_bill is None:
    print("[FAIL] 'billing-svc' not in alias_map -- reconstruct_context will find 0 events!")
elif canon_pay == canon_bill:
    print("[OK] Both names share the same canonical_id -- rename is transparent")
else:
    print("[FAIL] payments-svc and billing-svc have DIFFERENT canonical_ids -- rename broken!")

# -------------------------------------------------------
# STEP 4 -- Window query
# -------------------------------------------------------
print()
print("=" * 60)
print("STEP 4 -- EventStore window query")
print("=" * 60)

if canon_bill:
    from src.types import FAST_WINDOW_SECONDS
    window = engine._store.query_window(
        canonical_id=canon_bill,
        center_ts=T + 500,
        window_seconds=FAST_WINDOW_SECONDS,
    )
    print(f"[CHECK] query_window(billing-svc, center={T+500}, +-{FAST_WINDOW_SECONDS}s) -> {len(window)} events")
    for ev in window:
        print(f"         {ev.event_id:20s}  kind={ev.kind:12s}  ts={ev.timestamp}  svc={ev.raw_service_name}")
    if len(window) == 0:
        print("[FAIL] Window returned 0 events -- timestamp mismatch or canonical mismatch!")
    else:
        print("[OK] Window returned events correctly")

# -------------------------------------------------------
# STEP 5 -- Full reconstruct_context
# -------------------------------------------------------
print()
print("=" * 60)
print("STEP 5 -- reconstruct_context (fast mode)")
print("=" * 60)

signal = {
    "incident_id": "INC-DEBUG-1",
    "service": "billing-svc",
    "timestamp": T + 500,
    "severity": "critical",
    "data": {},
}

ctx = engine.reconstruct_context(signal, mode="fast")

print(f"\n[RESULT] incident_id           = {ctx['incident_id']}")
print(f"[RESULT] related_events count  = {len(ctx['related_events'])}")
print(f"[RESULT] causal_chain count    = {len(ctx['causal_chain'])}")
print(f"[RESULT] similar_past count    = {len(ctx['similar_past_incidents'])}")
print(f"[RESULT] suggested_remediations= {ctx['suggested_remediations']}")
print(f"[RESULT] confidence            = {ctx['confidence']}")

if len(ctx['related_events']) == 0:
    print("\n[FAIL] related_events is EMPTY -- harness will score 0 Precision/Recall")
else:
    print(f"\n[OK] related_events has {len(ctx['related_events'])} events")
    ids = [e['event_id'] for e in ctx['related_events']]
    print(f"     event_ids: {ids}")
    if "deploy-v1" in ids:
        print("[OK] Pre-rename event 'deploy-v1' is present -- cross-rename works!")
    else:
        print("[WARN] Pre-rename event 'deploy-v1' MISSING -- cross-rename broken!")

# -------------------------------------------------------
# STEP 6 -- Check CausalEdgeDict key names vs harness expectation
# -------------------------------------------------------
print()
print("=" * 60)
print("STEP 6 -- CausalEdgeDict key-name audit")
print("=" * 60)
if ctx['causal_chain']:
    edge = ctx['causal_chain'][0]
    print(f"  Edge keys present: {list(edge.keys())}")
    for expected_key in ('from_event_id', 'to_event_id', 'edge_type', 'confidence', 'rationale'):
        if expected_key in edge:
            print(f"  [OK]  '{expected_key}' present")
        else:
            print(f"  [FAIL] '{expected_key}' MISSING from CausalEdgeDict -- harness scoring will break!")
else:
    print("  No causal edges produced -- check relationship thresholds and event window")

# -------------------------------------------------------
# STEP 7 -- Adapter (myteam.py) sanity check
# -------------------------------------------------------
print()
print("=" * 60)
print("STEP 7 -- Adapter (adapters/myteam.py) smoke test")
print("=" * 60)

adapter = Engine()
adapter.ingest(raw_events)
ctx2 = adapter.reconstruct_context(signal, mode="fast")
print(f"[CHECK] Adapter related_events: {len(ctx2['related_events'])}")
print(f"[CHECK] Adapter causal_chain  : {len(ctx2['causal_chain'])}")

if len(ctx2['related_events']) == 0:
    print("[FAIL] Adapter returns empty results -- harness score = 0.000")
else:
    print("[OK] Adapter returns populated context")

adapter.close()
engine.close()

print()
print("=" * 60)
print("DEBUG SELFCHECK COMPLETE")
print("=" * 60)
