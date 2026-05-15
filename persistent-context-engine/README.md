# Persistent Context Engine

A sophisticated context reconstruction engine for distributed systems that intelligently synthesizes relationships, detects topology drift, and reconstructs incident context from raw signals.

## Features

- **Event Ingestion**: Flexible event intake from multiple sources
- **Context Reconstruction**: Assemble coherent context from fragmented signals
- **Relationship Synthesis**: Generate causal edges via rules, statistics, and behavior
- **Topology Drift Detection**: Track and resolve service renames across deployments
- **Hybrid Storage**: Graph, temporal, and hybrid memory substrates

## Quick Start

### Installation

```bash
git clone <repository-url>
cd persistent-context-engine
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### Running Tests

```bash
python -m pytest tests/ -v
```

### Docker

```bash
docker build -t persistent-context-engine:latest .
docker run persistent-context-engine:latest
```

## Architecture

See [docs/architecture.md](docs/architecture.md) for detailed architecture.

### Core Components

- **Engine** (`src/engine.py`): Main orchestrator
- **Memory Store** (`src/memory.py`): Flexible storage substrate
- **Relationships** (`src/relationships.py`): Causal edge synthesis
- **Drift Handler** (`src/drift_handler.py`): Topology drift detection

## Documentation

- [Architecture](docs/architecture.md)
- [Deployment Guide](docs/deployment.md)
- [Configuration](docs/configuration.md)
- [ADRs](docs/adr/) - Architecture Decision Records

## Testing

Comprehensive test suite covering:
- Unit tests for individual components
- Integration tests for full workflows
- Adversarial rename scenarios
- End-to-end incident analysis

```bash
python -m pytest tests/ -v --cov=src
```

## Benchmarks

Run the canonical benchmark suite:

```bash
bash bench/run.sh
```

## Usage Example

```python
from src.engine import PersistentContextEngine
from src.types import Event
from datetime import datetime

# Initialize engine
engine = PersistentContextEngine()

# Ingest events
event = {
    'timestamp': datetime.now(),
    'source': 'service_a',
    'data': {'error': 'timeout'}
}
engine.ingest_event(event)

# Reconstruct context
context = engine.reconstruct_context('incident_001', [event])

# Add relationships
engine.relationships.add_rule_based_relationship(
    'service_a', 'service_b', 'service_a → service_b'
)
```

## Contributing

See CONTRIBUTING.md (coming soon)

## License

MIT

## Status

Phase 6 - Production Ready

- ✅ Core engine implementation
- ✅ Comprehensive test coverage
- ✅ Docker containerization
- ✅ Architecture documentation
- ✅ Drift detection
- ✅ Relationship synthesis

## Demo

See [demo/demo.mp4](demo/demo.mp4) for a 5-minute walkthrough.

---

**Last Updated**: 2026-05-15
