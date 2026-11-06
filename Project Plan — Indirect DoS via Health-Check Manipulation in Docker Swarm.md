# Project Plan — Indirect DoS via Health-Check Manipulation in Docker Swarm

Nov 7, 2026 · @B14

*Information Security CEP-2026 · NED University, Software Engineering*

## Overview and demo flow

This project shows how an attacker can take a Docker Swarm service offline without touching it. The attacker only slows a dependency that the service health-check calls. Swarm then restarts the service again and again — a restart storm — and the service goes down. The project also builds a detector and a fix, and measures the result.

**The core weakness**

- In Docker Swarm, one health-check drives two actions at once: traffic routing and restart decisions.
- Many health-checks call a dependency, such as a database.
- When the dependency is slow, the health-check times out and fails.
- The restart policy then kills and restarts the task. The new task fails the same check. The loop repeats.

**Scope (kept simple on purpose)**

- One machine only. One node. No virtual machine and no cloud.
- You start Swarm with one command: `docker swarm init`.
- A small dummy web app is the victim service.

**The demonstration has three parts**

1. Show the problem. Deploy the vulnerable stack, slow the database, and record the outage.
2. Apply the fix. Change the health-check and the restart policy, then run the same attack.
3. Report. Record the numbers before and after, and write the report.

## Architecture and testbed

&#91;embedded content: Testbed on one Swarm node · request path, attack, and monitor\]

All parts run on one host. The attacker reaches only Toxiproxy and the database — never the web service. Docker runs the `/health` probe; when the database is slow, the probe fails and Swarm restarts the healthy service until it is down.

## Tools, stack, and repository layout

Use a small, well-known stack so the group can finish on time.

**Recommended stack**

| Part | Tool | Why |
| --- | --- | --- |
| Orchestrator | Docker Swarm (single node) | The subject of the study |
| Web service | Python + Flask | Simple to write and read |
| Dependency | PostgreSQL | A realistic database dependency |
| Latency injector | Toxiproxy | Adds delay to the database on command |
| Detector | Python + Docker SDK | Reads Docker events and restart counts |
| Load generator | Python `requests`, or `hey` | Measures availability during the test |

**Install on the host**

1. Install Docker Engine (it includes Swarm mode).
2. Start Swarm: `docker swarm init`.
3. Install Python 3 and `pip`.
4. Install the Python packages: `docker` and `requests`.

**Repository layout**

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

Keep two stack files: one vulnerable and one mitigated. The only differences are the health-check and the restart policy. This keeps the before/after comparison clean.

## Step 0 — Environment setup

**Goal:** a working single-node Swarm and an empty project repository.

**Tasks**

1. Install Docker Engine on the host.
2. Run `docker swarm init`. Confirm with `docker node ls` (one node, status Ready).
3. Create the repository folders from the layout above.
4. Add a `README.md` with the run order of all steps.
5. Install Python 3, `pip`, and the packages `docker` and `requests`.
6. Pull the base images first: `python:3.12-slim`, `postgres:16`, and the Toxiproxy image.

**Deliverables**

- A single-node Swarm in Ready state.
- The repository skeleton with all folders.
- A `README.md` with the step order.

**Done when**

- `docker node ls` shows one Ready node.
- `docker info` shows Swarm active.
- All folders exist, and the base images are present (`docker images`).

## Step 1 — Build the dummy web service

**Goal:** a small Flask app that proves the app logic works while its health-check depends on the database.

**Design two separate endpoints**

- `GET /work` — does real app work and returns 200. It does not call the database. This proves the app is alive and correct.
- `GET /health` — the vulnerable check. It runs a database query through Toxiproxy and returns 200 only if the query answers in time.

**Add clear logging**

- Log every `/work` success with a timestamp.
- Log every `/health` result (pass or fail) with the response time.
- This log is the evidence for the signature signal: app success while the health-check fails.

**Tasks**

