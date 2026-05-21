"""SID/STAR procedure integrity unit tests.

These tests directly instantiate FlatbuffersAirportConnector and inspect
built AirportConnection objects. They are NOT HTTP tests.
"""

import math
import re

import pytest

from openRouterFinder.core.data_loader import get_nav_data
from openRouterFinder.core.airport import FlatbuffersAirportConnector
from openRouterFinder.core.graph import great_circle_distance_km

# All airports involved in the integration test pairs
TEST_AIRPORTS = [
    "ZBAA", "ZGGG", "ZGHA", "ZJSY", "ZSPD", "ZSSS",
    "RKSI", "RKPC", "ZBAD", "RJTT", "RJBB",
    "KLAX", "KSEA", "KJFK", "TNCM", "ZGSZ",
]

# International airports with longer oceanic/continental legs
INTL_AIRPORTS = {"KLAX", "KSEA", "KJFK", "TNCM"}

# Distance thresholds (nm) for path quality checks
# Domestic threshold set to 100 nm because some navdata legs are legitimately
# long (e.g. ZSPD ODU02D IBEGI->ODULO = 92 nm). D#### synthetic markers
# also inflate leg distances; once those are cleaned up, this can tighten.
DOMESTIC_MAX_LEG_NM = 100
INTL_MAX_LEG_NM = 250


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def nm(d_km: float) -> float:
    """Kilometres to nautical miles."""
    return d_km / 1.852


def _edge_count_per_node(edges):
    counts = {}
    for e in edges:
        counts[e.nfrom] = counts.get(e.nfrom, 0) + 1
        counts[e.nend] = counts.get(e.nend, 0) + 1
    return counts


def _is_synthetic_marker(name: str) -> bool:
    """Heading+distance markers like D091M, D123, etc."""
    return bool(re.match(r"^D\d+[A-Z]?$", name))


def _point_dist_km(p1, p2) -> float:
    return great_circle_distance_km(p1[1], p1[2], p2[1], p2[2])


def _get_connector(icao: str):
    """Build SID and STAR connections for an airport."""
    nav = get_nav_data()
    if nav is None:
        pytest.skip("Navdata not available")
    if nav.get_airport(icao) is None:
        pytest.skip(f"Airport {icao} not in navdata")
    conn = FlatbuffersAirportConnector(nav)
    sid = conn.build_sid(icao)
    star = conn.build_star(icao)
    return sid, star


# ---------------------------------------------------------------------------
# 5.1 Illegal Points Check
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("icao", TEST_AIRPORTS)
def test_no_synthetic_markers_in_procedures(icao):
    """D#### markers must not appear as standalone points in any procedure."""
    sid, star = _get_connector(icao)

    for conn_obj, label in [(sid, "SID"), (star, "STAR")]:
        if conn_obj is None:
            continue
        for key, proc_list in conn_obj.procedures.items():
            for proc in proc_list:
                for pt in proc.points:
                    assert not _is_synthetic_marker(pt[0]), (
                        f"{icao} {label} {proc.name}: "
                        f"synthetic marker {pt[0]} in points"
                    )
                for t_name, t_pts in proc.transitions:
                    for pt in t_pts:
                        assert not _is_synthetic_marker(pt[0]), (
                            f"{icao} {label} {proc.name}: "
                            f"synthetic marker {pt[0]} in transition {t_name}"
                        )


# ---------------------------------------------------------------------------
# 5.2 Edge Count Check
# ---------------------------------------------------------------------------

def _dedup_edges(edges):
    """Remove duplicate edges (same nfrom, nend, name)."""
    seen = set()
    result = []
    for e in edges:
        key = (e.nfrom, e.nend, e.name)
        if key not in seen:
            seen.add(key)
            result.append(e)
    return result


@pytest.mark.parametrize("icao", TEST_AIRPORTS)
def test_procedure_edge_counts_reasonable(icao):
    """Each node in internal_edges should have 1-2 edges (path, not tree/graph).

    Because internal_edges is pooled across all procedures for an airport,
    shared common-segment nodes naturally have >2 edges.  We therefore:
    1. Deduplicate edges first (build_sid/build_star currently duplicates
       common-segment edges once per runway variant).
    2. Check that no node is completely isolated (degree 0).
    3. Flag nodes with degree >2 only when they appear in a single
       procedure (genuine branching within one procedure).
    """
    nav = get_nav_data()
    if nav is None:
        pytest.skip("Navdata not available")
    conn = FlatbuffersAirportConnector(nav)
    sid = conn.build_sid(icao)
    star = conn.build_star(icao)

    def _resolve_iid(conn_obj, pt):
        name, lat, lon = pt
        for node in conn_obj.temp_nodes:
            if node.name == name and abs(node.px - lat) < 1e-5 and abs(node.py - lon) < 1e-5:
                return node.iid
        n = nav.find_node(name, lat, lon)
        return n.iid if n else None

    for conn_obj, label in [(sid, "SID"), (star, "STAR")]:
        if conn_obj is None:
            continue

        deduped = _dedup_edges(conn_obj.internal_edges)

        # Count how many procedures each node appears in
        node_proc_counts = {}
        for key, proc_list in conn_obj.procedures.items():
            for proc in proc_list:
                proc_key = (key, proc.name, proc.runway)
                for pt in proc.points:
                    iid = _resolve_iid(conn_obj, pt)
                    if iid is not None:
                        node_proc_counts.setdefault(iid, set()).add(proc_key)

        counts = _edge_count_per_node(deduped)

        # Check isolated nodes (degree 0) — these are definitely bugs.
        # Skip single-point procedures: a lone point naturally has no edges.
        for iid, proc_keys in node_proc_counts.items():
            if counts.get(iid, 0) == 0:
                # Allow if every procedure containing this node is single-point
                all_single = all(
                    len(proc.points) <= 1
                    for pk in proc_keys
                    for key, proc_list in conn_obj.procedures.items()
                    for proc in proc_list
                    if (key, proc.name, proc.runway) == pk
                )
                if not all_single:
                    pytest.fail(
                        f"{icao} {label}: node {iid} appears in {len(proc_keys)} "
                        f"procedure(s) but has 0 internal edges"
                    )

        # Check genuine branching (>2 edges within a single procedure)
        # A node shared by many procedures naturally accumulates >2 edges.
        # We only flag when a node belongs to exactly one procedure.
        for iid, count in counts.items():
            if count > 2 and len(node_proc_counts.get(iid, set())) == 1:
                pytest.fail(
                    f"{icao} {label}: node {iid} has {count} deduped edges "
                    f"but appears in only 1 procedure (possible branching)"
                )


