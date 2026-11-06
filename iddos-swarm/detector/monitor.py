"""detector/monitor.py — real-time detector for the indirect-DoS restart storm.

It watches three signals (per the project plan) and names the cause:

  1. Docker health events   Stream container events and catch repeated
                            `health_status: unhealthy` transitions for the
                            watched service (health flapping).
  2. Restart frequency      Poll the service tasks and count restarts in a
                            sliding window. Alert past a threshold.
  3. The signature signal   When health fails, probe /work. If /work still
                            returns 200, the application is ALIVE -> this is an
                            indirect denial-of-service from a slow dependency,
                            NOT an application crash.

Alerts are printed and appended to results/alerts.log, each stamped with the
time so Step 6 can compute time-to-detection.

Usage:
    python monitor.py [--duration SECONDS]   # 0 (default) = run until Ctrl+C
"""

import argparse
import os
import threading
import time
from collections import deque
from datetime import datetime, timezone

import docker
import requests

# ---------------------------------------------------------------------------
# Config block (tuned for the single-node demo; edit here to re-tune).
# ---------------------------------------------------------------------------
WATCH_SERVICE = os.environ.get("WATCH_SERVICE", "app_web")
WORK_URL = os.environ.get("WORK_URL", "http://localhost:8000/work")

RESTART_WINDOW_S = 120        # sliding window for counting restarts
RESTART_THRESHOLD = 2         # >= this many restarts in the window => storm
HEALTH_WINDOW_S = 120         # sliding window for counting unhealthy events
HEALTH_FLAP_THRESHOLD = 2     # >= this many unhealthy transitions => flapping

POLL_INTERVAL_S = 3           # how often to poll tasks
ALERT_COOLDOWN_S = 15         # per-alert-type rate limit
WORK_PROBE_TIMEOUT_S = 2
# ---------------------------------------------------------------------------

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ALERTS_PATH = os.path.join(ROOT, "results", "alerts.log")


def now():
    return datetime.now(timezone.utc).astimezone()


def now_iso():
    return now().strftime("%Y-%m-%dT%H:%M:%S")


def parse_ts(ts: str) -> float:
    """Parse a Docker RFC3339 timestamp to epoch seconds (tolerant of nanos)."""
    if not ts:
        return 0.0
    ts = ts.strip()
    # Trim fractional seconds to 6 digits so %f parses.
    if "." in ts:
        head, frac = ts.split(".", 1)
        tzsuffix = ""
        for i, ch in enumerate(frac):
            if ch in "+-Zz":
                tzsuffix = frac[i:]
                frac = frac[:i]
                break
        frac = (frac + "000000")[:6]
        ts = f"{head}.{frac}{tzsuffix}"
    ts = ts.replace("Z", "+00:00").replace("z", "+00:00")
    try:
        return datetime.fromisoformat(ts).timestamp()
    except ValueError:
        return 0.0


