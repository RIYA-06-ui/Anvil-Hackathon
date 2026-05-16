#!/bin/bash
# Persistent Context Engine — Benchmark Runner
# Usage: ./bench/run.sh [OPTIONS]
# Options:
#   --quick              Run quick test (single seed, fast mode)
#   --seeds S1 S2...     Use specific seeds
#   --mode fast|deep     Context reconstruction mode (default: fast)
#   --out FILE           Output report.json path (default: report.json)

set -e  # Exit on error

# Get directory of this script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

# Defaults
QUICK=false
SEEDS="9999 31415 27182"
MODE="fast"
OUTPUT="report.json"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --quick)
            QUICK=true
            SEEDS="9999"
            shift
            ;;
        --seeds)
            shift
            SEEDS=()
            while [[ $# -gt 0 ]] && [[ $1 != --* ]]; do
                SEEDS+=("$1")
                shift
            done
            ;;
        --n-services)
            # Ignored in L3
            shift 2
            ;;
        --days)
            # Ignored in L3
            shift 2
            ;;
        --mode)
            MODE="$2"
            shift 2
            ;;
        --out)
            OUTPUT="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Verify Python
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python 3 not found"
    exit 1
fi

echo "=========================================="
echo "Persistent Context Engine — Benchmark"
echo "=========================================="
echo "Repo: $REPO_ROOT"
echo "Seeds: ${SEEDS[*]}"
echo "Mode: $MODE"
echo "Output: $OUTPUT"
echo "=========================================="
echo ""

# Change to repo root
cd "$REPO_ROOT"
export PYTHONPATH="$REPO_ROOT/persistent-context-engine"

# Verify required files exist
if [ ! -f "benchmark/bench-p02-context/run.py" ]; then
    echo "ERROR: benchmark/bench-p02-context/run.py not found. Did you clone the official harness?"
    exit 1
fi

if [ ! -f "persistent-context-engine/adapters/myteam.py" ]; then
    echo "ERROR: persistent-context-engine/adapters/myteam.py not found"
    exit 1
fi

# Copy adapter to benchmark harness to avoid Python import collision
echo "Copying adapter to benchmark harness..."
mkdir -p benchmark/bench-p02-context/adapters
cp persistent-context-engine/adapters/myteam.py benchmark/bench-p02-context/adapters/

# Run benchmark
FINAL_OUTPUT="$OUTPUT"
if [ "$QUICK" = true ]; then
    echo "Running QUICK mode (single seed)..."
    python3 benchmark/bench-p02-context/run.py \
        --adapter adapters.myteam:Engine \
        --mode "$MODE" \
        --seeds 9999 \
        --out "$FINAL_OUTPUT"
else
    echo "Running FULL benchmark across multiple seeds..."
    python3 benchmark/bench-p02-context/run.py \
        --adapter adapters.myteam:Engine \
        --mode "$MODE" \
        --seeds ${SEEDS[*]} \
        --out "$FINAL_OUTPUT"
fi


# Verify output
if [ ! -f "$FINAL_OUTPUT" ]; then
    echo "ERROR: Benchmark failed. No output file generated."
    exit 1
fi

# Print summary
echo ""
echo "=========================================="
echo "Benchmark Complete!"
echo "=========================================="
echo "Report: $FINAL_OUTPUT"
echo ""
echo "Metrics:"
python3 -c "
import json
try:
    with open('$FINAL_OUTPUT') as f:
        report = json.load(f)
    for key, val in report.items():
        if isinstance(val, float):
            print(f'  {key}: {val:.4f}')
        else:
            print(f'  {key}: {val}')
except Exception as e:
    print(f'  (Could not parse metrics: {e})')
" || true
echo "=========================================="

exit 0
