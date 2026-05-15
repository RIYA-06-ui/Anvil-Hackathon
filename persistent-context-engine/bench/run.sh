#!/bin/bash

# Canonical run script for persistent-context-engine benchmarks

set -e

echo "=========================================="
echo "Persistent Context Engine - Benchmark Suite"
echo "=========================================="
echo ""

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if Python is installed
if ! command -v python &> /dev/null; then
    echo "Python is not installed. Please install Python 3.8+"
    exit 1
fi

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo -e "${YELLOW}Creating virtual environment...${NC}"
    python -m venv venv
fi

# Activate virtual environment
echo -e "${YELLOW}Activating virtual environment...${NC}"
source venv/bin/activate

# Install/update dependencies
echo -e "${YELLOW}Installing dependencies...${NC}"
pip install -q -r requirements.txt

# Run tests
echo -e "${GREEN}Running unit tests...${NC}"
python -m pytest tests/ -v --tb=short

# Run integration tests
echo -e "${GREEN}Running integration tests...${NC}"
python -m pytest tests/test_integration.py -v

# Display coverage report if pytest-cov is installed
echo ""
echo -e "${GREEN}Generating coverage report...${NC}"
python -m pytest tests/ --cov=src --cov-report=term-missing

echo ""
echo -e "${GREEN}=========================================="
echo "Benchmark suite completed successfully!"
echo "==========================================${NC}"
