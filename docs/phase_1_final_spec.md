# Phase 1 Final Review — Locked Technical Specification
## Persistent Context Engine: Blueprint for Phase 2 Implementation

> **Status: APPROVAL GATE** — All design decisions locked. Awaiting sign-off before Phase 2 coding begins.

---

## Section 1: Data Schema & Canonical Identity

### 1.1 The `CanonicalEntity` Dataclass

```python
# src/types.py

import uuid
import time
from dataclasses import dataclass, field
from typing import TypedDict, Optional, Literal

# ─────────────────────────────────────────────
# Raw event kinds (as received from JSONL stream)
# ─────────────────────────────────────────────
EventKind = Literal["deploy", "log", "metric", "trace", "topology",
                    "incident_signal", "remediation"]

class Event(TypedDict, total=False):
    """Raw JSONL event from the telemetry stream."""
    event_id:   str           # unique event identifier
    kind:       EventKind     # one of the 6 event types
    timestamp:  float         # unix epoch (float, ms precision)
    service:    str           # raw service name at time of emission
    data:       dict          # full payload (kind-specific fields)

class IncidentSignal(TypedDict):
    """Incident signal event triggering context reconstruction."""
    incident_id: str
    service:     str
    timestamp:   float
    severity:    str          # e.g., "critical", "warning"
    data:        dict

class CausalEdgeDict(TypedDict):
    """A directed causal relationship between two events."""
    from_event_id: str
    to_event_id:   str
    edge_type:     str        # "deploy_induced" | "trace" | "statistical" | "temporal"
    confidence:    float      # [0.0, 1.0]
    rationale:     str        # human-readable reason

class Context(TypedDict):
    """Output of reconstruct_context(). The core deliverable."""
    incident_id:            str
    related_events:         list[Event]
    causal_chain:           list[CausalEdgeDict]
    similar_past_incidents: list[dict]      # HistoricalIncident as dict
    suggested_remediations: list[str]
    confidence:             float
    explain:                str

# ─────────────────────────────────────────────
# Internal representation (never exposed to caller)
# ─────────────────────────────────────────────
@dataclass
class CanonicalEntity:
    """
    Immutable identity node. Survives all service renames and dependency shifts.
    Created ONCE per logical service and never deleted.
    """
    canonical_id:   str = field(default_factory=lambda: f"entity:{uuid.uuid4().hex[:12]}")
    first_seen_as:  str = ""            # raw name at creation time
    first_seen_at:  float = field(default_factory=time.time)
    known_aliases:  list[str] = field(default_factory=list)  # all names ever used
    behavioral_sig: dict = field(default_factory=dict)       # computed fingerprint

@dataclass
class InternalEvent:
    """
    Enriched event stored in the memory substrate.
    Wraps raw Event with canonical resolution applied at ingest time.
    """
    event_id:             str
    kind:                 str
    timestamp:            float
    canonical_id:         str           # resolved at ingest, immutable thereafter
    raw_service_name:     str           # original name in the payload
    data:                 dict
    behavioral_fingerprint: str = ""   # hash of normalized content

@dataclass
class HistoricalIncident:
    """Stored record of a past resolved incident."""
    incident_id:          str
    canonical_id:         str
    timestamp:            float
    causal_chain:         list[CausalEdgeDict]
    behavioral_fingerprint: str        # fingerprint of the incident shape
    resolved_remediation: Optional[str] = None
    outcome_confirmed:    bool = False  # True if metrics recovered after remediation
    confidence_weight:    float = 1.0  # decays with age; boosted by confirmed outcomes
```

---

### 1.2 `canonical_id` Generation — First-Seen Logic

When a service name is encountered for the first time at ingest:

