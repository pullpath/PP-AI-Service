#!/bin/bash
# Start the Flask application in background with logging
# Automatically uses virtual environment if available

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Check if virtual environment exists and activate it
if [ -d "venv" ]; then
    echo "Using virtual environment..."
    source venv/bin/activate
    PYTHON_CMD="python"
elif [ -d ".venv" ]; then
    echo "Using virtual environment..."
    source .venv/bin/activate
    PYTHON_CMD="python"
else
    echo "No virtual environment found, using system Python..."
    # This may vary on your system. Check your executable path with `whereis python3`
    PYTHON_CMD="/usr/local/bin/python3"
fi

# Start the application in background
echo "Starting PP-AI-Service..."
nohup $PYTHON_CMD app.py > ~/ppaiservice.log 2>&1 &

# Get the PID
PID=$!
echo "PP-AI-Service started with PID: $PID"
echo "Logs: ~/ppaiservice.log"
echo "To stop: ./stop.sh or kill $PID"