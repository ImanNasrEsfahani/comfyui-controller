#!/usr/bin/env bash
# Used by BOTH GitHub Actions variants. Avoid assuming Ubuntu runners have ffmpeg.
set -Eeuo pipefail
if command -v ffmpeg >/dev/null 2>&1 && command -v ffprobe >/dev/null 2>&1; then
  echo "[scail2-ci] FFmpeg and FFprobe are already installed."
else
  echo "[scail2-ci] FFmpeg/FFprobe missing; installing prerequisites."
  if ! command -v apt-get >/dev/null 2>&1; then
    echo "::error::FFmpeg and FFprobe are required. Preinstall them on this non-APT self-hosted runner." >&2
    exit 1
  fi
  prefix=()
  if [[ "$(id -u)" -ne 0 ]]; then
    if command -v sudo >/dev/null 2>&1; then
      prefix=(sudo)
    else
      echo "::error::FFmpeg is missing and runner has no root/sudo. Install ffmpeg on the self-hosted runner." >&2
      exit 1
    fi
  fi
  "${prefix[@]}" env DEBIAN_FRONTEND=noninteractive apt-get update -qq
  "${prefix[@]}" env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends ffmpeg
fi
for binary in ffmpeg ffprobe; do
  if ! command -v "$binary" >/dev/null 2>&1; then
    echo "::error::$binary not found after prerequisite installation." >&2
    exit 1
  fi
  "$binary" -version | sed -n '1p'
done