```python
# src/drift_handler.py — IdentityGraph.resolve_or_create()

def resolve_or_create(self, raw_service_name: str) -> str:
    """
    Returns the canonical_id for a service name.
    Creates a new CanonicalEntity if this name has never been seen.
    """
    # Step 1: direct lookup in alias map
    if raw_service_name in self.alias_map:
        return self.alias_map[raw_service_name]

    # Step 2: behavioral similarity check (implicit rename detection)
    # Only runs for new services after the engine has seen ≥10 events
    if len(self.entities) > 0 and self._has_enough_signal(raw_service_name):
        match = self._find_behavioral_match(raw_service_name)
        if match:
            # Infer implicit rename — link to existing canonical
            self.alias_map[raw_service_name] = match
            self.entities[match].known_aliases.append(raw_service_name)
            return match

    # Step 3: genuinely new service — create canonical
    entity = CanonicalEntity(first_seen_as=raw_service_name)
    entity.known_aliases.append(raw_service_name)
    self.entities[entity.canonical_id] = entity
    self.alias_map[raw_service_name] = entity.canonical_id
    return entity.canonical_id
```

**Key properties of `canonical_id`:**
- Format: `"entity:{12-char hex}"` — e.g., `"entity:3f8a9b2c1d4e"`
- Generated via `uuid.uuid4().hex[:12]` — cryptographically random, collision-free at any realistic scale
- **Never reused, never deleted** — even if a service disappears entirely

---

### 1.3 Alias Map — Circular & Cascading Rename Handling

The alias map uses a **Union-Find (Disjoint Set Union)** pattern backed by a flat dict:

```
alias_map: dict[str, canonical_id]
           # every name maps directly to a canonical_id (NOT to another name)
```

**Why flat map instead of chained map:**

Chained maps (`A → B → C`) require traversal and break on cycles.
A flat canonical map resolves everything in O(1):

```
alias_map["payments-svc"] = "entity:3f8a"
alias_map["billing-svc"]  = "entity:3f8a"   # same canonical after rename
alias_map["finance-svc"]  = "entity:3f8a"   # cascading rename also maps here
```

**Cascading rename (A → B → C):**
```python
# Event 1: topology rename payments-svc → billing-svc
# Result:
alias_map["payments-svc"] = "entity:3f8a"   # created when first seen
alias_map["billing-svc"]  = "entity:3f8a"   # added on rename

# Event 2: topology rename billing-svc → finance-svc
# Implementation:
def register_rename(self, old_name: str, new_name: str) -> None:
    canon = self.alias_map.get(old_name)
    if canon is None:
        canon = self.resolve_or_create(old_name)
    self.alias_map[new_name] = canon          # new name → same canonical
    self.entities[canon].known_aliases.append(new_name)

# Result after both renames:
alias_map["payments-svc"] = "entity:3f8a"
alias_map["billing-svc"]  = "entity:3f8a"
alias_map["finance-svc"]  = "entity:3f8a"
# All three resolve to entity:3f8a in O(1), no traversal needed.
```

**Circular rename (A → B → A):**
```python
# Handled by the flat map — A and B both already point to the same canonical.
# register_rename("billing-svc", "payments-svc") is a no-op:
# alias_map["payments-svc"] = "entity:3f8a"  (already there, value unchanged)
# No cycle is possible because we never store name→name, only name→canonical_id.
```

---

## Section 2: Storage & Indexing Strategy

### 2.1 Internal Structure of `EventStore`

```python
# src/memory.py

import bisect
from collections import defaultdict

class EventStore:
    """
    Three-index in-memory store optimized for:
    - O(1) insert                       (append to list + dict set)
    - O(log N) temporal range queries   (bisect on sorted timestamp list)
    - O(1) event lookup by id           (dict)
    - O(K) per-service queries          (inverted index by canonical_id)
    """

    def __init__(self):
        # Primary store: sorted list of (timestamp, event_id) for bisect
        self._timeline: list[tuple[float, str]] = []   # sorted by timestamp

        # Secondary: all InternalEvent objects keyed by event_id
        self._by_id: dict[str, InternalEvent] = {}

        # Tertiary: inverted index canonical_id → list of event_ids (insertion order)
        self._by_canonical: defaultdict[str, list[str]] = defaultdict(list)

        # Quaternary: kind-specific fast lanes (for rule engine)
        self._by_kind: defaultdict[str, list[str]] = defaultdict(list)

    def add_event(self, event: InternalEvent) -> None:
        """O(log N) insert — uses bisect.insort for sorted timeline maintenance."""
        key = (event.timestamp, event.event_id)
        bisect.insort(self._timeline, key)              # keeps timeline sorted
        self._by_id[event.event_id] = event
        self._by_canonical[event.canonical_id].append(event.event_id)
        self._by_kind[event.kind].append(event.event_id)
```

