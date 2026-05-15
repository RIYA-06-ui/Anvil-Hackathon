# Deployment Guide

## Prerequisites

- Python 3.8+
- pip package manager

## Installation

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd persistent-context-engine
   ```

2. **Create virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

## Running Tests

```bash
python -m pytest tests/
```

## Docker Deployment

```bash
docker build -t persistent-context-engine:latest .
docker run -p 5000:5000 persistent-context-engine:latest
```

## Configuration

See `configuration.md` for environment variables and configuration options.
