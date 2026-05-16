#!/usr/bin/env bash
# Anvil Benchmark Runner Wrapper

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." && pwd )"
cd "$DIR"

# Make sure our engine is discoverable
export PYTHONPATH="$DIR/persistent-context-engine"

# Run the official benchmark harness to emit the required l3_report.json
echo "Running Persistent Context Engine Benchmark (L3 Final)..."
python benchmark/bench-p02-context/run.py --adapter adapters.myteam:Engine --out l3_report.json
cp l3_report.json report.json
echo "Benchmark complete. Results saved to l3_report.json and report.json."
