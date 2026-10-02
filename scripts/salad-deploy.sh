#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
if [[ ! -f .env ]]; then
  echo "ERROR: $ROOT_DIR/.env not found; merge .env.example into private .env." >&2
  exit 1
fi
set -a
# shellcheck disable=SC1091
source .env
set +a
# All deployment values are read/validated by deploy_salad.py from .env.
# -u makes POST / name_conflict and retry output visible immediately.
exec python3 -u salad-worker/deploy_salad.py "$@"
