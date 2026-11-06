"""load/measure.py — run the three scenarios and collect the four metrics.

Scenarios (same attack, same timing, measured the same way):
    1. baseline            vulnerable stack, NO attack        (control)
    2. vulnerable_attack   vulnerable stack, latency attack
    3. mitigated_attack    mitigated  stack, latency attack

Metrics per run:
    availability_pct   share of /work requests that return 200
    restart_count      web task restarts during the attack window
    mttr_s             time from toxic removed to web healthy again
    ttd_s             time from attack start to the detector's first alert

Outputs:
    results/metrics.csv        one row per scenario
    results/metrics_table.md   the before/after comparison table
    results/alerts_*.log       detector alerts captured per attack scenario

Run from the iddos-swarm/ directory:
    python load/measure.py
"""

import csv
import os
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RESULTS = os.path.join(ROOT, "results")
sys.path.insert(0, HERE)                       # run.py
sys.path.insert(0, os.path.join(ROOT, "detector"))  # monitor.py

from run import Sampler, availability, latency_stats  # noqa: E402
import monitor  # noqa: E402
from monitor import Detector, parse_ts  # noqa: E402

# --- knobs -----------------------------------------------------------------
WORK_URL = "http://localhost:8000/work"
RATE_HZ = 5.0
SETTLE_S = 15
BASELINE_S = 45
ATTACK_S = 90
MTTR_CAP_S = 120
LATENCY_MS = 5000
STACK = "app"
SERVICE = "app_web"
# ---------------------------------------------------------------------------


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def docker(args, timeout=60):
    return subprocess.run(["docker"] + args, capture_output=True, text=True, timeout=timeout)


def inject(cmd):
    subprocess.run([sys.executable, os.path.join(ROOT, "attack", "inject_latency.py"), cmd],
                   capture_output=True, text=True)


def web_health():
    out = docker(["ps", "--filter", f"label=com.docker.swarm.service.name={SERVICE}",
                  "--format", "{{.Status}}"]).stdout.lower()
    if "healthy" in out and "unhealthy" not in out:
        return "healthy"
    if "unhealthy" in out:
        return "unhealthy"
    if out.strip():
        return "starting"
    return "none"


def web_restart_count_since(epoch):
    """Count web task restarts (shutdown tasks) with a timestamp in the window."""
    cnt = 0
    try:
        client = monitor.docker.from_env()
        for tk in client.api.tasks(filters={"service": SERVICE}):
            if tk.get("DesiredState") != "shutdown":
                continue
            ts = parse_ts(tk.get("Status", {}).get("Timestamp", ""))
            if ts >= epoch - 2:
                cnt += 1
        client.close()
    except Exception as exc:  # noqa: BLE001
        log(f"restart count error: {exc}")
    return cnt


def wait_network_gone(name="app_iddosnet", cap=40):
    for _ in range(cap):
        if not docker(["network", "ls", "--filter", f"name={name}", "-q"]).stdout.strip():
            return
        time.sleep(1)


def wait_web_healthy(cap=120):
    for _ in range(cap):
        if web_health() == "healthy":
            return True
        time.sleep(2)
    return False


def deploy(stack_file):
    log(f"removing stack '{STACK}' ...")
    docker(["stack", "rm", STACK])
    wait_network_gone()
    log(f"deploying {stack_file} ...")
    docker(["stack", "deploy", "-c", os.path.join(ROOT, "stack", stack_file), STACK])
    log("waiting for web to become healthy ...")
    ok = wait_web_healthy(cap=90)
    log(f"web healthy: {ok}")
    time.sleep(SETTLE_S)


def measure_mttr(attack_end):
    """Seconds from toxic removed (attack_end) to web healthy again."""
    deadline = time.time() + MTTR_CAP_S
    while time.time() < deadline:
        if web_health() == "healthy":
            return round(time.time() - attack_end, 1)
        time.sleep(2)
    return float(MTTR_CAP_S)  # did not recover within cap


def run_attack_phase(sampler, scenario):
    """Run detector + attack, return (restart_count, mttr_s, ttd_s)."""
    det = Detector()
    det_thread = threading.Thread(target=det.run, kwargs={"duration_s": ATTACK_S + 40},
                                  daemon=True)
    det_thread.start()
    time.sleep(1)

    sampler.phase = "attack"
    attack_start = time.time()
    log(f"{scenario}: ATTACK ON ({LATENCY_MS}ms)")
    inject("add")
    time.sleep(ATTACK_S)
    inject("remove")
    attack_end = time.time()
    log(f"{scenario}: ATTACK OFF")

    sampler.phase = "recovery"
    restart_count = web_restart_count_since(attack_start)
    mttr = measure_mttr(attack_end)

    det._stop.set()
    det_thread.join(timeout=5)

    # Preserve this scenario's alert log.
    try:
        shutil.copyfile(os.path.join(RESULTS, "alerts.log"),
                        os.path.join(RESULTS, f"alerts_{scenario}.log"))
    except Exception:  # noqa: BLE001
        pass

    ttd = ""
    if det.first_alert_iso:
        try:
            fa = datetime.strptime(det.first_alert_iso, "%Y-%m-%dT%H:%M:%S").timestamp()
            ttd = round(fa - attack_start, 1)
        except Exception:  # noqa: BLE001
            ttd = ""
    log(f"{scenario}: restart_count={restart_count} mttr={mttr}s ttd={ttd} "
        f"alerts={det.alert_count}")
    return restart_count, mttr, ttd


