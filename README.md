# Persistent Context Engine — Anvil Hackathon (Problem 02)

A high-performance operational memory substrate for autonomous SRE that solves 
the "context amnesia" problem during complex, multi-service incidents. Uses 
**Topology-Independent Behavioral Matching** to identify incident patterns even 
when services are renamed, dependencies shift, or infrastructure drifts.

---

## Quickstart

### 1. Clone & Install
```bash
git clone https://github.com/RIYA-06-ui/Anvil-Hackathon
cd Anvil-Hackathon/persistent-context-engine
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Run Self-Check
```bash
python debug_selfcheck.py
```

### 3. Run Benchmark
```bash
chmod +x bench/run.sh
./bench/run.sh --quick
```

### 4. Run Tests
```bash
cd persistent-context-engine
pytest tests/
```

---

## Memory Persistence
The engine persists operational memory to `memory_snapshot.json` after each 
ingest batch. On restart, it loads from disk, enabling learning and context 
to survive across sessions. This fulfills Capability 06 (Continuous Learning).

---

## Architecture

### Core Components

| Component | Role |
|---|---|
| `TopologyTracker` | Resolves service identity across renames via CanonicalID |
| `TemporalMemoryStore` | Bisect-indexed event storage — O(log N + K) queries |
| `BehavioralFingerprint` | MD5/vector signature of incident role sequences |
| `BehavioralMatcher` | Fuzzy similarity matching decoupled from service names |
| `ContextCompiler` | Causal chain builder + remediation ranker |
| `Explainer` | Human-readable 3-paragraph narrative generator |

### How Topology Drift Is Handled

When `payments-svc` is renamed to `billing-svc`, a `topology` event fires.
`TopologyTracker` updates its alias map: `billing-svc → canonical:abc123`.
All historical events for `payments-svc` are already stored under `canonical:abc123`.
Future queries for either name resolve to the same canonical — transparently.
No re-indexing. No data migration. O(1) alias lookup.

### Confidence Formula

Every causal edge is scored as:
confidence = W_type × decay(Δt) × W_corr
- `W_type` — edge type weight (trace parent = 1.0, deploy-induced = 0.75, statistical = 0.40)
- `decay(Δt)` — exponential decay based on time between cause and effect
- `W_corr` — co-occurrence boost from historical frequency
- Edges below 0.25 are discarded (noise floor)
- Only edges ≥ 0.50 appear in `causal_chain` output

### Behavioral Fingerprinting

Instead of matching service names, the engine extracts *roles*:
`[DEPLOY_TARGET, LATENCY_SPIKE_SOURCE, ROLLBACK_TARGET]`

This role sequence is hashed into a vector signature. The `(shape_sim)^3` 
exponent sharpens similarity scores — pushing near-matches toward 0 and 
true matches toward 1. This is what enables cross-rename incident recall.

---

## Benchmark Results

| Metric | Target | Result |
|---|---|---|
| Ingest throughput | ≥ 1,000 evt/sec | ✅ Verified |
| Fast mode p95 | ≤ 2s | ✅ Verified |
| Deep mode p95 | ≤ 6s | ✅ Verified |
| Quick score | — | 0.635 |
| Deep stress score | — | 0.736 |
| Tests passing | 93 | ✅ 93/93 |

---

## Dependencies

See `requirements.txt` for pinned versions. Key packages:

- Python 3.11+
- No external API dependencies
- Pure Python stdlib for benchmark harness

---

## Reproducibility

A `Dockerfile` is included for clean reproducibility:

```bash
docker build -t context-engine .
docker run --rm context-engine
```

Or without Docker — just `pip install -r requirements.txt` on Python 3.11+.

---

## Key Design Decisions

- **No vector DB required** — behavioral fingerprints use weighted Jaccard 
  similarity, keeping the engine dependency-free and fast
- **Rename-transparent by design** — CanonicalID is assigned once at service 
  birth, alias map handles all future name changes
- **Noise floor at 0.25** — prevents weak correlations from polluting causal chains
- **Age decay on incidents** — older incidents get 50% weight after 
  `MEMORY_HORIZON_DAYS`, preventing stale patterns from dominating

---

## Repo Structure

persistent-context-engine/
├── src/
│   ├── engine.py          # Main orchestrator
│   ├── memory.py          # TemporalMemoryStore + IncidentMemory
│   ├── drift_handler.py   # IdentityGraph + BehavioralFingerprinting
│   ├── relationships.py   # Confidence-weighted edge synthesis
│   └── types.py           # All TypedDicts and dataclasses
├── adapters/
│   └── myteam.py          # Benchmark harness adapter
├── tests/                 # 93 tests, 100% passing
├── bench/
│   └── run.sh             # Benchmark runner
├── Dockerfile
├── requirements.txt
└── final_l2_report.json   # Benchmark results

