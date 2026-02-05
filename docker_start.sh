#!/bin/bash
# Build and start Docker container for PP-AI-Service

echo "Building Docker image..."
docker build . -t ai

if [ $? -ne 0 ]; then
    echo "✗ Docker build failed"
    exit 1
fi

echo "Starting Docker container..."
CONTAINER_ID=$(docker run --rm -p 8000:8000 -d ai)

if [ $? -eq 0 ]; then
    echo "✓ PP-AI-Service started in Docker"
    echo "Container ID: $CONTAINER_ID"
    echo "URL: http://localhost:8000"
    echo "To stop: ./docker_stop.sh"
else
    echo "✗ Failed to start container"
    exit 1
fi