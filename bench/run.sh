#!/usr/bin/env bash
# Anvil Benchmark Runner Wrapper

# Ensure we're in the correct directory
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." && pwd )"
cd "$DIR/persistent-context-engine"

# Run the benchmark harness using our adapter
echo "Running Persistent Context Engine Benchmark..."
python debug_selfcheck.py
