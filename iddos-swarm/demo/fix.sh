#!/usr/bin/env bash
# demo/fix.sh — apply the mitigation: redeploy with the mitigated stack.
#
#   ./demo/fix.sh
#
# Swaps the vulnerable stack for the mitigated one (liveness-only health-check
# + tuned restart policy). The dashboard stays up. After this, run the SAME
# attack again and watch the service stay available.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
echo "[fix] switching to the mitigated stack ..."
exec "$ROOT/demo/reset.sh" mitigated
