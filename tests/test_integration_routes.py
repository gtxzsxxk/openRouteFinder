"""HTTP API integration tests that mimic frontend calls."""

import os

os.environ["DISABLE_CAPTCHA"] = "true"

import pytest
from fastapi.testclient import TestClient
from openRouterFinder.api import app

def setup_module(module):
    """Trigger FastAPI startup events to build airport index."""
    with TestClient(app):
        pass


client = TestClient(app)

# Airport pairs to test (orig → dest)
# Added ZBAA→ZGSZ per user request
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
    ("KLAX", "KSEA"),
    ("KJFK", "KLAX"),
    ("ZBAA", "TNCM"),
    ("ZBAA", "ZGSZ"),
]

TEST_AIRPORTS = sorted(set(icao for pair in AIRPORT_PAIRS for icao in pair))


# Per CLAUDE.md: Test Failure = Our Bug, Not "Missing Data".
# Never skip a test because navdata appears missing. All AIRPORT_PAIRS
# represent real-world routes that MUST be computable.
# The old _navdata_supports_route() skip helper has been removed.
SKIP_PAIRS = set()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _node_degrees(segments: list) -> dict:
    """Build {node_name: degree} from routeSegments."""
    degree = {}
    for seg in segments:
        f, t = seg["from"], seg["to"]
        degree[f] = degree.get(f, 0) + 1
        degree[t] = degree.get(t, 0) + 1
    return degree


def _build_frontend_edges(
    route_segments: list,
    sid_proc,
    star_proc,
) -> list:
    """从原始 procedure + airway segments 构建完整航路边列表。

    routeSegments 中 SID/STAR 和 airway 已通过 airway 字段区分：
    - airway == "SID" 属于 SID
    - airway == "STAR" 属于 STAR
    - 其他属于 airway

    用原始 procedure 的 points 替换 routeSegments 中的 SID/STAR 部分，
    保留 airway 部分，拼接成完整路径后转为边列表。
    """
    # 从 routeSegments 提取 airway 节点序列
    airway_nodes = []
    for seg in route_segments:
        if seg["airway"] not in ("SID", "STAR"):
            if not airway_nodes or airway_nodes[-1] != seg["from"]:
                airway_nodes.append(seg["from"])
            airway_nodes.append(seg["to"])

    # SID/STAR procedure points: [[name, lat, lon], ...]
    sid_pts = [p[0] for p in (sid_proc[2] if sid_proc else [])]
    star_pts = [p[0] for p in (star_proc[2] if star_proc else [])]

    # 拼接完整节点序列：SID + airway + STAR，去重连接点
    complete = []
    for name in sid_pts:
        if not complete or complete[-1] != name:
            complete.append(name)
    for name in airway_nodes:
        if not complete or complete[-1] != name:
            complete.append(name)
    for name in star_pts:
        if not complete or complete[-1] != name:
            complete.append(name)

    # 转为边列表
    edges = []
    for i in range(len(complete) - 1):
        if complete[i] != complete[i + 1]:
            edges.append((complete[i], complete[i + 1]))

    return edges


def _check_topology(edges: list, label: str = "") -> list:
    """检查边列表是否构成一条无分叉的单一路径。

    返回错误消息列表（空列表表示无错误）。
    """
    if not edges:
        return []

    degree = {}
    for a, b in edges:
        degree[a] = degree.get(a, 0) + 1
        degree[b] = degree.get(b, 0) + 1

    errors = []

    for node, deg in degree.items():
        if deg > 2:
            errors.append(f"{label}: node {node} has degree {deg} > 2 (branching)")

    endpoints = [n for n, d in degree.items() if d == 1]
    if len(endpoints) != 2:
        errors.append(
            f"{label}: expected exactly 2 degree-1 nodes, got {len(endpoints)}: {endpoints}"
        )

    return errors


def _extract_airway_nodes(segments: list, airway: str) -> list:
    """Extract ordered node list for a given airway label from segments."""
    nodes = []
    for seg in segments:
        if seg["airway"] == airway:
            if not nodes or nodes[-1] != seg["from"]:
                nodes.append(seg["from"])
            nodes.append(seg["to"])
    return nodes