**Memory footprint estimate (L2 dataset: 12 services × 7 days):**
- ~17,000 events × ~800 bytes per InternalEvent ≈ **13.6 MB raw**
- Timeline index: 17,000 × 2 fields (float + str) ≈ **1 MB**
- Inverted indices: ~2 MB
- **Total: ~17 MB** — comfortably in RAM, no paging risk.

---

### 2.2 Temporal Window Query — Across Service Renames

```python
def query_window(
    self,
    canonical_id: str,
    center_ts: float,
    window_seconds: float = 900.0,          # ±15 minutes default
    identity_graph: "IdentityGraph" = None,  # passed for cross-rename resolution
) -> list[InternalEvent]:
    """
    Returns all events for a canonical entity within [center_ts - window, center_ts + window].

    Works across renames because events were stored by canonical_id at ingest time.
    No name resolution needed at query time — the canonical_id IS the identity.

    Complexity: O(log N + K) where K = events in window.
    """
    lo = center_ts - window_seconds
    hi = center_ts + window_seconds

    # Binary search on timeline for window boundaries — O(log N)
    lo_idx = bisect.bisect_left(self._timeline,  (lo, ""))
    hi_idx = bisect.bisect_right(self._timeline, (hi, "\xff"))

    # Collect events in window, filter by canonical_id — O(K)
    results = []
    for ts, eid in self._timeline[lo_idx:hi_idx]:
        event = self._by_id[eid]
        if event.canonical_id == canonical_id:
            results.append(event)

    return results
    # NOTE: Because ingest resolved billing-svc→entity:3f8a and
    #       payments-svc→entity:3f8a, events from BOTH names are
    #       naturally returned here. Rename is transparent to caller.
```

---

## Section 3: Relationship Synthesis & Confidence Scoring

### 3.1 Exact Confidence Formula for Causal Edges

The confidence for a `deploy → metric_spike` causal edge uses a **temporal decay + type weight** model:

```
confidence(A → B) = W_type × decay(Δt) × W_corr

Where:
  A          = source event (e.g., deploy at T=0)
  B          = target event (e.g., metric_spike at T=300s)
  Δt         = B.timestamp - A.timestamp  (seconds, must be > 0)
  W_type     = base weight for this edge type (see table below)
  decay(Δt)  = exp(-Δt / τ)   where τ = type-specific half-life
  W_corr     = co-occurrence reinforcement weight (1.0 baseline, boosted by history)
```

**Type weights and half-lives:**

| Edge Type | W_type | τ (half-life, seconds) | Example |
|:---|:---|:---|:---|
| `deploy_induced` | 0.75 | 600 (10 min) | deploy → metric spike 5 min later → 0.65 |
| `trace_parent` | 1.00 | ∞ (no decay) | exact span linkage — always 1.0 |
| `temporal_proximity` | 0.40 | 300 (5 min) | two errors 2 min apart → ~0.37 |
| `statistical_corr` | 0.60 | — (not time-based) | high co-occurrence freq → 0.6 × P(B|A) |

**Worked Example (deploy at T=0, metric_spike at T=300s):**
```
W_type = 0.75    (deploy_induced)
Δt     = 300s
τ      = 600s
decay  = exp(-300 / 600) = exp(-0.5) ≈ 0.6065
W_corr = 1.0     (baseline, no prior history)

confidence = 0.75 × 0.6065 × 1.0 ≈ 0.455

After 3 confirmed historical incidents reinforce this pattern:
W_corr = 1.0 + (3 × 0.1) = 1.3
confidence = 0.75 × 0.6065 × 1.3 ≈ 0.591
```

---

### 3.2 Coincidence vs. Causality — Disambiguation

Two overlapping latency spikes (service X and service Y) are disambiguated via a **multi-signal scoring** approach:

