# ADR-003: Relationship Synthesis Approaches

## Context
Multiple methods exist for inferring causal relationships from system signals:
- Rule-based analysis
- Statistical correlation
- Behavioral pattern matching

## Decision
Support all three approaches with composable relationship types:
1. **Rule-based**: Expert-defined causal rules
2. **Statistical**: Computed correlations from signal history
3. **Behavioral**: Learned patterns from incident analysis

## Rationale
- Different relationship types suit different scenarios
- Composition allows hybrid analysis
- Extensible for future ML-based approaches
- Clear provenance and confidence for each edge

## Consequences
- More complex relationship queries
- Need for confidence aggregation across methods
- Enables hybrid analysis strategies
- Better explainability of inferred relationships

## Status
Accepted

## Date
2026-05-15
