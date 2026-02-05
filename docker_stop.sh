#!/bin/bash
# Stop and clean up Docker container for PP-AI-Service

echo "Stopping PP-AI-Service Docker container..."

CONTAINER_ID=$(docker ps -q --filter ancestor=ai)

if [ -z "$CONTAINER_ID" ]; then
    echo "No running container found"
else
    docker stop $CONTAINER_ID
    echo "✓ Container stopped"
fi

echo "Removing Docker image..."
if docker images -q ai > /dev/null 2>&1; then
    docker rmi ai
    echo "✓ Image removed"
fi

echo "Cleaning up Docker system..."
docker system prune -f > /dev/null 2>&1
echo "✓ Cleanup complete"