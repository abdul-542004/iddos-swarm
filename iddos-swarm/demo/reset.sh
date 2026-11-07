#!/usr/bin/env bash
# demo/reset.sh — bring the demo to a clean, known state.
#
#   ./demo/reset.sh            # vulnerable stack + live dashboard (default)
#   ./demo/reset.sh mitigated  # mitigated stack + live dashboard
#   OBS=0 ./demo/reset.sh      # skip Grafana/Prometheus (app stack only)
#
# It removes any existing 'app' stack, waits for a full teardown, then deploys
# the requested stack and waits until the web service is healthy.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

STACK=app
MODE="${1:-vuln}"
OBS="${OBS:-1}"

case "$MODE" in
  vuln|vulnerable) APP=stack/vulnerable.yml ;;
  fixed|mitigated) APP=stack/mitigated.yml ;;
  *) echo "usage: reset.sh [vuln|mitigated]   (env OBS=0 to skip the dashboard)"; exit 1 ;;
esac

FILES=(-c "$APP")
if [ "$OBS" = "1" ]; then FILES+=(-c stack/observability.yml); fi

echo "[reset] removing any existing '$STACK' stack ..."
docker stack rm "$STACK" >/dev/null 2>&1 || true

echo "[reset] waiting for teardown ..."
for _ in $(seq 1 60); do
  [ -z "$(docker service ls --filter "name=${STACK}_" -q)" ] && break; sleep 1
done
for _ in $(seq 1 60); do
  docker network ls --filter "name=${STACK}_iddosnet" -q | grep -q . || break; sleep 1
done

if [ "$OBS" = "1" ]; then echo "[reset] deploying: $MODE (+dashboard)"; else echo "[reset] deploying: $MODE"; fi
docker stack deploy "${FILES[@]}" "$STACK" | grep -vi detach || true

echo "[reset] waiting for web to become healthy ..."
for _ in $(seq 1 60); do
  s="$(docker ps --filter 'label=com.docker.swarm.service.name=app_web' --format '{{.Status}}')"
  case "$s" in *healthy*) echo "[reset] web is healthy: $s"; break ;; esac
  sleep 2
done

echo "[reset] done. Endpoints:"
echo "          app   http://localhost:8000/work  (and /health /healthz /ready /metrics)"
echo "          toxi  http://localhost:8474"
if [ "$OBS" = "1" ]; then
  echo "          Grafana http://localhost:3000   Prometheus http://localhost:9090"
fi
