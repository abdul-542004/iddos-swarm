"""attack/capture_evidence.py — run the attack and capture the evidence.

Timeline:
    1. BASELINE  — sample /work, confirm ~100% availability (no attack).
    2. ATTACK    — add the latency toxic; keep sampling while Swarm storms.
    3. RECOVERY  — remove the toxic; confirm the service comes back.

While it runs it:
    * samples GET /work twice a second (availability of real app work),
    * snapshots `docker stack ps app` and the web restart count every few
      seconds (the restart storm),
    * at the end dumps the web service logs (the signature signal: /work
      succeeds while /health fails).

Outputs (under results/):
    availability_attack.csv   one row per /work sample
    stack_ps_attack.log       timestamped `docker stack ps` snapshots
    app_web_logs.txt          web service logs across the run
    attack_summary.txt        per-phase availability + restart counts

This is attack-demo evidence capture. The formal metric runner is Step 6.
"""

import csv
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RESULTS = os.path.join(ROOT, "results")
INJECT = os.path.join(HERE, "inject_latency.py")

WORK_URL = os.environ.get("WORK_URL", "http://localhost:8000/work")
SERVICE = os.environ.get("SERVICE", "app_web")
STACK = os.environ.get("STACK", "app")
LATENCY_MS = int(os.environ.get("LATENCY_MS", "5000"))

# Phase durations (seconds) — override via CLI args: baseline attack recovery
BASELINE_S = 15
ATTACK_S = 120
RECOVERY_S = 45

SAMPLE_HZ = 2.0            # /work samples per second
SNAPSHOT_EVERY_S = 5       # docker stack ps snapshot cadence


def now_iso():
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%dT%H:%M:%S")


def docker(args):
    try:
        out = subprocess.run(
            ["docker"] + args, capture_output=True, text=True, timeout=20
        )
        return (out.stdout or "") + (out.stderr or "")
    except Exception as exc:  # noqa: BLE001
        return f"<docker error: {exc}>\n"


def web_restart_count():
    """Count replaced web tasks (DesiredState=Shutdown) == restarts so far."""
    out = docker(["service", "ps", SERVICE, "--format", "{{.DesiredState}}"])
    return sum(1 for line in out.splitlines() if line.strip().lower().startswith("shutdown"))


class Sampler(threading.Thread):
    """Continuously sample /work and record each result with its phase."""

    def __init__(self):
        super().__init__(daemon=True)
        self.rows = []          # (ts, phase, ok, code, latency_ms)
        self.phase = "baseline"
        self._stop = threading.Event()

    def run(self):
        period = 1.0 / SAMPLE_HZ
        while not self._stop.is_set():
            t0 = time.monotonic()
            ok, code = False, 0
            try:
                r = requests.get(WORK_URL, timeout=2)
                code = r.status_code
                ok = (code == 200)
            except Exception:  # noqa: BLE001 - timeout/refused == unavailable
                ok, code = False, 0
            latency_ms = (time.monotonic() - t0) * 1000.0
            self.rows.append((now_iso(), self.phase, int(ok), code, round(latency_ms, 1)))
            dt = period - (time.monotonic() - t0)
            if dt > 0:
                time.sleep(dt)

    def stop(self):
        self._stop.set()


def availability(rows, phase):
    pts = [r for r in rows if r[1] == phase]
    if not pts:
        return (0.0, 0, 0)
    ok = sum(r[2] for r in pts)
    return (100.0 * ok / len(pts), ok, len(pts))


def run_phase(name, seconds, sampler, snap_fp):
    sampler.phase = name
    print(f"[{now_iso()}] --- {name.upper()} ({seconds}s) ---")
    end = time.monotonic() + seconds
    next_snap = 0.0
    while time.monotonic() < end:
        if time.monotonic() >= next_snap:
            rc = web_restart_count()
            header = f"\n===== {now_iso()} phase={name} web_restarts={rc} =====\n"
            snap_fp.write(header)
            snap_fp.write(docker(["stack", "ps", STACK, "--no-trunc"]))
            snap_fp.flush()
            print(f"[{now_iso()}] {name}: web_restarts={rc}")
            next_snap = time.monotonic() + SNAPSHOT_EVERY_S
        time.sleep(0.5)


def main():
    global BASELINE_S, ATTACK_S, RECOVERY_S
    args = sys.argv[1:]
    if len(args) == 3:
        BASELINE_S, ATTACK_S, RECOVERY_S = (int(a) for a in args)

    os.makedirs(RESULTS, exist_ok=True)
    snap_path = os.path.join(RESULTS, "stack_ps_attack.log")
    csv_path = os.path.join(RESULTS, "availability_attack.csv")
    logs_path = os.path.join(RESULTS, "app_web_logs.txt")
    summary_path = os.path.join(RESULTS, "attack_summary.txt")

    sampler = Sampler()
    sampler.start()

    with open(snap_path, "w", encoding="utf-8") as snap_fp:
        rc_start = web_restart_count()
        snap_fp.write(f"ATTACK EVIDENCE RUN  start={now_iso()}  latency={LATENCY_MS}ms\n")
        snap_fp.write(f"web_restarts at start = {rc_start}\n")

        run_phase("baseline", BASELINE_S, sampler, snap_fp)

        print(f"[{now_iso()}] >>> adding latency toxic ({LATENCY_MS}ms)")
        subprocess.run([sys.executable, INJECT, "add", "--latency", str(LATENCY_MS)],
                       capture_output=True, text=True)
        run_phase("attack", ATTACK_S, sampler, snap_fp)

        print(f"[{now_iso()}] >>> removing latency toxic")
        subprocess.run([sys.executable, INJECT, "remove"], capture_output=True, text=True)
        run_phase("recovery", RECOVERY_S, sampler, snap_fp)

        rc_end = web_restart_count()
        snap_fp.write(f"\nweb_restarts at end = {rc_end}\n")

    sampler.stop()
    time.sleep(0.5)
    rows = sampler.rows

    # Write per-sample availability CSV.
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["timestamp", "phase", "ok", "http_code", "latency_ms"])
        w.writerows(rows)

    # Dump web service logs (signature signal lives here).
    with open(logs_path, "w", encoding="utf-8") as f:
        f.write(docker(["service", "logs", "--no-task-ids", SERVICE]))

    # Summary.
    rc_end = web_restart_count()
    lines = []
    lines.append(f"Attack evidence summary  ({now_iso()})")
    lines.append(f"latency toxic = {LATENCY_MS} ms   phases(s): "
                 f"baseline={BASELINE_S} attack={ATTACK_S} recovery={RECOVERY_S}")
    lines.append("")
    lines.append(f"{'phase':<10} {'availability%':>13} {'ok/total':>12}")
    for ph in ("baseline", "attack", "recovery"):
        pct, ok, total = availability(rows, ph)
        lines.append(f"{ph:<10} {pct:>12.1f}% {f'{ok}/{total}':>12}")
    lines.append("")
    lines.append(f"web restart count (replaced tasks) at end = {rc_end}")
    lines.append("")
    lines.append("Signature signal: during the attack /work stays available in")
    lines.append("app logs while /health fails -> indirect DoS, not a crash.")
    summary = "\n".join(lines) + "\n"

    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(summary)

    print("\n" + summary)
    print(f"evidence written to {RESULTS}")


if __name__ == "__main__":
    main()
