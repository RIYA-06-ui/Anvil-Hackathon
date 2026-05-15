#!/bin/bash

# Canonical benchmark runner for Persistent Context Engine
# Invokes the Anvil-P-E harness (github.com/Sauhard74/Anvil-P-E) and generates
# final_l2_report.json with all metrics required by judges.

set -e

echo "=========================================="
echo "Persistent Context Engine — Benchmark Runner"
echo "=========================================="
echo ""

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HARNESS_DIR="${REPO_ROOT}/../Anvil-P-E"
BENCH_DIR="${HARNESS_DIR}/bench-p02-context"

# Check Python
if ! command -v python3 &> /dev/null && ! command -v python &> /dev/null; then
    echo -e "${RED}Python 3.11+ is required.${NC}"
    exit 1
fi

# Use python3 if available, else python
PY_CMD="python3"
if ! command -v python3 &> /dev/null; then
    PY_CMD="python"
fi

echo -e "${YELLOW}Step 1: Installing dependencies...${NC}"
if [ ! -d "${REPO_ROOT}/venv" ]; then
    ${PY_CMD} -m venv "${REPO_ROOT}/venv"
fi

source "${REPO_ROOT}/venv/bin/activate"
pip install -q -r "${REPO_ROOT}/requirements.txt"

echo -e "${YELLOW}Step 2: Cloning Anvil-P-E benchmark harness (if needed)...${NC}"
if [ ! -d "${HARNESS_DIR}" ]; then
    echo "Cloning from github.com/Sauhard74/Anvil-P-E..."
    git clone https://github.com/Sauhard74/Anvil-P-E "${HARNESS_DIR}"
fi

# Verify harness exists
if [ ! -f "${BENCH_DIR}/run.py" ]; then
    echo -e "${RED}ERROR: Benchmark harness not found at ${BENCH_DIR}/run.py${NC}"
    echo "Expected structure:"
    echo "  ${HARNESS_DIR}/bench-p02-context/run.py"
    echo "  ${HARNESS_DIR}/bench-p02-context/self_check.py"
    exit 1
fi

echo -e "${YELLOW}Step 3: Running canonical benchmark (L2 scenario)...${NC}"
cd "${BENCH_DIR}"

# Run the L2 benchmark with canonical seed
${PY_CMD} run.py \
    --adapter "adapters.myteam:Engine" \
    --mode fast \
    --seeds 42 \
    --n-services 12 \
    --days 7 \
    --out "${REPO_ROOT}/final_l2_report.json" \
    2>&1 | tee "${REPO_ROOT}/bench_output.log"

cd "${REPO_ROOT}"

echo ""
echo -e "${GREEN}Step 4: Benchmark complete!${NC}"
echo ""

# Display key metrics
if [ -f "${REPO_ROOT}/final_l2_report.json" ]; then
    echo -e "${GREEN}=== RESULTS ===${NC}"
    ${PY_CMD} -c "
import json
with open('${REPO_ROOT}/final_l2_report.json') as f:
    data = json.load(f)
    print(f\"Precision@5:     {data.get('metrics', {}).get('precision_at_5', 'N/A'):.3f}\")
    print(f\"Recall@5:        {data.get('metrics', {}).get('recall_at_5', 'N/A'):.3f}\")
    print(f\"Context F1:      {data.get('metrics', {}).get('context_f1', 'N/A'):.3f}\")
    print(f\"Latency p95 (s): {data.get('metrics', {}).get('latency_p95_seconds', 'N/A'):.3f}\")
    print(f\"Throughput:      {data.get('metrics', {}).get('throughput_events_per_sec', 'N/A'):.0f} evt/s\")
" 2>/dev/null || echo "Report generated: final_l2_report.json"
else
    echo -e "${RED}ERROR: final_l2_report.json not found${NC}"
    exit 1
fi

echo ""
echo -e "${YELLOW}Step 5: Running unit tests for code quality verification...${NC}"
cd "${REPO_ROOT}"
${PY_CMD} -m pytest tests/ -v --tb=short 2>&1 | tail -20

echo ""
echo -e "${GREEN}=========================================="
echo "Benchmark complete. Report saved to: final_l2_report.json"
echo "==========================================${NC}"
echo -e "${GREEN}=========================================="
echo "Benchmark suite completed successfully!"
echo "==========================================${NC}"
