#!/usr/bin/env bash
set -Eeuo pipefail
git pull --ff-only
docker compose up -d --build
docker image prune -f
docker compose ps
