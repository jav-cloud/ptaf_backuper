#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Check Python 3
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python 3 not found"
    exit 1
fi

# Create venv if not exists
if [ ! -d "venv" ]; then
    python3 -m venv venv
    if [ $? -ne 0 ]; then
        echo "ERROR: Failed to create venv"
        exit 1
    fi
fi

# Activate venv and install dependencies
source venv/bin/activate
pip install -r requirements.txt --no-cache-dir
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to install dependencies"
    exit 1
fi

# Run backup script
python3 backuper.py
EXIT_CODE=$?

deactivate
exit $EXIT_CODE