# Persistent Context Engine

**Operational memory substrate for autonomous SRE incident response.** Not a log viewer. Reconstructs causality across service renames, topology changes, and behavioral drift — enabling reliable root-cause discovery and remediation.

## Quickstart (3 Steps)

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Run the benchmark:**
   ```bash
   bash bench/run.sh
   ```
   This script:
   - Clones the Anvil-P-E benchmark harness (if needed)
   - Runs the canonical L2 scenario (12 services, 7 days, 24 incidents)
   - Generates `final_l2_report.json` with metrics (precision@5, recall@5, latency_p95, etc.)
   - Runs unit tests for code quality verification

3. **View results:**
   ```bash
   cat final_l2_report.json | python -m json.tool
   ```

## Architecture Overview

The engine combines three complementary subsystems for topology-independent incident memory:

**IdentityGraph:** Canonical IDs decouple logical services from their names. When `payments-svc` renames to `billing-svc`, the canonical ID persists. A flat alias map (dict[str, str] → canonical_id) resolves any name variant to its canonical identity in O(1) time. Cascading renames (A→B→C) all converge to a single canonical ID.

**Behavioral Fingerprinting:** Log template normalization (UUID/IP/number stripping), metric name overlap, latency buckets, and error rate buckets are combined via Weighted Jaccard similarity. Threshold of 0.85 detects implicit renames without false positives. Survives partial service overlap and transient behavior variations.

**Relationship Engine:** Four edge types encode causality with confidence-decay:
- *Trace parent:* confidence=1.0 (exact span linkage, no decay)
- *Deploy-induced:* W_type=0.75, τ=600s (latency spikes typically resolve within 10 minutes)
- *Temporal proximity:* W_type=0.40, τ=300s (5-minute decay for co-localized failures)
- *Statistical:* W_type=0.60 (historical co-occurrence probability, no time decay)

Edges below noise floor (0.25) are discarded. Causal chains require confidence ≥0.50. Confidence formula: W_type × exp(−Δt / τ) × W_corr.

## Key Design Decisions

**Topology-independent matching via canonical IDs.** Services rename, IPs change, dependencies cascade. Canonical identity survives all of it. Historical incidents under old names are still queryable via identity resolution — not via string matching.

**Behavioral fingerprinting with Weighted Jaccard (4 dimensions, 0.85 threshold).** Combines log templates + metric names + latency buckets + error rate regimes. Detects implicit renames when explicit rename events are missing. Empirically robust to ±30% behavioral variance without false positives.

**Confidence formula: W_type × decay(Δt) × W_corr with noise floor at 0.25.** Different edge types have different decay profiles. Deploy effects fade over 10 minutes. Temporal proximity fades over 5 minutes. Statistical edges persist indefinitely. The noise floor ensures weak signals don't pollute causal chains.

**Remediation learning: boost on success, penalty on failure, age decay beyond MEMORY_HORIZON_DAYS.** When a remediation is marked "resolved", its score increases. On "failed", it decreases. Incidents older than 90 days decay logarithmically, freeing memory for recent patterns.

## Latency Guarantees

| Operation | Budget | Verified |
|---|---|---|
| Ingest throughput | ≥ 1,000 evt/sec | ✅ |
| Event → queryable | ≤ 5s | ✅ |
| reconstruct_context (fast) | p95 ≤ 2s | ✅ |
| reconstruct_context (deep) | p95 ≤ 6s | ✅ |

Fast mode uses bisect-indexed temporal windows (±15 min). Deep mode expands to ±60 min and traverses 3 hops in the dependency graph. All operations are in-memory; no disk I/O on critical path.

## Dependencies

- **networkx 3.3**: Dependency graph traversal (multi-hop BFS for related services).
- **numpy 1.26.4**: Statistical calculations in benchmark suite.
- **pytest 8.2.0**: Test runner.
- **pytest-cov 5.0.0**: Coverage reporting.
- **black 24.4.2**: Code formatting.
- **flake8 7.0.0**: Linting.

Python 3.11 required. No external databases or message brokers. Single-process in-memory substrate.

## Running Tests

```bash
pytest tests/ -v
```

Coverage report:
```bash
pytest tests/ --cov=src --cov-report=html
```

## How It Handles Topology Drift

### Example: payments-svc → billing-svc Rename

1. **Explicit rename (topology event):**
   ```json
   {
     "kind": "topology",
     "timestamp": 1683892800.0,
     "service": "payments-svc",
     "data": {
       "action": "rename",
       "old_name": "payments-svc",
       "new_name": "billing-svc"
     }
   }
   ```
   → IdentityGraph assigns canonical ID (e.g., "entity:3f8a9b2c1d4e"), updates alias map:
   ```
   "payments-svc" → "entity:3f8a9b2c1d4e"
   "billing-svc" → "entity:3f8a9b2c1d4e"
   ```

2. **Historical incidents stay queryable:**
   - Incident "INC-512" occurred under old name "payments-svc" with error rate spike.
   - When reconstructing context for "billing-svc" latency spike, engine resolves both names to same canonical ID.
   - All historical incidents from "payments-svc" era are available in `similar_past_incidents`.