class Detector:
    def __init__(self):
        self.client = docker.from_env()
        self.api = self.client.api
        self.unhealthy_events = deque()      # epoch seconds of unhealthy events
        self.lock = threading.Lock()
        self._last_alert = {}                # alert-type -> monotonic time
        self._stop = threading.Event()
        self.first_alert_iso = None
        self.alert_count = 0
        # Reset the alert log for a clean sample run.
        os.makedirs(os.path.dirname(ALERTS_PATH), exist_ok=True)
        with open(ALERTS_PATH, "w", encoding="utf-8") as f:
            f.write(f"# detector started {now_iso()}  service={WATCH_SERVICE}\n")
            f.write(f"# thresholds: restarts>={RESTART_THRESHOLD}/{RESTART_WINDOW_S}s, "
                    f"unhealthy>={HEALTH_FLAP_THRESHOLD}/{HEALTH_WINDOW_S}s\n")

    # -- alert helpers ------------------------------------------------------
    def _app_alive(self):
        """Is the application logic alive, independent of Swarm routing?

        During the storm Swarm removes the unhealthy task from the ingress
        mesh, so an EXTERNAL /work probe fails even though the process is fine.
        To prove the app is actually alive we probe /work INSIDE the running
        container (docker exec), which bypasses the mesh. This is the heart of
        the signature signal: app work succeeds while /health fails.
        """
        try:
            conts = self.client.containers.list(
                filters={"label": f"com.docker.swarm.service.name={WATCH_SERVICE}"})
            if conts:
                probe = ("import urllib.request,sys; "
                         "sys.exit(0 if urllib.request.urlopen("
                         "'http://localhost:8000/work', timeout=2).status==200 else 1)")
                res = conts[0].exec_run(["python", "-c", probe])
                return res.exit_code == 0
        except Exception:  # noqa: BLE001
            pass
        # Fallback: external probe (works when the task is still in rotation).
        try:
            return requests.get(WORK_URL, timeout=WORK_PROBE_TIMEOUT_S).status_code == 200
        except Exception:  # noqa: BLE001
            return False

    def alert(self, kind, severity, message, cooldown=ALERT_COOLDOWN_S):
        mono = time.monotonic()
        last = self._last_alert.get(kind, -1e9)
        if mono - last < cooldown:
            return
        self._last_alert[kind] = mono
        line = f"{now_iso()}  {severity:<8} {kind:<18} {message}"
        print("ALERT  " + line, flush=True)
        with open(ALERTS_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        self.alert_count += 1
        if self.first_alert_iso is None:
            self.first_alert_iso = now_iso()

    # -- signal 1: health events -------------------------------------------
    def watch_health_events(self):
        events = self.client.events(decode=True, filters={"type": "container"})
        for ev in events:
            if self._stop.is_set():
                break
            action = ev.get("Action") or ev.get("status") or ""
            if not action.startswith("health_status"):
                continue
            attrs = ev.get("Actor", {}).get("Attributes", {})
            svc = attrs.get("com.docker.swarm.service.name", "")
            if svc != WATCH_SERVICE:
                continue
            if action.endswith("unhealthy"):
                t = time.time()
                with self.lock:
                    self.unhealthy_events.append(t)
                    self._trim(self.unhealthy_events, HEALTH_WINDOW_S)
                    count = len(self.unhealthy_events)
                # Signature signal: health failed; is the app itself still alive?
                if self._app_alive():
                    self.alert(
                        "INDIRECT-DOS", "CRITICAL",
                        f"{WATCH_SERVICE} health=unhealthy but internal /work "
                        f"returns 200 (app logic ALIVE). Cause: dependency "
                        f"latency slowing /health, NOT an application crash.")
                else:
                    self.alert(
                        "HEALTH-FAIL", "WARNING",
                        f"{WATCH_SERVICE} health=unhealthy and /work unreachable "
                        f"at this instant (task being killed/rescheduled).")
                if count >= HEALTH_FLAP_THRESHOLD:
                    self.alert(
                        "HEALTH-FLAP", "CRITICAL",
                        f"{WATCH_SERVICE} went unhealthy {count}x in "
                        f"{HEALTH_WINDOW_S}s (health flapping).")

    @staticmethod
    def _trim(dq, window_s):
        cutoff = time.time() - window_s
        while dq and dq[0] < cutoff:
            dq.popleft()

    # -- signal 2: restart frequency ---------------------------------------
    def poll_restarts(self):
        while not self._stop.is_set():
            try:
                tasks = self.api.tasks(filters={"service": WATCH_SERVICE})
            except Exception as exc:  # noqa: BLE001
                tasks = []
                print(f"[{now_iso()}] task poll error: {exc}", flush=True)
            cutoff = time.time() - RESTART_WINDOW_S
            restarts = 0
            for tk in tasks:
                if tk.get("DesiredState") != "shutdown":
                    continue
                ts = parse_ts(tk.get("Status", {}).get("Timestamp", ""))
                if ts >= cutoff:
                    restarts += 1
            if restarts >= RESTART_THRESHOLD:
                cause = ("dependency latency (internal /work still 200, app alive)"
                         if self._app_alive() else "task unavailable")
                self.alert(
                    "RESTART-STORM", "CRITICAL",
                    f"{WATCH_SERVICE} restarted {restarts}x in {RESTART_WINDOW_S}s "
                    f"(threshold {RESTART_THRESHOLD}). Cause: {cause}.",
                    cooldown=max(ALERT_COOLDOWN_S, 20))
            self._stop.wait(POLL_INTERVAL_S)

    # -- lifecycle ----------------------------------------------------------
    def run(self, duration_s=0):
        print(f"[{now_iso()}] detector watching '{WATCH_SERVICE}' "
              f"(restart>={RESTART_THRESHOLD}/{RESTART_WINDOW_S}s, "
              f"unhealthy>={HEALTH_FLAP_THRESHOLD}/{HEALTH_WINDOW_S}s)", flush=True)
        t_health = threading.Thread(target=self.watch_health_events, daemon=True)
        t_poll = threading.Thread(target=self.poll_restarts, daemon=True)
        t_health.start()
        t_poll.start()
        try:
            if duration_s > 0:
                self._stop.wait(duration_s)
            else:
                while not self._stop.is_set():
                    self._stop.wait(1)
        except KeyboardInterrupt:
            pass
        finally:
            self._stop.set()
            # Nudge the blocking events() stream to unblock the process exit.
            try:
                self.client.close()
            except Exception:  # noqa: BLE001
                pass
            print(f"[{now_iso()}] detector stopped. alerts raised: {self.alert_count}"
                  + (f" (first at {self.first_alert_iso})" if self.first_alert_iso else ""),
                  flush=True)


def main():
    p = argparse.ArgumentParser(description="Indirect-DoS restart-storm detector.")
    p.add_argument("--duration", type=int, default=0,
                   help="seconds to run, then stop (0 = until Ctrl+C)")
    args = p.parse_args()
    Detector().run(args.duration)


if __name__ == "__main__":
    main()
