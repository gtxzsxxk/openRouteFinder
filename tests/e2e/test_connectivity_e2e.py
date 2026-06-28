"""E2E connectivity fuzz: random airport pairs must route bidirectionally.

Picks N random *distinct* airport pairs from the full navdata airport list and
asserts each routes in BOTH directions over the real HTTP service. This is the
discovery test for region-level connectivity bugs (e.g. the CYVR->KSFO
regression) that a curated, hand-picked pair list would never surface.

Per CLAUDE.md, a disconnected pair is a route-engine / data-pipeline bug, never
"an unreachable real-world pair": valid airway paths exist for these pairs (a
human can hand-build one), so if the engine returns "No result." that is our
bug. There is deliberately **no distance gate** — long intercontinental pairs
(e.g. EDNG->NZCG) are routable through the global airway network and must
connect like any other.

Reproducibility (the whole point of "random"): each run uses a fresh random
seed, printed in the failure report. Replay an exact run by exporting
``CONN_TEST_SEED=<seed>``. Override the sample size with ``CONN_TEST_PAIRS``
(default 100).
"""

import os
import random
from pathlib import Path

import pytest

from openRouterFinder.core.storage.reader import MmappedNavData

REPO_ROOT = Path(__file__).parent.parent.parent
NAVDATA = REPO_ROOT / "data" / "navdata_2604.fb.zst"

NUM_PAIRS = int(os.environ.get("CONN_TEST_PAIRS", "100"))


def _all_icaos() -> list[str]:
    """Full airport ICAO pool, read directly from navdata (test setup only)."""
    nav = MmappedNavData(NAVDATA)
    try:
        out = []
        for i in range(nav._nav.AirportsLength()):
            ap = nav._nav.Airports(i)
            icao = ap.Icao().decode() if ap.Icao() else ""
            if icao:
                out.append(icao)
        return out
    finally:
        nav.close()


def _route(client, orig, dest):
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


def _connected(resp) -> bool:
    """A pair is connected when the engine returns a real, non-trivial route."""
    if resp.status_code != 200:
        return False
    body = resp.json()
    if body.get("route") in (None, "", "No result."):
        return False
    return len(body.get("nodes", [])) >= 2


@pytest.mark.e2e
def test_random_pairs_connect_bidirectionally(client):
    """Random airport pairs must route in both directions over real HTTP.

    Fails with the full list of disconnected (orig -> dest) directions plus the
    seed needed to replay the exact sample.
    """
    if not NAVDATA.exists():
        pytest.skip("navdata_2604.fb.zst not available — connectivity fuzz needs real navdata")

    icaos = _all_icaos()
    assert len(icaos) >= 2, "navdata exposes fewer than 2 airports"

    env_seed = os.environ.get("CONN_TEST_SEED")
    seed = int(env_seed) if env_seed else random.SystemRandom().randrange(1 << 32)
    rng = random.Random(seed)
    print(f"\n[connectivity fuzz] seed={seed} pairs={NUM_PAIRS}")

    failures: list[str] = []
    for _ in range(NUM_PAIRS):
        a, b = rng.sample(icaos, 2)
        for orig, dest in ((a, b), (b, a)):
            if not _connected(_route(client, orig, dest)):
                failures.append(f"{orig} -> {dest}")

    assert not failures, (
        f"\nseed={seed} (export CONN_TEST_SEED={seed} to replay this exact sample); "
        f"sampled {NUM_PAIRS} pairs.\n"
        f"{len(failures)} disconnected direction(s) — each is a route-engine bug "
        f"(a valid airway path exists), not a real-world gap:\n  " + "\n  ".join(failures)
    )
