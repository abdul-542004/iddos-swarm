# Demo runbook — Indirect DoS via Health-Check Manipulation

A repeatable 8–10 minute live demo: show the problem, then the fix.

## Before the demo

- Docker Desktop running; single-node Swarm active (`docker node ls` → one Ready node).
- Images built: `docker build -t iddos-app:vuln app/` and
  `docker build -f app/Dockerfile.fixed -t iddos-app:fixed app/`.
- Python deps: `pip install docker requests`.
- Run the whole thing once as a rehearsal (see below). Keep a **screen
  recording** of a good run as a fallback.
- Open two or three terminals, plus a browser tab on http://localhost:3000
  (Grafana) if you are showing the dashboard.

All commands are run from the `iddos-swarm/` directory.

> **Windows PowerShell users:** use the `.ps1` scripts instead of `.sh`
> (`.sh` needs a POSIX shell). The commands below show the `.sh` form; the
> PowerShell equivalents are:
>
> | Bash | PowerShell |
> | --- | --- |
> | `./demo/reset.sh` | `.\demo\reset.ps1` |
> | `./demo/reset.sh mitigated` | `.\demo\reset.ps1 mitigated` |
> | `OBS=0 ./demo/reset.sh` | `.\demo\reset.ps1 vuln -NoDashboard` |
> | `./demo/attack.sh` / `./demo/attack.sh off` | `.\demo\attack.ps1` / `.\demo\attack.ps1 off` |
> | `./demo/fix.sh` | `.\demo\fix.ps1` |
> | `./demo/detect.sh` | `.\demo\detect.ps1` |
>
> If PowerShell blocks the scripts ("running scripts is disabled"), allow them
> for this session only: `Set-ExecutionPolicy -Scope Process Bypass`.
> You can also run the `.sh` versions through Git Bash: `bash demo/reset.sh`.

## The run

**1. Clean start — vulnerable stack + dashboard (~30 s to healthy)**

```bash
./demo/reset.sh            # vulnerable stack + Grafana/Prometheus
```

Show the healthy system: `curl http://localhost:8000/work` → 200. Open Grafana
(dashboard "IDDoS — Health-Check Restart Storm"): web UP, flat lines.

**2. Start a little load and the detector (two terminals)**

```bash
# terminal A — steady load on /work, prints availability
python load/run.py --duration 300 --rate 5

# terminal B — the live detector
./demo/detect.sh
```

Point out: availability ~100%, detector quiet.

**3. Launch the attack**

```bash
# terminal C
./demo/attack.sh           # inject 5000 ms latency on the DB path
```

Watch, over ~30–60 s:
- Grafana: the **UP** panel shows red gaps; restart count climbs; `/work` rate
  dips; health **fail** line rises.
- Detector (terminal B): `INDIRECT-DOS` / `HEALTH-FLAP` / `RESTART-STORM`
  alerts, naming the cause as dependency latency — **not** a crash.
- `docker stack ps app` → web task restarts with
  `"non-zero exit (137): ... unhealthy container"`.
- The app log still shows `WORK ok` — the code is fine; Swarm is killing it.

**4. Stop the attack, show recovery**

```bash
./demo/attack.sh off
```

The service recovers; Grafana lines settle.

**5. Apply the fix**

```bash
./demo/fix.sh              # redeploy the mitigated stack (dashboard stays)
```

One line to explain: the health-check now probes `/healthz` (local liveness,
no database), and the restart policy is bounded.

**6. Run the SAME attack on the mitigated stack**

```bash
./demo/attack.sh
```

Watch: restart count stays **0**, availability stays **100%**, detector stays
**silent**. `/ready` would report "not ready" (degraded) but the service stays
up. Then:

```bash
./demo/attack.sh off
```

**7. Show the numbers**

Open `results/metrics_table.md` and the charts
`results/fig_availability.png`, `results/fig_restarts.png`:

| Scenario | Availability | Restarts | MTTR | TTD |
| --- | --- | --- | --- | --- |
| Baseline (no attack) | 100% | 0 | — | — |
| Vulnerable + attack | 21% | 2 | 13 s | 17.7 s |
| Mitigated + attack | 100% | 0 | 0.2 s | — |

## Tear down

```bash
docker stack rm app
```

## If something breaks

- Play the backup screen recording.
- Grafana slow to load: give it ~20 s after `reset.sh`, or re-open the tab.
- Attack "does nothing": confirm the toxic is set — `python attack/inject_latency.py status`.
- Want it faster/leaner: `OBS=0 ./demo/reset.sh` skips the dashboard.
