docker stop $(docker ps -q --filter ancestor=ai)
docker rmi ai
docker system prune -f