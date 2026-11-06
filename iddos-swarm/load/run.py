"""load/run.py — steady load generator + availability meter for /work.

Sends GET /work at a fixed rate for a fixed duration, records every request's
success and latency, and prints the availability and latency summary. Also
usable as a library: the measurement harness (measure.py) imports Sampler and
availability().

Usage:
    python run.py [--url URL] [--duration S] [--rate HZ] [--out CSV]
"""

import argparse
import csv
import threading
import time


def _get(url, timeout):
    import requests
    t0 = time.monotonic()
    try:
        r = requests.get(url, timeout=timeout)
        return (r.status_code == 200), r.status_code, (time.monotonic() - t0) * 1000.0
    except Exception:  # noqa: BLE001 - any error == request unavailable
        return False, 0, (time.monotonic() - t0) * 1000.0


class Sampler(threading.Thread):
    """Background thread that samples a URL at a fixed rate and records rows."""

    def __init__(self, url, rate_hz=5.0, req_timeout=2.0):
        super().__init__(daemon=True)
        self.url = url
        self.period = 1.0 / rate_hz
        self.req_timeout = req_timeout
        self.rows = []            # (epoch, phase, ok(0/1), http_code, latency_ms)
        self.phase = "load"
        self._stop = threading.Event()

    def run(self):
        while not self._stop.is_set():
            t0 = time.monotonic()
            ok, code, lat = _get(self.url, self.req_timeout)
            self.rows.append((time.time(), self.phase, int(ok), code, round(lat, 1)))
            dt = self.period - (time.monotonic() - t0)
            if dt > 0:
                self._stop.wait(dt)

    def stop(self):
        self._stop.set()


def availability(rows, phase=None):
    """Return (availability_pct, ok_count, total)."""
    pts = [r for r in rows if phase is None or r[1] == phase]
    if not pts:
        return (0.0, 0, 0)
    ok = sum(r[2] for r in pts)
    return (100.0 * ok / len(pts), ok, len(pts))


def latency_stats(rows, phase=None, only_ok=True):
    """Return (avg_ms, p95_ms) over samples (optionally only successful)."""
    pts = [r for r in rows if (phase is None or r[1] == phase) and (r[2] == 1 or not only_ok)]
    lats = sorted(r[4] for r in pts)
    if not lats:
        return (0.0, 0.0)
    avg = sum(lats) / len(lats)
    p95 = lats[min(len(lats) - 1, int(0.95 * len(lats)))]
    return (round(avg, 1), round(p95, 1))


def write_csv(rows, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["epoch", "phase", "ok", "http_code", "latency_ms"])
        w.writerows(rows)


def main():
    p = argparse.ArgumentParser(description="Steady /work load generator + availability meter.")
    p.add_argument("--url", default="http://localhost:8000/work")
    p.add_argument("--duration", type=float, default=60.0, help="seconds")
    p.add_argument("--rate", type=float, default=5.0, help="requests per second")
    p.add_argument("--out", default="", help="optional CSV output path")
    args = p.parse_args()

    s = Sampler(args.url, rate_hz=args.rate)
    print(f"load: GET {args.url} @ {args.rate}/s for {args.duration}s")
    s.start()
    time.sleep(args.duration)
    s.stop()
    time.sleep(0.3)

    pct, ok, total = availability(s.rows)
    avg, p95 = latency_stats(s.rows)
    print(f"availability: {pct:.1f}%  ({ok}/{total})")
    print(f"latency (ok): avg {avg} ms   p95 {p95} ms")
    if args.out:
        write_csv(s.rows, args.out)
        print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
