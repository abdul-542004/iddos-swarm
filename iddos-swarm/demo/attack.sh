#!/usr/bin/env bash
# demo/attack.sh — the one attack action: add (or remove) the latency toxic.
#
#   ./demo/attack.sh            # add a 5000ms latency toxic (start the attack)
#   ./demo/attack.sh 8000       # add an 8000ms latency toxic
#   ./demo/attack.sh off        # remove the toxic (stop the attack)
#
# The attacker only slows the database path through Toxiproxy. The web
# container is never touched.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [ "${1:-}" = "off" ]; then
  python attack/inject_latency.py remove
  echo "[attack] toxic removed — watch the service recover."
else
  LAT="${1:-5000}"
  python attack/inject_latency.py add --latency "$LAT" >/dev/null
  echo "[attack] latency ${LAT}ms injected on the database path."
  echo "[attack] watch: restart count climbing, availability falling, /work still works in the app log."
  echo "[attack] stop with:  ./demo/attack.sh off"
fi
