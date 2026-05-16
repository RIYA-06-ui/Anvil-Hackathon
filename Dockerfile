FROM python:3.11-slim-bookworm

WORKDIR /app

LABEL maintainer="Hackathon Submission"
LABEL description="Persistent Context Engine for Autonomous SRE"

COPY . /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

RUN chmod +x /app/bench/run.sh

EXPOSE 5000

ENTRYPOINT ["/app/bench/run.sh"]
CMD ["--quick"]