def _find_best_procedure_key(nodes: list, procedures: dict) -> str | None:
    """Find the procedure key whose points+transitions contain the most route nodes."""
    best_key = None
    best_score = 0
    for key, proc_list in procedures.items():
        for proc in proc_list:
            all_names = set(p[0] for p in proc[2])
            for _, t_pts in proc[3]:
                for pt in t_pts:
                    all_names.add(pt[0])
            score = sum(1 for n in nodes if n in all_names)
            if score > best_score:
                best_score = score
                best_key = key
    return best_key


def _check_procedure_continuity(
    nodes: list,
    proc_list: list,
    label: str,
    orig: str,
    dest: str,
):
    """Assert that nodes form a continuous subsequence in at least one procedure.

    When pooled internal_edges contain shortcut edges from other procedures,
    A* may skip intermediate nodes (e.g. KIMMO3's ARVIN and AMONT are
    bypassed by WAYVE1's EHF→LOPES edge).  This helper walks the route
    nodes and verifies that every adjacent pair is consecutive in the
    procedure's points list.

    Single-point or short procedures (where fewer than 2 route nodes match)
    are skipped silently — they are normal for airports where the procedure
    is just an anchor to the airway network.
    """
    # Collect all point names across every procedure variant for this key.
    all_pt_names = set()
    for proc in proc_list:
        for p in proc[2]:
            all_pt_names.add(p[0])

    # Filter route nodes to those that actually belong to a procedure.
    proc_nodes = [n for n in nodes if n in all_pt_names]

    # If fewer than 2 route nodes match any procedure points, this is a
    # single-point / airport-only segment — nothing to validate.
    if len(proc_nodes) < 2:
        return

    # Find the single procedure that contains the *most* route nodes.
    best_proc = None
    best_subseq = []
    for proc in proc_list:
        pt_names = [p[0] for p in proc[2]]
        subseq = [n for n in nodes if n in pt_names]
        if len(subseq) > len(best_subseq):
            best_subseq = subseq
            best_proc = proc

    if best_proc is None or len(best_subseq) < 2:
        return

    # Verify every adjacent pair in best_subseq is consecutive in the
    # chosen procedure's points list.
    pt_names = [p[0] for p in best_proc[2]]
    for i in range(len(best_subseq) - 1):
        a, b = best_subseq[i], best_subseq[i + 1]
        a_idx = pt_names.index(a)
        b_idx = pt_names.index(b)
        assert b_idx == a_idx + 1, (
            f"{orig}→{dest} {label} {best_proc[0]}: "
            f"{a} → {b} not consecutive in points "
            f"(indices {a_idx} → {b_idx}, expected {a_idx + 1}). "
            f"Procedure points: {pt_names}"
        )