1. Write `app/app.py` with `/work` and `/health`.
2. Read the database host, port, and timeout from environment variables.
3. Write `app/Dockerfile`. Add a `HEALTHCHECK` that calls `/health` with a short timeout (for example `--timeout=3s --interval=5s --retries=3`).
4. Build the image: `docker build -t iddos-app:vuln app/`.

**Deliverables**

- `app/app.py`, `app/Dockerfile`, and a built image `iddos-app:vuln`.

**Done when**

- `/work` returns 200 with no database.
- `/health` returns 200 when the database is fast, and fails when the database is slow.
- The container logs show both endpoints clearly.

**Keep it simple:** use one small table, or even a `SELECT 1` query, for `/health`. The point is the dependency call, not the data.

## Step 2 — Deploy the vulnerable stack

**Goal:** run the service, the database, and the latency injector as one Swarm stack with the vulnerable settings.

**Stack services** (`stack/vulnerable.yml`, compose version 3.8)

- `web` — the `iddos-app:vuln` image. The health-check calls `/health`. The vulnerable restart policy uses `condition: any`, a short `delay`, and no `max_attempts`.
- `db` — PostgreSQL.
- `toxiproxy` — sits between `web` and `db`. The app connects to the database through Toxiproxy, not directly.

**Key vulnerable settings** (state them clearly in the file)

- The `HEALTHCHECK` depends on the database.
- `restart_policy` has no limit, so restarts can loop without end.

**Tasks**

1. Write `stack/vulnerable.yml` with the three services on one overlay network.
2. Set the app to reach the database through the Toxiproxy address.
3. Create the Toxiproxy route (proxy) from `web` to `db` at start-up.
4. Deploy: `docker stack deploy -c stack/vulnerable.yml app`.
5. Confirm the services are healthy: `docker service ls` and `docker stack ps app`.

**Deliverables**

- `stack/vulnerable.yml` and a running, healthy stack.

**Done when**

- `docker service ls` shows `web` replicated and healthy.
- `/work` and `/health` both return 200 through the stack.
- Toxiproxy passes database traffic with no added delay.

## Step 3 — Demonstrate the attack

**Goal:** prove that added database latency causes a restart storm and an outage, while the app code stays correct.

The attack is one action: add a latency *toxic* to the Toxiproxy route so database replies take longer than the health-check timeout.

**Procedure**

1. Record the baseline. Start the load generator against `/work`. Confirm availability near 100%.
2. Start the detector and the metric logger.
3. Launch the attack. Add a latency toxic (for example 5000 ms) with the Toxiproxy API.
4. Observe the restart storm:
   - `/health` times out and fails.
   - Swarm marks the task unhealthy and restarts it.
   - The new task fails the same check. The restarts repeat.
5. Capture the evidence:
   - `docker stack ps app` shows the restart count climbing.
   - The app log shows `/work` still succeeds when reachable.
   - Availability of `/work` drops as tasks are killed mid-request.
6. Stop the attack. Remove the toxic. Confirm the service recovers.

**Deliverables**

- `attack/inject_latency.py` (add and remove the toxic).
- A captured evidence set in `results/`: `docker stack ps` output, app logs, and the availability log.

**Done when**

- The restart count rises fast during the attack.
- The service is unavailable, but the app log shows the code still works.
- The service recovers after the toxic is removed.

**Important:** the victim container is never attacked. Only the database path is slowed.

## Step 4 — Build the detection layer

**Goal:** a small monitor that detects the restart storm in real time and names its cause.

**What the monitor watches**

- *Docker health events.* Stream `docker events` filtered to `health_status`. Detect repeated `starting → unhealthy` transitions inside a sliding window.
- *Restart frequency.* Poll the service tasks and count restarts per service. Alert when the count crosses a threshold, for example more than 5 restarts in 2 minutes.
- *The signature signal.* Compare app log success against health-check failure. When `/work` succeeds but `/health` fails, flag an indirect denial-of-service, not a real crash.

**Tasks**

1. Write `detector/monitor.py` using the Docker SDK for Python.
2. Stream health-state events and keep a per-service sliding window.
3. Count restarts per service and apply the threshold.
4. Read the app log (or a shared status endpoint) to detect the divergence signal.
5. Print clear alerts and write them to `results/alerts.log`.

