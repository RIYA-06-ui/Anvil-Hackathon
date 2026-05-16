import sys
import json

# Add the persistent-context-engine directory to the Python path
sys.path.append("c:\\Users\\RIYA\\OneDrive\\Desktop\\Asccent_Anvil\\persistent-context-engine")

from adapters.myteam import Engine

e = Engine()

print('\n[1] Ingesting events: Deploying payments-svc, triggering latency spike & errors...')
e.ingest([
    {"ts": "2026-05-10T14:21:30Z", "kind": "deploy", "service": "payments-svc", "version": "v2.14.0", "actor": "ci"},
    {"ts": "2026-05-10T14:22:01Z", "kind": "log", "service": "checkout-api", "level": "error", "msg": "timeout calling payments-svc", "trace_id": "abc123"},
    {"ts": "2026-05-10T14:22:01Z", "kind": "metric", "service": "payments-svc", "name": "latency_p99_ms", "value": 4820},
    {"ts": "2026-05-10T14:22:08Z", "kind": "trace", "trace_id": "abc123", "spans": [{"svc": "checkout-api", "dur_ms": 5012}, {"svc": "payments-svc", "dur_ms": 4980}]},
    {"ts": "2026-05-10T14:30:00Z", "kind": "topology", "change": "rename", "from": "payments-svc", "to": "billing-svc"}
])

print('\n[2] Renaming payments-svc -> billing-svc...')

print('\n[3] Reconstructing context for INC-714 (checkout-api timeout)...')
signal = {"ts": "2026-05-10T14:32:11Z", "incident_id": "INC-714", "trigger": "alert:checkout-api/error-rate>5%"}
ctx = e.reconstruct_context(signal, mode="fast")

print('\n[4] Output Context:')
print(json.dumps(ctx, indent=2, default=str))
