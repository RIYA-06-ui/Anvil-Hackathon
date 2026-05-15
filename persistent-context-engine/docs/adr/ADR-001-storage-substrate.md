# ADR-001: Storage Substrate Design

## Context
We need a flexible memory substrate that can support multiple access patterns:
- Event queries by timestamp
- Entity relationship traversal
- Temporal correlation analysis

## Decision
Implement a hybrid storage model combining:
1. **Graph store** for entity relationships
2. **Temporal store** for event sequences
3. **Query router** to leverage appropriate store

## Rationale
- **Graph mode**: Efficient for causal analysis
- **Temporal mode**: Optimal for sequence reconstruction
- **Hybrid mode**: Best of both with routing intelligence

## Consequences
- Increased implementation complexity
- Storage overhead for dual representation
- Flexibility in handling diverse query patterns
- Better performance for typical incident analysis workflows

## Status
Accepted

## Date
2026-05-15
