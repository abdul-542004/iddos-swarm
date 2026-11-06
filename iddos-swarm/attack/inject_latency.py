"""attack/inject_latency.py — the one and only attack action.

The attacker never touches the web container. It only slows the database path
by adding a Toxiproxy *latency toxic* to the `postgres` proxy. The web service's
/health check then exceeds its timeout, Swarm marks the task unhealthy, and the
restart storm begins.

Usage:
    python inject_latency.py add [--latency 5000] [--jitter 0]
    python inject_latency.py remove
    python inject_latency.py status

Config via environment:
    TOXIPROXY_URL   default http://localhost:8474
    PROXY_NAME      default postgres
"""

import argparse
import json
import os
import sys

import requests

TOXIPROXY_URL = os.environ.get("TOXIPROXY_URL", "http://localhost:8474").rstrip("/")
PROXY_NAME = os.environ.get("PROXY_NAME", "postgres")
TOXIC_NAME = "latency_downstream"


def _toxics_url():
    return f"{TOXIPROXY_URL}/proxies/{PROXY_NAME}/toxics"


def add(latency_ms: int, jitter_ms: int) -> int:
    """Add a downstream latency toxic (delays DB replies to the app)."""
    # Remove a stale toxic first so repeated runs are idempotent.
    requests.delete(f"{_toxics_url()}/{TOXIC_NAME}", timeout=5)
    payload = {
        "name": TOXIC_NAME,
        "type": "latency",
        "stream": "downstream",
        "toxicity": 1.0,
        "attributes": {"latency": latency_ms, "jitter": jitter_ms},
    }
    r = requests.post(_toxics_url(), json=payload, timeout=5)
    if r.status_code not in (200, 201):
        print(f"ERROR adding toxic: HTTP {r.status_code} {r.text}", file=sys.stderr)
        return 1
    print(f"ATTACK ON  latency={latency_ms}ms jitter={jitter_ms}ms on proxy '{PROXY_NAME}'")
    print(json.dumps(r.json(), indent=2))
    return 0


def remove() -> int:
    """Remove the latency toxic (ends the attack)."""
    r = requests.delete(f"{_toxics_url()}/{TOXIC_NAME}", timeout=5)
    if r.status_code not in (200, 204, 404):
        print(f"ERROR removing toxic: HTTP {r.status_code} {r.text}", file=sys.stderr)
        return 1
    print(f"ATTACK OFF toxic '{TOXIC_NAME}' removed from proxy '{PROXY_NAME}'")
    return 0


def status() -> int:
    """Show the proxy and any active toxics."""
    r = requests.get(f"{TOXIPROXY_URL}/proxies/{PROXY_NAME}", timeout=5)
    if r.status_code != 200:
        print(f"ERROR: HTTP {r.status_code} {r.text}", file=sys.stderr)
        return 1
    data = r.json()
    toxics = data.get("toxics", [])
    print(f"proxy '{PROXY_NAME}': listen={data.get('listen')} upstream={data.get('upstream')} enabled={data.get('enabled')}")
    if not toxics:
        print("toxics: none (clean path, no added delay)")
    else:
        for t in toxics:
            print(f"toxic: {t['name']} type={t['type']} stream={t['stream']} attrs={t['attributes']}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Control the Toxiproxy latency attack.")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add", help="add the latency toxic (start the attack)")
    a.add_argument("--latency", type=int, default=5000, help="added delay in ms (default 5000)")
    a.add_argument("--jitter", type=int, default=0, help="random jitter in ms (default 0)")
    sub.add_parser("remove", help="remove the latency toxic (stop the attack)")
    sub.add_parser("status", help="show proxy and active toxics")
    args = p.parse_args(argv)

    if args.cmd == "add":
        return add(args.latency, args.jitter)
    if args.cmd == "remove":
        return remove()
    if args.cmd == "status":
        return status()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