def main():
    os.makedirs(RESULTS, exist_ok=True)
    results = []  # dict rows

    # ---- Scenarios 1 & 2 on the vulnerable stack -------------------------
    deploy("vulnerable.yml")
    sampler = Sampler(WORK_URL, rate_hz=RATE_HZ)
    sampler.start()

    sampler.phase = "baseline"
    log("baseline (no attack) ...")
    time.sleep(BASELINE_S)
    b_pct, b_ok, b_tot = availability(sampler.rows, "baseline")
    b_avg, b_p95 = latency_stats(sampler.rows, "baseline")
    results.append(dict(scenario="baseline", stack="vulnerable", attack="no",
                        availability_pct=round(b_pct, 1), restart_count=0,
                        mttr_s="", ttd_s="", lat_avg_ms=b_avg, lat_p95_ms=b_p95,
                        samples=b_tot))

    rc, mttr, ttd = run_attack_phase(sampler, "vulnerable_attack")
    v_pct, v_ok, v_tot = availability(sampler.rows, "attack")
    v_avg, v_p95 = latency_stats(sampler.rows, "attack")
    results.append(dict(scenario="vulnerable_attack", stack="vulnerable", attack="yes",
                        availability_pct=round(v_pct, 1), restart_count=rc,
                        mttr_s=mttr, ttd_s=ttd, lat_avg_ms=v_avg, lat_p95_ms=v_p95,
                        samples=v_tot))
    sampler.stop()
    time.sleep(0.3)

    # ---- Scenario 3 on the mitigated stack -------------------------------
    deploy("mitigated.yml")
    sampler = Sampler(WORK_URL, rate_hz=RATE_HZ)
    sampler.start()
    sampler.phase = "warmup"
    time.sleep(5)
    rc, mttr, ttd = run_attack_phase(sampler, "mitigated_attack")
    m_pct, m_ok, m_tot = availability(sampler.rows, "attack")
    m_avg, m_p95 = latency_stats(sampler.rows, "attack")
    results.append(dict(scenario="mitigated_attack", stack="mitigated", attack="yes",
                        availability_pct=round(m_pct, 1), restart_count=rc,
                        mttr_s=mttr, ttd_s=ttd, lat_avg_ms=m_avg, lat_p95_ms=m_p95,
                        samples=m_tot))
    sampler.stop()
    time.sleep(0.3)

    # ---- write metrics.csv ----------------------------------------------
    cols = ["scenario", "stack", "attack", "availability_pct", "restart_count",
            "mttr_s", "ttd_s", "lat_avg_ms", "lat_p95_ms", "samples"]
    csv_path = os.path.join(RESULTS, "metrics.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(results)

    # ---- write before/after table ---------------------------------------
    def row(r):
        ttd = r["ttd_s"] if r["ttd_s"] != "" else "—"
        mttr = r["mttr_s"] if r["mttr_s"] != "" else "—"
        return (f"| {r['scenario']} | {r['stack']} | {r['attack']} | "
                f"{r['availability_pct']}% | {r['restart_count']} | {mttr} | {ttd} |")

    table = [
        "# Step 6 — before/after metrics",
        "",
        f"Same latency attack ({LATENCY_MS} ms), {ATTACK_S}s attack window, "
        f"/work sampled at {RATE_HZ}/s.",
        "",
        "| Scenario | Stack | Attack | Availability | Restarts | MTTR (s) | TTD (s) |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ] + [row(r) for r in results] + [
        "",
        "- **Availability** — share of `/work` requests returning 200.",
        "- **Restarts** — web task restarts during the attack window.",
        "- **MTTR** — seconds from toxic removed to web healthy again.",
        "- **TTD** — seconds from attack start to the detector's first alert "
        "(`—` = no alert, i.e. no storm to detect).",
    ]
    table_path = os.path.join(RESULTS, "metrics_table.md")
    with open(table_path, "w", encoding="utf-8") as f:
        f.write("\n".join(table) + "\n")

    print("\n" + "\n".join(table))
    print(f"\nwrote {csv_path}\nwrote {table_path}")


if __name__ == "__main__":
    main()