**Deliverables**

- `detector/monitor.py` and a sample `results/alerts.log` from an attack run.

**Done when**

- The monitor raises an alert within a set time during the attack (the time-to-detection metric).
- The alert states the cause: dependency latency, not an application crash.

Keep the thresholds in a small config block so the group can tune them.

## Step 5 — Apply the mitigation

**Goal:** stop the restart storm by separating process health from dependency health, then prove the same attack fails.

**Core fix (required, simple)**

- Make the Docker `HEALTHCHECK` a local-only liveness probe. It checks that the process answers, and it does not call the database. A slow database no longer fails the check, so Swarm no longer kills the container.
- Tune the restart policy. Add `max_attempts` and a backoff `window`, so even a real failure cannot storm.

**Defence-in-depth (optional, add if time allows)**

- Add a readiness endpoint. `GET /ready` checks the database. A reverse proxy uses `/ready` to route traffic. When the database is slow, the service leaves the rotation but is not killed.
- Add a circuit breaker around the database call. After repeated slow calls, the app fails fast and returns a clear error, instead of hanging.

**Tasks**

1. Add a local liveness endpoint (for example `/healthz`) and point the Dockerfile `HEALTHCHECK` at it.
2. Build a mitigated image `iddos-app:fixed`.
3. Write `stack/mitigated.yml` with the liveness-only check and the tuned restart policy.
4. (Optional) add `/ready` and a small reverse proxy; add the circuit breaker.
5. Deploy the mitigated stack and run the same attack from Step 3.

**Deliverables**

- The app changes, `iddos-app:fixed`, and `stack/mitigated.yml`.

**Done when**

- The same latency attack no longer causes a restart storm.
- The service stays up. It may serve a clear "degraded" response, but it stays available.
- The restart count stays low or zero during the attack.

## Step 6 — Measure and compare

**Goal:** numbers that prove the fix works. Run the same test in three scenarios and record the metrics.

**Scenarios**

1. Baseline — no attack.
2. Attack on the vulnerable stack.
3. Attack on the mitigated stack.

**Metrics** (define once, measure the same way each time)

| Metric | Meaning | How to measure |
| --- | --- | --- |
| Availability % | Share of `/work` requests that succeed | Success count ÷ total requests |
| restart\_count | Task restarts during the window | `docker stack ps` / Docker API |
| MTTR | Mean time to recover after the attack stops | Time from toxic removed to healthy |
| Time-to-detection | Delay from attack start to the first alert | Detector time − attack time |

**Tasks**

1. Write `load/run.py` to send steady `/work` requests and record success and latency.
2. Run each scenario for a fixed time (for example 3 minutes).
3. Collect the four metrics for each run into `results/metrics.csv`.
4. Build a before/after table and one or two charts.

**Deliverables**

- `load/run.py`, `results/metrics.csv`, and a before/after comparison table.

**Done when**

- The three runs are complete and repeatable.
- The table shows a clear delta: the mitigated stack keeps availability high and restart\_count low.

## Step 7 — Write the project report

**Goal:** a clear report that follows the slides and uses the measured results.

**Suggested sections** (map to the slide deck)

1. Introduction and motivation — the health-check that drives both routing and restarts.
2. Problem description — the indirect denial-of-service and the restart storm.
3. Relevance to containers — why this is an orchestration problem, not a generic web-app bug.
4. Threat model — the attacker slows a dependency; the victim container is never touched.
5. Testbed design — the single-node Swarm, the services, and the latency injector.
6. Attack demonstration — method, evidence, and the baseline outage.
7. Detection — the monitor, the thresholds, and the signature signal.
8. Mitigation — the liveness-only check, the tuned restart policy, and the optional layers.
9. Results — the before/after table and charts for the four metrics.
10. Conclusion and future work.
11. References — use the list from the approved topic.

**Tasks**

