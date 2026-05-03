#!/bin/bash
cd /home/deploy/apps/trading-bot-platform && /usr/bin/docker compose -f docker-compose.prod.yml up -d --build
