# Phase 1: Architecture Design & System Specification
## Persistent Context Engine — Operational Memory Substrate

---

## 1.1 Constraints Document

### Non-Negotiable Requirements

**Input:**
- JSONL telemetry stream with 6 event kinds: `deploy`, `log`, `metric`, `trace`, `topology`, `incident_signal`, `remediation`
- Events may arrive out-of-order (tolerate up to 5s jitter)
- Services may be renamed at any point via `topology` events

**Output:**
- `Context` TypedDict with: `related_events`, `causal_chain`, `similar_past_incidents`, `suggested_remediations`, `confidence`, `explain`

**Hard Latency Budgets:**
- Ingest throughput: ≥ 1,000 events/sec
- Ingestion lag (event → queryable): ≤ 5s
- `reconstruct_context` p95 ≤ 2s (fast mode)
- `reconstruct_context` p95 ≤ 6s (deep mode)

**Topology Drift:**
- Must match incidents across service renames (`payments-svc` → `billing-svc`)
- Must preserve causal history through dependency shifts

### Soft Constraints & Design Trade-offs

| Trade-off | Decision | Rationale |
|:---|:---|:---|
| In-memory vs. persistent DB | In-memory with snapshot | Guarantees 2s latency; bounded dataset (12 svcs × 7 days) fits in RAM |
| Full traversal vs. indexed retrieval | Pre-computed temporal index + lazy graph | Index for fast path, full graph for deep path |
| LLM for `explain` vs. template | Template-first, optional LLM | Guarantees latency and reproducibility |
| Precision vs. recall | Recall-first for similar_incidents | Better to surface more incidents and rank than miss them |

---

## 1.2 Architecture Decision Memo

**Chosen Paradigm: Hybrid — Temporal Event Log + Canonical Identity Graph + Behavioral Fingerprint Store**

### Trade-off Analysis

| Architecture | Topology Drift | Ingest Speed | Query Speed | Implementation Complexity |
|:---|:---|:---|:---|:---|
| Graph DB (Neo4j) | Medium (aliases as nodes) | Low (I/O overhead) | Medium | High |
| Temporal Log only | None (name-coupled) | **High** | **High** | Low |
| Vector/Embedding only | Low (name drift corrupts) | Medium | Medium | Medium |
| Bayesian/HMM | None natively | Medium | Low | Very High |
| **Hybrid (chosen)** | **High (canonical IDs)** | **High** | **High** | Medium |

**Why Hybrid wins:**

1. **Topology drift** is solved by decoupling identity from topology. Every service gets a `canonical_id` assigned on first seen. Renames update an alias map — the canonical ID never changes.
2. **Throughput** is solved by an append-only event list with O(1) insertion and O(log N) temporal lookup via `bisect`.
3. **Latency** is solved by pre-indexing: (a) temporal buckets for fast windowed retrieval, (b) canonical-ID→events index for identity-resolved queries.

**Worked Example (deploy → latency → error → rollback):**
- `deploy` event appended at T=0 under canonical_id=C1 (payments-svc)
- `metric_spike` at T=300s → temporal proximity rule fires → weak causal edge to deploy
- `error_log` at T=310s → trace propagation matches span → strong causal edge
- Rename: payments-svc → billing-svc; alias_map updated, C1 unchanged
- `incident_signal` for billing-svc at T=700s → resolves to C1 → finds all prior events

---

## 1.3 Core Data Structures