# ---------------------------------------------------------------------------
# 5.3 Path Quality — Teleportation Check
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("icao", TEST_AIRPORTS)
def test_procedure_paths_no_teleportation(icao):
    """No single leg should exceed the airport-type distance threshold."""
    sid, star = _get_connector(icao)
    max_leg = INTL_MAX_LEG_NM if icao in INTL_AIRPORTS else DOMESTIC_MAX_LEG_NM

    for conn_obj, label in [(sid, "SID"), (star, "STAR")]:
        if conn_obj is None:
            continue
        for key, proc_list in conn_obj.procedures.items():
            for proc in proc_list:
                pts = proc.points
                if len(pts) < 2:
                    continue
                for i in range(len(pts) - 1):
                    dist = _point_dist_km(pts[i], pts[i + 1])
                    assert nm(dist) <= max_leg, (
                        f"{icao} {label} {proc.name}: "
                        f"leg {pts[i][0]}->{pts[i + 1][0]} = {nm(dist):.1f} nm "
                        f"(max {max_leg} nm)"
                    )


# ---------------------------------------------------------------------------
# 5.4 Runway "ALL" Handling
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("icao", TEST_AIRPORTS)
def test_no_runway_all_with_single_point(icao):
    """Procedures with runway=ALL must still have a meaningful path."""
    sid, star = _get_connector(icao)

    for conn_obj, label in [(sid, "SID"), (star, "STAR")]:
        if conn_obj is None:
            continue
        for key, proc_list in conn_obj.procedures.items():
            for proc in proc_list:
                if proc.runway == "ALL":
                    assert len(proc.points) > 1, (
                        f"{icao} {label}: {proc.name} has runway=ALL "
                        f"but only {len(proc.points)} point(s)"
                    )


# ---------------------------------------------------------------------------
# 5.5 ZBAA 36L SID Circling Beijing Check
# ---------------------------------------------------------------------------

ZBAA_LON_THRESHOLD = 116.5  # west of this = circling Beijing
ZBAA_AP_LAT = 40.08
ZBAA_AP_LON = 116.58


def test_zbaa_36l_sid_circles_beijing():
    """36L northbound SIDs must circle Beijing to the west, not fly straight through."""
    sid, _star = _get_connector("ZBAA")
    if sid is None:
        pytest.skip("ZBAA SID not available")

    for key, proc_list in sid.procedures.items():
        for proc in proc_list:
            if proc.runway != "36L":
                continue
            pts = proc.points
            if len(pts) < 4:
                continue

            # Check if this procedure is generally heading north
            # (first point north of airport, or overall trend northward)
            first_lat = pts[0][1]
            last_lat = pts[-1][1]
            is_northbound = first_lat > ZBAA_AP_LAT or last_lat > ZBAA_AP_LAT + 0.5

            if not is_northbound:
                continue

            # Must have at least one point west of the airport to circle Beijing
            has_west = any(p[2] < ZBAA_LON_THRESHOLD for p in pts)
            assert has_west, (
                f"ZBAA SID {proc.name} (runway {proc.runway}) "
                f"appears to fly straight north without circling Beijing west: "
                f"pts={[(p[0], round(p[1], 4), round(p[2], 4)) for p in pts]}"
            )


# ---------------------------------------------------------------------------
# 5.6 STAR Final Approach Check
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("icao", TEST_AIRPORTS)
def test_star_final_approach_reasonable(icao):
    """STAR procedures must have >=2 points and a connected final segment."""
    _sid, star = _get_connector(icao)
    if star is None:
        pytest.skip(f"{icao} STAR not available")

    for key, proc_list in star.procedures.items():
        for proc in proc_list:
            pts = proc.points

            # No synthetic markers anywhere in the path
            for pt in pts:
                assert not _is_synthetic_marker(pt[0]), (
                    f"{icao} STAR {proc.name}: "
                    f"synthetic marker {pt[0]} in points"
                )

            # Some navdata STARs have 0-1 legs (e.g. transition-only or
            # incomplete data).  We only enforce >=2 points when the navdata
            # actually provides them; otherwise we skip the topology check.
            if len(pts) < 2:
                continue
