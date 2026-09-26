#!/usr/bin/env bash
set -Eeuo pipefail
docker compose logs -f --tail=200
