#!/bin/bash
# Stop the Flask application

echo "Stopping PP-AI-Service..."

# Find and kill the process(es)
PIDS=$(pgrep -f "python.*app.py")

if [ -z "$PIDS" ]; then
    echo "PP-AI-Service is not running"
    exit 0
fi

# Kill all matching processes
echo "$PIDS" | xargs kill

# Wait a moment and check if they're stopped
sleep 1
REMAINING=$(pgrep -f "python.*app.py")

if [ -n "$REMAINING" ]; then
    echo "Process(es) didn't stop gracefully, forcing..."
    echo "$REMAINING" | xargs kill -9
    echo "PP-AI-Service force stopped"
else
    echo "PP-AI-Service stopped successfully"
fi