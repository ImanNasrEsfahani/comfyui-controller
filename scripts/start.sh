#!/usr/bin/env bash
set -Eeuo pipefail
docker compose up -d --build
docker compose ps