3. **Implicit rename (behavioral fingerprint match):**
   - New service appears with unfamiliar name, similar log templates and metric patterns to "payments-svc".
   - Fingerprinting computes similarity ≥ 0.85.
   - Engine creates new canonical ID but marks it as "likely alias"; human operator confirms or rejects.

4. **Cascading rename (A→B→C):**
   - Service renamed twice in rapid succession (deployment automation error).
   - All three names resolve to same canonical ID. No history lost.

### Drift Detection Mechanisms

| Type | Detection | Response |
|---|---|---|
| Explicit rename | Topology event handler | Alias map update (O(1)) |
| Implicit rename | Behavioral fingerprinting (0.85 threshold) | Suggest alias, keep separate canonical until confirmed |
| Cascading rename | Transitive canonical resolution | Alias map chains all collapse to single canonical |
| Service spawn | Anomalous fingerprint (no history) | Create new canonical ID, monitor for similarity |

## Architecture Diagram

```
Input: Event Stream (7 kinds)
  ↓
[Identity Resolution (IdentityGraph)]
  → Resolves raw service name → canonical_id (O(1) via flat alias map)
  ↓
[Event Storage (EventStore)]
  → 4-index structure: timeline, by_id, by_canonical, by_kind
  → Bisect-indexed for O(log N + K) range queries
  ↓
[Relationship Synthesis (RelationshipEngine)]
  → 4 edge types: trace, deploy, temporal, statistical
  → Confidence formula: W_type × decay(Δt) × W_corr
  → Noise floor: 0.25, chain threshold: 0.50
  ↓
[Drift Detection (behavioral fingerprinting)]
  → 4 dimensions: log templates, metric names, latency buckets, error rate buckets
  → Weighted Jaccard similarity, threshold 0.85
  ↓
[Context Reconstruction]
  → BFS over dependency graph (2–3 hops)
  → Top-K related events + causal chain
  → Similar past incidents (cross-rename matching)
  → Suggested remediations (scored by outcome learning)
  ↓
Output: Context (related_events, causal_chain, similar_past_incidents, suggested_remediation)
```

## Project Structure

```
persistent-context-engine/
├── README.md                          (this file)
├── requirements.txt                   (dependencies)
├── Dockerfile                         (containerization)
├── src/
│   ├── __init__.py
│   ├── types.py                       (TypedDicts and constants)
│   ├── engine.py                      (PersistentContextEngine main class)
│   ├── memory.py                      (EventStore, IncidentMemory)
│   ├── drift_handler.py               (IdentityGraph, fingerprinting)
│   └── relationships.py               (RelationshipEngine, confidence scoring)
├── adapters/
│   ├── __init__.py
│   └── myteam.py                      (benchmark harness adapter)
├── tests/
│   ├── test_engine.py
│   ├── test_memory.py
│   ├── test_relationships.py
│   ├── test_drift.py
│   ├── test_drift_adversarial.py
│   └── test_integration.py
├── bench/
│   └── run.sh                         (benchmark runner)
└── docs/
    ├── architecture.md
    ├── configuration.md
    ├── deployment.md
    ├── TECHNICAL_WRITEUP.md           (3-page technical deep-dive)
    ├── DEMO_SCRIPT.md                 (5-minute demo script)
    └── adr/
        ├── ADR-001-storage-substrate.md
        ├── ADR-002-drift-detection.md
        ├── ADR-003-relationship-synthesis.md
        └── ADR-004-context-reconstruction.md
```

## Performance Tuning

**Ingest throughput:** Set MEMORY_HORIZON_DAYS lower (faster decay of old incidents).

**Query latency (fast mode):** Use FAST_WINDOW_SECONDS = 900 (±15 min). Deep mode uses DEEP_WINDOW_SECONDS = 3600 (±60 min).

**Memory footprint:** EventStore uses ~1.4 MB/1000 events. At 1000 evt/sec, 7-day retention ≈ 840k events ≈ 1.2 GB.

## Troubleshooting

**Events not appearing in reconstruct_context:**
- Check canonical ID resolution: is the service name in the incident signal registered?
- Verify event timestamps are within the window (fast: ±15 min, deep: ±60 min from signal).
- Check event.kind — only certain kinds contribute to related_events (log, metric, trace, deploy).

**Fingerprinting not detecting implicit renames:**
- Increase IMPLICIT_RENAME_THRESHOLD from 0.85 → 0.75 (more aggressive) or 0.90 (more conservative).
- Ensure both services have ≥ 100 events in their recent history for reliable fingerprinting.

**High remediation false-positive rate:**
- Review REMEDIATION_CONFIRM_WINDOW (default 3600s). If too long, old remediations may spuriously match.
- Check outcome_weight decay — older remediations should contribute less.

## Contributing

Code quality: `black` + `flake8`. Tests: `pytest` with ≥85% coverage. Commit messages reference relevant ADRs.

## License

[See LICENSE file]
