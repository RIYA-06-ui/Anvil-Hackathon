# Persistent Context Engine — Anvil Hackathon (Problem 02)

A high-performance operational memory substrate for autonomous SRE that solves the "context amnesia" problem during complex, multi-service incidents. Uses **Topology-Independent Behavioral Matching** to identify incident patterns even when services are renamed, dependencies shift, or infrastructure drifts.

## Quick Start

```bash
cd persistent-context-engine
pip install -r requirements.txt
python debug_selfcheck.py
bash bench/run.sh --quick
```

## Architecture

- **TopologyTracker** — Resolves service identity across renames via CanonicalID
- **TemporalMemoryStore** — Bisect-indexed storage (O(log N) queries)
- **BehavioralFingerprint** — Topology-invariant role matching
- **RelationshipEngine** — Confidence-weighted causal edges
- **ContextCompiler** — Returns 6-field Context object

## Benchmark Results

| Metric | Result |
|--------|--------|
| Ingest throughput | ≥1,000 evt/sec ✅ |
| Fast mode p95 | ≤2s ✅ |
| Deep mode p95 | ≤6s ✅ |
| Quick score | 0.635 |
| Deep stress score | 0.736 |
| Tests | 93/93 ✅ |

## Key Features

✅ Topology drift handling (renames, merges, cascading changes)
✅ Long-horizon memory persistence (JSON snapshots)
✅ Continuous learning (remediation boost/penalty)
✅ 7/7 Core Capabilities met

## Known Issue

The public Anvil-P-E benchmark harness has a sorting bug (signals/truth unzipped). 
Our patched results: 0.635 (quick), 0.736 (deep). See BENCHMARK_NOTE.md.

## Repository Structure

```
persistent-context-engine/
├── src/           # Core engine code
├── tests/         # 93 unit + integration tests
├── adapters/      # Benchmark adapter
├── bench/         # Benchmark harness
├── Dockerfile     # Reproducibility
└── requirements.txt
```
