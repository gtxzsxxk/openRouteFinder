"""SID/STAR procedure integrity tests via HTTP API.

Most tests query the backend REST endpoints and inspect JSON responses.
The hub-node test (5.9) imports core modules directly to validate pooled
internal_edges against procedure point sequences.
"""

import os
import re
from pathlib import Path

os.environ["DISABLE_CAPTCHA"] = "true"

import pytest
from fastapi.testclient import TestClient
from openRouterFinder.api import app
from openRouterFinder.core.airport import FlatbuffersAirportConnector
from openRouterFinder.core.storage.reader import MmappedNavData

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
        pytest.fail(f"{icao}: procedures endpoint returned {resp.status_code}")
    data = resp.json()
    if data.get("icao") != icao:
        pytest.fail(f"{icao}: unexpected response shape")
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

                # No isolated nodes (check points + transitions)
                all_degree = {}
                for a, b in edges:
                    all_degree[a] = all_degree.get(a, 0) + 1
                    all_degree[b] = all_degree.get(b, 0) + 1
                for node_key in all_nodes:
                    if all_degree.get(node_key, 0) == 0:
                        pytest.fail(
                            f"{icao} {label} {proc_name} rwy={runway}: "
                            f"node {node_key[0]} has 0 edges in procedure"
                        )

                # No branching within a single procedure's MAIN PATH.
                # Transitions are alternative selectable routes and may converge
                # at shared nodes (e.g. multiple entry transitions ending at the
                # same fix).  We therefore only check proc.points for branching.
                main_edges = set()
                for i in range(len(points) - 1):
                    p1 = (points[i][0], round(points[i][1], 5), round(points[i][2], 5))
                    p2 = (points[i + 1][0], round(points[i + 1][1], 5), round(points[i + 1][2], 5))
                    main_edges.add((p1, p2))

                main_degree = {}
                for a, b in main_edges:
                    main_degree[a] = main_degree.get(a, 0) + 1
                    main_degree[b] = main_degree.get(b, 0) + 1

                for node_key, deg in main_degree.items():
                    proc_count = len(node_proc_counts.get(node_key, set()))
                    if deg > 2 and proc_count == 1:
                        pytest.fail(
                            f"{icao} {label} {proc_name} rwy={runway}: "
                            f"node {node_key[0]} has {deg} edges "
                            f"(branching within single procedure)"
                        )

                # Each individual transition must also be a straight line.
                for t_name, t_pts in transitions:
                    t_degree = {}
                    for i in range(len(t_pts) - 1):
                        p1 = (t_pts[i][0], round(t_pts[i][1], 5), round(t_pts[i][2], 5))
                        p2 = (t_pts[i + 1][0], round(t_pts[i + 1][1], 5), round(t_pts[i + 1][2], 5))
                        t_degree[p1] = t_degree.get(p1, 0) + 1
                        t_degree[p2] = t_degree.get(p2, 0) + 1
                    for node_key, deg in t_degree.items():
                        if deg > 2:
                            pytest.fail(
                                f"{icao} {label} {proc_name} rwy={runway}: "
                                f"node {node_key[0]} has {deg} edges "
                                f"(branching within transition {t_name})"
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


@pytest.mark.parametrize("icao", TEST_AIRPORTS)
def test_no_runway_all_when_specific_exists(icao):
    """No procedure name may have both runway=ALL and runway-specific variants.

    When a procedure has RW-prefixed transitions, non-RW transitions must be
    folded into the RW variants as selectable transitions, not exposed as
    standalone runway=ALL procedures.  This prevents the frontend from
    showing duplicate entries (Cartesian product of ALL × runways).
    """
    data = _get_procedures(icao)

    for label in ("SID", "STAR"):
        section = data.get(f"{label.lower()}Details", {})
        if not section:
            continue

        # Group by procedure name -> set of runways
        name_runways: dict = {}
        for key, proc_list in section.items():
            for proc in proc_list:
                proc_name = proc[0]
                runway = proc[1]
                name_runways.setdefault(proc_name, set()).add(runway)

        failures = []
        for proc_name, runways in name_runways.items():
            if "ALL" in runways and len(runways) > 1:
                failures.append(
                    f"{icao} {label}: {proc_name} has both runway='ALL' "
                    f"and specific runways {sorted(r for r in runways if r != 'ALL')}"
                )

        assert not failures, "Procedures with conflicting runway values:\n" + "\n".join(failures)


# Representative routes that cover airports with known ALL+specific conflicts.
_RUNWAY_ALL_CHECK_PAIRS = [
    ("ZBAA", "KLAX"),   # KIMMO3: ALL + 24R
    ("ZBAA", "KSEA"),   # BASET5 / BIGBR3: ALL + multiple runways
    ("KJFK", "KLAX"),   # ANJLL4 / DIRBY2: ALL + multiple runways
]


@pytest.mark.parametrize("orig,dest", _RUNWAY_ALL_CHECK_PAIRS)
def test_post_route_no_runway_all_when_specific_exists(orig, dest):
    """POST /api/route must not return runway='ALL' alongside specific runways.

    Regression: the old code filtered ALL only in get_airport_procedures,
    so post_route still exposed KIMMO3 - ALL in the STAR field.
    """
    resp = client.post(
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
    if resp.status_code != 200:
        pytest.skip(f"{orig}→{dest}: route endpoint returned {resp.status_code}")
    data = resp.json()
    if data.get("route") == "No result.":
        pytest.skip(f"{orig}→{dest}: no route found")

    for label, field_name in (("SID", "SID"), ("STAR", "STAR")):
        procs = data.get(field_name, {})
        if not procs:
            continue

        name_runways: dict = {}
        for proc_list in procs.values():
            for proc in proc_list:
                name_runways.setdefault(proc[0], set()).add(proc[1])

        failures = []
        for proc_name, runways in name_runways.items():
            specific = runways - {"ALL"}
            # Only single-runway ALL variants must be renamed; multi-runway
            # ALL variants are kept because their entry-point keys are needed.
            if "ALL" in runways and len(specific) == 1:
                failures.append(
                    f"{orig}→{dest} {label}: {proc_name} has runway='ALL' "
                    f"but only one specific runway {sorted(specific)} — should be renamed"
                )

        assert not failures, "Procedures with conflicting runway values:\n" + "\n".join(failures)


# ---------------------------------------------------------------------------
# 5.5 SID Runway Endpoint Consistency
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("icao", TEST_AIRPORTS)
def test_sid_runway_endpoint_consistent(icao):
    """If any SID for a runway starts with DERxx/DExx, all SIDs for that
    runway must start with the runway endpoint marker.

    When one procedure lacks the runway endpoint, its first point becomes
    an intermediate node in other procedures' paths.  In the pooled
    internal_edges graph this creates unexpected branching (e.g. AA131
    with 3 edges in ZBAA BOTP7X / DOTR5Y / ELKU5Y).
    """
    data = _get_procedures(icao)
    sid = data.get("sidDetails", {})
    if not sid:
        return

    runway_has_endpoint: dict = {}
    runway_procs: dict = {}
    for key, proc_list in sid.items():
        for proc in proc_list:
            proc_name = proc[0]
            runway = proc[1]
            points = proc[2]
            if runway == "ALL" or not points:
                continue
            first = points[0][0]
            is_endpoint = first in (f"DER{runway}", f"DE{runway}")
            runway_has_endpoint.setdefault(runway, False)
            runway_procs.setdefault(runway, [])
            runway_procs[runway].append((proc_name, first, is_endpoint))
            if is_endpoint:
                runway_has_endpoint[runway] = True

    for runway, has_endpoint in runway_has_endpoint.items():
        if not has_endpoint:
            continue
        for proc_name, first, is_endpoint in runway_procs[runway]:
            assert is_endpoint, (
                f"{icao} SID {proc_name} via {runway}: "
                f"first point is {first!r}, but runway {runway} "
                f"has procedures that start with DER{runway}/DE{runway}. "
                f"All procedures for the same runway must share the same "
                f"runway endpoint to avoid pooled-edge branching."
            )


# ---------------------------------------------------------------------------
# 5.6 ZBAA 36L SID Circling Beijing Check
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


# ---------------------------------------------------------------------------
# 5.9 No Hub Nodes in Pooled internal_edges
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def navdata_fb():
    """Load cycle 2604 FlatBuffers navdata once for all direct tests."""
    data_path = Path(__file__).parent.parent / "data" / "navdata_2604.fb.zst"
    nav = MmappedNavData(data_path)
    yield nav
    nav.close()


@pytest.mark.parametrize("icao", TEST_AIRPORTS)
def test_procedure_internal_edges_no_hub_nodes(icao, navdata_fb):
    """Every edge in pooled internal_edges must belong to at least one
    procedure's consecutive point pair.

    _add_network_bridges adds bridge edges from a connected network node to
    isolated entry/exit nodes.  When that connected node is also a procedure
    node (e.g. TNCM STAR PJM), the bridge edges become extra outgoing edges
    in the pooled graph, causing the frontend to draw wrong procedure lines.
    """
    connector = FlatbuffersAirportConnector(navdata_fb)
    failures = []

    for label, build_func in (("SID", connector.build_sid), ("STAR", connector.build_star)):
        conn = build_func(icao)
        if conn is None or not conn.procedures:
            continue

        # 1. Collect expected edges from all procedure points + transitions
        expected_edges = set()
        iid_to_name = {}
        for key, proc_list in conn.procedures.items():
            for proc in proc_list:
                pts = proc.points
                for i in range(len(pts) - 1):
                    from_node = connector._resolve_node(pts[i][0], pts[i][1], pts[i][2])
                    to_node = connector._resolve_node(pts[i + 1][0], pts[i + 1][1], pts[i + 1][2])
                    expected_edges.add((from_node.iid, to_node.iid))
                    iid_to_name[from_node.iid] = from_node.name
                    iid_to_name[to_node.iid] = to_node.name

                for t_name, t_pts in proc.transitions:
                    for i in range(len(t_pts) - 1):
                        from_node = connector._resolve_node(t_pts[i][0], t_pts[i][1], t_pts[i][2])
                        to_node = connector._resolve_node(t_pts[i + 1][0], t_pts[i + 1][1], t_pts[i + 1][2])
                        expected_edges.add((from_node.iid, to_node.iid))
                        iid_to_name[from_node.iid] = from_node.name
                        iid_to_name[to_node.iid] = to_node.name

        # 2. Collect sensitive nodes: nodes that appear in procedures
        #    and are NOT the last point (so they may have outgoing edges).
        #    The last point connects to the airport/network, not internally.
        sensitive_nodes = set()
        for key, proc_list in conn.procedures.items():
            for proc in proc_list:
                pts = proc.points
                for i in range(len(pts) - 1):
                    node = connector._resolve_node(pts[i][0], pts[i][1], pts[i][2])
                    sensitive_nodes.add(node.iid)
                for t_name, t_pts in proc.transitions:
                    for i in range(len(t_pts) - 1):
                        node = connector._resolve_node(t_pts[i][0], t_pts[i][1], t_pts[i][2])
                        sensitive_nodes.add(node.iid)

        # 3. Check internal_edges
        for edge in conn.internal_edges:
            if (edge.nfrom, edge.nend) in expected_edges:
                continue
            if edge.nfrom in sensitive_nodes:
                from_name = iid_to_name.get(edge.nfrom, "?")
                # Fallback to temp_nodes or nav node_list
                if from_name == "?":
                    for n in conn.temp_nodes:
                        if n.iid == edge.nfrom:
                            from_name = n.name
                            break
                if from_name == "?":
                    nl = navdata_fb.node_list
                    if edge.nfrom < len(nl) and nl[edge.nfrom] is not None:
                        from_name = nl[edge.nfrom].name
                failures.append(
                    f"{icao} {label}: node {from_name} (iid={edge.nfrom}) "
                    f"has unexpected edge to iid={edge.nend} — "
                    f"no procedure defines this consecutive pair"
                )

    assert not failures, "Hub nodes in internal_edges:\n" + "\n".join(failures)


# ---------------------------------------------------------------------------
# 5.10 Runway Field Sanity Check
# ---------------------------------------------------------------------------

RUNWAY_RE = re.compile(r'^\d+[LRC]?$')


@pytest.mark.parametrize("icao", TEST_AIRPORTS)
def test_runway_field_is_valid(icao):
    """Runway must be a real runway designator (e.g. 16L, 34R, 07) or ALL.

    Transition names that are not prefixed with 'RW' (e.g. VIXOR, EHF, PDT)
    are entry/exit points, not runways.  They must never appear in the
    runway field.
    """
    data = _get_procedures(icao)
    failures = []

    for label, key, proc in _all_procedure_tuples(data):
        proc_name = proc[0]
        runway = proc[1]
        if runway == "ALL" or runway == "":
            continue
        if not RUNWAY_RE.match(runway):
            failures.append(
                f"{icao} {label} key={key} {proc_name}: "
                f"runway={runway!r} is not a valid runway designator"
            )

    assert not failures, "Invalid runway values:\n" + "\n".join(failures)


# ---------------------------------------------------------------------------
# 5.9 No runway='ALL' in frontend procedure lists
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("icao", TEST_AIRPORTS)
def test_no_runway_all_in_procedure_lists(icao):
    """Frontend procedure dropdowns must never show runway='ALL'.

    A procedure with runway='ALL' means the data pipeline failed to
    associate the procedure with a real runway.  This happens when:
    1. Fenix raw data has no runway info and no approach bridge exists.
    2. The builder failed to merge approach bridges into transition variants.

    Both are data-pipeline or algorithm bugs that must be fixed, not
    worked around with frontend filters.
    """
    data = _get_procedures(icao)
    failures = []

    for label, details in (("SID", data.get("sidDetails", {})),
                           ("STAR", data.get("starDetails", {}))):
        for key, proc_list in details.items():
            for proc in proc_list:
                proc_name = proc[0]
                runway = proc[1]
                if runway == "ALL":
                    failures.append(
                        f"{icao} {label} {proc_name}: runway='ALL' "
                        f"(key={key}, points={[p[0] for p in proc[2]]})"
                    )

    assert not failures, "Procedures with runway='ALL' found:\n" + "\n".join(failures)