```python
# types.py

# Canonical entity — survives renames
CanonicalID = str  # e.g., "entity:uuid4"

@dataclass
class InternalEvent:
    event_id: str
    kind: str                        # deploy|log|metric|trace|topology|incident_signal|remediation
    timestamp: float                 # unix epoch, float for sub-second
    canonical_id: CanonicalID        # resolved at ingest time
    raw_service_name: str            # original name at ingest
    data: dict                       # full raw payload
    behavioral_fingerprint: str      # hash of stripped log template or metric shape

@dataclass
class CausalEdge:
    source_id: str                   # event_id
    target_id: str                   # event_id
    edge_type: str                   # 'temporal', 'trace', 'rule_based', 'probabilistic'
    confidence: float

@dataclass
class HistoricalIncident:
    incident_id: str
    canonical_id: CanonicalID
    timestamp: float
    causal_chain: list[CausalEdge]
    behavioral_fingerprint: str      # fingerprint of the incident shape
    remediation: str | None

# Memory Substrate
class EventStore:
    events_by_time: list[InternalEvent]     # sorted; bisect for O(log N) range queries
    events_by_id: dict[str, InternalEvent]
    events_by_canonical: dict[CanonicalID, list[InternalEvent]]  # fast per-service queries

class IdentityGraph:
    alias_map: dict[str, CanonicalID]        # "billing-svc" -> "entity:abc123"
    canonical_names: dict[CanonicalID, str]  # canonical_id -> latest known name
    behavioral_signatures: dict[CanonicalID, dict]  # for implicit drift detection

class IncidentMemory:
    incidents_by_canonical: dict[CanonicalID, list[HistoricalIncident]]
    incidents_by_fingerprint: dict[str, list[HistoricalIncident]]
```

**Query Plan for `reconstruct_context(signal, mode)`:**
1. `alias_map.get(signal.service)` → `canonical_id`
2. `bisect` temporal window ± 15m on `events_by_time`
3. Filter window by `canonical_id` (and dependencies via topology graph)
4. Run `RelationshipEngine.build_chain()` over filtered events
5. `IncidentMemory.query(canonical_id)` → rank by fingerprint similarity
6. Extract `suggested_remediations` from top matches
7. Render `explain` narrative

---

## 1.4 Relationship Synthesis Algorithm

### Rule-Based Causal Edges
```
if event_A.kind == "deploy" and event_B.kind in ["metric", "log"]:
    if abs(event_B.timestamp - event_A.timestamp) < DEPLOY_WINDOW (15 min):
        if same_canonical_id(event_A, event_B) or is_downstream(event_B, event_A):
            create_edge(A → B, type="deploy_induced", confidence=0.7)

if trace_event.parent_span_id == other_event.span_id:
    create_edge(other → trace_event, type="trace", confidence=0.95)
```

### Statistical Edges (Co-occurrence)
- Maintain rolling 24h co-occurrence matrix per canonical_id pair
- If P(metric_spike_B | deploy_A) > 0.6 → create statistical edge (confidence = P)

### Behavioral Edges
- Log fingerprint = strip dynamic tokens (IPs, UUIDs, numbers) from log templates
- Hash normalized template → `behavioral_fingerprint`
- Incidents with identical fingerprints are **behaviorally equivalent** regardless of service name

### Continuous Learning
```
if remediation.outcome == "resolved":
    if metrics recover within 10 min:
        incident_memory.reinforce(canonical_id, incident_fingerprint, remediation.action)
        # Increases confidence weight for this remediation strategy
```

---

## 1.5 Topology Drift Handling Strategy

### Step 1: Explicit Rename Detection
```
on event(kind="topology", data.change="rename"):
    old_name = data.old_service
    new_name = data.new_service
    canon = alias_map.get(old_name) or create_canonical(old_name)
    alias_map[new_name] = canon
    alias_map[old_name] = canon  # both resolve to same canonical
```

### Step 2: Behavioral Fingerprinting (Implicit Drift)
```
# For new services with no explicit rename link:
new_service_sig = compute_signature(events_for_new_service)
for canonical_id, sig in behavioral_signatures.items():
    if cosine_similarity(new_service_sig, sig) > 0.90:
        alias_map[new_service] = canonical_id  # infer rename
```
**Signature components:** (log volume ratio, avg metric level, dependency degree, deploy frequency)

