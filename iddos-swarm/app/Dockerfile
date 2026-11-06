# iddos-app:vuln — the VULNERABLE victim image.
#
# The vulnerability lives in the HEALTHCHECK below: it calls /health, which in
# turn depends on the database (through Toxiproxy). A slow database therefore
# fails the container health-check, and Swarm restarts a process that is in
# fact perfectly alive. Step 5 replaces this with a local-only liveness probe.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    APP_PORT=8000

WORKDIR /app

# Install Python dependencies first for better layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

EXPOSE 8000

# --- The vulnerable health-check -------------------------------------------
# It probes /health, which performs a database round-trip through Toxiproxy.
# Short timeout + short interval + few retries => a slow DB quickly flips the
# container to "unhealthy", which drives Swarm's restart decision.
# The probe uses only the Python standard library (no curl needed).
HEALTHCHECK --interval=5s --timeout=3s --retries=3 --start-period=10s \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health', timeout=3).status==200 else 1)" || exit 1

CMD ["python", "app.py"]