# ---------------------------------------------------------------------------
# 3.1 Basic route query
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("orig,dest", AIRPORT_PAIRS)
def test_route_query_returns_valid_route(orig, dest):
    """Each airport pair must return a valid route with auto-selected SID/STAR."""
    response = client.post(
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
    assert response.status_code == 200, f"{orig}→{dest}: {response.text}"
    data = response.json()
    assert data["route"] != "No result.", f"{orig}→{dest}: no route found"
    assert data["route"] != "", f"{orig}→{dest}: empty route"
    assert len(data.get("nodes", [])) >= 2, f"{orig}→{dest}: insufficient nodes"
    assert data["distance"] != "0.00 nm / 0.00 km", f"{orig}→{dest}: zero distance"


# ---------------------------------------------------------------------------
# 3.2 Route topology — no branching (each node ≤ 2 edges)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("orig,dest", AIRPORT_PAIRS)
def test_route_topology_no_branching(orig, dest):
    """完整航路拓扑检查：模拟前端拼接 SID + 主航路 + STAR，验证无分支。

    分三部分检查：
    1. 自动选中的 SID/STAR 组合：按前端逻辑拼出完整航路，检查拓扑。
       主航路 nodes 是 A* 基于特定 SID/STAR 计算的，只有匹配的组合
       才能拼成连续路径。
    2. 每个 SID procedure 变体自身：检查 points 序列是否单一路径。
    3. 每个 STAR procedure 变体自身：检查 points 序列是否单一路径。
    """
    response = client.post(
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
    assert response.status_code == 200, f"{orig}→{dest}: {response.text}"
    data = response.json()
    if data["route"] == "No result.":
        pytest.fail(f"{orig}→{dest}: no route found — navdata or algorithm bug")

    route_segments = data.get("routeSegments", [])
    sid_data = data.get("SID", {})
    star_data = data.get("STAR", {})

    errors = []

    # ------------------------------------------------------------------
    # Part 1: 实线主航路（routeSegments）自身必须无分支
    # ------------------------------------------------------------------
    seg_degree = _node_degrees(route_segments)
    for node, deg in seg_degree.items():
        if deg > 2:
            errors.append(
                f"{orig}→{dest} routeSegments: node {node} has degree {deg} > 2"
            )
    seg_endpoints = [n for n, d in seg_degree.items() if d == 1]
    if len(seg_endpoints) != 2:
        errors.append(
            f"{orig}→{dest} routeSegments: expected 2 endpoints, got {len(seg_endpoints)}: {seg_endpoints}"
        )

    # ------------------------------------------------------------------
    # Part 2: 每条虚线 SID 自身必须无分支
    # ------------------------------------------------------------------
    for key, proc_list in sid_data.items():
        for proc in proc_list:
            pts = [p[0] for p in proc[2]]
            proc_edges = [(pts[i], pts[i + 1]) for i in range(len(pts) - 1) if pts[i] != pts[i + 1]]
            label = f"{orig} SID={key} rwy={proc[1]}"
            errs = _check_topology(proc_edges, label)
            errors.extend(errs)

    # ------------------------------------------------------------------
    # Part 3: 每条虚线 STAR 自身必须无分支
    # ------------------------------------------------------------------
    for key, proc_list in star_data.items():
        for proc in proc_list:
            pts = [p[0] for p in proc[2]]
            proc_edges = [(pts[i], pts[i + 1]) for i in range(len(pts) - 1) if pts[i] != pts[i + 1]]
            label = f"{dest} STAR={key} rwy={proc[1]}"
            errs = _check_topology(proc_edges, label)
            errors.extend(errs)

    assert not errors, "Route topology errors:\n" + "\n".join(errors)


# ---------------------------------------------------------------------------
# 3.3 Procedure path continuity — no skipped nodes
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("orig,dest", AIRPORT_PAIRS)
def test_route_procedure_segments_continuous(orig, dest):
    """SID/STAR segments must follow complete procedure paths without skipping.

    When internal_edges are pooled across all procedures for an airport,
    A* may use a shortcut edge from one procedure (e.g. WAYVE1's EHF→LOPES)
    while traversing another (e.g. KIMMO3), bypassing intermediate nodes
    (ARVIN, AMONT).  This test verifies that every adjacent pair of nodes
    in the route's SID/STAR segment is consecutive in the corresponding
    procedure definition.
    """
    response = client.post(
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
    assert response.status_code == 200, f"{orig}→{dest}: {response.text}"
    data = response.json()
    if data["route"] == "No result.":
        pytest.fail(f"{orig}→{dest}: no route found — navdata or algorithm bug")

    for label, field_name in [("SID", "SID"), ("STAR", "STAR")]:
        nodes = _extract_airway_nodes(data.get("routeSegments", []), label)
        if len(nodes) < 2:
            continue

        procedures = data.get(field_name, {})
        if not procedures:
            continue

        # Infer the actually-used procedure by matching route nodes.
        proc_key = _find_best_procedure_key(nodes, procedures)
        if not proc_key:
            continue

        proc_list = procedures[proc_key]
        _check_procedure_continuity(nodes, proc_list, label, orig, dest)


# ---------------------------------------------------------------------------
# 3.4 Exhaustive SID exits — every exit must produce a valid route
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("orig,dest", AIRPORT_PAIRS)
def test_all_sid_exits_produce_valid_routes(orig, dest):
    """穷举 orig 的所有 SID exit points，每个 exit 都应生成有效 route。

    不局限于自动选中的 SID，而是遍历该机场所有 SID exit nodes，
    对每个 exit 查询 route（STAR 自动选择），验证返回 route 的拓扑、
    连续性及 procedure 覆盖完整性。
    """
    sid_exits = _get_sid_exits(orig)
    if not sid_exits:
        pytest.fail(f"{orig}→{dest}: no SID exits — navdata or algorithm bug")

    failures = []
    total = 0
    for sid in sid_exits:
        total += 1
        response = client.post(
            "/api/route",
            json={
                "orig": orig,
                "dest": dest,
                "validCode": "",
                "validToken": "",
                "sidExit": sid,
                "starEntry": "",
                "cycle": "2604",
            },
        )
        if response.status_code == 500:
            failures.append(f"SID={sid}: HTTP 500")
            continue
        if response.status_code == 404:
            failures.append(f"SID={sid}: HTTP 404")
            continue
        if response.status_code != 200:
            failures.append(f"SID={sid}: HTTP {response.status_code}")
            continue

        data = response.json()
        if data.get("route") == "No result.":
            failures.append(f"SID={sid}: no route found")
            continue

        # Validity checks
        if len(data.get("nodes", [])) < 2:
            failures.append(f"SID={sid}: insufficient nodes")
        if data.get("distance") == "0.00 nm / 0.00 km":
            failures.append(f"SID={sid}: zero distance")

        # Topology check on routeSegments
        route_segments = data.get("routeSegments", [])
        seg_degree = _node_degrees(route_segments)
        for node, deg in seg_degree.items():
            if deg > 2:
                failures.append(f"SID={sid}: node {node} degree {deg} > 2")
        seg_endpoints = [n for n, d in seg_degree.items() if d == 1]
        if len(seg_endpoints) != 2 and len(seg_endpoints) != 0:
            failures.append(
                f"SID={sid}: expected 2 endpoints, got {len(seg_endpoints)}"
            )

        # SID procedure continuity — exhaustively find best-matching procedure
        sid_nodes = _extract_airway_nodes(route_segments, "SID")
        if len(sid_nodes) >= 2:
            sid_procedures = data.get("SID", {})
            if sid_procedures:
                proc_key = _find_best_procedure_key(sid_nodes, sid_procedures)
                if proc_key:
                    proc_list = sid_procedures[proc_key]
                    try:
                        _check_procedure_continuity(
                            sid_nodes, proc_list, "SID", orig, dest
                        )
                    except AssertionError as e:
                        failures.append(f"SID={sid}: {e}")

        # STAR procedure continuity
        star_nodes = _extract_airway_nodes(route_segments, "STAR")
        if len(star_nodes) >= 2:
            star_procedures = data.get("STAR", {})
            if star_procedures:
                proc_key = _find_best_procedure_key(star_nodes, star_procedures)
                if proc_key:
                    proc_list = star_procedures[proc_key]
                    try:
                        _check_procedure_continuity(
                            star_nodes, proc_list, "STAR", orig, dest
                        )
                    except AssertionError as e:
                        failures.append(f"SID={sid}: STAR continuity: {e}")

    assert not failures, (
        f"{orig}→{dest}: {len(failures)}/{total} SID exits failed:\n"
        + "\n".join(failures[:20])
        + (f"\n... and {len(failures) - 20} more" if len(failures) > 20 else "")
    )


# ---------------------------------------------------------------------------
# 3.5 Exhaustive STAR entries — every entry must produce a valid route
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("orig,dest", AIRPORT_PAIRS)
def test_all_star_entries_produce_valid_routes(orig, dest):
    """穷举 dest 的所有 STAR entry points，每个 entry 都应生成有效 route。

    不局限于自动选中的 STAR，而是遍历该机场所有 STAR entry nodes，
    对每个 entry 查询 route（SID 自动选择），验证返回 route 的拓扑、
    连续性及 procedure 覆盖完整性。
    """
    star_entries = _get_star_entries(dest)
    if not star_entries:
        pytest.fail(f"{orig}→{dest}: no STAR entries — navdata or algorithm bug")

    failures = []
    total = 0
    for star in star_entries:
        total += 1
        response = client.post(
            "/api/route",
            json={
                "orig": orig,
                "dest": dest,
                "validCode": "",
                "validToken": "",
                "sidExit": "",
                "starEntry": star,
                "cycle": "2604",
            },
        )
        if response.status_code == 500:
            failures.append(f"STAR={star}: HTTP 500")
            continue
        if response.status_code == 404:
            failures.append(f"STAR={star}: HTTP 404")
            continue
        if response.status_code != 200:
            failures.append(f"STAR={star}: HTTP {response.status_code}")
            continue

        data = response.json()
        if data.get("route") == "No result.":
            failures.append(f"STAR={star}: no route found")
            continue

        if len(data.get("nodes", [])) < 2:
            failures.append(f"STAR={star}: insufficient nodes")
        if data.get("distance") == "0.00 nm / 0.00 km":
            failures.append(f"STAR={star}: zero distance")

        route_segments = data.get("routeSegments", [])
        seg_degree = _node_degrees(route_segments)
        for node, deg in seg_degree.items():
            if deg > 2:
                failures.append(f"STAR={star}: node {node} degree {deg} > 2")
        seg_endpoints = [n for n, d in seg_degree.items() if d == 1]
        if len(seg_endpoints) != 2 and len(seg_endpoints) != 0:
            failures.append(
                f"STAR={star}: expected 2 endpoints, got {len(seg_endpoints)}"
            )

        sid_nodes = _extract_airway_nodes(route_segments, "SID")
        if len(sid_nodes) >= 2:
            sid_procedures = data.get("SID", {})
            if sid_procedures:
                proc_key = _find_best_procedure_key(sid_nodes, sid_procedures)
                if proc_key:
                    proc_list = sid_procedures[proc_key]
                    try:
                        _check_procedure_continuity(
                            sid_nodes, proc_list, "SID", orig, dest
                        )
                    except AssertionError as e:
                        failures.append(f"STAR={star}: SID continuity: {e}")

        star_nodes = _extract_airway_nodes(route_segments, "STAR")
        if len(star_nodes) >= 2:
            star_procedures = data.get("STAR", {})
            if star_procedures:
                proc_key = _find_best_procedure_key(star_nodes, star_procedures)
                if proc_key:
                    proc_list = star_procedures[proc_key]
                    try:
                        _check_procedure_continuity(
                            star_nodes, proc_list, "STAR", orig, dest
                        )
                    except AssertionError as e:
                        failures.append(f"STAR={star}: {e}")

    assert not failures, (
        f"{orig}→{dest}: {len(failures)}/{total} STAR entries failed:\n"
        + "\n".join(failures[:20])
        + (f"\n... and {len(failures) - 20} more" if len(failures) > 20 else "")
    )


# ---------------------------------------------------------------------------
# 3.6 ZBAA → KLAX KIMMO3 regression test
# ---------------------------------------------------------------------------

def test_zbaa_klax_kimmo3_includes_all_nodes():
    """ZBAA→KLAX via KIMMO3 must not skip ARVIN and AMONT.

    Regression test for a bug where pooled internal_edges allowed A* to
    use WAYVE1's EHF→LOPES shortcut while traversing KIMMO3, bypassing
    ARVIN and AMONT.
    """
    response = client.post(
        "/api/route",
        json={
            "orig": "ZBAA",
            "dest": "KLAX",
            "validCode": "",
            "validToken": "",
            "sidExit": "",
            "starEntry": "",
            "cycle": "2604",
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["route"] != "No result.", "ZBAA→KLAX: no route found"

    star_nodes = _extract_airway_nodes(data["routeSegments"], "STAR")
    assert "ARVIN" in star_nodes, f"ARVIN missing from STAR: {star_nodes}"
    assert "AMONT" in star_nodes, f"AMONT missing from STAR: {star_nodes}"

    # Verify expected order within the STAR segment
    expected = ["EHF", "ARVIN", "AMONT", "LOPES", "LHS"]
    for i, node in enumerate(expected):
        assert node in star_nodes, f"{node} missing from STAR segment"
        if i > 0:
            prev_idx = star_nodes.index(expected[i - 1])
            curr_idx = star_nodes.index(node)
            assert curr_idx == prev_idx + 1, (
                f"Expected {expected[i - 1]} → {node} consecutive, "
                f"got indices {prev_idx} → {curr_idx} in {star_nodes}"
            )


# ---------------------------------------------------------------------------
# 3.7 Airport procedures availability
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("icao", TEST_AIRPORTS)
def test_airport_procedures_available(icao):
    """Each test airport must have SID/STAR procedures available."""
    response = client.get(f"/api/airports/{icao}/procedures?cycle=2604")
    assert response.status_code == 200, f"{icao}: {response.text}"
    data = response.json()
    # At least one of SID or STAR should be non-empty for major airports
    sid_count = len(data.get("sid", {}).get("exits", []))
    star_count = len(data.get("star", {}).get("entries", []))
    assert sid_count > 0 or star_count > 0, f"{icao}: no procedures found"


# ---------------------------------------------------------------------------
# 3.8 Airport autocomplete
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("query,expected_icao", [
    ("ZB", "ZBAA"),          # ICAO prefix match
    ("Incheon", "RKSI"),     # Name substring match
    ("RJTT", "RJTT"),        # Exact ICAO match
])
def test_airport_autocomplete(query, expected_icao):
    """GET /api/airports?q= must return matching airports."""
    response = client.get(f"/api/airports?q={query}")
    assert response.status_code == 200
    data = response.json()
    assert "airports" in data
    icaos = [ap["icao"] for ap in data["airports"]]
    assert expected_icao in icaos, f"Expected {expected_icao} in {icaos}"


def test_airport_autocomplete_empty_query():
    """Empty query must return the first 50 airports."""
    response = client.get("/api/airports?q=")
    assert response.status_code == 200
    data = response.json()
    assert len(data["airports"]) > 0


def test_airport_autocomplete_no_query():
    """No query param must return the first 50 airports."""
    response = client.get("/api/airports")
    assert response.status_code == 200
    data = response.json()
    assert len(data["airports"]) > 0


# ---------------------------------------------------------------------------
# 3.9 Cycles endpoint
# ---------------------------------------------------------------------------

def test_cycles_endpoint():
    """GET /api/cycles must return cycle list and default cycle."""
    response = client.get("/api/cycles")
    assert response.status_code == 200
    data = response.json()
    assert "cycles" in data
    assert "default" in data
    assert "disableCaptcha" in data
    assert len(data["cycles"]) > 0
    assert data["default"] is not None


# ---------------------------------------------------------------------------
# 3.10 Exhaustive SID x STAR Cartesian product
# ---------------------------------------------------------------------------

def _get_sid_exits(icao: str) -> list:
    """Fetch SID exit names for an airport."""
    resp = client.get(f"/api/airports/{icao}/procedures?cycle=2604")
    if resp.status_code != 200:
        return []
    data = resp.json()
    return [e["name"] for e in data.get("sid", {}).get("exits", [])]


def _get_star_entries(icao: str) -> list:
    """Fetch STAR entry names for an airport."""
    resp = client.get(f"/api/airports/{icao}/procedures?cycle=2604")
    if resp.status_code != 200:
        return []
    data = resp.json()
    return [e["name"] for e in data.get("star", {}).get("entries", [])]


@pytest.mark.parametrize("orig,dest", AIRPORT_PAIRS)
def test_exhaustive_sid_star_combinations(orig, dest):
    """For each airport pair, test every SID x STAR combination.

    Not all combinations produce a valid route (incompatible SID/STAR pairs
    or missing airway connectivity), but none should crash with 500.
    """
    sid_exits = _get_sid_exits(orig)
    star_entries = _get_star_entries(dest)

    if not sid_exits or not star_entries:
        pytest.skip(f"{orig}→{dest}: no SID/STAR to combine")

    failures = []
    total = 0
    for sid in sid_exits:
        for star in star_entries:
            total += 1
            response = client.post(
                "/api/route",
                json={
                    "orig": orig,
                    "dest": dest,
                    "validCode": "",
                    "validToken": "",
                    "sidExit": sid,
                    "starEntry": star,
                    "cycle": "2604",
                },
            )
            if response.status_code == 500:
                failures.append(
                    f"{orig}→{dest} SID={sid} STAR={star}: HTTP 500"
                )
            elif response.status_code not in (200, 404):
                failures.append(
                    f"{orig}→{dest} SID={sid} STAR={star}: HTTP {response.status_code}"
                )

    assert not failures, (
        f"{orig}→{dest}: {len(failures)}/{total} SID×STAR combinations failed:\n"
        + "\n".join(failures[:20])
        + (f"\n... and {len(failures) - 20} more" if len(failures) > 20 else "")
    )
