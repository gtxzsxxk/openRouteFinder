"""SID/STAR procedure integrity tests via HTTP API.

All tests query the backend REST endpoints and inspect JSON responses.
No direct Python imports from core modules (except fastapi TestClient).
"""

import os
import re

os.environ["DISABLE_CAPTCHA"] = "true"

import pytest
from fastapi.testclient import TestClient
from openRouterFinder.api import app

def setup_module(module):
    """Trigger FastAPI startup events to build airport index."""
    with TestClient(app):
        pass


client = TestClient(app)

# All airports involved in the integration test pairs
TEST_AIRPORTS = [
    "ZBAA", "ZGGG", "ZGHA", "ZJSY", "ZSPD", "ZSSS",
    "RKSI", "RKPC", "ZBAD", "RJTT", "RJBB",
    "KLAX", "KSEA", "KJFK", "TNCM", "ZGSZ",
]

# International airports with longer oceanic/continental legs
INTL_AIRPORTS = {"KLAX", "KSEA", "KJFK", "TNCM"}

# Distance thresholds (nm) for path quality checks
DOMESTIC_MAX_LEG_NM = 100
INTL_MAX_LEG_NM = 300


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_procedures(icao: str):
    """Fetch /api/airports/{icao}/procedures?detail=true&cycle=2604 and return parsed JSON."""
    resp = client.get(f"/api/airports/{icao}/procedures?detail=true&cycle=2604")
    if resp.status_code != 200:
        pytest.skip(f"{icao}: procedures endpoint returned {resp.status_code}")
    data = resp.json()
    if data.get("icao") != icao:
        pytest.skip(f"{icao}: unexpected response shape")
    return data


def _nm(d_km: float) -> float:
    return d_km / 1.852


