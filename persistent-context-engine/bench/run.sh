#!/usr/bin/env bash
# Anvil Benchmark Runner

# Ensure we're in the correct directory
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." && pwd )"
cd "$DIR"

# Ensure python path includes the project root
export PYTHONPATH=".:$PYTHONPATH"

# Run the benchmark harness using our adapter
echo "Running Persistent Context Engine Benchmark..."
python ../benchmark/bench-p02-context/run.py \
    --adapter adapters.myteam:Engine \
    --mode fast \
    "$@"
