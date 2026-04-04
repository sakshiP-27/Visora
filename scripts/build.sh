#!/bin/bash

# stop and remove old containers (ignore errors if they don't exist)
docker stop zoro sanji nami 2>/dev/null
docker rm zoro sanji nami 2>/dev/null

# build the images
docker build -f Dockerfile-Zoro -t zoro-backend ./backend
docker build -f Dockerfile-Sanji -t sanji-genai ./genAI
docker build -f Dockerfile-Nami -t nami-frontend ./frontend

# create docker network (ignore if already exists)
docker network create strawhats 2>/dev/null

# start the containers
docker run -d --env-file .env --network strawhats --name sanji -p 4000:4000 sanji-genai
docker run -d --env-file .env --network strawhats --name zoro -p 3000:3000 zoro-backend
docker run -d --network strawhats --name nami -p 8080:80 nami-frontend

# wait for containers to be ready
sleep 3

# health checks
echo "--- Health Checks ---"
curl -s http://localhost:4000/health
echo ""
curl -s http://localhost:3000/health
echo ""
curl -s http://localhost:8080 | head -1
echo ""
