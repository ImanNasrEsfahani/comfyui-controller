#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
if [[ ! -f .env ]]; then
  echo "ERROR: private .env not found" >&2
  exit 1
fi
set -a
# shellcheck disable=SC1091
source .env
set +a
# Always prefer the ACTIVE config in SQLite, not the old .env values.
exec python3 -u scripts/run-salad-deploy.py "$@"
