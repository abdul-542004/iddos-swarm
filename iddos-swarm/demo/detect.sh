#!/usr/bin/env bash
# demo/detect.sh — run the live detector so the audience sees alerts.
#
#   ./demo/detect.sh              # run until Ctrl+C
#   ./demo/detect.sh --duration 150
#
# Streams health events + restart counts and raises alerts, naming the cause
# (dependency latency, not a crash). Also appended to results/alerts.log.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
exec python detector/monitor.py "$@"
