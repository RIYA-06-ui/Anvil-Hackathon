# Stage 1: Build dependencies
FROM python:3.11-slim AS builder

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Stage 2: Runtime
FROM python:3.11-slim AS runtime

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy source
COPY src/ ./src/
COPY adapters/ ./adapters/
COPY tests/ ./tests/

# Ensure package is importable
ENV PYTHONPATH=/app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Default: run self-check (override for benchmark run)
CMD ["python", "-m", "pytest", "tests/", "-v", "--tb=short"]
