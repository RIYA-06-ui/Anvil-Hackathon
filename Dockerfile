# Persistent Context Engine — Production Environment
FROM python:3.11-slim-bookworm

# Set working directory
WORKDIR /app

# Metadata
LABEL maintainer="Hackathon Submission"
LABEL description="Persistent Context Engine for Autonomous SRE"

# Copy entire codebase
COPY . /app

# Install system dependencies (if any)
RUN apt-get update && apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

# Make benchmark script executable
RUN chmod +x /app/bench/run.sh

# Ensure package is importable
ENV PYTHONPATH=/app/persistent-context-engine
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Expose port (not strictly needed, but good practice)
EXPOSE 5000

# Default command: run quick benchmark
ENTRYPOINT ["/app/bench/run.sh"]
CMD ["--quick"]
