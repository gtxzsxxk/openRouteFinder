"""HTTP API integration tests that mimic frontend calls."""

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
    ("KSEA", "KLAX"),
    ("KLAX", "KSEA"),
    ("KJFK", "KLAX"),
    ("ZBAA", "TNCM"),
    ("ZBAA", "ZGSZ"),
]

# 需要跑完整 SID × STAR 笛卡尔积的航线
EXHAUSTIVE_CARTESIAN_PAIRS = [
    ("ZBAA", "ZGGG"),
    ("RJTT", "RJBB"),
    ("RJBB", "RJTT"),
    ("KLAX", "KSEA"),
    ("KLAX", "KJFK"),
    ("ZBAA", "TNCM"),
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
    """Find the procedure key whose main points contain the most route nodes.

    We intentionally ignore transitions here to match the scoring logic in
    _best_proc_for_run() (dijkstra.py), which only considers proc.points.
    Including transitions would incorrectly inflate scores for procedures
    that list unrelated transitions (e.g. KJFK DEEZZ6 under the HEERO key
    carries the CANDR/TOWIN transitions, making it indistinguishable from
    the DEEZZ key).
    """
    best_key = None
    best_score = 0
    # Sort keys alphabetically so tie-breaking is deterministic and
    # independent of dict insertion order.
    for key, proc_list in sorted(procedures.items()):
        for proc in proc_list:
            proc_names = [p[0] for p in proc[2]]
            score = sum(1 for n in nodes if n in proc_names)
            if score > best_score:
                best_score = score
                best_key = key
            elif score == best_score and best_key is not None:
                # Tie-break: prefer key whose name appears in the route nodes
                # (more specific procedure over generic superset)
                if key in nodes and best_key not in nodes:
                    best_key = key
    return best_key if best_score >= 2 else None


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
    # When two procedures tie (e.g. RUK01A vs RUK02A under key RUKLI),
    # prefer the shorter one — it is the more specific match.
    best_proc = None
    best_subseq = []
    for proc in proc_list:
        pt_names = [p[0] for p in proc[2]]
        subseq = [n for n in nodes if n in pt_names]
        if len(subseq) > len(best_subseq):
            best_subseq = subseq
            best_proc = proc
        elif len(subseq) == len(best_subseq) and len(subseq) >= 2:
            if best_proc is None or len(proc[2]) < len(best_proc[2]):
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
# 3.4 SID/STAR node name consistency
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("orig,dest", AIRPORT_PAIRS)
def test_route_sid_star_node_name_matches_procedure(orig, dest):
    """sidNodeName / starNodeName must point to the procedure actually used.

    When pooled internal_edges share nodes across procedures, the old
    _find_procedure_key_for_node() could return the wrong procedure key
    (e.g. BOTP7X instead of DOTR5Y for ZBAA 36R).  The frontend then
    displays the wrong procedure even though the route itself is correct.

    This test verifies that the reported sidNodeName/starNodeName key
    corresponds to a procedure whose points overlap the actual route nodes.
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
    if data.get("route") == "No result.":
        pytest.fail(f"{orig}→{dest}: no route found — navdata or algorithm bug")

    nodes = [n["name"] for n in data.get("nodes", [])]
    if len(nodes) < 2:
        pytest.fail(f"{orig}→{dest}: insufficient nodes")

    for label, field_name, node_name_field in [
        ("SID", "SID", "sidNodeName"),
        ("STAR", "STAR", "starNodeName"),
    ]:
        proc_key = data.get(node_name_field)
        if not proc_key:
            continue

        procedures = data.get(field_name, {})
        if proc_key not in procedures:
            pytest.fail(
                f"{orig}→{dest} {label}: {node_name_field}={proc_key!r} "
                f"but no such key in {label} procedures. "
                f"Available keys: {list(procedures.keys())}"
            )

        proc_list = procedures[proc_key]
        if not proc_list:
            pytest.fail(
                f"{orig}→{dest} {label}: {node_name_field}={proc_key!r} "
                f"but procedure list is empty."
            )

        # Extract the airway nodes for this label from routeSegments.
        # When a route actually follows a procedure, the segment nodes
        # should match one of the procedures under the reported key.
        # If they don't, _find_procedure_key_for_node picked the wrong key.
        seg_nodes = _extract_airway_nodes(data.get("routeSegments", []), label)
        if len(seg_nodes) < 2:
            continue

        best_key = _find_best_procedure_key(seg_nodes, procedures)
        if best_key is None:
            continue

        assert proc_key == best_key, (
            f"{orig}→{dest} {label}: {node_name_field}={proc_key!r} "
            f"but the actual route segment best matches key={best_key!r}. "
            f"This means the wrong procedure key was reported. "
            f"Route {label} nodes: {seg_nodes}"
        )


# ---------------------------------------------------------------------------
# 3.4.1 Frontend procedure selection simulation
# ---------------------------------------------------------------------------

def _simulate_frontend_procedure_selection(seg_nodes: list, proc_list: list, label: str = "SID"):
    """模拟前端 _matchProcedureIndex + _matchTransitionIndex 的选择逻辑。

    返回 (selected_proc, selected_transition_points, full_point_names)
    其中 full_point_names 是前端最终用来画线的点名称序列。
    """
    route_node_names = set(seg_nodes)

    # _matchProcedureIndex
    best_proc_idx = 0
    best_score = -1
    for i, proc in enumerate(proc_list):
        point_names = set(p[0] for p in proc[2])
        score = sum(1 for name in point_names if name in route_node_names)
        # Also consider transitions
        for t in proc[3]:
            t_point_names = set(p[0] for p in t[1])
            t_score = sum(1 for name in t_point_names if name in route_node_names)
            if t_score > score:
                score = t_score
        score = score * 1000 + len(proc[2])
        if score > best_score:
            best_score = score
            best_proc_idx = i

    selected_proc = proc_list[best_proc_idx]
    transitions = selected_proc[3] or []

    # _matchTransitionIndex
    best_trans_idx = -1
    best_trans_score = -1
    for i, t in enumerate(transitions):
        t_points = t[1]
        t_point_names = set(p[0] for p in t_points)
        score = sum(1 for name in t_point_names if name in route_node_names)
        score = score * 1000 + len(t_points)
        if score > best_trans_score:
            best_trans_score = score
            best_trans_idx = i

    # Build full points sequence like the frontend does
    main_points = [p[0] for p in selected_proc[2]]
    full_points = list(main_points)
    if best_trans_idx >= 0:
        trans_points = [p[0] for p in transitions[best_trans_idx][1]]
        main_names = set(main_points)
        if label == "STAR":
            # STAR: transition comes before main points.
            # If transition's last point is not in main, it's a replacement.
            if trans_points and trans_points[-1] not in main_names:
                full_points = list(trans_points)
            else:
                # Prepend non-overlapping transition points before main
                prepended = [tp for tp in trans_points if tp not in main_names]
                full_points = prepended + full_points
        else:
            # SID: main points come before transition.
            # If transition's first point is not in main, it's a replacement.
            if trans_points and trans_points[0] not in main_names:
                full_points = list(trans_points)
            else:
                # Append non-overlapping transition points after main
                for tp in trans_points:
                    if tp not in main_names:
                        full_points.append(tp)

    return selected_proc, best_trans_idx, full_points


@pytest.mark.parametrize("orig,dest", AIRPORT_PAIRS)
def test_frontend_procedure_selection_matches_route(orig, dest):
    """模拟前端选择 SID/STAR procedure 的逻辑，验证选中结果与航路一致。

    前端根据 sidNodeName 获取 procedure 列表，然后用 _matchProcedureIndex
    和 _matchTransitionIndex 选择最匹配的 variant 和 transition。本测试在
    后端模拟这一过程，然后验证选中的 procedure+transition 的 points 序列
    包含航路 segment 作为连续子序列。如果前端会选中错误的 procedure（例如
    航路实际走 DOTR5Y 但前端选中 BOTP7X），测试就会失败。
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
    if data.get("route") == "No result.":
        pytest.fail(f"{orig}→{dest}: no route found — navdata or algorithm bug")

    for label, field_name, node_name_field in [
        ("SID", "SID", "sidNodeName"),
        ("STAR", "STAR", "starNodeName"),
    ]:
        seg_nodes = _extract_airway_nodes(data.get("routeSegments", []), label)
        if len(seg_nodes) < 2:
            continue

        proc_key = data.get(node_name_field)
        if not proc_key:
            continue

        procedures = data.get(field_name, {})
        if proc_key not in procedures:
            continue

        proc_list = procedures[proc_key]
        if not proc_list:
            continue

        selected_proc, _trans_idx, full_points = _simulate_frontend_procedure_selection(
            seg_nodes, proc_list, label
        )

        # Strip airport nodes (first/last) from the segment because procedure
        # points start at the runway endpoint, not the airport itself.
        check_nodes = list(seg_nodes)
        if check_nodes and check_nodes[0] not in full_points:
            check_nodes = check_nodes[1:]
        if check_nodes and check_nodes[-1] not in full_points:
            check_nodes = check_nodes[:-1]

        if len(check_nodes) < 2:
            continue

        # Verify every adjacent pair in check_nodes is consecutive in the
        # selected procedure+transition points.  If any pair is not, the
        # frontend would draw a line that doesn't match the actual route.
        errors = []
        for i in range(len(check_nodes) - 1):
            a, b = check_nodes[i], check_nodes[i + 1]
            if a in full_points and b in full_points:
                a_idx = full_points.index(a)
                if a_idx + 1 < len(full_points) and full_points[a_idx + 1] == b:
                    continue
            errors.append(f"{a}→{b}")

        if errors:
            pytest.fail(
                f"{orig}→{dest} {label}: frontend would select "
                f"{selected_proc[0]!r} rwy={selected_proc[1]!r} "
                f"but route segment {check_nodes} contains non-consecutive "
                f"pairs {errors} in the selected procedure+transition "
                f"points {full_points}. "
                f"This means the frontend would display the wrong procedure."
            )


# ---------------------------------------------------------------------------
# 3.5 Exhaustive SID exits — every exit must produce a valid route
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
# 3.6 ZBAA → KLAX procedure continuity regression test
# ---------------------------------------------------------------------------

def test_zbaa_klax_procedure_continuity():
    """ZBAA→KLAX STAR segment must follow a complete procedure path without
    skipping intermediate nodes.

    Regression test for a bug where pooled internal_edges allowed A* to
    use WAYVE1's EHF→LOPES shortcut while traversing KIMMO3, bypassing
    ARVIN and AMONT.  The walk test verifies this for all airport pairs;
    this test additionally checks the specific KIMMO3 path when it is used.
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
    star_key = data.get("starNodeName")
    if not star_key:
        return

    star_procs = data.get("STAR", {})
    if star_key not in star_procs:
        return

    proc_list = star_procs[star_key]
    _check_procedure_continuity(star_nodes, proc_list, "STAR", "ZBAA", "KLAX")


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


@pytest.mark.parametrize("orig,dest", EXHAUSTIVE_CARTESIAN_PAIRS)
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


# ---------------------------------------------------------------------------
# 3.11 Complete API response structure validation
# ---------------------------------------------------------------------------

RUNWAY_RE = re.compile(r'^\d+[LRC]?$')


def _assert_api_response_structure(data: dict, orig: str, dest: str):
    """Assert that the /api/route response contains all expected fields with valid types/values.

    This is a comprehensive structural check that every field the frontend depends on
    is present and well-formed.  It catches regressions in any output field, not just
    the ones covered by behavioural tests above.
    """
    errors = []

    # --- Top-level required fields ---
    required_top = [
        "data_version", "total_time", "route", "distance",
        "SID", "STAR", "airportName",
        "sidNodeName", "starNodeName",
        "sidRouteNodeName", "starRouteNodeName",
        "routeSegments", "nodes",
        "weather", "airportDetails", "parsedWeather",
        "origRunways", "destRunways",
    ]
    for key in required_top:
        if key not in data:
            errors.append(f"missing top-level key: {key}")

    if errors:
        return errors

    # --- Scalar fields ---
    if not isinstance(data["data_version"], str) or not data["data_version"]:
        errors.append(f"data_version={data['data_version']!r} is not a non-empty string")
    if not isinstance(data["total_time"], str):
        errors.append(f"total_time type={type(data['total_time']).__name__} != str")
    if not isinstance(data["route"], str) or not data["route"]:
        errors.append(f"route={data['route']!r} is empty")
    if not isinstance(data["distance"], str) or "nm" not in data["distance"]:
        errors.append(f"distance={data['distance']!r} missing 'nm'")

    # --- airportName ---
    ap_name = data.get("airportName", [])
    if not isinstance(ap_name, list) or len(ap_name) < 2:
        errors.append(f"airportName={ap_name!r} is not a list of length >= 2")

    # --- SID / STAR ---
    for label in ("SID", "STAR"):
        procs = data.get(label, {})
        if not isinstance(procs, dict):
            errors.append(f"{label} type={type(procs).__name__} != dict")
            continue
        for key, proc_list in procs.items():
            if not isinstance(proc_list, list):
                errors.append(f"{label}[{key!r}] is not a list")
                continue
            for proc in proc_list:
                # proc tuple: [name, runway, points, transitions]
                if not isinstance(proc, list) or len(proc) != 4:
                    errors.append(f"{label}[{key!r}] procedure shape {type(proc).__name__} len={len(proc) if isinstance(proc, list) else 'N/A'}")
                    continue
                pname, prunway, ppoints, ptrans = proc
                if not isinstance(pname, str):
                    errors.append(f"{label}[{key!r}] name type={type(pname).__name__}")
                if not isinstance(prunway, str):
                    errors.append(f"{label}[{key!r}] runway type={type(prunway).__name__}")
                elif prunway not in ("ALL", "") and not RUNWAY_RE.match(prunway):
                    errors.append(f"{label}[{key!r}] {pname}: runway={prunway!r} is not a valid runway designator")
                # points
                if not isinstance(ppoints, list):
                    errors.append(f"{label}[{key!r}] {pname}: points type={type(ppoints).__name__}")
                else:
                    for pt in ppoints:
                        if not isinstance(pt, list) or len(pt) != 3:
                            errors.append(f"{label}[{key!r}] {pname}: point shape {pt!r}")
                            break
                        if not isinstance(pt[0], str):
                            errors.append(f"{label}[{key!r}] {pname}: point name type={type(pt[0]).__name__}")
                            break
                # transitions
                if not isinstance(ptrans, list):
                    errors.append(f"{label}[{key!r}] {pname}: transitions type={type(ptrans).__name__}")
                else:
                    for t in ptrans:
                        if not isinstance(t, list) or len(t) != 2:
                            errors.append(f"{label}[{key!r}] {pname}: transition shape {t!r}")
                            break
                        tname, tpts = t
                        if not isinstance(tname, str):
                            errors.append(f"{label}[{key!r}] {pname}: transition name type={type(tname).__name__}")
                            break
                        if not isinstance(tpts, list):
                            errors.append(f"{label}[{key!r}] {pname}: transition points type={type(tpts).__name__}")
                            break
                        for pt in tpts:
                            if not isinstance(pt, list) or len(pt) != 3:
                                errors.append(f"{label}[{key!r}] {pname}: transition point shape {pt!r}")
                                break

    # --- routeSegments ---
    segs = data.get("routeSegments", [])
    if not isinstance(segs, list):
        errors.append(f"routeSegments type={type(segs).__name__} != list")
    else:
        for i, seg in enumerate(segs):
            if not isinstance(seg, dict):
                errors.append(f"routeSegments[{i}] type={type(seg).__name__}")
                continue
            for k in ("from", "to", "airway"):
                if k not in seg:
                    errors.append(f"routeSegments[{i}] missing key '{k}'")
                    break
            if "from" in seg and not isinstance(seg["from"], str):
                errors.append(f"routeSegments[{i}]['from'] type={type(seg['from']).__name__}")
            if "to" in seg and not isinstance(seg["to"], str):
                errors.append(f"routeSegments[{i}]['to'] type={type(seg['to']).__name__}")
            if "airway" in seg and not isinstance(seg["airway"], str):
                errors.append(f"routeSegments[{i}]['airway'] type={type(seg['airway']).__name__}")

    # --- nodes ---
    nodes = data.get("nodes", [])
    if not isinstance(nodes, list):
        errors.append(f"nodes type={type(nodes).__name__} != list")
    elif len(nodes) < 2:
        errors.append(f"nodes length={len(nodes)} < 2")
    else:
        for i, n in enumerate(nodes):
            if not isinstance(n, dict):
                errors.append(f"nodes[{i}] type={type(n).__name__}")
                continue
            for k in ("name", "lat", "lon"):
                if k not in n:
                    errors.append(f"nodes[{i}] missing key '{k}'")
                    break
            if "name" in n and not isinstance(n["name"], str):
                errors.append(f"nodes[{i}]['name'] type={type(n['name']).__name__}")
            if "lat" in n and not isinstance(n["lat"], (int, float)):
                errors.append(f"nodes[{i}]['lat'] type={type(n['lat']).__name__}")
            if "lon" in n and not isinstance(n["lon"], (int, float)):
                errors.append(f"nodes[{i}]['lon'] type={type(n['lon']).__name__}")

    # --- weather ---
    weather = data.get("weather", [])
    if not isinstance(weather, list) or len(weather) != 2:
        errors.append(f"weather={weather!r} is not a list of length 2")
    else:
        for i, w in enumerate(weather):
            if not isinstance(w, str):
                errors.append(f"weather[{i}] type={type(w).__name__} != str")

    # --- airportDetails ---
    apd = data.get("airportDetails", {})
    if not isinstance(apd, dict):
        errors.append(f"airportDetails type={type(apd).__name__} != dict")
    else:
        for k in ("orig", "dest"):
            if k not in apd:
                errors.append(f"airportDetails missing key '{k}'")

    # --- parsedWeather ---
    pw = data.get("parsedWeather", [])
    if not isinstance(pw, list) or len(pw) != 2:
        errors.append(f"parsedWeather={pw!r} is not a list of length 2")
    else:
        for i, p in enumerate(pw):
            if not isinstance(p, dict):
                errors.append(f"parsedWeather[{i}] type={type(p).__name__} != dict")
                continue
            for k in ("raw", "station", "windDirection", "windSpeed",
                      "visibility", "clouds", "temperature", "dewpoint", "qnh"):
                if k not in p:
                    errors.append(f"parsedWeather[{i}] missing key '{k}'")
                    break
            if "clouds" in p and not isinstance(p["clouds"], list):
                errors.append(f"parsedWeather[{i}]['clouds'] type={type(p['clouds']).__name__}")

    # --- origRunways / destRunways ---
    for label in ("origRunways", "destRunways"):
        rwys = data.get(label, [])
        if not isinstance(rwys, list):
            errors.append(f"{label} type={type(rwys).__name__} != list")
        else:
            for i, rw in enumerate(rwys):
                if not isinstance(rw, dict):
                    errors.append(f"{label}[{i}] type={type(rw).__name__} != dict")
                    continue
                for k in ("name", "thresholds"):
                    if k not in rw:
                        errors.append(f"{label}[{i}] missing key '{k}'")
                        break
                if "thresholds" in rw and not isinstance(rw["thresholds"], list):
                    errors.append(f"{label}[{i}]['thresholds'] type={type(rw['thresholds']).__name__}")

    # --- active transitions ---
    for key in ("activeSIDTransition", "activeSTARTransition"):
        val = data.get(key)
        if val is not None and not isinstance(val, str):
            errors.append(f"{key}={val!r} type={type(val).__name__} != str")

    # --- Node name references must be non-empty strings ---
    for key in ("sidNodeName", "starNodeName", "sidRouteNodeName", "starRouteNodeName"):
        val = data.get(key)
        if val is not None and (not isinstance(val, str) or not val):
            errors.append(f"{key}={val!r} is empty or not a string")

    return errors


@pytest.mark.parametrize("orig,dest", AIRPORT_PAIRS)
def test_route_response_structure_complete(orig, dest):
    """Every /api/route response field must be present and well-formed.

    This catches regressions in any output field, including ones not exercised
    by behavioural tests (e.g. airportDetails, parsedWeather, runway arrays).
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
    if data.get("route") == "No result.":
        pytest.fail(f"{orig}→{dest}: no route found — navdata or algorithm bug")

    errors = _assert_api_response_structure(data, orig, dest)
    assert not errors, "\n".join(errors)


# ---------------------------------------------------------------------------
# Helpers for route walking
# ---------------------------------------------------------------------------

def _build_full_node_sequence(segments: list) -> list:
    """Build ordered node list from routeSegments (from/to chain)."""
    nodes = []
    for seg in segments:
        if not nodes or nodes[-1] != seg["from"]:
            nodes.append(seg["from"])
        nodes.append(seg["to"])
    return nodes


def _build_adjacency_from_segments(segments: list) -> dict:
    """Build {from: {to, ...}} adjacency from routeSegments."""
    adj = {}
    for seg in segments:
        f, t = seg["from"], seg["to"]
        adj.setdefault(f, set()).add(t)
    return adj


def _verify_sid_star_complete_path(
    seg_nodes: list,
    procedures: dict,
    label: str,
    orig: str,
    dest: str,
) -> list:
    """Verify seg_nodes forms a complete contiguous subsequence of some procedure.

    For SID: seg_nodes[0] is the airport, seg_nodes[1:] should be a contiguous
    subsequence starting from the first point of the procedure.

    For STAR: seg_nodes[-1] is the airport, seg_nodes[:-1] should be a contiguous
    subsequence ending at the last point of the procedure.
    """
    errors = []
    if len(seg_nodes) < 2:
        return errors

    # Determine procedure nodes (excluding airport)
    if label == "SID":
        proc_seg_nodes = seg_nodes[1:]  # Skip airport at start
    else:
        proc_seg_nodes = seg_nodes[:-1]  # Skip airport at end

    if len(proc_seg_nodes) < 2:
        return errors

    # Find best matching procedure and check against ALL procedures
    best_proc = None
    best_key = None
    best_score = 0
    valid_procs = []

    for key, proc_list in procedures.items():
        for proc in proc_list:
            proc_names = [p[0] for p in proc[2]]
            all_names = set(proc_names)
            for _, t_pts in proc[3]:
                all_names.update(p[0] for p in t_pts)
            score = sum(1 for n in seg_nodes if n in all_names)
            if score > best_score:
                best_score = score
                best_proc = proc
                best_key = key

            # Check if this procedure fully validates the segment
            if score < 2:
                continue

            # Check consecutive pairs
            has_gap = False
            for i in range(len(proc_seg_nodes) - 1):
                a, b = proc_seg_nodes[i], proc_seg_nodes[i + 1]
                if a not in proc_names or b not in proc_names:
                    continue
                a_idx = proc_names.index(a)
                b_idx = proc_names.index(b)
                if b_idx != a_idx + 1:
                    has_gap = True
                    break

            if has_gap:
                continue

            # Check boundary conditions
            if label == "SID" and proc_seg_nodes:
                if proc_seg_nodes[0] != proc_names[0]:
                    continue
            if label == "STAR" and proc_seg_nodes:
                if proc_seg_nodes[-1] != proc_names[-1]:
                    continue

            valid_procs.append(proc)

    if valid_procs:
        return errors

    if best_proc is None or best_score < 2:
        return errors

    proc_names = [p[0] for p in best_proc[2]]

    # Report errors using the best-matching procedure
    for i in range(len(proc_seg_nodes) - 1):
        a, b = proc_seg_nodes[i], proc_seg_nodes[i + 1]
        if a not in proc_names or b not in proc_names:
            continue
        a_idx = proc_names.index(a)
        b_idx = proc_names.index(b)
        if b_idx != a_idx + 1:
            errors.append(
                f"{orig}->{dest} {label}: {a} -> {b} not consecutive in "
                f"{best_proc[0]} rwy={best_proc[1]} (indices {a_idx} -> {b_idx}, "
                f"expected {a_idx + 1}). Procedure points: {proc_names}"
            )

    if label == "SID" and proc_seg_nodes and proc_names:
        if proc_seg_nodes[0] != proc_names[0]:
            errors.append(
                f"{orig}->{dest} SID: first proc node {proc_seg_nodes[0]!r} != "
                f"procedure first point {proc_names[0]!r} ({best_proc[0]} rwy={best_proc[1]}). "
                f"SID segment: {seg_nodes}"
            )

    if label == "STAR" and proc_seg_nodes and proc_names:
        if proc_seg_nodes[-1] != proc_names[-1]:
            errors.append(
                f"{orig}->{dest} STAR: last proc node {proc_seg_nodes[-1]!r} != "
                f"procedure last point {proc_names[-1]!r} ({best_proc[0]} rwy={best_proc[1]}). "
                f"STAR segment: {seg_nodes}"
            )

    return errors


def _walk_and_verify_route(data: dict, orig: str, dest: str) -> list:
    """Walk the complete route and return list of error messages.

    Verifies:
    1. Complete node sequence starts at orig and ends at dest
    2. Every consecutive pair has an edge in routeSegments
    3. No duplicate consecutive nodes
    4. SID segment matches a complete procedure path (from first point)
    5. STAR segment matches a complete procedure path (to last point)
    6. No node appears more than once (no cycles)
    """
    errors = []
    segments = data.get("routeSegments", [])
    nodes = [n["name"] for n in data.get("nodes", [])]

    if not segments:
        errors.append("empty routeSegments")
        return errors

    # 1. Build full node sequence from segments
    seg_nodes = _build_full_node_sequence(segments)

    # 2. Verify nodes list matches segment-derived sequence
    if nodes != seg_nodes:
        errors.append(
            f"nodes list mismatch: nodes={nodes} != seg_nodes={seg_nodes}"
        )

    # 3. Build adjacency and walk
    adj = _build_adjacency_from_segments(segments)
    for i in range(len(seg_nodes) - 1):
        a, b = seg_nodes[i], seg_nodes[i + 1]
        if a == b:
            errors.append(f"duplicate consecutive node: {a} at index {i}")
            continue
        if a not in adj or b not in adj[a]:
            errors.append(
                f"broken edge: {a} -> {b} not found in routeSegments"
            )

    # 4. Verify start/end
    if seg_nodes[0] != orig:
        errors.append(
            f"route starts at {seg_nodes[0]!r}, expected {orig!r}"
        )
    if seg_nodes[-1] != dest:
        errors.append(
            f"route ends at {seg_nodes[-1]!r}, expected {dest!r}"
        )

    # 5. No cycles: each node should appear at most once
    seen = set()
    for i, n in enumerate(seg_nodes):
        if n in seen:
            errors.append(f"node {n!r} appears multiple times (cycle at index {i})")
        seen.add(n)

    # 6. Verify SID/STAR complete procedure paths
    sid_nodes = _extract_airway_nodes(segments, "SID")
    sid_procs = data.get("SID", {})
    errors.extend(_verify_sid_star_complete_path(
        sid_nodes, sid_procs, "SID", orig, dest
    ))

    star_nodes = _extract_airway_nodes(segments, "STAR")
    star_procs = data.get("STAR", {})
    errors.extend(_verify_sid_star_complete_path(
        star_nodes, star_procs, "STAR", orig, dest
    ))

    return errors


# ---------------------------------------------------------------------------
# 3.12 Walk the complete route — from departure runway to destination runway
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("orig,dest", AIRPORT_PAIRS)
def test_walk_complete_route_auto_sid_star(orig, dest):
    """Walk the complete route for auto-selected SID/STAR.

    Verifies every step from departure airport -> SID -> airway -> STAR ->
    destination airport is connected with no gaps, no cycles, and no skipped
    procedure nodes.
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
    assert response.status_code == 200, f"{orig}->{dest}: {response.text}"
    data = response.json()
    if data.get("route") == "No result.":
        pytest.fail(f"{orig}->{dest}: no route found — navdata or algorithm bug")

    errors = _walk_and_verify_route(data, orig, dest)
    assert not errors, f"{orig}->{dest} route walk errors:\n" + "\n".join(errors)


# ---------------------------------------------------------------------------
# 3.13 Walk complete route for every SID exit
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("orig,dest", AIRPORT_PAIRS)
def test_walk_complete_route_all_sid_exits(orig, dest):
    """Walk the complete route for every SID exit point."""
    sid_exits = _get_sid_exits(orig)
    if not sid_exits:
        pytest.fail(f"{orig}->{dest}: no SID exits — navdata or algorithm bug")

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
        if response.status_code != 200:
            continue  # Skip non-200; other tests check for crashes

        data = response.json()
        if data.get("route") == "No result.":
            continue  # Some SID/dest pairs genuinely have no route

        errors = _walk_and_verify_route(data, orig, dest)
        if errors:
            failures.append(f"SID={sid}:\n" + "\n".join(errors))

    assert not failures, (
        f"{orig}->{dest}: {len(failures)}/{total} SID exits failed walk:\n"
        + "\n\n".join(failures[:10])
        + (f"\n... and {len(failures) - 10} more" if len(failures) > 10 else "")
    )


# ---------------------------------------------------------------------------
# 3.14 Walk complete route for every STAR entry
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("orig,dest", AIRPORT_PAIRS)
def test_walk_complete_route_all_star_entries(orig, dest):
    """Walk the complete route for every STAR entry point."""
    star_entries = _get_star_entries(dest)
    if not star_entries:
        pytest.fail(f"{orig}->{dest}: no STAR entries — navdata or algorithm bug")

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
        if response.status_code != 200:
            continue

        data = response.json()
        if data.get("route") == "No result.":
            continue

        errors = _walk_and_verify_route(data, orig, dest)
        if errors:
            failures.append(f"STAR={star}:\n" + "\n".join(errors))

    assert not failures, (
        f"{orig}->{dest}: {len(failures)}/{total} STAR entries failed walk:\n"
        + "\n\n".join(failures[:10])
        + (f"\n... and {len(failures) - 10} more" if len(failures) > 10 else "")
    )


# ---------------------------------------------------------------------------
# 3.15 Boundary node correctness — sidRouteNodeName / starRouteNodeName
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("orig,dest", AIRPORT_PAIRS)
def test_route_boundary_nodes_are_semantically_correct(orig, dest):
    """sidRouteNodeName and starRouteNodeName must be boundary nodes that
    actually belong to the reported procedure and sit at the SID/airway
    and airway/STAR boundaries.

    This catches bugs like the ZBAA→ZGGG STAR switch issue where
    starRouteNodeName pointed to a node from the wrong procedure
    (ENVIP3's FI21 instead of IKAVO3's IKAVO), causing old STAR
    waypoints to persist on the frontend map.
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
    if data.get("route") == "No result.":
        pytest.fail(f"{orig}→{dest}: no route found — navdata or algorithm bug")

    nodes = [n["name"] for n in data.get("nodes", [])]
    route_segments = data.get("routeSegments", [])

    # --- SID boundary ---
    sid_route_node = data.get("sidRouteNodeName")
    sid_key = data.get("sidNodeName")
    if sid_route_node and sid_key:
        # 1. Must be in the actual route nodes
        assert sid_route_node in nodes, (
            f"{orig}→{dest} SID: sidRouteNodeName={sid_route_node!r} "
            f"not found in route nodes: {nodes}"
        )

        # 2. Must be in the reported procedure's points or transitions
        sid_procs = data.get("SID", {})
        assert sid_key in sid_procs, (
            f"{orig}→{dest} SID: sidNodeName={sid_key!r} not in SID procedures"
        )
        found_in_proc = False
        for proc in sid_procs[sid_key]:
            proc_node_names = [p[0] for p in proc[2]]
            trans_node_names = []
            for _, tpts in proc[3]:
                trans_node_names.extend([p[0] for p in tpts])
            if sid_route_node in proc_node_names or sid_route_node in trans_node_names:
                found_in_proc = True
                break
        assert found_in_proc, (
            f"{orig}→{dest} SID: sidRouteNodeName={sid_route_node!r} "
            f"not found in any variant of procedure {sid_key!r}. "
            f"This means the boundary node does not belong to the reported procedure."
        )

        # 3. Must be the last (or only) point of the reported procedure or
        # one of its transitions.  When _fill_procedure_gaps extends the
        # route through a transition, the boundary node becomes the
        # transition's exit point (network side) rather than the main
        # procedure's last point.
        sid_seg_nodes = _extract_airway_nodes(route_segments, "SID")
        proc_last_points = set()
        for proc in sid_procs[sid_key]:
            pts = [p[0] for p in proc[2]]
            if pts:
                proc_last_points.add(pts[-1])
            for t_name, t_pts in proc[3]:
                if t_pts:
                    proc_last_points.add(t_pts[-1][0])
        if proc_last_points:
            assert sid_route_node in proc_last_points, (
                f"{orig}→{dest} SID: sidRouteNodeName={sid_route_node!r} "
                f"is not the last point of any variant of procedure {sid_key!r}. "
                f"Procedure last points: {sorted(proc_last_points)}. "
                f"SID segment: {sid_seg_nodes}"
            )

    # --- STAR boundary ---
    star_route_node = data.get("starRouteNodeName")
    star_key = data.get("starNodeName")
    if star_route_node and star_key:
        # 1. Must be in the actual route nodes
        assert star_route_node in nodes, (
            f"{orig}→{dest} STAR: starRouteNodeName={star_route_node!r} "
            f"not found in route nodes: {nodes}"
        )

        # 2. Must be in the reported procedure's points or transitions.
        # This catches the ZBAA→ZGGG bug where starRouteNodeName was FI21
        # (from ENVIP3) but the route actually used IKAVO3.
        star_procs = data.get("STAR", {})
        assert star_key in star_procs, (
            f"{orig}→{dest} STAR: starNodeName={star_key!r} not in STAR procedures"
        )
        found_in_proc = False
        for proc in star_procs[star_key]:
            proc_node_names = [p[0] for p in proc[2]]
            trans_node_names = []
            for _, tpts in proc[3]:
                trans_node_names.extend([p[0] for p in tpts])
            if star_route_node in proc_node_names or star_route_node in trans_node_names:
                found_in_proc = True
                break
        assert found_in_proc, (
            f"{orig}→{dest} STAR: starRouteNodeName={star_route_node!r} "
            f"not found in any variant of procedure {star_key!r}. "
            f"This means the boundary node does not belong to the reported procedure."
        )

        # 3. Must appear in the STAR segment of routeSegments.
        # It need not be the first node: the segment may start with a
        # bridge/transition node (e.g. PGS) that is not part of the
        # procedure itself (e.g. BOGET2 starts at BUGGA).
        star_seg_nodes = _extract_airway_nodes(route_segments, "STAR")
        if star_seg_nodes:
            assert star_route_node in star_seg_nodes, (
                f"{orig}→{dest} STAR: starRouteNodeName={star_route_node!r} "
                f"not found in STAR segment {star_seg_nodes}."
            )


# ---------------------------------------------------------------------------
# 3.16 Transition continuity — STAR transition points must not be skipped
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("orig,dest", AIRPORT_PAIRS)
def test_star_transition_points_are_not_skipped_by_airway(orig, dest):
    """When A* enters a STAR via a transition, the route must contain every
    transition point.  If A* takes an airway shortcut (e.g. EHF → LHS
    instead of EHF → LOPES → PAIDD → JEFFY → LHS), the skipped
    transition points cause the frontend star-line to fork from the route
    line at the transition start, producing the visual 'three edges' bug.
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
    if response.status_code != 200:
        return
    data = response.json()
    if data.get("route") == "No result.":
        return

    active_trans = data.get("activeSTARTransition")
    star_key = data.get("starNodeName")
    if not active_trans or not star_key:
        return

    nodes = [n["name"] for n in data.get("nodes", [])]
    star_procs = data.get("STAR", {})

    failures = []
    for proc in star_procs.get(star_key, []):
        for t_name, t_pts in proc[3]:
            if t_name != active_trans:
                continue
            trans_names = [p[0] for p in t_pts]
            if not trans_names:
                continue

            # Skip runway transitions (final approach paths).  A* may take a
            # direct airway/bridge to the runway, skipping intermediate final
            # approach fixes; this is normal routing behaviour.
            if t_name.startswith("RW"):
                continue

            # The transition start must be present in the route; if it is not,
            # A* entered via a different point and this transition is irrelevant.
            start_name = trans_names[0]
            if start_name not in nodes:
                continue

            # Every transition point must appear in the route.  Missing points
            # mean A* bypassed them via an airway shortcut.
            missing = [n for n in trans_names if n not in nodes]
            if missing:
                failures.append(
                    f"{orig}→{dest} STAR={star_key} transition={active_trans}: "
                    f"skipped transition points {missing}"
                )

    assert not failures, "\n".join(failures)


# ---------------------------------------------------------------------------
# 3.17 Standard route assertions — must produce known-correct routes
# ---------------------------------------------------------------------------

def test_standard_route_rjbb_rjtt():
    """RJBB→RJTT must produce the standard route via SHTLE transition.

    Standard answer: RJBB SID SHTLE Y71 XAC STAR RJTT
    """
    response = client.post(
        "/api/route",
        json={
            "orig": "RJBB",
            "dest": "RJTT",
            "validCode": "",
            "validToken": "",
            "sidExit": "",
            "starEntry": "",
            "cycle": "2604",
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["route"] != "No result.", "RJBB→RJTT: no route found"

    route = data["route"]
    expected = "RJBB SID SHTLE Y71 XAC STAR RJTT"
    assert route == expected, (
        f"RJBB→RJTT route mismatch.\n"
        f"Expected: {expected}\n"
        f"Got:      {route}"
    )
    assert data.get("activeSIDTransition") == "SHTLE", (
        f"RJBB→RJTT active SID transition must be SHTLE, got: {data.get('activeSIDTransition')}"
    )


def test_standard_route_klax_kjfk():
    """KLAX→KJFK must produce a valid route via BEALE/WLKES transitions.

    The exact airway labels between JHW and WLKES may vary due to
    tie-breaking among physically identical segments (J106/J70/Q476
    share the same JHW→HOXIE→DMACK→STENT→MAGIO path).  We verify
    the critical structure: BEALE SID exit, J146→GIJ→J554→JHW
    airway core, and WLKES STAR entry.
    """
    response = client.post(
        "/api/route",
        json={
            "orig": "KLAX",
            "dest": "KJFK",
            "validCode": "",
            "validToken": "",
            "sidExit": "",
            "starEntry": "",
            "cycle": "2604",
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["route"] != "No result.", "KLAX→KJFK: no route found"

    route = data["route"]
    parts = route.split()

    # Core structural checks
    assert parts[0] == "KLAX", f"KLAX→KJFK must start with KLAX, got: {parts[0]}"
    assert parts[1] == "SID", f"KLAX→KJFK missing SID label, got: {parts[1]}"
    assert "BEALE" in parts, f"KLAX→KJFK missing BEALE SID exit, route: {route}"
    assert "J146" in parts, f"KLAX→KJFK missing J146 airway, route: {route}"
    assert "GIJ" in parts, f"KLAX→KJFK missing GIJ waypoint, route: {route}"
    assert "J554" in parts, f"KLAX→KJFK missing J554 airway, route: {route}"
    assert "JHW" in parts, f"KLAX→KJFK missing JHW waypoint, route: {route}"
    assert "WLKES" in parts, f"KLAX→KJFK missing WLKES STAR entry, route: {route}"
    assert "STAR" in parts, f"KLAX→KJFK missing STAR label, route: {route}"
    assert parts[-1] == "KJFK", f"KLAX→KJFK must end with KJFK, got: {parts[-1]}"

    # Transition checks
    assert data.get("activeSIDTransition") == "BEALE", (
        f"KLAX→KJFK active SID transition must be BEALE, got: {data.get('activeSIDTransition')}"
    )
    assert data.get("activeSTARTransition") == "WLKES", (
        f"KLAX→KJFK active STAR transition must be WLKES, got: {data.get('activeSTARTransition')}"
    )


# ---------------------------------------------------------------------------
# 3.18 Standard routes from rfinder — must match known optimal answers
# ---------------------------------------------------------------------------

# Helpers for distance parsing
def _parse_distance_nm(dist_str: str) -> float:
    """Extract nautical-mile value from 'xxx.xx nm / yyy.yy km' string."""
    if not dist_str:
        return 0.0
    parts = dist_str.split()
    if parts and parts[0].replace(".", "", 1).replace("-", "", 1).isdigit():
        return float(parts[0])
    return 0.0


STANDARD_ROUTES = [
    # (orig, dest, expected_route, expected_dist_nm)
    ("ZBAA", "ZGGG", "ZBAA SID OMDEK W37 VIKEB V66 VESUX W45 IKAVO STAR ZGGG", 1031.5),
    ("ZBAA", "ZGHA", "ZBAA SID OMDEK W37 GUSIV STAR ZGHA", 742.9),
    ("ZGHA", "ZJSY", "ZGHA SID OLTUS R343 ENKUS W120 IVPUB W159 BHY W70 NYB G221 UPRIS STAR ZJSY", 702.3),
    ("ZBAA", "ZSPD", "ZBAA SID ELKUR W40 YQG W142 DALIM A593 VMB W161 SASAN STAR ZSPD", 637.6),
    ("RJTT", "RJBB", "RJTT SID LAXAS Y56 TOHME Y54 KOHWA Y544 DUBKA STAR RJBB", 254.4),
    ("KLAX", "KSEA", "KLAX SID EHF J5 LKV STAR KSEA", 832.3),
    ("RKPC", "ZBAD", "RKPC SID LIMDI Y677 TOLIS Y655 NONOS Z55 AGAVO A591 IKEKA W4 HCH W200 DOVIV W55 DUMAP STAR ZBAD", 718.5),
    ("ZBAA", "RKSI", "ZBAA SID MUGLO W34 ANRAT A326 DONVO G597 AGAVO Y644 GONAV STAR RKSI", 520.8),
    ("KLAX", "KJFK", "KLAX SID BEALE J146 GIJ J554 JHW J70 HOXIE Q476 WLKES STAR KJFK", 2172.1),
]


@pytest.mark.parametrize("orig,dest,expected_route,expected_dist_nm", STANDARD_ROUTES)
def test_standard_route_from_rfinder(orig, dest, expected_route, expected_dist_nm):
    """Route must exactly match the known optimal answer from rfinder.

    Per CLAUDE.md: test failure means our bug — never skip.
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
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["route"] != "No result.", f"{orig}→{dest}: no route found"

    route = data["route"]
    dist_str = data.get("distance", "")
    actual_dist_nm = _parse_distance_nm(dist_str)

    assert route == expected_route, (
        f"{orig}→{dest} route mismatch.\n"
        f"Expected: {expected_route}\n"
        f"Got:      {route}\n"
        f"Distance: {dist_str} (optimal: {expected_dist_nm} nm)"
    )
    # Allow 1 % tolerance for distance calculation differences
    assert actual_dist_nm <= expected_dist_nm * 1.01, (
        f"{orig}→{dest} distance too long.\n"
        f"Expected <= {expected_dist_nm * 1.01:.1f} nm, got {actual_dist_nm:.1f} nm"
    )


# ---------------------------------------------------------------------------
# 3.19 SID transition continuity — points must not be skipped
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("orig,dest", AIRPORT_PAIRS)
def test_sid_transition_points_are_not_skipped_by_airway(orig, dest):
    """When A* exits a SID via a transition, the route must contain every
    transition point.  If A* takes an airway shortcut, the skipped
    transition points cause the frontend sid-line to fork from the route.
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
    if response.status_code != 200:
        return
    data = response.json()
    if data.get("route") == "No result.":
        return

    active_trans = data.get("activeSIDTransition")
    sid_key = data.get("sidNodeName")
    if not active_trans or not sid_key:
        return

    nodes = [n["name"] for n in data.get("nodes", [])]
    sid_procs = data.get("SID", {})

    failures = []
    for proc in sid_procs.get(sid_key, []):
        for t_name, t_pts in proc[3]:
            if t_name != active_trans:
                continue
            trans_names = [p[0] for p in t_pts]
            if not trans_names:
                continue

            # Skip runway transitions
            if t_name.startswith("RW"):
                continue

            # The transition start must be present in the route
            start_name = trans_names[0]
            if start_name not in nodes:
                continue

            # Every transition point must appear in the route
            missing = [n for n in trans_names if n not in nodes]
            if missing:
                failures.append(
                    f"{orig}→{dest} SID={sid_key} transition={active_trans}: "
                    f"skipped transition points {missing}"
                )

    assert not failures, "\n".join(failures)
