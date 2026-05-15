# ADR-004: Context Reconstruction Algorithm

## Context
Given a set of events and relationships, we must reconstruct the causal context of an incident.
This requires resolving aliases, ordering events, and connecting components.

## Decision
Implement multi-phase reconstruction:
1. **Normalization**: Resolve renames and aliases via drift handler
2. **Sequencing**: Order events by timestamp
3. **Linking**: Connect events via synthesized relationships
4. **Enrichment**: Add contextual metadata and confidence scores

## Rationale
- Clear separation of concerns
- Each phase can be independently optimized
- Supports partial reconstruction for incomplete data
- Enables incremental updates as new data arrives

## Consequences
- Sequential processing pipeline
- Potential for improved parallelization in future
- Clear debugging and analysis points
- Extensible for additional enrichment phases

## Status
Accepted

## Date
2026-05-15