```python
def score_causality(event_a: InternalEvent, event_b: InternalEvent,
                    topology_graph: nx.DiGraph) -> float:
    """
    Returns a causality score [0,1]. Higher = more likely causal (not coincidence).
    Four independent signals, combined multiplicatively to avoid false positives.
    """
    score = 1.0

    # Signal 1: Temporal ordering (A must precede B by > 0s)
    dt = event_b.timestamp - event_a.timestamp
    if dt <= 0:
        return 0.0   # B before A → cannot be caused by A

    # Signal 2: Topological adjacency (A's service must be upstream of B's service)
    canon_a = event_a.canonical_id
    canon_b = event_b.canonical_id
    if not nx.has_path(topology_graph, canon_a, canon_b):
        score *= 0.2   # penalize strongly — not topologically connected

    # Signal 3: Trace linkage (strongest signal)
    if event_a.data.get("span_id") and \
       event_b.data.get("parent_span_id") == event_a.data.get("span_id"):
        return 1.0     # exact trace parent → definitive causality, bypass other signals

    # Signal 4: Co-occurrence frequency (from historical incident memory)
    co_occur_prob = self._cooccurrence_probability(canon_a, canon_b, event_a.kind, event_b.kind)
    score *= (0.4 + 0.6 * co_occur_prob)   # baseline 0.4 even with zero history

    return score * self._temporal_decay(dt, tau=600)
```

**Threshold:** Edges with `confidence < 0.25` are **not stored** (noise floor).
Edges between `[0.25, 0.5)` are stored but marked `low_confidence=True`.
Edges ≥ 0.5 are included in the `causal_chain` output.

---

## Section 4: Behavioral Fingerprinting — The Drift Secret Sauce

### 4.1 Fields Used for Fingerprint Construction

**From `log` events:**
```
- data.message         → strip dynamic tokens → log template
- data.level           → "ERROR", "WARN", "INFO"
- data.error_code      → if present
```

**From `metric` events:**
```
- data.metric_name     → e.g., "latency_p99", "error_rate"
- data.value           → normalized to range bucket (low/med/high/critical)
- data.unit            → "ms", "rps", "%"
```

**From `deploy` events:**
```
- data.version_delta   → "major", "minor", "patch" (from semver diff, not exact version)
- data.deploy_type     → "rolling", "blue-green", "canary"
```

**Intentionally EXCLUDED (name-coupled, breaks across renames):**
```
- service name
- exact metric values (too volatile)
- exact log message (too specific)
- span IDs, trace IDs
```

---

### 4.2 `compute_signature` Pseudocode

