"""E2E performance measurement: single route-query latency.

Measurement-only — these tests never assert a time threshold (timings are
machine- and load-dependent, so a hard ceiling would be flaky). They time real
HTTP route queries over the same 20 already-connected pairs the functional e2e
suite uses, and print latency statistics. Run with ``-s`` to see the numbers:

    pytest tests/e2e/test_perf_e2e.py -s -m perf

The suite runs serially, so while a perf test runs nothing else is hitting the
server — the measurement reflects single-query latency, not latency under load.

Two scenarios:
  * ``test_perf_continuous`` — back-to-back requests over the pair set, repeated
    for several rounds. Cache-friendly: round 1 pays cold procedure builds,
    later rounds show warm-cache latency.
  * ``test_perf_interval_random`` — one request per second, random order, biased
    to the longest (intercontinental) pairs. Models spread-out real traffic
    hitting diverse procedures.

Tunables (env): ``PERF_ROUNDS`` (default 3), ``PERF_INTERVAL_REQUESTS``
(default 10), ``PERF_INTERVAL_SECONDS`` (default 1.0).
"""

import os
import random
import statistics
import time

import pytest

from openRouterFinder.core.graph import great_circle_distance_km

# Mirrors the connected pairs in tests/e2e/test_routes_e2e.py (self-contained by
# the same convention every e2e module follows). These are known-routable.
CONNECTED_PAIRS = [
    ("ZBAA", "ZGGG"),
    ("ZBAA", "ZGHA"),
    ("ZGHA", "ZJSY"),
    ("ZBAA", "ZSPD"),
    ("ZBAA", "ZSSS"),
    ("ZBAA", "RKSI"),
    ("ZBAA", "RKPC"),
    ("RKPC", "ZBAD"),
    ("RKPC", "RKSI"),
    ("ZBAA", "RJTT"),
    ("RJTT", "RJBB"),
    ("ZBAA", "KLAX"),
    ("ZBAA", "KSEA"),
    ("KSEA", "KLAX"),
    ("KLAX", "KSEA"),
    ("KJFK", "KLAX"),
    ("ZBAA", "TNCM"),
    ("ZBAA", "ZGSZ"),
    ("VHHH", "RCTP"),
    ("CYVR", "KSFO"),
]

PERF_ROUNDS = int(os.environ.get("PERF_ROUNDS", "3"))
PERF_INTERVAL_REQUESTS = int(os.environ.get("PERF_INTERVAL_REQUESTS", "10"))
PERF_INTERVAL_SECONDS = float(os.environ.get("PERF_INTERVAL_SECONDS", "1.0"))


def _post_route(client, orig, dest):
    return client.post(
        "/api/route",
        json={
            "orig": orig,
            "dest": dest,
            "validCode": "",
            "validToken": "",
            "sidExit": "",
            "starEntry": "",
            "cycle": "2604",
        },
    )


def _timed_query(client, orig, dest) -> tuple[float, bool]:
    """Return (seconds, connected) for one HTTP route query."""
    t0 = time.perf_counter()
    resp = _post_route(client, orig, dest)
    dt = time.perf_counter() - t0
    connected = resp.status_code == 200 and resp.json().get("route") not in (
        None,
        "",
        "No result.",
    )
    return dt, connected


def _airport_coords(client, icao) -> tuple[float, float] | None:
    resp = client.get(f"/api/airports/{icao}?cycle=2604")
    if resp.status_code != 200:
        return None
    d = resp.json()
    return float(d["lat"]), float(d["lon"])


def _report(label: str, samples: list[float]) -> None:
    """Print a latency summary block (visible with `pytest -s`)."""
    if not samples:
        print(f"\n[perf] {label}: no samples")
        return
    ms = [s * 1000 for s in samples]
    ms_sorted = sorted(ms)
    p95 = ms_sorted[min(len(ms_sorted) - 1, round(0.95 * (len(ms_sorted) - 1)))]
    print(
        f"\n[perf] {label}  n={len(ms)}\n"
        f"       min={min(ms):.0f}ms  median={statistics.median(ms):.0f}ms  "
        f"mean={statistics.mean(ms):.0f}ms  p95={p95:.0f}ms  max={max(ms):.0f}ms"
    )


@pytest.mark.e2e
@pytest.mark.perf
def test_perf_continuous(client):
    """Back-to-back latency over the connected pairs, several rounds.

    Round 1 includes cold procedure builds; later rounds are cache-warm. Each
    round's stats are printed plus an overall warm (rounds >= 2) summary.
    """
    print(f"\n[perf] continuous: {len(CONNECTED_PAIRS)} pairs x {PERF_ROUNDS} rounds")
    warm: list[float] = []
    for rnd in range(1, PERF_ROUNDS + 1):
        round_samples: list[float] = []
        for orig, dest in CONNECTED_PAIRS:
            dt, _ = _timed_query(client, orig, dest)
            round_samples.append(dt)
        _report(f"continuous round {rnd}{' (cold)' if rnd == 1 else ' (warm)'}", round_samples)
        if rnd >= 2:
            warm.extend(round_samples)
    if warm:
        _report("continuous warm overall (rounds>=2)", warm)


@pytest.mark.e2e
@pytest.mark.perf
def test_perf_interval_random(client):
    """One request per second, random order, biased to the longest pairs.

    Models spread-out real traffic on long intercontinental routes that exercise
    diverse procedures rather than repeatedly hitting one warm path.
    """
    # Rank pairs by great-circle distance; sample from the longer half.
    coords: dict[str, tuple[float, float]] = {}
    ranked: list[tuple[float, tuple[str, str]]] = []
    for orig, dest in CONNECTED_PAIRS:
        for icao in (orig, dest):
            if icao not in coords:
                c = _airport_coords(client, icao)
                if c is not None:
                    coords[icao] = c
        if orig in coords and dest in coords:
            d = great_circle_distance_km(*coords[orig], *coords[dest])
            ranked.append((d, (orig, dest)))
    ranked.sort(reverse=True)
    long_pairs = [p for _, p in ranked[: max(1, len(ranked) // 2)]]
    print(
        f"\n[perf] interval: {PERF_INTERVAL_REQUESTS} requests, "
        f"{PERF_INTERVAL_SECONDS}s gap, from {len(long_pairs)} longest pairs "
        f"(longest {ranked[0][0]:.0f}km {ranked[0][1][0]}->{ranked[0][1][1]})"
    )

    rng = random.Random()  # truly random order each run
    samples: list[float] = []
    for i in range(PERF_INTERVAL_REQUESTS):
        orig, dest = rng.choice(long_pairs)
        dt, connected = _timed_query(client, orig, dest)
        samples.append(dt)
        print(f"       {orig}->{dest}: {dt * 1000:.0f}ms{'' if connected else '  [NO ROUTE]'}")
        if i < PERF_INTERVAL_REQUESTS - 1:
            time.sleep(PERF_INTERVAL_SECONDS)
    _report("interval random", samples)