1. Fill each section from the captured results.
2. Add the before/after table and the charts.
3. Add screenshots of the restart storm and the recovered state.
4. Cite the references already approved for the topic.

**Deliverables**

- The report in `report/`, with figures and tables.

**Done when**

- Every section is complete and backed by evidence from `results/`.
- The report matches the demonstration the group will show.

## Step 8 — Prepare the demonstration

**Goal:** a short, repeatable live demo that shows the problem, then the fix.

**Demo runbook (about 8–10 minutes)**

1. Show the healthy stack. Run the load generator. Point to near-100% availability.
2. Start the detector so the audience sees live alerts.
3. Launch the attack (add the latency toxic). Watch the restart count climb and availability fall.
4. Show the app log: `/work` still works. The app is not broken; Swarm is killing it.
5. Remove the attack. Deploy the mitigated stack.
6. Launch the same attack. Show that the service stays up and the restart count stays flat.
7. Show the before/after table.

**Tasks**

1. Write reset scripts so the demo starts clean every time (`demo/reset.sh`, `demo/attack.sh`, `demo/fix.sh`).
2. Rehearse the full run at least twice.
3. Prepare a fallback recording in case the live demo fails.

**Deliverables**

- The demo scripts and a tested runbook in `demo/`.
- A backup screen recording in `results/`.

**Done when**

- The full demo runs end to end from a clean state in one session.
- Each step shows a clear, visible result.

## Metrics and acceptance criteria

Use these targets to judge success. They are simple and easy to show.

| Metric | Vulnerable (expected) | Mitigated (target) |
| --- | --- | --- |
| Availability % of `/work` during attack | Large drop (service down) | Stays high (for example ≥ 95%) |
| restart\_count during a 3-minute attack | High and rising | Low or zero |
| MTTR after the attack stops | Longer (the storm must settle) | Short (no storm) |
| Time-to-detection | Not applicable (no detector) | Within a set time (for example ≤ 30 s) |

**Acceptance criteria for the whole project**

- The attack reproducibly causes a restart storm on the vulnerable stack.
- The detector alerts during the attack and names the cause.
- The same attack does not cause a storm on the mitigated stack.
- The before/after table shows a clear, measured improvement.

Set the exact numbers after the first baseline run. Real values from your own host are better than guesses.

## Scope limits and simplifications

State these in the report so the scope is clear and the work stays at undergraduate level.

- **One node only.** No multi-node cluster, no cloud, and no virtual machine. A single-node Swarm shows the same restart behaviour.
- **One dependency.** One database is enough to show the cascade. More services are not needed.
- **Toxiproxy for latency.** It is simple and repeatable. A network tool such as `tc netem` is an alternative, but it is harder to set up.
- **The liveness/readiness split is the core fix.** The reverse proxy, the readiness routing, and the circuit breaker are optional extras, added only if time allows.
- **No real attacker tooling.** The attack is a controlled latency injection. This keeps the lab safe and legal.

These limits keep the project small, safe, and easy to demonstrate, while still proving the full idea.

## How to delegate steps to agents

Hand the steps to agents in order. Each step above is one work package. Give each agent only what it needs.

**Order of delegation**

1. Step 0 — Environment setup.
2. Step 1 — Web service.
3. Step 2 — Vulnerable stack.
4. Step 3 — Attack demonstration.
5. Step 4 — Detector.
6. Step 5 — Mitigation.
7. Step 6 — Measurement.
8. Step 7 — Report.
9. Step 8 — Demo.

**For each agent, give**

- **Input:** the repository state from the previous step, and that step's section from this plan.
- **Task:** the numbered tasks in the section.
- **Output:** the listed deliverable files, saved in the right folder.
- **Check:** the "Done when" list for that step.

**Rules for a clean hand-off**

- One step per agent. Do not mix steps.
- Each agent saves (commits) its files before the next step starts.
- If a step changes a shared file (for example the app), note the change for the next agent.

Steps 1, 2, and 4 can overlap once the vulnerable stack exists. Keep the attack, mitigation, and measurement steps in order, because each one uses the result of the step before it.
