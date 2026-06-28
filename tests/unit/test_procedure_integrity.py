"""SID/STAR procedure structural invariants via direct connector introspection.

These checks inspect the in-memory ``AirportConnection`` graph built by
``FlatbuffersAirportConnector`` — procedure point sequences, transitions and
pooled ``internal_edges`` — which the HTTP API does not expose.  Route-level and
endpoint-output invariants that ARE visible over HTTP live in ``tests/e2e/``
instead.

Coverage is a curated set of representative airports (every specifically-named
invariant — TNCM hub, ZGGG IKAVO3, ZBAA 36L — plus all route-pair airports).
Builds are memoised per ICAO so the 10 tests share one build pass.

Requires ``data/navdata_2604.fb.zst``; skips gracefully when absent.
"""

import os
from math import atan2, cos, radians, sin, sqrt
from pathlib import Path

os.environ["DISABLE_CAPTCHA"] = "true"

import pytest

from openRouterFinder.core.airport import FlatbuffersAirportConnector
from openRouterFinder.core.storage.reader import MmappedNavData

DATA_PATH = Path(__file__).parent.parent.parent / "data" / "navdata_2604.fb.zst"

# Curated representative airports: all specifically-named invariants plus every
# airport used in e2e route pairs.  See module docstring for rationale.
TEST_AIRPORTS = [
    "ZBAA",
    "ZGGG",
    "ZGHA",
    "ZJSY",
    "ZSPD",
    "ZSSS",
    "RKSI",
    "RKPC",
    "ZBAD",
    "RJTT",
    "RJBB",
    "KLAX",
    "KSEA",
    "KJFK",
    "TNCM",
    "ZGSZ",
    "VHHH",
    "RCTP",
    "CYVR",
    "KSFO",
]

# International airports with longer oceanic/continental legs.
INTL_AIRPORTS = {"KLAX", "KSEA", "KJFK", "TNCM", "KSFO", "RCTP", "VHHH"}

DOMESTIC_MAX_LEG_NM = 100
INTL_MAX_LEG_NM = 300


@pytest.fixture(scope="module")
def navdata_fb():
    """Load cycle 2604 FlatBuffers navdata once for all tests."""
    if not DATA_PATH.exists():
        pytest.skip("navdata_2604.fb.zst not available")
    nav = MmappedNavData(DATA_PATH)
    yield nav
    nav.close()


# Memoised (connector, sid_conn, star_conn) per ICAO so each of the 10 tests
# reuses one build pass instead of rebuilding procedures.
_BUILD_CACHE: dict = {}


def _conns(navdata_fb, icao):
    """Return memoised (connector, sid_conn, star_conn) for an airport.

    The same connector instance is returned alongside its built connections so
    callers may use ``connector._resolve_node`` against the graph it produced.
    """
    if icao not in _BUILD_CACHE:
        connector = FlatbuffersAirportConnector(navdata_fb)
        _BUILD_CACHE[icao] = (
            connector,
            connector.build_sid(icao),
            connector.build_star(icao),
        )
    return _BUILD_CACHE[icao]


def _labelled_conns(navdata_fb, icao):
    """Yield (label, conn) for the non-None SID/STAR connections."""
    _connector, sid, star = _conns(navdata_fb, icao)
    for label, conn in (("SID", sid), ("STAR", star)):
        if conn is not None:
            yield label, conn


def _all_procs(navdata_fb, icao):
    """Yield (label, key, Procedure) for every built procedure."""
    for label, conn in _labelled_conns(navdata_fb, icao):
        for key, proc_list in conn.procedures.items():
            for proc in proc_list:
                yield label, key, proc


def _nm(d_km: float) -> float:
    return d_km / 1.852


