# iddos-swarm — Indirect DoS via Health-Check Manipulation in Docker Swarm

Information Security CEP-2026 · NED University, Software Engineering · Group B14

A single-node Docker Swarm lab that demonstrates how slowing a **dependency**
(a database) can push a healthy service into a **restart storm** — an indirect
denial of service — because one health-check drives both traffic routing and
restart decisions. The project then builds a detector and a mitigation, and
measures the before/after result.

> **Scope:** one machine, one Swarm node, one dummy web service, one database.
> The attack is a controlled latency injection through Toxiproxy. The victim
> container is never touched directly. This keeps the lab safe and repeatable.

## Prerequisites

- Docker Engine with Swarm mode (`docker swarm init`, one Ready node).
- Python 3.12+ with `pip`.
- Python packages: `docker`, `requests`.
- Base images pulled: `python:3.12-slim`, `postgres:16`,
  `ghcr.io/shopify/toxiproxy:2.9.0`.

## Repository layout

```
iddos-swarm/
  app/         the dummy web service (Flask) + Dockerfile
  stack/       Swarm stack files (vulnerable and mitigated)
  attack/      latency-injection scripts (Toxiproxy control)
  detector/    the monitor script
  load/        the load generator + availability meter
  demo/        reset and demo scripts
  results/     captured logs, metrics, and charts
  report/      the project report and figures
  README.md    how to run each step
```

## Run order (one step per work package)

| Step | What it does | Key artifacts |
| ---- | ------------ | ------------- |
| 0 | **Environment setup** — single-node Swarm, repo skeleton, base images | this repo, `docker node ls` |
| 1 | **Web service** — Flask app with `/work` (no DB) and `/health` (DB via Toxiproxy) | `app/app.py`, `app/Dockerfile`, image `iddos-app:vuln` |
| 2 | **Vulnerable stack** — deploy `web` + `db` + `toxiproxy` with vulnerable settings | `stack/vulnerable.yml` |
| 3 | **Attack** — add a latency toxic, capture the restart storm and outage | `attack/inject_latency.py`, `results/` evidence |
| 4 | **Detector** — monitor health events, restart counts, and the signature signal | `detector/monitor.py`, `results/alerts.log` |
| 5 | **Mitigation** — liveness-only check + tuned restart policy; same attack fails | `iddos-app:fixed`, `stack/mitigated.yml` |
| 6 | **Measure** — baseline / vulnerable / mitigated; four metrics | `load/run.py`, `results/metrics.csv` |
| 7 | **Report** — write up method, evidence, and results | `report/` |
| 8 | **Demo** — repeatable live runbook | `demo/reset.sh`, `demo/attack.sh`, `demo/fix.sh` |

Steps 1, 2, and 4 can overlap once the vulnerable stack exists. Keep the attack,
mitigation, and measurement steps in order — each uses the result of the one
before it.

### Optional defence-in-depth (Step 5 extra)

`stack/mitigated-plus.yml` adds two optional layers on top of the core fix:

- a **circuit breaker** around the DB call, so `/ready` fails fast (≈10 ms)
  instead of hanging for `DB_TIMEOUT` once the database is repeatedly slow;
- a **reverse proxy** (`proxy`, HAProxy on `:8080`) that health-checks the web
  service on `/ready` and de-routes a slow instance **without killing it**.

Use the clean `stack/mitigated.yml` for the Step 6 before/after comparison;
`mitigated-plus.yml` is only for demonstrating the extra layers. Evidence:
`results/defense_in_depth_proof.txt`.

## Quick start (Steps 0–1, done)

```bash
# Step 0 — environment
docker swarm init                 # already active on this host
docker node ls                    # one node, STATUS Ready
pip install docker requests

# Step 1 — build the web service image
docker build -t iddos-app:vuln app/
```

See each step's section in the project plan for the full task list and the
"Done when" checks.
