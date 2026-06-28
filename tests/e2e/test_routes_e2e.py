"""End-to-end route invariants over a real HTTP server.

One parametrized test per airport pair calls a single rich validator so all
route-level invariants live in one place.
"""

import pytest

AIRPORT_PAIRS = [
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


def validate_route(resp, orig, dest):
    """All route-level invariants visible from the HTTP response.

    Procedure-leg geometry (no teleportation within SID/STAR) is enforced
    separately in tests/unit/test_procedure_integrity.py.  Enroute airway legs
    are intentionally not distance-checked here: the engine only traverses real
    airway edges, whose legs (especially oceanic) are legitimately long.
    """
    assert resp.status_code == 200, f"{orig}->{dest}: {resp.text}"
    body = resp.json()

    # 1. Route present and non-trivial
    assert body.get("route") not in (None, "", "No result."), f"{orig}->{dest}: no route"
    assert len(body.get("nodes", [])) >= 2, f"{orig}->{dest}: <2 nodes"
    assert body.get("distance") != "0.00 nm / 0.00 km", f"{orig}->{dest}: zero distance"

    segs = body.get("routeSegments", [])
    assert segs, f"{orig}->{dest}: no routeSegments"

    # 2. Simple path — no node visited twice across the assembled airway chain
    chain = []
    for s in segs:
        if not chain or chain[-1] != s["from"]:
            chain.append(s["from"])
        chain.append(s["to"])
    assert len(chain) == len(set(chain)), f"{orig}->{dest}: repeated node in path {chain}"

    # 3. SID/STAR segments contiguous (all SID segs form one run, likewise STAR)
    def _contiguous(tag):
        idx = [i for i, s in enumerate(segs) if s["airway"] == tag]
        if idx:
            assert idx == list(range(idx[0], idx[-1] + 1)), (
                f"{orig}->{dest}: {tag} segments not contiguous"
            )

    _contiguous("SID")
    _contiguous("STAR")


@pytest.mark.e2e
@pytest.mark.parametrize("orig,dest", AIRPORT_PAIRS)
def test_route_e2e(client, orig, dest):
    validate_route(_post_route(client, orig, dest), orig, dest)
