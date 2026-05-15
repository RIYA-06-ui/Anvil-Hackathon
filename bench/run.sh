#!/usr/bin/env bash
# Anvil Benchmark Runner Wrapper

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." && pwd )"
cd "$DIR"

# Make sure our engine is discoverable
export PYTHONPATH="$DIR/persistent-context-engine"

# Run the official benchmark harness to emit the required report.json
echo "Running Persistent Context Engine Benchmark..."
python benchmark/bench-p02-context/run.py --adapter adapters.myteam:Engine --mode fast --seeds 42 101 --out report.json
echo "Benchmark complete. Results saved to report.json."