### Step 3: Cross-Drift Incident Matching
- Month 1: `payments-svc` incident stored under `canonical=C1`
- Later: topology event maps `billing-svc → C1`
- Month 2: `billing-svc` incident → resolves to `C1` → returns Month 1 incident as `similar_past_incident`

### Decay/Forgetting
- Incidents older than `MEMORY_HORIZON` (default 90 days) have confidence linearly decayed by 50%
- They are retained but ranked lower — never forgotten, just weighted less

---

## 1.6 Worked Example Trace (INC-714)

| Step | Event | System Action | Internal State |
|:---|:---|:---|:---|
| 1 | `deploy(payments-svc, v1.0, T=0)` | Assign canonical `C1`, store | `alias_map: {payments-svc→C1}` |
| 2 | `log(payments-svc, ERROR, T=305s)` | Resolve to C1, fingerprint log | Edge candidate vs deploy |
| 3 | `metric(payments-svc, latency_p99=850ms, T=310s)` | Resolve to C1, store | Rule: deploy→metric within 15m ✓ |
| 4 | `trace(payments-svc, span, T=315s)` | Trace span linked to error log | Causal edge: log→trace (confidence 0.95) |
| 5 | `topology(rename: payments-svc→billing-svc)` | Update alias map | `alias_map: {payments-svc→C1, billing-svc→C1}` |
| 6 | `incident_signal(billing-svc, INC-714, T=400s)` | Resolve billing-svc→C1 | Window fetch: T=385s to T=415s |
| 7 | `reconstruct_context(INC-714)` | Build causal chain | deploy(T=0)→metric(T=310)→log→trace |
| 8 | Similarity query | Fetch past incidents for C1 | Match payments-svc incident (same C1) |
| 9 | Remediation lookup | Find successful rollback for C1 | suggest: `rollback billing-svc to v2.13.4` |

**Output Context:**
```python
Context(
    related_events=[deploy_ev, log_ev, metric_ev, trace_ev],
    causal_chain=[
        {"from": deploy_ev, "to": metric_ev, "confidence": 0.7},
        {"from": metric_ev, "to": log_ev,    "confidence": 0.8},
    ],
    similar_past_incidents=[payments_outage_month1],  # matched via C1
    suggested_remediations=["rollback to v2.13.4"],
    confidence=0.78,
    explain="Deploy of billing-svc at T=0 caused latency spike (p99=850ms) 310s later,
             followed by cascading errors. Behaviorally matches payments-svc outage from
             [DATE]. Recommended remediation: rollback (historical success rate: 100%)."
)
```

---

## 1.7 Technology Stack

| Component | Decision | Version | Rationale |
|:---|:---|:---|:---|
| **Runtime** | Python | 3.11+ | Required by harness; asyncio for ingest pipeline |
| **Storage** | Custom In-Memory | n/a | Guarantees latency; bounded dataset |
| **Graph Logic** | `networkx` | 3.3 | Fast in-memory DAG for causal chains |
| **Numerical** | `numpy` | 1.26 | Behavioral fingerprint similarity |
| **Embeddings** | `sentence-transformers` | 2.7 (optional) | Fallback for implicit drift detection |
| **Testing** | `pytest` + `pytest-cov` | 8.x | Standard, clean integration |
| **Reproducibility** | Docker (multi-stage) | 24.x | Ubiquitous; guarantees benchmark reproducibility |
| **Serialization** | `orjson` | 3.9 | 3-5x faster than stdlib json for high-throughput ingest |
| **LLM (explain)** | Template engine (default) | n/a | Zero latency, zero cost; optional OpenAI fallback |

**Cost Estimate (if OpenAI enabled):**
- L2 benchmark: ~30 context reconstructions × ~500 tokens = 15k tokens = ~$0.02 (gpt-4o-mini)
- Default: $0 (template engine)

---

*Phase 1 Complete. Awaiting approval to proceed to Phase 2: Implementation.*