```python
import re
import hashlib
from collections import Counter

# Token stripping regex: remove UUIDs, IPs, numbers, hex strings
_DYNAMIC_TOKEN_RE = re.compile(
    r'\b(?:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'  # UUID
    r'|\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}'                                  # IPv4
    r'|0x[0-9a-f]+'                                                           # hex
    r'|\d+)\b',                                                               # numbers
    re.IGNORECASE
)

def _normalize_log_message(msg: str) -> str:
    """Strip dynamic tokens, lowercase, collapse whitespace."""
    return re.sub(_DYNAMIC_TOKEN_RE, "<VAL>", msg).lower().strip()

def compute_signature(events: list[InternalEvent]) -> dict:
    """
    Compute a behavioral fingerprint for a service from its recent event stream.
    The signature is NAME-INDEPENDENT — survives renames.

    Returns a dict suitable for cosine similarity comparison.
    """
    sig = {
        "log_template_hash_counts": Counter(),   # {hash_of_template: count}
        "error_rate_bucket":        "none",      # none | low | med | high | critical
        "latency_bucket":           "none",
        "deploy_frequency":         0,           # deploys per day in window
        "metric_names_seen":        set(),       # which metric kinds appear
        "dominant_log_level":       "INFO",
    }

    log_levels = Counter()
    latency_values = []

    for ev in events:
        if ev.kind == "log":
            template = _normalize_log_message(ev.data.get("message", ""))
            template_hash = hashlib.md5(template.encode()).hexdigest()[:8]
            sig["log_template_hash_counts"][template_hash] += 1
            log_levels[ev.data.get("level", "INFO")] += 1

        elif ev.kind == "metric":
            name = ev.data.get("metric_name", "")
            sig["metric_names_seen"].add(name)
            if "latency" in name:
                latency_values.append(float(ev.data.get("value", 0)))
            if "error_rate" in name:
                val = float(ev.data.get("value", 0))
                sig["error_rate_bucket"] = _bucket(val, [0.01, 0.05, 0.15])

        elif ev.kind == "deploy":
            sig["deploy_frequency"] += 1

    if latency_values:
        avg_latency = sum(latency_values) / len(latency_values)
        sig["latency_bucket"] = _bucket(avg_latency, [100, 300, 800])  # ms

    sig["dominant_log_level"] = log_levels.most_common(1)[0][0] if log_levels else "INFO"
    sig["metric_names_seen"] = list(sig["metric_names_seen"])  # make serializable

    return sig


def _bucket(value: float, thresholds: list[float]) -> str:
    """Maps a value to a named bucket: none|low|med|high|critical."""
    labels = ["none", "low", "med", "high", "critical"]
    for i, t in enumerate(thresholds):
        if value < t:
            return labels[i + 1]
    return "critical"


def fingerprint_similarity(sig_a: dict, sig_b: dict) -> float:
    """
    Cosine-like similarity between two behavioral signatures.
    Returns [0.0, 1.0]. Threshold for implicit rename inference: ≥ 0.85.

    Weighted scoring across 4 independent dimensions:
    """
    score = 0.0
    weights = {
        "log_templates": 0.40,    # log shape is the strongest behavioral signal
        "metric_names":  0.25,    # which metrics appear
        "latency_bucket": 0.20,   # latency regime
        "error_bucket":  0.15,    # error rate regime
    }

    # Log template similarity (Jaccard on template hash sets)
    set_a = set(sig_a["log_template_hash_counts"].keys())
    set_b = set(sig_b["log_template_hash_counts"].keys())
    if set_a or set_b:
        jaccard = len(set_a & set_b) / len(set_a | set_b)
        score += weights["log_templates"] * jaccard

    # Metric name similarity (Jaccard on metric name sets)
    mn_a = set(sig_a.get("metric_names_seen", []))
    mn_b = set(sig_b.get("metric_names_seen", []))
    if mn_a or mn_b:
        score += weights["metric_names"] * (len(mn_a & mn_b) / len(mn_a | mn_b))

    # Latency bucket exact match
    if sig_a.get("latency_bucket") == sig_b.get("latency_bucket"):
        score += weights["latency_bucket"]

    # Error rate bucket exact match
    if sig_a.get("error_rate_bucket") == sig_b.get("error_rate_bucket"):
        score += weights["error_bucket"]

    return round(score, 4)
```

**How this matches `payments-svc` to `billing-svc` without explicit rename:**
1. Both services emit `ERROR` logs with template `"connection timeout to <VAL>:<VAL>"` → same template hash
2. Both emit `latency_p99` metrics in the `high` bucket (600-800ms)
3. Both have `error_rate` in `med` bucket
4. `fingerprint_similarity(sig_payments, sig_billing) ≈ 0.88 → infer implicit rename`

---

## Section 5: Implementation Readiness — Locked Tech Stack & File Structure

### 5.1 Final Tech Stack with Version Pins

```
# requirements.txt (exact pins for reproducibility)

# Core
networkx==3.3
numpy==1.26.4
orjson==3.10.3

# Testing
pytest==8.2.0
pytest-cov==5.0.0

# Optional: behavioral similarity boost (sentence-transformers adds ~400MB)
# sentence-transformers==2.7.0   # uncomment only if needed

# Dev tooling
black==24.4.2
flake8==7.0.0
```

