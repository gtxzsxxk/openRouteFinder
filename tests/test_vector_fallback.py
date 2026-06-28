"""Tests for the synthetic radar-vector SID/STAR fallback.

Some airports (e.g. CYVR / Vancouver) publish only radar-vector departures:
every SID leg is a heading-to-altitude / heading-to-vectors leg with no
waypoint, so the normal builder yields zero procedures and the route engine
has nothing to start from.  ``FlatbuffersAirportConnector`` synthesises a
single ``RADAR VECTORS`` procedure connecting the airport to the nearest
airway fix so such airports remain routable.  See
``_add_synthetic_vector_fallback`` in ``core/airport.py``.
"""

import os
from pathlib import Path

os.environ["DISABLE_CAPTCHA"] = "true"

import pytest

from openRouterFinder.core.airport import FlatbuffersAirportConnector
from openRouterFinder.core.data_loader import search_route
from openRouterFinder.core.graph import Node, great_circle_distance_km
from openRouterFinder.core.storage.reader import MmappedNavData

DATA_PATH = Path(__file__).parent.parent / "data" / "navdata_2604.fb.zst"


@pytest.fixture(scope="module")
def navdata_fb():
    nav = MmappedNavData(DATA_PATH)
    yield nav
    nav.close()


def _synthetic_procs(conn):
    return [
        p for proc_list in conn.procedures.values() for p in proc_list if p.name == "RADAR VECTORS"
    ]


def test_cyvr_sid_is_vector_only_and_gets_synthetic_procedure(navdata_fb):
    """CYVR's 5 SIDs are all radar-vector legs; build_sid must fall back."""
    connector = FlatbuffersAirportConnector(navdata_fb)
    conn = connector.build_sid("CYVR")

    assert conn is not None
    synth = _synthetic_procs(conn)
    assert len(synth) == 1, "expected exactly one synthetic SID procedure"
    proc = synth[0]
    assert proc.runway == ""
    assert len(proc.points) == 2
    # SID direction: airport first, network fix second.
    assert proc.points[0][0] == "CYVR"
    assert proc.points[1][0] != "CYVR"
    # The synthetic connection must exist so data_loader's guard passes.
    assert any(e.name == "SID" for e in conn.connections)


def test_synthetic_sid_leg_respects_no_teleportation(navdata_fb):
    """The synthetic airport->fix leg must stay under the domestic threshold."""
    connector = FlatbuffersAirportConnector(navdata_fb)
    conn = connector.build_sid("CYVR")
    proc = _synthetic_procs(conn)[0]
    (_, lat1, lon1), (_, lat2, lon2) = proc.points
    dist_nm = great_circle_distance_km(lat1, lon1, lat2, lon2) / 1.852
    assert dist_nm <= 100, f"synthetic leg too long: {dist_nm:.1f} nm"


def test_star_fallback_reverses_direction(navdata_fb):
    """Symmetry: the STAR fallback orders points fix->airport (network->airport).

    CYVR publishes real STARs, so we exercise the helper directly on a STAR
    connection to confirm the reversed point order and the network->airport
    connection edge.
    """
    connector = FlatbuffersAirportConnector(navdata_fb)
    # An empty connection anchored at CYVR's airport node.
    base = connector.build_star("CYVR")
    assert base is not None
    airport_node = base.airport_node

    from openRouterFinder.core.airport import AirportConnection

    empty = AirportConnection(
        airport_node=Node(
            iid=airport_node.iid,
            name=airport_node.name,
            px=airport_node.px,
            py=airport_node.py,
        ),
        connections=[],
        procedures={},
    )
    connector._add_synthetic_vector_fallback(empty, 2)

    synth = _synthetic_procs(empty)
    assert len(synth) == 1
    proc = synth[0]
    assert len(proc.points) == 2
    # STAR direction: network fix first, airport last.
    assert proc.points[0][0] != "CYVR"
    assert proc.points[1][0] == "CYVR"
    # Connection edge runs network fix -> airport.
    assert any(e.name == "STAR" and e.nend == airport_node.iid for e in empty.connections)


def test_cyvr_ksfo_route_is_computable():
    """Regression: CYVR -> KSFO must produce a real route, not None (404).

    ``search_route`` is exactly what the ``/api/route`` endpoint runs; it
    returns None precisely when the endpoint would raise 404.  Asserting on it
    directly avoids the FastAPI executor and keeps the test environment-robust.
    """
    result = search_route("CYVR", "KSFO", cycle="2604")
    assert result is not None, "CYVR->KSFO should be routable via vector fallback"
    assert result.get("route") not in (None, "", "No result.")
    assert result.get("distance") != "0.00 nm / 0.00 km"
    # Route should depart via the synthetic radar-vector SID.
    assert "SID" in result["route"]
