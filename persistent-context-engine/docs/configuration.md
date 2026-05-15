# Configuration Guide

## Environment Variables

### Storage Configuration
- `STORAGE_TYPE`: Type of memory storage (`graph`, `temporal`, `hybrid`)
  - Default: `hybrid`

### Engine Configuration
- `EVENT_BUFFER_SIZE`: Maximum events to keep in memory
  - Default: `10000`
- `CONTEXT_TTL`: Time-to-live for reconstructed contexts (seconds)
  - Default: `3600`

### Drift Detection
- `DRIFT_CONFIDENCE_THRESHOLD`: Minimum confidence for rename detection
  - Default: `0.7`
- `DRIFT_HISTORY_LIMIT`: Maximum rename history entries
  - Default: `1000`

## Configuration File

Create a `.env` file in the project root:

```env
STORAGE_TYPE=hybrid
EVENT_BUFFER_SIZE=10000
CONTEXT_TTL=3600
DRIFT_CONFIDENCE_THRESHOLD=0.7
DRIFT_HISTORY_LIMIT=1000
```

## Profiles

### Development
```env
STORAGE_TYPE=hybrid
EVENT_BUFFER_SIZE=1000
CONTEXT_TTL=1800
```

### Production
```env
STORAGE_TYPE=graph
EVENT_BUFFER_SIZE=50000
CONTEXT_TTL=7200
```