def _point_dist_km(p1, p2) -> float:
    """Great-circle distance between two (name, lat, lon) points."""
    R = 6378.137
    lat1, lon1 = radians(p1[1]), radians(p1[2])
    lat2, lon2 = radians(p2[1]), radians(p2[2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * R * atan2(sqrt(a), sqrt(1 - a))


def _is_empty_name_marker(name: str) -> bool:
    # Fenix stores every procedure waypoint in the Waypoints table.  D-prefixed
    # identifiers (e.g. D321Y) are real waypoints, not synthetic markers.  Only
    # an empty name indicates a synthetic heading+distance marker.
    return not name


# ---------------------------------------------------------------------------
# 5.1 Illegal Points Check
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("icao", TEST_AIRPORTS)
def test_no_empty_name_markers_in_procedures(icao, navdata_fb):
    """Empty-name markers must not appear as standalone points in any procedure."""
    for label, _key, proc in _all_procs(navdata_fb, icao):
        for pt in proc.points:
            assert not _is_empty_name_marker(pt[0]), (
                f"{icao} {label} {proc.name}: empty-name marker in points"
            )
        for t_name, t_pts in proc.transitions:
            for pt in t_pts:
                assert not _is_empty_name_marker(pt[0]), (
                    f"{icao} {label} {proc.name}: empty-name marker in transition {t_name}"
                )


# ---------------------------------------------------------------------------
# 5.2 Edge Count Check — no isolated nodes, no branching within one procedure
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("icao", TEST_AIRPORTS)
def test_procedure_edge_counts_reasonable(icao, navdata_fb):
    """No isolated node; no branching within a single procedure's main path.

    internal_edges are pooled across all procedures, so shared nodes naturally
    accumulate >2 edges.  We therefore only flag main-path degree >2 when a
    node belongs to exactly ONE procedure variant.
    """
    for label, conn in _labelled_conns(navdata_fb, icao):
        section = conn.procedures
        if not section:
            continue

        # Pass 1: count how many procedure variants each (name,lat,lon) appears in.
        node_proc_counts: dict = {}
        for key, proc_list in section.items():
            for proc in proc_list:
                proc_key = (key, proc.name, proc.runway)
                for pt in proc.points:
                    nk = (pt[0], round(pt[1], 5), round(pt[2], 5))
                    node_proc_counts.setdefault(nk, set()).add(proc_key)
                for _t, t_pts in proc.transitions:
                    for pt in t_pts:
                        nk = (pt[0], round(pt[1], 5), round(pt[2], 5))
                        node_proc_counts.setdefault(nk, set()).add(proc_key)

        # Pass 2: per-procedure edge checks.
        for key, proc_list in section.items():
            for proc in proc_list:
                all_nodes = []
                edges = set()
                for i in range(len(proc.points) - 1):
                    p1 = (
                        proc.points[i][0],
                        round(proc.points[i][1], 5),
                        round(proc.points[i][2], 5),
                    )
                    p2 = (
                        proc.points[i + 1][0],
                        round(proc.points[i + 1][1], 5),
                        round(proc.points[i + 1][2], 5),
                    )
                    edges.add((p1, p2))
                    all_nodes.extend([p1, p2])
                for _t, t_pts in proc.transitions:
                    for i in range(len(t_pts) - 1):
                        p1 = (t_pts[i][0], round(t_pts[i][1], 5), round(t_pts[i][2], 5))
                        p2 = (t_pts[i + 1][0], round(t_pts[i + 1][1], 5), round(t_pts[i + 1][2], 5))
                        edges.add((p1, p2))
                        all_nodes.extend([p1, p2])

                if len(all_nodes) < 2:
                    continue

                # No isolated nodes.
                degree: dict = {}
                for a, b in edges:
                    degree[a] = degree.get(a, 0) + 1
                    degree[b] = degree.get(b, 0) + 1
                for nk in all_nodes:
                    assert degree.get(nk, 0) != 0, (
                        f"{icao} {label} {proc.name} rwy={proc.runway}: "
                        f"node {nk[0]} has 0 edges in procedure"
                    )

                # No branching within the MAIN PATH (transitions may converge).
                main_edges = set()
                for i in range(len(proc.points) - 1):
                    p1 = (
                        proc.points[i][0],
                        round(proc.points[i][1], 5),
                        round(proc.points[i][2], 5),
                    )
                    p2 = (
                        proc.points[i + 1][0],
                        round(proc.points[i + 1][1], 5),
                        round(proc.points[i + 1][2], 5),
                    )
                    main_edges.add((p1, p2))
                main_degree: dict = {}
                for a, b in main_edges:
                    main_degree[a] = main_degree.get(a, 0) + 1
                    main_degree[b] = main_degree.get(b, 0) + 1
                for nk, deg in main_degree.items():
                    if deg > 2 and len(node_proc_counts.get(nk, set())) == 1:
                        pytest.fail(
                            f"{icao} {label} {proc.name} rwy={proc.runway}: "
                            f"node {nk[0]} has {deg} edges (branching within single procedure)"
                        )

                # Each individual transition must also be a straight line.
                for t_name, t_pts in proc.transitions:
                    t_degree: dict = {}
                    for i in range(len(t_pts) - 1):
                        p1 = (t_pts[i][0], round(t_pts[i][1], 5), round(t_pts[i][2], 5))
                        p2 = (t_pts[i + 1][0], round(t_pts[i + 1][1], 5), round(t_pts[i + 1][2], 5))
                        t_degree[p1] = t_degree.get(p1, 0) + 1
                        t_degree[p2] = t_degree.get(p2, 0) + 1
                    for nk, deg in t_degree.items():
                        assert deg <= 2, (
                            f"{icao} {label} {proc.name} rwy={proc.runway}: "
                            f"node {nk[0]} has {deg} edges (branching within transition {t_name})"
                        )


# ---------------------------------------------------------------------------
# 5.3 Path Quality — Teleportation Check
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("icao", TEST_AIRPORTS)
def test_procedure_paths_no_teleportation(icao, navdata_fb):
    """No single leg should exceed the airport-type distance threshold."""
    max_leg = INTL_MAX_LEG_NM if icao in INTL_AIRPORTS else DOMESTIC_MAX_LEG_NM
    for label, _key, proc in _all_procs(navdata_fb, icao):
        pts = proc.points
        if len(pts) < 2:
            continue
        for i in range(len(pts) - 1):
            dist = _point_dist_km(pts[i], pts[i + 1])
            assert _nm(dist) <= max_leg, (
                f"{icao} {label} {proc.name}: "
                f"leg {pts[i][0]}->{pts[i + 1][0]} = {_nm(dist):.1f} nm (max {max_leg} nm)"
            )


# ---------------------------------------------------------------------------
# 5.4 Runway "ALL" must have a path
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("icao", TEST_AIRPORTS)
def test_no_runway_all_with_single_point(icao, navdata_fb):
    """Procedures with runway=ALL must still have a meaningful (>1 point) path."""
    for label, _key, proc in _all_procs(navdata_fb, icao):
        if proc.runway == "ALL":
            assert len(proc.points) > 1, (
                f"{icao} {label}: {proc.name} has runway=ALL but only {len(proc.points)} point(s)"
            )


# ---------------------------------------------------------------------------
# 5.5 SID Runway Endpoint Consistency
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("icao", TEST_AIRPORTS)
def test_sid_runway_endpoint_consistent(icao, navdata_fb):
    """If any SID for a runway starts with DERxx/DExx, all SIDs for that runway must.

    When one procedure lacks the runway endpoint, its first point becomes an
    intermediate node in other procedures' paths, creating unexpected branching
    in the pooled internal_edges graph.
    """
    _connector, sid, _star = _conns(navdata_fb, icao)
    if sid is None or not sid.procedures:
        return

    runway_has_endpoint: dict = {}
    runway_procs: dict = {}
    for _key, proc_list in sid.procedures.items():
        for proc in proc_list:
            if proc.runway == "ALL" or not proc.points:
                continue
            first = proc.points[0][0]
            is_endpoint = first in (f"DER{proc.runway}", f"DE{proc.runway}")
            runway_has_endpoint.setdefault(proc.runway, False)
            runway_procs.setdefault(proc.runway, [])
            runway_procs[proc.runway].append((proc.name, first, is_endpoint))
            if is_endpoint:
                runway_has_endpoint[proc.runway] = True

    for runway, has_endpoint in runway_has_endpoint.items():
        if not has_endpoint:
            continue
        for proc_name, first, is_endpoint in runway_procs[runway]:
            assert is_endpoint, (
                f"{icao} SID {proc_name} via {runway}: first point is {first!r}, but runway "
                f"{runway} has procedures starting with DER{runway}/DE{runway}. All procedures "
                f"for the same runway must share the runway endpoint to avoid pooled branching."
            )


# ---------------------------------------------------------------------------
# 5.6 ZBAA 36L SID Circling Beijing Check
# ---------------------------------------------------------------------------

ZBAA_LON_THRESHOLD = 116.5
ZBAA_AP_LAT = 40.08


def test_zbaa_36l_sid_circles_beijing(navdata_fb):
    """36L northbound SIDs must circle Beijing to the west, not fly straight through."""
    _connector, sid, _star = _conns(navdata_fb, "ZBAA")
    assert sid is not None
    for _key, proc_list in sid.procedures.items():
        for proc in proc_list:
            if proc.runway != "36L" or len(proc.points) < 4:
                continue
            first_lat = proc.points[0][1]
            last_lat = proc.points[-1][1]
            is_northbound = first_lat > ZBAA_AP_LAT or last_lat > ZBAA_AP_LAT + 0.5
            if not is_northbound:
                continue
            has_west = any(p[2] < ZBAA_LON_THRESHOLD for p in proc.points)
            assert has_west, (
                f"ZBAA SID {proc.name} (runway {proc.runway}) appears to fly straight north "
                f"without circling Beijing west: "
                f"pts={[(p[0], round(p[1], 4), round(p[2], 4)) for p in proc.points]}"
            )


# ---------------------------------------------------------------------------
# 5.7 STAR Final Approach Check
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("icao", TEST_AIRPORTS)
def test_star_final_approach_reasonable(icao, navdata_fb):
    """STAR procedures must have no empty-name markers in their points."""
    _connector, _sid, star = _conns(navdata_fb, icao)
    if star is None:
        return
    for _key, proc_list in star.procedures.items():
        for proc in proc_list:
            for pt in proc.points:
                assert not _is_empty_name_marker(pt[0]), (
                    f"{icao} STAR {proc.name}: empty-name marker in points"
                )


# ---------------------------------------------------------------------------
# 5.8 ZGGG IKAVO3 Approach Bridge Check
# ---------------------------------------------------------------------------


def test_zggg_ikavo3_approach_bridge_exists(navdata_fb):
    """IKAVO3 for runways 19R/20L/20R must have at least one waypoint
    geographically between LUPVU and the airport to guide the final approach.
    """
    _connector, _sid, star = _conns(navdata_fb, "ZGGG")
    assert star is not None
    ap_lat = star.airport_node.px
    ap_lon = star.airport_node.py

    failures = []
    for _key, proc_list in star.procedures.items():
        for proc in proc_list:
            if proc.name != "IKAVO3" or proc.runway not in ("19R", "20L", "20R"):
                continue
            pts = proc.points

            lupvu_idx = next((i for i, pt in enumerate(pts) if pt[0] == "LUPVU"), None)
            if lupvu_idx is None:
                failures.append(f"IKAVO3 runway {proc.runway}: LUPVU not found in points")
                continue

            lupvu = pts[lupvu_idx]
            d_lupvu_ap = _point_dist_km(lupvu, ("AP", ap_lat, ap_lon))

            candidates = list(pts[lupvu_idx + 1 :])
            for _t_name, t_pts in proc.transitions:
                candidates.extend(t_pts)

            if not candidates:
                failures.append(
                    f"IKAVO3 runway {proc.runway}: no waypoint after LUPVU "
                    f"({[p[0] for p in pts]} / transitions={len(proc.transitions)})"
                )
                continue

            has_bridge = False
            for pt in candidates:
                d_pt_ap = _point_dist_km(pt, ("AP", ap_lat, ap_lon))
                d_lupvu_pt = _point_dist_km(lupvu, pt)
                if d_pt_ap >= d_lupvu_ap:
                    continue
                if d_lupvu_pt + d_pt_ap <= d_lupvu_ap * 1.5:
                    has_bridge = True
                    break

            if not has_bridge:
                cand_str = [(p[0], round(_point_dist_km(lupvu, p), 1)) for p in candidates]
                failures.append(
                    f"IKAVO3 runway {proc.runway}: no waypoint between LUPVU and airport "
                    f"among {cand_str}"
                )

    assert not failures, "ZGGG IKAVO3 approach bridge issues:\n" + "\n".join(failures)


# ---------------------------------------------------------------------------
# 5.9 ZGGG IKAVO3 Points Completeness Check
# ---------------------------------------------------------------------------


def test_zggg_ikavo3_has_complete_points(navdata_fb):
    """IKAVO3 for all runways must have a complete approach path with >2 points.

    Fenix stores the common main legs (IKAVO -> LUPVU) separately from
    runway-specific transition legs (LUPVU -> D321Y).  The full path is the
    union of main points and the matching transition for that runway.
    """
    _connector, _sid, star = _conns(navdata_fb, "ZGGG")
    assert star is not None

    failures = []
    for _key, proc_list in star.procedures.items():
        for proc in proc_list:
            if proc.name != "IKAVO3":
                continue
            full_path = list(proc.points)
            seen = {p[0] for p in full_path}
            for t_name, t_pts in proc.transitions:
                t_rwy = t_name[2:] if t_name.startswith("RW") else t_name
                if t_rwy == proc.runway:
                    for tp in t_pts:
                        if tp[0] not in seen:
                            full_path.append(tp)
                            seen.add(tp[0])
            if len(full_path) <= 2:
                failures.append(
                    f"{proc.name} runway {proc.runway}: only {len(full_path)} points "
                    f"{[p[0] for p in full_path]} — incomplete approach path"
                )

    assert not failures, "ZGGG IKAVO3 incomplete points:\n" + "\n".join(failures)


# ---------------------------------------------------------------------------
# 5.10 No Hub Nodes in Pooled internal_edges
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("icao", TEST_AIRPORTS)
def test_procedure_internal_edges_no_hub_nodes(icao, navdata_fb):
    """Every edge in pooled internal_edges must belong to at least one
    procedure's consecutive point pair.

    _add_network_bridges adds bridge edges from a connected network node to
    isolated entry/exit nodes.  When that connected node is also a procedure
    node (e.g. TNCM STAR PJM), the bridge edges become extra outgoing edges in
    the pooled graph, causing the frontend to draw wrong procedure lines.
    """
    connector, sid, star = _conns(navdata_fb, icao)
    failures = []

    for label, conn in (("SID", sid), ("STAR", star)):
        if conn is None or not conn.procedures:
            continue

        # 1. Collect expected edges from all procedure points + transitions.
        expected_edges = set()
        iid_to_name = {}
        for _key, proc_list in conn.procedures.items():
            for proc in proc_list:
                pts = proc.points
                for i in range(len(pts) - 1):
                    from_node = connector._resolve_node(pts[i][0], pts[i][1], pts[i][2])
                    to_node = connector._resolve_node(pts[i + 1][0], pts[i + 1][1], pts[i + 1][2])
                    expected_edges.add((from_node.iid, to_node.iid))
                    iid_to_name[from_node.iid] = from_node.name
                    iid_to_name[to_node.iid] = to_node.name
                for _t_name, t_pts in proc.transitions:
                    for i in range(len(t_pts) - 1):
                        from_node = connector._resolve_node(t_pts[i][0], t_pts[i][1], t_pts[i][2])
                        to_node = connector._resolve_node(
                            t_pts[i + 1][0], t_pts[i + 1][1], t_pts[i + 1][2]
                        )
                        expected_edges.add((from_node.iid, to_node.iid))
                        iid_to_name[from_node.iid] = from_node.name
                        iid_to_name[to_node.iid] = to_node.name

        # 2. Sensitive nodes: procedure nodes that are NOT the last point (so
        #    they may legitimately have outgoing internal edges).
        sensitive_nodes = set()
        for _key, proc_list in conn.procedures.items():
            for proc in proc_list:
                pts = proc.points
                for i in range(len(pts) - 1):
                    node = connector._resolve_node(pts[i][0], pts[i][1], pts[i][2])
                    sensitive_nodes.add(node.iid)
                for _t_name, t_pts in proc.transitions:
                    for i in range(len(t_pts) - 1):
                        node = connector._resolve_node(t_pts[i][0], t_pts[i][1], t_pts[i][2])
                        sensitive_nodes.add(node.iid)

        # 3. Check internal_edges.
        for edge in conn.internal_edges:
            if (edge.nfrom, edge.nend) in expected_edges:
                continue
            if edge.nfrom in sensitive_nodes:
                from_name = iid_to_name.get(edge.nfrom, "?")
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
                    f"{icao} {label}: node {from_name} (iid={edge.nfrom}) has unexpected edge "
                    f"to iid={edge.nend} — no procedure defines this consecutive pair"
                )

    assert not failures, "Hub nodes in internal_edges:\n" + "\n".join(failures)
