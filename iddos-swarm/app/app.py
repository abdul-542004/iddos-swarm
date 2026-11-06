"""iddos-app — dummy victim web service.

Endpoints:

  GET /work    Does real application work and returns 200. It does NOT touch
               the database. This proves the app logic is alive and correct.

  GET /health  The *vulnerable* health-check (used by the vulnerable stack).
               It opens a fresh database connection THROUGH Toxiproxy and runs
               `SELECT 1`. It returns 200 only if the database answers within
               DB_TIMEOUT seconds. Under injected latency it times out and
               returns 503 — even though /work is still fine.

  GET /healthz The MITIGATED LIVENESS probe (Step 5). Local-only: it confirms
               the process answers and does NOT touch the database, so a slow
               dependency can no longer fail the container health-check.

  GET /ready   The MITIGATED READINESS probe (Step 5). Depends on the database
               so a reverse proxy can de-route a slow instance WITHOUT killing
               it. The same code serves both the vulnerable and fixed images;
               only the Dockerfile HEALTHCHECK target differs.

The log is the evidence for the "signature signal" the detector looks for:
app work succeeds while the health-check fails. That divergence means an
indirect denial-of-service (a slow dependency), not an application crash.
"""

import logging
import os
import threading
import time

import psycopg2
from flask import Flask, jsonify

# --- Configuration (all from environment, with safe local defaults) ---------
DB_HOST = os.environ.get("DB_HOST", "toxiproxy")
DB_PORT = int(os.environ.get("DB_PORT", "5432"))
DB_NAME = os.environ.get("DB_NAME", "iddos")
DB_USER = os.environ.get("DB_USER", "iddos")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "iddos")
# Seconds the /health DB call may take before it is treated as a failure.
# A fresh connection is opened per check, so this bounds the whole round-trip
# (connect handshake + query). Under a latency toxic the connect alone exceeds
# it, which is exactly the vulnerability being demonstrated.
DB_TIMEOUT = float(os.environ.get("DB_TIMEOUT", "2"))
APP_PORT = int(os.environ.get("APP_PORT", "8000"))

# Circuit-breaker config (defence-in-depth, Step 5 optional). After
# CB_FAIL_THRESHOLD consecutive DB failures the breaker OPENS and /ready fails
# fast (no DB call, no hang) until CB_RESET_TIMEOUT_S passes, then it tries one
# probe (half-open) before closing again.
CB_FAIL_THRESHOLD = int(os.environ.get("CB_FAIL_THRESHOLD", "3"))
CB_RESET_TIMEOUT_S = float(os.environ.get("CB_RESET_TIMEOUT_S", "15"))

# --- Logging: one clear line per request, with timestamps -------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("iddos-app")

app = Flask(__name__)

# Count /work calls so the "real work" is visibly doing something.
_work_counter = 0


def _check_database():
    """Open a fresh connection through Toxiproxy and run SELECT 1.

    Returns (ok: bool, elapsed_ms: float, detail: str).
    A fresh connection each call is intentional: the latency toxic then delays
    the connection handshake itself, so a short DB_TIMEOUT reliably trips.
    """
    start = time.monotonic()
    conn = None
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            connect_timeout=max(1, int(round(DB_TIMEOUT))),
            # Bound the query server-side too (milliseconds).
            options=f"-c statement_timeout={int(DB_TIMEOUT * 1000)}",
        )
        with conn.cursor() as cur:
            cur.execute("SELECT 1;")
            cur.fetchone()
        elapsed_ms = (time.monotonic() - start) * 1000.0
        return True, elapsed_ms, "ok"
    except Exception as exc:  # noqa: BLE001 - any DB error means unhealthy
        elapsed_ms = (time.monotonic() - start) * 1000.0
        return False, elapsed_ms, f"{type(exc).__name__}: {exc}".strip()
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass


class CircuitBreaker:
    """Minimal thread-safe circuit breaker (closed -> open -> half-open).

    While OPEN it short-circuits the protected call so the caller fails fast
    instead of waiting on a slow dependency every time.
    """

    def __init__(self, threshold, reset_timeout):
        self.threshold = threshold
        self.reset_timeout = reset_timeout
        self.failures = 0
        self.state = "closed"
        self.opened_at = 0.0
        self.lock = threading.Lock()

    def allow(self):
        """Return (allowed, state): may the protected call run right now?"""
        with self.lock:
            if self.state == "open":
                if time.monotonic() - self.opened_at >= self.reset_timeout:
                    self.state = "half-open"   # let a single trial through
                    return True, "half-open"
                return False, "open"
            return True, self.state

    def record_success(self):
        with self.lock:
            self.failures = 0
            self.state = "closed"

    def record_failure(self):
        with self.lock:
            self.failures += 1
            if self.state == "half-open" or self.failures >= self.threshold:
                self.state = "open"
                self.opened_at = time.monotonic()


db_breaker = CircuitBreaker(CB_FAIL_THRESHOLD, CB_RESET_TIMEOUT_S)


def _check_database_guarded():
    """DB check behind the circuit breaker (used by /ready).

    Returns (ok, elapsed_ms, detail, breaker_state). When the breaker is open
    it returns immediately (fail fast) without calling the database at all.
    """
    allowed, state = db_breaker.allow()
    if not allowed:
        return False, 0.0, "circuit_open: failing fast, database marked bad", state
    ok, elapsed_ms, detail = _check_database()
    if ok:
        db_breaker.record_success()
    else:
        db_breaker.record_failure()
    return ok, elapsed_ms, detail, db_breaker.state


@app.get("/work")
def work():
    """Real app work. No database. Proves the app is alive and correct."""
    global _work_counter
    _work_counter += 1
    # A tiny bit of deterministic "work" so the endpoint is not a no-op.
    result = sum(i * i for i in range(1000))
    log.info("WORK ok n=%d result=%d", _work_counter, result)
    return jsonify(status="ok", endpoint="work", count=_work_counter), 200


@app.get("/health")
def health():
    """Vulnerable health-check: healthy only if the database answers in time."""
    ok, elapsed_ms, detail = _check_database()
    if ok:
        log.info("HEALTH pass db_ms=%.1f", elapsed_ms)
        return jsonify(status="healthy", db_ms=round(elapsed_ms, 1)), 200
    log.warning("HEALTH fail db_ms=%.1f detail=%s", elapsed_ms, detail)
    return (
        jsonify(status="unhealthy", db_ms=round(elapsed_ms, 1), detail=detail),
        503,
    )


@app.get("/healthz")
def healthz():
    """Local-only LIVENESS probe (the Step 5 fix).

    It only confirms the process can answer HTTP. It does NOT touch the
    database, so a slow dependency can no longer fail the container
    health-check, and Swarm no longer kills a perfectly alive container.
    """
    return jsonify(status="alive"), 200


@app.get("/ready")
def ready():
    """READINESS probe: depends on the database.

    A reverse proxy can use /ready to pull a slow instance OUT of the traffic
    rotation without killing it. When the database is slow the service reports
    "not ready" (503) but stays up; liveness (/healthz) keeps it running.

    The DB check is guarded by a circuit breaker: after repeated slow calls the
    breaker opens and /ready returns immediately (fail fast) instead of hanging
    for DB_TIMEOUT on every request.
    """
    ok, elapsed_ms, detail, breaker = _check_database_guarded()
    if ok:
        log.info("READY ok db_ms=%.1f breaker=%s", elapsed_ms, breaker)
        return jsonify(status="ready", db_ms=round(elapsed_ms, 1), breaker=breaker), 200
    log.warning("READY not-ready db_ms=%.1f breaker=%s detail=%s",
                elapsed_ms, breaker, detail)
    return (
        jsonify(status="not-ready", db_ms=round(elapsed_ms, 1),
                breaker=breaker, detail=detail),
        503,
    )


@app.get("/")
def index():
    return jsonify(
        service="iddos-app",
        endpoints=["/work", "/health", "/healthz", "/ready"],
        db_target=f"{DB_HOST}:{DB_PORT}",
        db_timeout_s=DB_TIMEOUT,
    ), 200


if __name__ == "__main__":
    log.info(
        "starting iddos-app port=%d db=%s:%d timeout=%.1fs",
        APP_PORT, DB_HOST, DB_PORT, DB_TIMEOUT,
    )
    # threaded=True so /health and /work can be served concurrently; a stuck
    # /health must not block /work (that is the whole point of the demo).
    app.run(host="0.0.0.0", port=APP_PORT, threaded=True)