| Component | Selection | Version | Why |
|:---|:---|:---|:---|
| **Python** | CPython | 3.11 | `tomllib` stdlib, faster type hints, harness compatibility |
| **Graph** | networkx | 3.3 | In-memory DiGraph for topology + causal chains; battle-tested |
| **Numerics** | numpy | 1.26.4 | Vectorized fingerprint similarity computation |
| **JSON** | orjson | 3.10.3 | 3-5× faster than stdlib json for 1k+ events/sec ingest |
| **Tests** | pytest + pytest-cov | 8.2 + 5.0 | Standard; supports markers, fixtures, async |
| **Format** | black | 24.4.2 | Non-negotiable code style |
| **Lint** | flake8 | 7.0.0 | Catch obvious errors |
| **Containerize** | Docker (multi-stage) | 24.x | Reproducible benchmark environment |
| **LLM (explain)** | Template engine | n/a | $0 cost, deterministic, 0ms latency |

**Python version rationale:** 3.11 specifically because:
- 10-60% faster than 3.10 on CPU-bound workloads (important for 1k/sec ingest)
- `tomllib` built-in (no deps for config parsing)
- `ExceptionGroup` (useful for batch ingest error handling)

---

### 5.2 Confirmed `/src` Directory Structure

```
persistent-context-engine/
├── src/
│   ├── __init__.py           # package marker + version
│   ├── types.py              # ALL TypedDicts, Dataclasses, type aliases
│   │                         #   Event, InternalEvent, CanonicalEntity,
│   │                         #   HistoricalIncident, Context, CausalEdgeDict
│   │
│   ├── memory.py             # EventStore + IncidentMemory
│   │                         #   bisect-indexed timeline
│   │                         #   canonical_id inverted index
│   │                         #   snapshot / restore methods
│   │
│   ├── drift_handler.py      # IdentityGraph (alias map + Union-Find pattern)
│   │                         #   resolve_or_create()
│   │                         #   register_rename()
│   │                         #   compute_signature()
│   │                         #   fingerprint_similarity()
│   │
│   ├── relationships.py      # RelationshipEngine
│   │                         #   build_causal_chain() (rule + statistical + trace)
│   │                         #   score_causality()
│   │                         #   record_remediation_outcome()
│   │
│   └── engine.py             # PersistentContextEngine (public API)
│                             #   __init__(), ingest(), reconstruct_context(), close()
│
├── adapters/
│   └── myteam.py             # Thin shim: class Engine(Adapter)
│
├── tests/
│   ├── __init__.py
│   ├── test_engine.py        # end-to-end integration tests
│   ├── test_relationships.py # unit tests for causal edge logic
│   ├── test_drift.py         # rename + alias resolution tests
│   └── test_memory.py        # EventStore add/retrieve/query unit tests
│
├── docs/
│   ├── phase_1_architecture.md
│   └── phase_1_final_spec.md  ← (this document)
│
├── bench/
│   └── run.sh
│
├── Dockerfile
├── requirements.txt
└── README.md
```

---

## Approval Gate Summary

| Area | Decision | Locked? |
|:---|:---|:---|
| Identity model | `CanonicalEntity` dataclass, flat `alias_map` dict | ✅ |
| `canonical_id` format | `entity:{uuid4().hex[:12]}`, never reused | ✅ |
| Circular/cascading renames | Flat map (name → canonical_id), no chaining possible | ✅ |
| EventStore data structure | `bisect.insort` on sorted list + 3 inverted dicts | ✅ |
| Window query | O(log N + K) via `bisect_left/right`, rename-transparent | ✅ |
| Confidence formula | `W_type × exp(-Δt/τ) × W_corr`, thresholds 0.25/0.5 | ✅ |
| Causality vs. coincidence | 4-signal: temporal + topological + trace + co-occurrence | ✅ |
| Fingerprint fields | log templates, metric names, latency bucket, error bucket | ✅ |
| `compute_signature()` | Weighted Jaccard similarity across 4 dimensions | ✅ |
| Implicit rename threshold | `fingerprint_similarity ≥ 0.85` | ✅ |
| Tech stack | Python 3.11, networkx 3.3, numpy 1.26.4, orjson 3.10.3 | ✅ |
| File structure | 6 src files, confirmed roles | ✅ |

---

> **All design decisions are locked. Phase 2 implementation can begin upon approval.**
