# Architecture

## Overview
The Persistent Context Engine is designed to ingest events, synthesize relationships, and reconstruct context from distributed system signals.

## Core Components

### 1. Engine (`src/engine.py`)
Main orchestrator that coordinates:
- Event ingestion
- Context reconstruction
- Incident signal processing

### 2. Memory Store (`src/memory.py`)
Flexible storage substrate supporting:
- **Graph Mode**: Entity relationship graphs
- **Temporal Mode**: Time-series event storage
- **Hybrid Mode**: Combined graph + temporal

### 3. Relationship Manager (`src/relationships.py`)
Synthesizes causal edges:
- Rule-based relationships
- Statistical correlations
- Behavioral patterns

### 4. Drift Handler (`src/drift_handler.py`)
Topology drift detection:
- Rename tracking
- Name resolution through history
- Confidence scoring

## Data Flow

```
Events → Engine.ingest_event() → MemoryStore
                ↓
              Relationships (synthesis)
                ↓
        DriftHandler (reconciliation)
                ↓
        Engine.reconstruct_context()
                ↓
           Context Output
```

## Type System

See `src/types.py` for core type definitions:
- `Event`: Raw signal with timestamp, source, and data
- `Context`: Reconstructed context linking events
- `IncidentSignal`: High-level incident representation
