# Persistent Context Engine — Anvil Hackathon Submission

A high-performance memory substrate for autonomous SRE, designed to solve the "context amnesia" problem during complex, multi-service incidents. It uses **Topology-Independent Behavioral Matching** to identify incident patterns even when services are renamed or boundaries shift.

## Quickstart

### 1. Install Dependencies
```bash
cd persistent-context-engine
python -m venv venv
source venv/bin/activate  # On Windows use `venv\Scripts\activate`
pip install -r requirements.txt
```

### 2. Run Benchmark Harness (self_check.py)
Validate your installation and run the official benchmark harness:
```bash
python ../benchmark/bench-p02-context/self_check.py --adapter adapters.myteam:Engine --quick
```

### 3. Run Benchmark (report.json)
Execute the submission script to ingest samples and generate the final report:
```bash
chmod +x bench/run.sh
./bench/run.sh
```

## Architecture Overview

1. **Ingest & Identity Resolution (`TopologyTracker`)**: Listens to topology events and maintains a unified mapping. All subsequent storage and queries use a `CanonicalID`.
2. **Behavioral Fingerprinting (`BehavioralFingerprint`)**: Extracts topology-invariant behavioral roles (Initiator, Remediation Target) to construct an MD5/vector-based signature of the incident.
3. **Temporal Memory Store (`TemporalMemoryStore`)**: A tri-indexed `(timeline, id, canonical)` structure allowing $O(\log N)$ temporal range queries, ensuring fast reconstruction windows.
4. **Behavioral Matcher (`BehavioralMatcher`)**: Retrieves historical incidents via fuzzy similarity scoring on the behavioral fingerprints, completely decoupled from service names.
5. **Context Compilation (`ContextCompiler` & `Explainer`)**: Sorts and truncates causal chains, deduplicates matches, merges suggested remediations, and writes an auditable 3-paragraph summary.

## Core Mechanisms

- **Memory Representation**: Events are stored in `TemporalMemoryStore` using a `CanonicalID`. Queries are transparent across names (e.g. `billing-svc` resolves to the same events as `payments-svc` did).
- **Drift Strategy**: Instead of checking strings, we map a graph of role sequences (`deploy → latency spike → rollback`) and apply a cubed shape similarity exponent (`(shape_sim)^3`) against vector signatures to guarantee matches across architectural drift.

## Environment & Reproducibility
A `Dockerfile` is provided for guaranteed reproducibility:
```bash
cd persistent-context-engine
docker build -t context-engine .
docker run --rm context-engine
```
