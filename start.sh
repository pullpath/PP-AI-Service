docker build . -t ai-service
docker run --rm -p 8000:8000 -d ai-service