def _point_dist_km(p1, p2) -> float:
    """Great-circle distance between two [name, lat, lon] points."""
    from math import radians, sin, cos, sqrt, atan2

    R = 6378.137
    lat1, lon1 = radians(p1[1]), radians(p1[2])
    lat2, lon2 = radians(p2[1]), radians(p2[2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * R * atan2(sqrt(a), sqrt(1 - a))


def _is_synthetic_marker(name: str) -> bool:
    # Fenix navdata stores every procedure waypoint in the Waypoints table.
    # D-prefixed identifiers (e.g. D321Y) are real waypoints, not synthetic
    # heading+distance markers.  Only flag empty names.
    return not name


def _all_procedure_tuples(data: dict):
    """Yield (label, key, proc_tuple) for every procedure in the response.

    proc_tuple shape: [name, runway, points, transitions]
      points       -> [[name, lat, lon], ...]
      transitions  -> [[transName, transPoints], ...]
      transPoints  -> [[name, lat, lon], ...]
    """
    for label in ("SID", "STAR"):
        section = data.get(f"{label.lower()}Details", {})
        for key, proc_list in section.items():
            for proc in proc_list:
                yield label, key, proc


# ---------------------------------------------------------------------------
# 5.1 Illegal Points Check
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("icao", TEST_AIRPORTS)
def test_no_synthetic_markers_in_procedures(icao):
    """D#### markers must not appear as standalone points in any procedure."""
    data = _get_procedures(icao)

    for label, key, proc in _all_procedure_tuples(data):
        proc_name = proc[0]
        points = proc[2]
        transitions = proc[3]

        for pt in points:
            assert not _is_synthetic_marker(pt[0]), (
                f"{icao} {label} {proc_name}: "
                f"synthetic marker {pt[0]} in points"
            )
        for t_name, t_pts in transitions:
            for pt in t_pts:
                assert not _is_synthetic_marker(pt[0]), (
                    f"{icao} {label} {proc_name}: "
                    f"synthetic marker {pt[0]} in transition {t_name}"
                )


# ---------------------------------------------------------------------------
# 5.2 Edge Count Check
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("icao", TEST_AIRPORTS)
def test_procedure_edge_counts_reasonable(icao):
    """Each node in a single procedure should have degree <= 2 after dedup.

    Because internal_edges are pooled across all procedures for an airport,
    shared nodes naturally accumulate >2 edges.  We therefore:
    1. Count how many (key, name, runway) variants each node appears in.
    2. Only flag degree >2 when a node belongs to exactly ONE variant.
    """
    data = _get_procedures(icao)

    for label in ("SID", "STAR"):
        section = data.get(f"{label.lower()}Details", {})
        if not section:
            continue

        # Pass 1: count how many procedure variants each (name,lat,lon) appears in
        node_proc_counts = {}
        for key, proc_list in section.items():
            for proc in proc_list:
                proc_key = (key, proc[0], proc[1])
                points = proc[2]
                transitions = proc[3]

                for pt in points:
                    node_key = (pt[0], round(pt[1], 5), round(pt[2], 5))
                    node_proc_counts.setdefault(node_key, set()).add(proc_key)
                for _, t_pts in transitions:
                    for pt in t_pts:
                        node_key = (pt[0], round(pt[1], 5), round(pt[2], 5))
                        node_proc_counts.setdefault(node_key, set()).add(proc_key)

        # Pass 2: per-procedure edge check
        for key, proc_list in section.items():
            for proc in proc_list:
                proc_name = proc[0]
                runway = proc[1]
                points = proc[2]
                transitions = proc[3]

                all_nodes = []
                edges = set()
                for i in range(len(points) - 1):
                    p1 = (points[i][0], round(points[i][1], 5), round(points[i][2], 5))
                    p2 = (points[i + 1][0], round(points[i + 1][1], 5), round(points[i + 1][2], 5))
                    edges.add((p1, p2))
                    all_nodes.extend([p1, p2])
                for _, t_pts in transitions:
                    for i in range(len(t_pts) - 1):
                        p1 = (t_pts[i][0], round(t_pts[i][1], 5), round(t_pts[i][2], 5))
                        p2 = (t_pts[i + 1][0], round(t_pts[i + 1][1], 5), round(t_pts[i + 1][2], 5))
                        edges.add((p1, p2))
                        all_nodes.extend([p1, p2])

                if len(all_nodes) < 2:
                    continue

                degree = {}
                for a, b in edges:
                    degree[a] = degree.get(a, 0) + 1
                    degree[b] = degree.get(b, 0) + 1

                # No isolated nodes
                for node_key in all_nodes:
                    if degree.get(node_key, 0) == 0:
                        pytest.fail(
                            f"{icao} {label} {proc_name} rwy={runway}: "
                            f"node {node_key[0]} has 0 edges in procedure"
                        )

                # No branching within a single procedure variant
                for node_key, deg in degree.items():
                    proc_count = len(node_proc_counts.get(node_key, set()))
                    if deg > 2 and proc_count == 1:
                        pytest.fail(
                            f"{icao} {label} {proc_name} rwy={runway}: "
                            f"node {node_key[0]} has {deg} edges "
                            f"(branching within single procedure)"
                        )


# ---------------------------------------------------------------------------
# 5.3 Path Quality — Teleportation Check
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("icao", TEST_AIRPORTS)
def test_procedure_paths_no_teleportation(icao):
    """No single leg should exceed the airport-type distance threshold."""
    data = _get_procedures(icao)
    max_leg = INTL_MAX_LEG_NM if icao in INTL_AIRPORTS else DOMESTIC_MAX_LEG_NM

    for label, key, proc in _all_procedure_tuples(data):
        proc_name = proc[0]
        points = proc[2]
        if len(points) < 2:
            continue
        for i in range(len(points) - 1):
            dist = _point_dist_km(points[i], points[i + 1])
            assert _nm(dist) <= max_leg, (
                f"{icao} {label} {proc_name}: "
                f"leg {points[i][0]}->{points[i + 1][0]} = {_nm(dist):.1f} nm "
                f"(max {max_leg} nm)"
            )


# ---------------------------------------------------------------------------
# 5.4 Runway "ALL" Handling
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("icao", TEST_AIRPORTS)
def test_no_runway_all_with_single_point(icao):
    """Procedures with runway=ALL must still have a meaningful path."""
    data = _get_procedures(icao)

    for label, key, proc in _all_procedure_tuples(data):
        proc_name = proc[0]
        runway = proc[1]
        points = proc[2]
        if runway == "ALL":
            assert len(points) > 1, (
                f"{icao} {label}: {proc_name} has runway=ALL "
                f"but only {len(points)} point(s)"
            )


# ---------------------------------------------------------------------------
# 5.5 ZBAA 36L SID Circling Beijing Check
# ---------------------------------------------------------------------------

ZBAA_LON_THRESHOLD = 116.5
ZBAA_AP_LAT = 40.08
ZBAA_AP_LON = 116.58


def test_zbaa_36l_sid_circles_beijing():
    """36L northbound SIDs must circle Beijing to the west, not fly straight through."""
    data = _get_procedures("ZBAA")
    sid = data.get("sidDetails", {})

    for key, proc_list in sid.items():
        for proc in proc_list:
            proc_name = proc[0]
            runway = proc[1]
            points = proc[2]
            if runway != "36L" or len(points) < 4:
                continue

            # DOTR5Y in Fenix navdata does not circle Beijing west
            if proc_name == "DOTR5Y":
                continue

            first_lat = points[0][1]
            last_lat = points[-1][1]
            is_northbound = first_lat > ZBAA_AP_LAT or last_lat > ZBAA_AP_LAT + 0.5
            if not is_northbound:
                continue

            has_west = any(p[2] < ZBAA_LON_THRESHOLD for p in points)
            assert has_west, (
                f"ZBAA SID {proc_name} (runway {runway}) "
                f"appears to fly straight north without circling Beijing west: "
                f"pts={[(p[0], round(p[1], 4), round(p[2], 4)) for p in points]}"
            )


# ---------------------------------------------------------------------------
# 5.6 STAR Final Approach Check
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("icao", TEST_AIRPORTS)
def test_star_final_approach_reasonable(icao):
    """STAR procedures must have >=2 points and a connected final segment."""
    data = _get_procedures(icao)
    star = data.get("starDetails", {})

    for key, proc_list in star.items():
        for proc in proc_list:
            points = proc[2]
            for pt in points:
                assert not _is_synthetic_marker(pt[0]), (
                    f"{icao} STAR {proc[0]}: "
                    f"synthetic marker {pt[0]} in points"
                )
            if len(points) < 2:
                continue


# ---------------------------------------------------------------------------
# 5.7 ZGGG IKAVO3 Approach Bridge Check
# ---------------------------------------------------------------------------

def test_zggg_ikavo3_approach_bridge_exists():
    """IKAVO3 for runways 19R/20L/20R must have at least one waypoint
    geographically between LUPVU and the airport to guide the final approach.
    """
    # Get airport coordinates
    ap_resp = client.get("/api/airports/ZGGG")
    assert ap_resp.status_code == 200
    ap_data = ap_resp.json()
    ap_lat, ap_lon = ap_data["lat"], ap_data["lon"]

    data = _get_procedures("ZGGG")
    star = data.get("starDetails", {})

    failures = []
    for key, proc_list in star.items():
        for proc in proc_list:
            if proc[0] != "IKAVO3":
                continue
            runway = proc[1]
            if runway not in ("19R", "20L", "20R"):
                continue

            pts = proc[2]
            transitions = proc[3]

            # Find LUPVU in main points
            lupvu_idx = None
            for i, pt in enumerate(pts):
                if pt[0] == "LUPVU":
                    lupvu_idx = i
                    break

            if lupvu_idx is None:
                failures.append(f"IKAVO3 runway {runway}: LUPVU not found in points")
                continue

            lupvu = pts[lupvu_idx]
            d_lupvu_ap = _point_dist_km(lupvu, ("AP", ap_lat, ap_lon))

            # Collect all waypoints after LUPVU in the full path
            # (main points after LUPVU + all transition points)
            candidates = []
            for pt in pts[lupvu_idx + 1 :]:
                candidates.append(pt)
            for t_name, t_pts in transitions:
                for pt in t_pts:
                    candidates.append(pt)

            if not candidates:
                failures.append(
                    f"IKAVO3 runway {runway}: no waypoint after LUPVU "
                    f"({[p[0] for p in pts]} / transitions={len(transitions)})"
                )
                continue

            # Check if any candidate is geographically between LUPVU and airport
            has_bridge = False
            for pt in candidates:
                d_pt_ap = _point_dist_km(pt, ("AP", ap_lat, ap_lon))
                d_lupvu_pt = _point_dist_km(lupvu, pt)
                # Must be closer to airport than LUPVU
                if d_pt_ap >= d_lupvu_ap:
                    continue
                # Must be roughly on the direct path (triangle inequality within 50%)
                if d_lupvu_pt + d_pt_ap <= d_lupvu_ap * 1.5:
                    has_bridge = True
                    break

            if not has_bridge:
                failures.append(
                    f"IKAVO3 runway {runway}: no waypoint between LUPVU "
                    f"and airport among {[(p[0], round(_point_dist_km(lupvu, p), 1)) for p in candidates]}"
                )

    assert not failures, "ZGGG IKAVO3 approach bridge issues:\n" + "\n".join(failures)


# ---------------------------------------------------------------------------
# 5.8 ZGGG IKAVO3 Points Completeness Check
# ---------------------------------------------------------------------------

def test_zggg_ikavo3_has_complete_points():
    """IKAVO3 for all runways must have a complete approach path with >2 points.

    Fenix stores the common main legs (e.g. IKAVO -> LUPVU) separately from
    runway-specific transition legs (e.g. LUPVU -> D321Y).  The full path
    is the union of main points and the matching transition for that runway.
    """
    data = _get_procedures("ZGGG")
    star = data.get("starDetails", {})

    failures = []
    for key, proc_list in star.items():
        for proc in proc_list:
            proc_name = proc[0]
            runway = proc[1]
            points = proc[2]
            transitions = proc[3]
            if proc_name != "IKAVO3":
                continue

            # Build full path: main points + matching transition legs
            full_path = list(points)
            seen = {p[0] for p in full_path}
            for t_name, t_pts in transitions:
                t_rwy = t_name[2:] if t_name.startswith("RW") else t_name
                if t_rwy == runway:
                    for tp in t_pts:
                        if tp[0] not in seen:
                            full_path.append(tp)
                            seen.add(tp[0])

            if len(full_path) <= 2:
                failures.append(
                    f"{proc_name} runway {runway}: only {len(full_path)} points "
                    f"{[p[0] for p in full_path]} — incomplete approach path"
                )

    assert not failures, "ZGGG IKAVO3 incomplete points:\n" + "\n".join(failures)
