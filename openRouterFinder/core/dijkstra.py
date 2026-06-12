"""A* route finding engine with isolated per-request state."""

import heapq
import math
import time

import orjson

from openRouterFinder.core.airport import AirportConnection, Procedure
from openRouterFinder.core.graph import (
    Node,
    great_circle_distance_km,
)


def _procs_to_dict(procs: dict) -> dict:
    """Convert Procedure objects to JSON-serializable tuples [name, runway, points, transitions]."""
    result = {}
    for key, proc_list in procs.items():
        result[key] = [
            [p.name, p.runway, p.points, [[t[0], t[1]] for t in p.transitions]] for p in proc_list
        ]
    return result


def build_route_info(
    data_version: str,
    total_time: str,
    route: str,
    dist: str,
    node_info: list,
    sid: dict,
    star: dict,
    airport_name: list,
    active_sid_transition: str | None = None,
    active_star_transition: str | None = None,
    route_segments: list | None = None,
    sid_node_name: str | None = None,
    star_node_name: str | None = None,
    sid_route_node_name: str | None = None,
    star_route_node_name: str | None = None,
) -> str:
    result = {
        "data_version": data_version,
        "total_time": total_time,
        "route": route,
        "distance": dist,
        "nodeinformation": node_info,
        "SID": _procs_to_dict(sid),
        "STAR": _procs_to_dict(star),
        "airportName": airport_name,
        "activeSIDTransition": active_sid_transition,
        "activeSTARTransition": active_star_transition,
        "sidNodeName": sid_node_name,
        "starNodeName": star_node_name,
        "sidRouteNodeName": sid_route_node_name,
        "starRouteNodeName": star_route_node_name,
    }
    if route_segments is not None:
        result["routeSegments"] = route_segments
    return orjson.dumps(result).decode()


class RouteEngine:
    """Per-request route calculator. Thread-safe: no shared mutable state."""

    def __init__(
        self,
        node_list: tuple[Node | None, ...],
        data_version: str,
        node_index: dict[tuple[str, float, float], Node] | None = None,
    ):
        self.node_list = node_list
        self.data_version = data_version
        self.num_nodes = len(node_list)

        # O(1) node lookup by (name, lat, lon) for procedure assembly
        if node_index is not None:
            self._node_index = node_index
        else:
            self._node_index: dict[tuple[str, float, float], Node] = {}
            for node in node_list:
                if node is not None:
                    self._node_index[node.node_key()] = node

        # Precompute edge distances once (edges are shared, so this only
        # needs to run on the first RouteEngine instantiation).
        for node in node_list:
            if node is not None:
                for edge in node.next_list:
                    if edge.dist == 0.0 and edge.nend < self.num_nodes:
                        next_node = node_list[edge.nend]
                        if next_node is not None:
                            edge.dist = great_circle_distance_km(
                                node.px,
                                node.py,
                                next_node.px,
                                next_node.py,
                            )

        # Precompute T-route skip cache per node for fast _should_skip_edge.
        self._node_has_non_t: list[bool] = [False] * self.num_nodes
        for node in node_list:
            if node is not None:
                self._node_has_non_t[node.iid] = any(
                    not (
                        e.name
                        and e.name[0] == "T"
                        and len(e.name) > 1
                        and e.name[1:].isdigit()
                    )
                    for e in node.next_list
                )

    def search(
        self,
        orig: str,
        dest: str,
        sid_conn: AirportConnection,
        star_conn: AirportConnection,
        airport_names: list[str],
        sid_exit: str | None = None,
        star_entry: str | None = None,
    ) -> str | None:
        """Run mixed-graph A* search. Returns JSON string or None."""
        timestart = time.time()

        # Fast path: mixed-graph A* (single search)
        mixed_result = self._mixed_graph_astar(
            orig, dest, sid_conn, star_conn, airport_names, sid_exit, star_entry
        )
        if mixed_result is not None:
            return mixed_result

        # Fallback: phase-separated search
        # Phase 1: Bearing-based SID selection (fast reference)
        sid_proc, sid_boundary = self._select_procedure(
            sid_conn, star_conn.airport_node, is_sid=True, filter_name=sid_exit
        )

        if sid_proc is None or sid_boundary is None:
            return build_route_info(
                self.data_version,
                "0.00",
                "No result.",
                "0.00 nm / 0.00 km",
                None,
                {},
                {},
                [],
            )

        # Phase 2: SID transition selection
        sid_transition_result = self._select_sid_transition(
            sid_proc, sid_conn, star_conn, star_conn.airport_node
        )
        sid_transition_pts = None
        if sid_transition_result is not None:
            _, sid_transition_pts, sid_boundary = sid_transition_result

        # Phase 3+4: Alternating optimization of STAR and SID.
        # A single pass (select STAR then re-select SID) is greedy and can
        # lock into a local optimum.  Iterating until convergence finds the
        # true best (SID, STAR) pair.
        sid_candidates = self._collect_procedure_candidates(
            sid_conn, is_sid=True, filter_name=sid_exit
        )
        star_candidates = self._collect_procedure_candidates(
            star_conn, is_sid=False, filter_name=star_entry, sid_conn=sid_conn, star_conn=star_conn
        )
        if not star_candidates:
            return build_route_info(
                self.data_version,
                "0.00",
                "No result.",
                "0.00 nm / 0.00 km",
                None,
                {},
                {},
                [],
            )

        # Initial STAR selection before entering the alternating loop.
        star_proc, star_boundary, star_t_name = self._select_procedure_astar(
            star_candidates, sid_boundary.iid, is_sid=False, conn=star_conn
        )
        if star_proc is None or star_boundary is None:
            return build_route_info(
                self.data_version,
                "0.00",
                "No result.",
                "0.00 nm / 0.00 km",
                None,
                {},
                {},
                [],
            )

        for _ in range(5):
            prev_sid_name = sid_proc.name
            prev_sid_t = sid_transition_result[0] if sid_transition_result else None
            prev_star_name = star_proc.name if star_proc else None
            prev_star_t = star_t_name

            # Select best STAR for current SID boundary
            star_proc, star_boundary, star_t_name = self._select_procedure_astar(
                star_candidates, sid_boundary.iid, is_sid=False, conn=star_conn
            )
            if star_proc is None or star_boundary is None:
                return build_route_info(
                    self.data_version,
                    "0.00",
                    "No result.",
                    "0.00 nm / 0.00 km",
                    None,
                    {},
                    {},
                    [],
                )
            prev_star_t = star_t_name

            # Select best SID for current STAR boundary
            if sid_candidates:
                astar_sid, astar_sid_boundary, astar_sid_t_name = self._select_procedure_astar(
                    sid_candidates, star_boundary.iid, is_sid=True, conn=sid_conn
                )
                if astar_sid is not None and astar_sid_boundary is not None:
                    sid_proc = astar_sid
                    sid_boundary = astar_sid_boundary
                    if astar_sid_t_name is not None:
                        sid_transition_result = (astar_sid_t_name, None, sid_boundary)
                        for t_name, t_pts in sid_proc.transitions:
                            if t_name == astar_sid_t_name:
                                sid_transition_pts = list(t_pts)
                                break
                        else:
                            sid_transition_pts = None
                    else:
                        sid_transition_result = self._select_sid_transition(
                            sid_proc, sid_conn, star_conn, star_conn.airport_node
                        )
                        if sid_transition_result is not None:
                            _, sid_transition_pts, sid_boundary = sid_transition_result
                        else:
                            sid_transition_pts = None

            # Check convergence
            curr_sid_t = sid_transition_result[0] if sid_transition_result else None
            if (
                sid_proc.name == prev_sid_name
                and curr_sid_t == prev_sid_t
                and star_proc.name == prev_star_name
                and star_t_name == prev_star_t
            ):
                break

        if star_proc is None or star_boundary is None or sid_boundary is None:
            return build_route_info(
                self.data_version,
                "0.00",
                "No result.",
                "0.00 nm / 0.00 km",
                None,
                {},
                {},
                [],
            )

        # Phase 5: Airway A* (zero-copy, pure airway graph).
        # Forbid passing through SID/STAR procedure nodes to prevent cycles
        # where the airway revisits a procedure waypoint.
        def _build_forbidden(sid_p, star_p, sid_t_pts=None):
            forbidden = set()
            for pt in sid_p.points:
                node = self._find_node_for_point(pt, sid_conn, star_conn)
                if node is not None:
                    forbidden.add(node.iid)
            # Also forbid SID transition waypoints (except the boundary which
            # is the airway start) so the airway cannot backtrack through
            # transition nodes (e.g. LAXX1 OCN transition then airway V165
            # returning to DANAH).
            if sid_t_pts is not None:
                for pt in sid_t_pts:
                    node = self._find_node_for_point(pt, sid_conn, star_conn)
                    if node is not None and node.iid != sid_boundary.iid:
                        forbidden.add(node.iid)
            for pt in star_p.points:
                node = self._find_node_for_point(pt, sid_conn, star_conn)
                if node is not None:
                    forbidden.add(node.iid)
            forbidden.discard(sid_boundary.iid)
            return forbidden

        forbidden_iids = _build_forbidden(sid_proc, star_proc, sid_transition_pts)
        forbidden_iids.discard(star_boundary.iid)

        airway_route = self._astar_airway(sid_boundary.iid, star_boundary.iid, forbidden_iids)

        if airway_route is not None:
            airway_route = self._reassign_airways(airway_route, sid_boundary.iid)

        # Fallback: if no STAR filter was requested and the selected STAR is
        # unreachable via pure airway graph, try auto-selected STAR (matches old
        # mixed-graph behaviour where all procedures were implicitly available).
        if airway_route is None and not star_entry:
            fallback_candidates = self._collect_procedure_candidates(
                star_conn, is_sid=False, filter_name=None, sid_conn=sid_conn, star_conn=star_conn
            )
            fallback_proc, fallback_boundary, _ = self._select_procedure_astar(
                fallback_candidates, sid_boundary.iid, is_sid=False
            )
            if fallback_proc is not None and fallback_boundary is not None:
                forbidden_iids = _build_forbidden(sid_proc, fallback_proc, sid_transition_pts)
                forbidden_iids.discard(fallback_boundary.iid)
                airway_route = self._astar_airway(
                    sid_boundary.iid, fallback_boundary.iid, forbidden_iids
                )
                if airway_route is not None:
                    star_proc = fallback_proc
                    star_boundary = fallback_boundary

        if airway_route is None:
            return build_route_info(
                self.data_version,
                "0.00",
                "No result.",
                "0.00 nm / 0.00 km",
                None,
                {},
                {},
                [],
            )

        # Phase 6: Assemble full route
        route_list = self._assemble_route(
            sid_conn,
            sid_proc,
            airway_route,
            star_proc,
            star_conn,
            sid_boundary=sid_boundary,
            star_boundary=star_boundary,
            sid_transition_pts=sid_transition_pts,
        )

        # Recalculate distance
        dist_km = self._calc_route_distance(route_list, sid_conn, star_conn)
        dist_nm = dist_km / 1.852
        dist_str = f"{dist_nm:.2f} nm / {dist_km:.2f} km"

        route_total = self._sort_route(orig, route_list)
        node_info = self._build_node_info(sid_conn, star_conn, route_list)
        route_segments = self._build_route_segments(sid_conn, route_list)

        # SID/STAR node names (procedure keys)
        sid_node_name = sid_proc.points[-1][0] if sid_proc.points else None
        star_node_name = star_proc.points[0][0] if star_proc.points else None

        # Boundary nodes: the last route node belonging to the SID procedure
        # and the first route node belonging to the STAR procedure.
        # This correctly handles single-point procedures where the airway
        # ends at the procedure point (the point is skipped in the STAR loop
        # because it duplicates the last airway node).
        sid_route_node_name = None
        if sid_proc and sid_proc.points:
            sid_names = {p[0] for p in sid_proc.points}
            for _, node_name, _ in route_list:
                if node_name in sid_names:
                    sid_route_node_name = node_name

        star_route_node_name = None
        if star_proc and star_proc.points:
            star_names = {p[0] for p in star_proc.points}
            for t_name, t_pts in star_proc.transitions:
                star_names.update(p[0] for p in t_pts)
            for _, node_name, _ in route_list:
                if node_name in star_names:
                    star_route_node_name = node_name
                    break

        # Active transitions
        route_node_names = {node_name for _, node_name, _ in route_list}
        active_sid_transition = self._find_active_transition(
            sid_proc, route_node_names, is_sid=True
        )
        active_star_transition = self._find_active_transition(
            star_proc, route_node_names, is_sid=False
        )

        time_total = time.time() - timestart
        sttime = "%.2f" % (time_total * 1000)

        return build_route_info(
            self.data_version,
            sttime,
            route_total,
            dist_str,
            node_info,
            sid_conn.procedures,
            star_conn.procedures,
            airport_names,
            active_sid_transition,
            active_star_transition,
            route_segments,
            sid_node_name,
            star_node_name,
            sid_route_node_name,
            star_route_node_name,
        )

    def _select_procedure(
        self,
        conn: AirportConnection,
        other_airport_node: Node,
        is_sid: bool,
        filter_name: str | None = None,
    ) -> tuple[Procedure | None, Node | None]:
        """Deterministically select the best procedure and its airway boundary node.

        If filter_name is given, only consider procedures whose key matches.
        Otherwise pick the procedure whose exit/entry direction best aligns
        with the great-circle route to/from the other airport.
        """
        candidates: list[tuple[Procedure, Node, str]] = []

        effective_filter = filter_name if filter_name else None
        for key, proc_list in conn.procedures.items():
            if effective_filter is not None and key != effective_filter:
                continue
            for proc in proc_list:
                boundary = self._find_boundary_node(conn, proc, is_sid)
                if boundary is not None:
                    candidates.append((proc, boundary, key))

        if not candidates:
            return None, None

        if len(candidates) == 1:
            return candidates[0][0], candidates[0][1]

        ap_lat, ap_lon = conn.airport_node.px, conn.airport_node.py
        other_lat, other_lon = other_airport_node.px, other_airport_node.py

        if is_sid:
            # SID: prefer exit bearing closest to airport -> destination
            target_bearing = self._bearing(ap_lat, ap_lon, other_lat, other_lon)
            best_proc, best_boundary = None, None
            best_score = float("inf")
            for proc, boundary, _ in candidates:
                if proc.points:
                    exit_lat, exit_lon = proc.points[-1][1], proc.points[-1][2]
                    exit_bearing = self._bearing(ap_lat, ap_lon, exit_lat, exit_lon)
                    score = abs(self._angle_diff(target_bearing, exit_bearing))
                    if score < best_score:
                        best_score = score
                        best_proc, best_boundary = proc, boundary
            return best_proc, best_boundary
        # STAR: prefer entry bearing closest to source -> airport
        # (i.e. bearing from entry point toward airport)
        target_bearing = self._bearing(other_lat, other_lon, ap_lat, ap_lon)
        best_proc, best_boundary = None, None
        best_score = float("inf")
        for proc, boundary, _ in candidates:
            if proc.points:
                entry_lat, entry_lon = proc.points[0][1], proc.points[0][2]
                entry_bearing = self._bearing(entry_lat, entry_lon, ap_lat, ap_lon)
                score = abs(self._angle_diff(target_bearing, entry_bearing))
                if score < best_score:
                    best_score = score
                    best_proc, best_boundary = proc, boundary
        return best_proc, best_boundary

    def _find_boundary_node(
        self,
        conn: AirportConnection,
        proc: Procedure,
        is_sid: bool,
    ) -> Node | None:
        """Find the airway node that serves as the boundary between procedure and airway.

        For SID: the exit point (last point). If it is a temp node, follow
        bridge_edges to the connected airway node.
        For STAR: the entry point (first point). If it is a temp node, follow
        bridge_edges backward to the connected airway node.
        """
        if not proc.points:
            return None

        pt = proc.points[-1] if is_sid else proc.points[0]

        name, lat, lon = pt
        key = (name, round(lat, 6), round(lon, 6))
        node = self._node_index.get(key)

        if node is None:
            # Search temp nodes
            for temp in conn.temp_nodes:
                if temp.name == name and abs(temp.px - lat) < 1e-6 and abs(temp.py - lon) < 1e-6:
                    node = temp
                    break

        if node is None:
            return None

        # Node has outgoing airway edges — it's already a valid boundary.
        if node.next_list:
            return node

        # Node has no outgoing edges.  Try bridge_edges to find the
        # connected airway node.  SID and STAR use opposite directions.
        for edge in conn.bridge_edges:
            if is_sid:
                # SID bridge: temp -> airway (nfrom = node, nend = airway)
                if edge.nfrom == node.iid and 0 <= edge.nend < self.num_nodes:
                    airway_node = self.node_list[edge.nend]
                    if airway_node is not None:
                        return airway_node
            else:
                # STAR bridge: airway -> temp (nfrom = airway, nend = node)
                if edge.nend == node.iid and 0 <= edge.nfrom < self.num_nodes:
                    airway_node = self.node_list[edge.nfrom]
                    if airway_node is not None:
                        return airway_node

        # No outgoing edges and no bridge edge.
        # SID: exit point is a dead-end — A* cannot continue on airway.
        # STAR: entry point is an airway terminus — A* only needs to reach it.
        return None if is_sid else node

    def _select_sid_transition(
        self,
        sid_proc: Procedure,
        sid_conn: AirportConnection,
        star_conn: AirportConnection,
        dest_node: Node,
    ) -> tuple[str, list[tuple[str, float, float]], Node] | None:
        """Select the best SID transition and return (name, points, boundary_node).

        The boundary_node is the airway node connected to the transition end.
        If no transition is suitable, returns None.

        Scoring uses the main procedure's last point as the reference, because
        transitions branch from the common endpoint.  This avoids picking a
        transition that is geographically close to the airport but points in
        the wrong direction from the procedure exit (e.g. GARDY4 MISEN).
        """
        if not sid_proc.transitions:
            return None

        # Reference point: main procedure's last point (the common endpoint)
        if sid_proc.points:
            ref_pt = sid_proc.points[-1]
            ref_lat, ref_lon = ref_pt[1], ref_pt[2]
        else:
            ref_lat, ref_lon = sid_conn.airport_node.px, sid_conn.airport_node.py

        dest_lat, dest_lon = dest_node.px, dest_node.py
        target_bearing = self._bearing(ref_lat, ref_lon, dest_lat, dest_lon)

        best = None
        best_score = float("inf")

        for t_name, t_pts in sid_proc.transitions:
            if t_name.startswith("RW"):
                continue
            if len(t_pts) < 2:
                continue

            end_pt = t_pts[-1]
            end_node = self._find_node_for_point(end_pt, sid_conn, star_conn)
            if end_node is None:
                continue

            # Follow bridge_edges to find the connected airway node
            boundary = end_node
            if not boundary.next_list:
                for edge in sid_conn.bridge_edges:
                    if edge.nfrom == boundary.iid and 0 <= edge.nend < self.num_nodes:
                        airway_node = self.node_list[edge.nend]
                        if airway_node is not None:
                            boundary = airway_node
                            break

            if not boundary.next_list:
                continue

            end_lat, end_lon = end_pt[1], end_pt[2]
            end_bearing = self._bearing(ref_lat, ref_lon, end_lat, end_lon)
            score = abs(self._angle_diff(target_bearing, end_bearing))

            if score < best_score:
                best_score = score
                best = (t_name, t_pts, boundary)

        return best

    @staticmethod
    def _is_excluded_airway(name: str) -> bool:
        """Check if an airway is a T-route (terminal route).

        T-routes should be excluded from enroute A*.

        T-routes are low-altitude terminal routes that provide shortcuts in
        terminal areas but fragment the enroute airway graph, causing A* to
        deviate from standard high-altitude routes.
        """
        if not name:
            return False
        return name[0] == "T" and len(name) > 1 and name[1:].isdigit()

    def _should_skip_edge(self, curr_node, edge_name: str) -> bool:
        """Determine whether to skip an edge during A* traversal.

        T-routes are excluded only when the current node has non-T
        alternatives. This allows departure from terminal-only nodes
        (e.g. WUMOX) while preventing T-route shortcuts in the enroute
        core where J/V/Q airways are available.
        """
        if not edge_name or edge_name[0] != "T" or not edge_name[1:].isdigit():
            return False
        return self._node_has_non_t[curr_node.iid]

    @staticmethod
    def _edge_sort_key(name: str) -> tuple:
        """Sort key for airway names to ensure deterministic tie-breaking.

        Extracts alphabetic prefix and numeric suffix so that J70 sorts
        before J106 (70 < 106).
        """
        prefix = ""
        num_str = ""
        for c in name:
            if c.isalpha() and not num_str:
                prefix += c
            elif c.isdigit():
                num_str += c
            else:
                break
        return (prefix, int(num_str) if num_str else 999999, name)

    def _astar_airway(
        self,
        start_iid: int,
        end_iid: int,
        forbidden_iids: set | None = None,
    ) -> list[tuple[str, str, int]] | None:
        """Zero-copy Dijkstra on the pure airway graph (node.next_list only).

        Returns route_list of (edge_name, node_name, node_iid) or None.
        """
        INF = float("inf")
        dists = [INF] * self.num_nodes
        prev_edge: list[tuple[int, str] | None] = [None] * self.num_nodes

        start_node = self.node_list[start_iid]
        end_node = self.node_list[end_iid]
        if start_node is None or end_node is None:
            return None

        dists[start_iid] = 0.0

        queue = []
        # Use (dist, dist, node_iid) for deterministic tie-breaking
        heapq.heappush(queue, (0.0, 0.0, start_iid))

        while queue:
            _dist, _g_score, curr = heapq.heappop(queue)

            if curr == end_iid:
                break

            if dists[curr] == INF:
                continue

            curr_node = self.node_list[curr]
            if curr_node is None:
                continue

            for edge in curr_node.next_list:
                next_node = self.node_list[edge.nend]
                if next_node is None:
                    continue
                if forbidden_iids and edge.nend in forbidden_iids:
                    continue
                if self._should_skip_edge(curr_node, edge.name):
                    continue

                nd = dists[curr] + edge.dist
                if nd < dists[edge.nend]:
                    dists[edge.nend] = nd
                    prev_edge[edge.nend] = (curr, edge.name)
                    heapq.heappush(queue, (nd, nd, edge.nend))

        if dists[end_iid] == INF:
            return None

        # Backtrack
        route = []
        curr = end_iid
        while curr != start_iid and prev_edge[curr] is not None:
            prev_iid, edge_name = prev_edge[curr]
            route.append((edge_name, self.node_list[curr].name, curr))
            curr = prev_iid
        route.reverse()
        return route

    def _astar_airway_distance(
        self,
        start_iid: int,
        end_iid: int,
        forbidden_iids: set | None = None,
    ) -> float | None:
        """Run Dijkstra and return only the total distance (no path reconstruction)."""
        INF = float("inf")
        dists = [INF] * self.num_nodes
        prev_edge: list[tuple[int, str] | None] = [None] * self.num_nodes

        start_node = self.node_list[start_iid]
        end_node = self.node_list[end_iid]
        if start_node is None or end_node is None:
            return None

        _end_lat, _end_lon = end_node.px, end_node.py
        dists[start_iid] = 0.0

        queue = []
        heapq.heappush(queue, (0.0, 0.0, start_iid))

        while queue:
            _f_score, _g_score, curr = heapq.heappop(queue)

            if curr == end_iid:
                break

            if dists[curr] == INF:
                continue

            curr_node = self.node_list[curr]
            if curr_node is None:
                continue

            for edge in curr_node.next_list:
                next_node = self.node_list[edge.nend]
                if next_node is None:
                    continue
                if forbidden_iids and edge.nend in forbidden_iids:
                    continue
                if self._should_skip_edge(curr_node, edge.name):
                    continue

                nd = dists[curr] + edge.dist
                if nd < dists[edge.nend]:
                    dists[edge.nend] = nd
                    prev_edge[edge.nend] = (curr, edge.name)
                    heapq.heappush(queue, (nd, nd, edge.nend))

        if dists[end_iid] == INF:
            return None
        return dists[end_iid]

    def _collect_procedure_candidates(
        self,
        conn: AirportConnection,
        is_sid: bool,
        filter_name: str | None = None,
        sid_conn: AirportConnection | None = None,
        star_conn: AirportConnection | None = None,
    ) -> list[tuple[Procedure, Node, str, str | None]]:
        """Collect all procedure candidates with their boundary nodes.

        For STAR, also includes transition boundaries. Transition candidates
        are identified by their start point on the airway graph.

        Returns list of (procedure, boundary_node, key, transition_name).
        transition_name is None for main procedure boundary.
        """
        candidates: list[tuple[Procedure, Node, str, str | None]] = []
        effective_filter = filter_name if filter_name else None

        for key, proc_list in conn.procedures.items():
            if effective_filter is not None and key != effective_filter:
                continue
            for proc in proc_list:
                # Main procedure boundary
                boundary = self._find_boundary_node(conn, proc, is_sid)
                if boundary is not None:
                    # For SID, skip main-procedure candidates whose boundary is
                    # reached via a bridge edge.  Transition candidates are kept
                    # because their boundary is the transition's network-side exit
                    # point, which may have a direct airway connection.
                    keep_main = True
                    if is_sid and proc.points:
                        last_pt = proc.points[-1]
                        last_node = self._find_node_for_point(last_pt, conn, None)
                        if last_node is not None and last_node.iid != boundary.iid:
                            keep_main = False
                    if keep_main:
                        candidates.append((proc, boundary, key, None))

                # For SID, also collect transition boundaries.
                # SID transitions are reversed (runway->network); the airway
                # boundary is the LAST point (network-side exit).
                if is_sid:
                    for t_name, t_pts in proc.transitions:
                        if t_name.startswith("RW"):
                            continue
                        if len(t_pts) < 2:
                            continue

                        end_pt = t_pts[-1]
                        end_node = self._find_node_for_point(end_pt, conn, None)
                        if end_node is None:
                            continue

                        boundary = end_node
                        if not boundary.next_list:
                            for edge in conn.bridge_edges:
                                if edge.nfrom == boundary.iid and 0 <= edge.nend < self.num_nodes:
                                    airway_node = self.node_list[edge.nend]
                                    if airway_node is not None:
                                        boundary = airway_node
                                        break

                        if boundary is not None and boundary.next_list:
                            candidates.append((proc, boundary, key, t_name))

                # For STAR, also collect transition boundaries
                if not is_sid:
                    for t_name, t_pts in proc.transitions:
                        if t_name.startswith("RW"):
                            continue
                        if len(t_pts) < 2:
                            continue

                        # Find the airway node for transition start
                        start_pt = t_pts[0]
                        start_node = self._find_node_for_point(start_pt, sid_conn, star_conn)
                        if start_node is None:
                            continue

                        # Ensure it's an airway node (has outgoing edges or via bridge)
                        boundary = start_node
                        if not boundary.next_list:
                            # STAR bridge: airway -> temp
                            for edge in conn.bridge_edges:
                                if edge.nend == boundary.iid and 0 <= edge.nfrom < self.num_nodes:
                                    airway_node = self.node_list[edge.nfrom]
                                    if airway_node is not None:
                                        boundary = airway_node
                                        break

                        if boundary is not None and boundary.next_list:
                            candidates.append((proc, boundary, key, t_name))

        # For SID, filter out candidates whose boundary is an airway start
        # that immediately leads to another candidate boundary.  This prevents
        # selecting a SID that drops onto an airway at an intermediate point
        # when a more standard entry (the next airway point that is also a
        # SID anchor) exists.
        if is_sid:
            boundary_iids = {b.iid for _, b, _, _ in candidates}
            filtered = []
            for proc, boundary, key, t_name in candidates:
                # Transition candidates are always valid airway entry points
                # (the transition's network-side exit).  Skipping them here
                # caused GARDY4(BEALE) to be discarded because BEALE->LAS
                # is a normal J146 leg and LAS is another candidate.
                if t_name is not None:
                    filtered.append((proc, boundary, key, t_name))
                    continue

                skip = False
                for edge in boundary.next_list:
                    if edge.nend in boundary_iids and edge.nend != boundary.iid:
                        skip = True
                        break
                if not skip:
                    filtered.append((proc, boundary, key, t_name))
            candidates = filtered

        return candidates

    def _calc_procedure_distance(
        self,
        proc: Procedure,
        conn: AirportConnection,
        transition_name: str | None = None,
    ) -> float:
        """Calculate total distance of a procedure and optional transition in km."""
        points: list[tuple[str, float, float]] = []

        if transition_name is not None:
            for t_name, t_pts in proc.transitions:
                if t_name == transition_name:
                    points = list(t_pts)
                    break

        proc_points = list(proc.points)

        # Merge transition and main procedure points correctly.
        # SID: transition starts where main procedure ends
        #      (transition[0] == proc_points[-1]).
        # STAR: transition ends where main procedure starts
        #       (transition[-1] == proc_points[0]).
        if points and proc_points:
            if points[0][0] == proc_points[-1][0]:
                points = list(proc_points) + points[1:]
            elif points[-1][0] == proc_points[0][0]:
                points = list(points) + proc_points[1:]
            else:
                points = list(points) + list(proc_points)
        elif proc_points:
            points = list(proc_points)

        if len(points) < 2:
            return 0.0

        dist_km = 0.0
        for i in range(len(points) - 1):
            _, lat1, lon1 = points[i]
            _, lat2, lon2 = points[i + 1]
            dist_km += great_circle_distance_km(lat1, lon1, lat2, lon2)

        return dist_km

    def _select_procedure_astar(
        self,
        candidates: list[tuple[Procedure, Node, str, str | None]],
        other_boundary_iid: int,
        is_sid: bool,
        conn: AirportConnection | None = None,
    ) -> tuple[Procedure | None, Node | None, str | None]:
        """Select best procedure by total distance (airway + procedure).

        For SID: airway from boundary to other_boundary + SID procedure distance.
        For STAR: airway from other_boundary to boundary + STAR procedure distance.

        Returns (procedure, boundary_node, transition_name).
        transition_name is None when the main procedure boundary wins.
        """
        if not candidates:
            return None, None, None

        if len(candidates) == 1:
            return candidates[0][0], candidates[0][1], candidates[0][3]

        best_proc, best_boundary, best_t_name = None, None, None
        best_dist = float("inf")

        for proc, boundary, _key, t_name in candidates:
            if is_sid:
                dist = self._astar_airway_distance(boundary.iid, other_boundary_iid)
            else:
                dist = self._astar_airway_distance(other_boundary_iid, boundary.iid)

            if dist is not None and conn is not None:
                if is_sid:
                    # SID: use actual procedure+transition distance.
                    # GC distance from airport to boundary is too optimistic and
                    # can pick a short transition whose airway later backtracks
                    # through transition waypoints (e.g. LAXX1 OCN transition
                    # then airway V165 returns to DANAH).
                    proc_dist = self._calc_procedure_distance(proc, conn, transition_name=t_name)
                else:
                    # STAR: use GC distance from boundary to airport.
                    # _calc_procedure_distance sums every waypoint leg, which
                    # overestimates curved STARs (e.g. HAWKZ8 LKV transition
                    # sums to 325 nm but the compressed route distance is
                    # 308 nm).  GC aligns with _calc_route_distance which
                    # compresses consecutive STAR nodes into a single segment.
                    proc_dist = great_circle_distance_km(
                        boundary.px,
                        boundary.py,
                        conn.airport_node.px,
                        conn.airport_node.py,
                    )
                dist += proc_dist

            if dist is not None and dist < best_dist:
                best_dist = dist
                best_proc = proc
                best_boundary = boundary
                best_t_name = t_name

        if best_proc is None:
            # Fallback: return first candidate
            return candidates[0][0], candidates[0][1], candidates[0][3]

        return best_proc, best_boundary, best_t_name

    def _find_insertion_transition(
        self,
        airway_route: list[tuple[str, str, int]],
        star_proc: Procedure,
    ) -> list[tuple[str, float, float]] | None:
        """Find the STAR transition whose start is in the airway route.

        Returns the transition point list (including start and end) or None.
        """
        if not star_proc.transitions or not airway_route:
            return None

        airway_names = {name for _, name, _ in airway_route}
        best_transition = None
        best_start_idx = -1

        for t_name, t_pts in star_proc.transitions:
            if t_name.startswith("RW"):
                continue
            if len(t_pts) < 2:
                continue
            start_name = t_pts[0][0]
            if start_name not in airway_names:
                continue
            for i, (_, name, _) in enumerate(airway_route):
                if name == start_name and i > best_start_idx:
                    best_start_idx = i
                    best_transition = t_pts
                    break

        return best_transition

    def _assemble_route(
        self,
        sid_conn: AirportConnection,
        sid_proc: Procedure,
        airway_route: list[tuple[str, str, int]],
        star_proc: Procedure,
        star_conn: AirportConnection,
        sid_boundary: Node | None = None,
        star_boundary: Node | None = None,
        sid_transition_pts: list[tuple[str, float, float]] | None = None,
    ) -> list[tuple[str, str, int]]:
        """Assemble full route: SID -> airway -> STAR."""
        route: list[tuple[str, str, int]] = []

        # SID segment (skip first point if it's the airport itself)
        if sid_proc.points:
            start_idx = 1 if sid_proc.points[0][0] == sid_conn.airport_node.name else 0

            # If the airway starts at a node inside the SID procedure, only
            # include SID points before that node. This prevents gaps where
            # the boundary node is skipped but later procedure points are added.
            first_airway_name = airway_route[0][1] if airway_route else None
            sid_end_idx = len(sid_proc.points)
            if first_airway_name is not None:
                for idx, pt in enumerate(sid_proc.points):
                    if pt[0] == first_airway_name:
                        sid_end_idx = idx
                        break

            for i in range(start_idx, sid_end_idx):
                node = self._find_node_for_point(sid_proc.points[i], sid_conn, star_conn)
                if node is not None:
                    route.append(("SID", node.name, node.iid))

        # Insert SID transition points (between SID and airway)
        if sid_transition_pts is not None:
            # Skip first point if it's the last SID main point (avoid duplication)
            t_start = 0
            if sid_proc.points and sid_transition_pts[0][0] == sid_proc.points[-1][0]:
                t_start = 1
            # Skip last point if it's the first airway point (avoid duplication)
            t_end = len(sid_transition_pts)
            if airway_route and sid_transition_pts[-1][0] == airway_route[0][1]:
                t_end -= 1

            for i in range(t_start, t_end):
                pt = sid_transition_pts[i]
                node = self._find_node_for_point(pt, sid_conn, star_conn)
                if node is not None:
                    if route and route[-1][2] == node.iid:
                        continue
                    route.append(("SID", node.name, node.iid))

        # If the SID boundary (the actual A* start node) is not the last
        # point in the SID segment, insert bridge edge nodes to close the gap.
        # This happens when _find_boundary_node followed a bridge edge
        # (e.g. RAMEN -> BIGEX) and the airway route starts from the
        # bridged node rather than the procedure's last point.
        if sid_boundary is not None and route and route[-1][2] != sid_boundary.iid and airway_route:
            # Find bridge edge from last SID node to sid_boundary.
            # Bridge nodes are not part of the procedure itself, so they
            # are tagged with an empty airway label so frontend SID matching
            # only sees actual procedure points.
            last_sid_iid = route[-1][2]
            for edge in sid_conn.bridge_edges:
                if edge.nfrom == last_sid_iid and edge.nend == sid_boundary.iid:
                    route.append(("", sid_boundary.name, sid_boundary.iid))
                    break
            else:
                # No direct bridge — try to walk bridge edges
                visited = set()
                curr = last_sid_iid
                while curr != sid_boundary.iid:
                    found = False
                    for edge in sid_conn.bridge_edges:
                        if edge.nfrom == curr and edge.nend not in visited:
                            visited.add(edge.nend)
                            node = self.node_list[edge.nend]
                            if node is not None:
                                route.append(("", node.name, node.iid))
                                curr = edge.nend
                                found = True
                                break
                    if not found:
                        break

        # Determine if a STAR transition needs to be inserted
        transition_pts = self._find_insertion_transition(airway_route, star_proc)

        # Airway segment: filter out nodes that also appear in STAR procedure
        # (except the last airway node which is the boundary to STAR)
        filtered_airway = list(airway_route)

        # If a transition starts inside the airway, truncate the airway at the
        # transition start so the transition points form the path to the STAR.
        if transition_pts is not None:
            start_name = transition_pts[0][0]
            for i, (_, name, _) in enumerate(filtered_airway):
                if name == start_name:
                    filtered_airway = filtered_airway[: i + 1]
                    break

        if star_proc and star_proc.points and filtered_airway:
            star_node_names = {p[0] for p in star_proc.points}
            # If an internal airway node is also in STAR, truncate airway there
            truncate_idx = None
            for i, (_edge_name, node_name, _iid) in enumerate(filtered_airway):
                if node_name in star_node_names and i < len(filtered_airway) - 1:
                    truncate_idx = i
                    break
            if truncate_idx is not None:
                filtered_airway = filtered_airway[: truncate_idx + 1]

        route.extend(filtered_airway)

        # Insert transition points (skip start – already in airway)
        if transition_pts is not None:
            for pt in transition_pts[1:]:
                node = self._find_node_for_point(pt, sid_conn, star_conn)
                if node is not None:
                    if route and route[-1][2] == node.iid:
                        continue
                    route.append(("STAR", node.name, node.iid))

        # STAR segment
        if star_proc.points:
            last_airway_iid = filtered_airway[-1][2] if filtered_airway else None
            last_airway_name = filtered_airway[-1][1] if filtered_airway else None

            # Find where the truncated airway ends in the STAR procedure.
            # If the airway ends at an internal STAR node (e.g. SAUGS in
            # [WAYVE, SAUGS, KIMMO, UPDOC]), start the STAR loop from that
            # index so the STAR subsequence is contiguous.
            star_start_idx = 0
            if last_airway_name is not None:
                for idx, pt in enumerate(star_proc.points):
                    if pt[0] == last_airway_name:
                        star_start_idx = idx
                        break

            # Only insert a bridge edge when the airway does NOT end at any
            # STAR point (normal boundary case: airway end -> STAR start).
            if star_start_idx == 0 and last_airway_name != star_proc.points[0][0]:
                first_star_pt = star_proc.points[0]
                first_star_node = self._find_node_for_point(first_star_pt, sid_conn, star_conn)
                if first_star_node is not None and first_star_node.iid != last_airway_iid:
                    for edge in star_conn.bridge_edges:
                        if edge.nfrom == last_airway_iid and edge.nend == first_star_node.iid:
                            route.append(("STAR", first_star_node.name, first_star_node.iid))
                            break

            for pt in star_proc.points[star_start_idx:]:
                node = self._find_node_for_point(pt, sid_conn, star_conn)
                if node is not None:
                    # Skip the node already present as the last airway node
                    if node.iid == last_airway_iid:
                        continue
                    # Skip consecutive duplicates
                    if route and route[-1][2] == node.iid:
                        continue
                    route.append(("STAR", node.name, node.iid))

        # Ensure route reaches the destination airport
        if not route or route[-1][2] != star_conn.airport_node.iid:
            route.append(("STAR", star_conn.airport_node.name, star_conn.airport_node.iid))

        return route

    def _find_node_for_point(
        self,
        pt: tuple[str, float, float],
        sid_conn: AirportConnection | None = None,
        star_conn: AirportConnection | None = None,
    ) -> Node | None:
        """Find node for a procedure point (name, lat, lon)."""
        name, lat, lon = pt
        key = (name, round(lat, 6), round(lon, 6))
        node = self._node_index.get(key)
        if node is not None:
            return node
        if sid_conn is not None:
            for temp in sid_conn.temp_nodes:
                if temp.name == name and abs(temp.px - lat) < 1e-6 and abs(temp.py - lon) < 1e-6:
                    return temp
        if star_conn is not None:
            for temp in star_conn.temp_nodes:
                if temp.name == name and abs(temp.px - lat) < 1e-6 and abs(temp.py - lon) < 1e-6:
                    return temp
        return None

    def _calc_route_distance(
        self,
        route_list: list[tuple[str, str, int]],
        sid_conn: AirportConnection,
        star_conn: AirportConnection,
    ) -> float:
        """Calculate total distance in km using compressed route nodes.

        Unlike _compress_route (used for route-string display) which drops
        intermediate airway nodes, the distance version keeps both the entry
        and exit of each airway segment.  This ensures the summed great-circle
        legs follow the actual airway path rather than taking a shortcut
        between arbitrary waypoints, matching standard flight-planning tools.
        """
        compressed = self._compress_route_for_distance(route_list)

        dist_km = 0.0
        prev_node = sid_conn.airport_node
        for _, _, iid in compressed:
            node = self._get_node(iid, sid_conn, star_conn)
            if node is not None and node.iid != prev_node.iid:
                dist_km += great_circle_distance_km(
                    prev_node.px,
                    prev_node.py,
                    node.px,
                    node.py,
                )
                prev_node = node
        return dist_km

    def _find_active_transition(
        self,
        proc: Procedure | None,
        route_node_names: set,
        is_sid: bool,
    ) -> str | None:
        """Find the transition whose nodes best match the route."""
        if proc is None or not proc.transitions:
            return None

        best = None
        best_score = 0

        for t_name, t_pts in proc.transitions:
            if t_name.startswith("RW"):
                continue
            t_names = [p[0] for p in t_pts]
            if not t_names:
                continue

            # Directional check: SID transition starts in route, STAR ends in route
            if is_sid:
                if t_names[0] not in route_node_names:
                    continue
            else:
                if t_names[-1] not in route_node_names:
                    continue

            score = sum(1 for n in t_names if n in route_node_names)
            if score > best_score:
                best_score = score
                best = t_name

        return best

    @staticmethod
    def _bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calculate bearing from point 1 to point 2 in degrees (0-360)."""
        lat1r = math.radians(lat1)
        lat2r = math.radians(lat2)
        dlon = math.radians(lon2 - lon1)
        x = math.sin(dlon) * math.cos(lat2r)
        y = math.cos(lat1r) * math.sin(lat2r) - math.sin(lat1r) * math.cos(lat2r) * math.cos(dlon)
        bearing = math.degrees(math.atan2(x, y))
        return (bearing + 360) % 360

    @staticmethod
    def _angle_diff(a1: float, a2: float) -> float:
        """Minimum difference between two bearings in degrees."""
        diff = abs(a1 - a2) % 360
        return diff if diff <= 180 else 360 - diff

    def _get_node(
        self,
        iid: int,
        sid_conn: AirportConnection,
        star_conn: AirportConnection,
    ) -> Node | None:
        if iid == sid_conn.airport_node.iid:
            return sid_conn.airport_node
        if iid == star_conn.airport_node.iid:
            return star_conn.airport_node
        if 0 <= iid < self.num_nodes:
            node = self.node_list[iid]
            if node is not None and node.iid == iid:
                return node
        for node in sid_conn.temp_nodes:
            if node.iid == iid:
                return node
        for node in star_conn.temp_nodes:
            if node.iid == iid:
                return node
        return None

    def _reassign_airways(
        self,
        airway_route: list[tuple[str, str, int]],
        start_iid: int,
    ) -> list[tuple[str, str, int]]:
        """Reassign airway names to prefer airway switching at waypoints.

        When two consecutive waypoints are connected by multiple airways,
        prefer the airway that differs from the previous segment, but only
        when A* itself has switched airways.  If A* stayed on the same
        airway, keep that name so intermediate nodes do not get fragmented
        into spurious airway changes.
        """
        if not airway_route:
            return []

        result: list[tuple[str, str, int]] = []
        prev_iid = start_iid

        for orig_edge_name, node_name, curr_iid in airway_route:
            prev_node = self.node_list[prev_iid]
            airways: set[str] = set()
            for edge in prev_node.next_list:
                if edge.nend == curr_iid:
                    airways.add(edge.name)

            if len(airways) == 1:
                best_airway = airways.pop()
            elif len(airways) > 1:
                prev_airway = result[-1][0] if result else None
                # If A* itself stayed on this airway, honour its choice so
                # intermediate nodes inside a long airway are not split into
                # spurious airway changes (e.g. J146 -> J60 -> J146 ...).
                if orig_edge_name in airways:
                    best_airway = orig_edge_name
                elif prev_airway is not None:
                    different = {a for a in airways if a != prev_airway}
                    best_airway = min(different) if different else min(airways)
                else:
                    best_airway = min(airways)
            else:
                # No airway found (should not happen); keep original
                best_airway = orig_edge_name

            result.append((best_airway, node_name, curr_iid))
            prev_iid = curr_iid

        return result

    def _compress_route(self, route_list: list[tuple[str, str, int]]) -> list[tuple[str, str, int]]:
        """Compress airway nodes to match rfinder SortRoute conventions.

        Each group (SID, airway, STAR, or bridge) keeps its *last* node,
        matching the original SortRoute behaviour where consecutive entries
        on the same airway replace the previous one.
        """
        compressed: list[tuple[str, str, int]] = []
        current_group: str | None = None
        group_nodes: list[tuple[str, str, int]] = []

        for item in route_list:
            edge_name = item[0]

            if edge_name != current_group:
                # Flush previous group: keep last node
                if group_nodes:
                    compressed.append(group_nodes[-1])
                    group_nodes = []
                current_group = edge_name

            group_nodes.append(item)

        # Flush final group: keep last node
        if group_nodes:
            compressed.append(group_nodes[-1])

        return compressed

    def _compress_route_for_distance(
        self, route_list: list[tuple[str, str, int]]
    ) -> list[tuple[str, str, int]]:
        """Compress route for distance calculation.

        Unlike _compress_route which drops intermediate airway nodes for
        route-string display, this keeps both the entry and exit of each
        airway segment so the summed great-circle legs match the actual
        airway path.
        """
        compressed: list[tuple[str, str, int]] = []
        current_group: str | None = None
        group_nodes: list[tuple[str, str, int]] = []

        for item in route_list:
            edge_name = item[0]
            if edge_name != current_group:
                if group_nodes:
                    if current_group in ("SID", "STAR", ""):
                        compressed.append(group_nodes[-1])
                    else:
                        # airway: keep entry and exit
                        compressed.append(group_nodes[0])
                        if len(group_nodes) > 1:
                            compressed.append(group_nodes[-1])
                    group_nodes = []
                current_group = edge_name
            group_nodes.append(item)

        if group_nodes:
            if current_group in ("SID", "STAR", ""):
                compressed.append(group_nodes[-1])
            else:
                compressed.append(group_nodes[0])
                if len(group_nodes) > 1:
                    compressed.append(group_nodes[-1])

        # Remove consecutive duplicates by iid
        deduped: list[tuple[str, str, int]] = []
        for item in compressed:
            if not deduped or deduped[-1][2] != item[2]:
                deduped.append(item)

        return deduped

    def _sort_route(self, orig: str, route_list: list[tuple[str, str, int]]) -> str:
        """Merge consecutive edges on same airway."""
        compressed = self._compress_route(route_list)
        parts = [orig]
        for edge_name, node_name, _ in compressed:
            parts.extend([edge_name, node_name])
        return " ".join(parts)

    def _build_node_info(
        self,
        sid_conn: AirportConnection,
        star_conn: AirportConnection,
        route_list: list[tuple[str, str, int]],
    ) -> list[list]:
        """Build list of [name, lat, lon] for each node in route."""
        result = [[sid_conn.airport_node.name, sid_conn.airport_node.px, sid_conn.airport_node.py]]
        for _, _, iid in route_list:
            node = self._get_node(iid, sid_conn, star_conn)
            if node:
                result.append([node.name, node.px, node.py])
        return result

    def _build_route_segments(
        self,
        sid_conn: AirportConnection,
        route_list: list[tuple[str, str, int]],
    ) -> list[dict]:
        """Build list of route segments with airway names."""
        segments = []
        prev_name = sid_conn.airport_node.name
        for edge_name, node_name, _ in route_list:
            segments.append(
                {
                    "from": prev_name,
                    "to": node_name,
                    "airway": edge_name,
                }
            )
            prev_name = node_name
        return segments

    def _mixed_graph_astar(
        self,
        orig: str,
        dest: str,
        sid_conn: AirportConnection,
        star_conn: AirportConnection,
        airport_names: list[str],
        sid_exit: str | None = None,
        star_entry: str | None = None,
    ) -> str | None:
        """Mixed-graph A*: single search with weighted pseudo-edges for SID/STAR.

        Returns JSON string or None if no route found.
        """
        timestart = time.time()

        sid_candidates = self._collect_procedure_candidates(
            sid_conn, is_sid=True, filter_name=sid_exit
        )
        star_candidates = self._collect_procedure_candidates(
            star_conn, is_sid=False, filter_name=star_entry, sid_conn=sid_conn, star_conn=star_conn
        )
        if not sid_candidates or not star_candidates:
            return None

        # Build forbidden set from all procedure point coordinates.  Use
        # (name, lat, lon) keys instead of names alone so that airway nodes
        # sharing a name but located elsewhere are not blocked.
        forbidden_keys = set()
        for proc, boundary, key, t_name in sid_candidates:
            for pt in proc.points:
                forbidden_keys.add((pt[0], round(pt[1], 6), round(pt[2], 6)))
            for _trans_name, trans_pts in proc.transitions:
                for pt in trans_pts:
                    forbidden_keys.add((pt[0], round(pt[1], 6), round(pt[2], 6)))
        for proc, boundary, key, t_name in star_candidates:
            for pt in proc.points:
                forbidden_keys.add((pt[0], round(pt[1], 6), round(pt[2], 6)))
            for _trans_name, trans_pts in proc.transitions:
                for pt in trans_pts:
                    forbidden_keys.add((pt[0], round(pt[1], 6), round(pt[2], 6)))

        # STAR boundaries must be reachable from airway, so remove them from forbidden
        for proc, boundary, key, t_name in star_candidates:
            forbidden_keys.discard((boundary.name, round(boundary.px, 6), round(boundary.py, 6)))

        # Prune candidates to the most promising N per side (by boundary
        # distance to the opposite airport) to keep A* search fast.
        _MAX_CANDIDATES = 50
        if len(sid_candidates) > _MAX_CANDIDATES:
            sid_candidates = sorted(
                sid_candidates,
                key=lambda c: great_circle_distance_km(
                    c[1].px, c[1].py,
                    star_conn.airport_node.px, star_conn.airport_node.py,
                ),
            )[:_MAX_CANDIDATES]
        if len(star_candidates) > _MAX_CANDIDATES:
            star_candidates = sorted(
                star_candidates,
                key=lambda c: great_circle_distance_km(
                    c[1].px, c[1].py,
                    sid_conn.airport_node.px, sid_conn.airport_node.py,
                ),
            )[:_MAX_CANDIDATES]

        # Airport nodes with positive IIDs beyond num_nodes
        start_iid = self.num_nodes
        end_iid = self.num_nodes + 1
        end_lat = star_conn.airport_node.px
        end_lon = star_conn.airport_node.py

        # SID pseudo-edges: airport -> boundary, weight = procedure distance
        # If boundary is a temp node (negative iid), map to the corresponding
        # airway node so A* can traverse from it.
        sid_pseudo = []
        for proc, boundary, key, t_name in sid_candidates:
            weight = self._calc_procedure_distance(proc, sid_conn, t_name)
            target_iid = boundary.iid
            if target_iid < 0 or target_iid >= self.num_nodes:
                for node in self.node_list:
                    if node is not None and node.name == boundary.name:
                        target_iid = node.iid
                        break
            sid_pseudo.append((target_iid, weight, proc, boundary, key, t_name))

        # STAR pseudo-edges: boundary -> airport, weight = GC distance
        # (aligns with _select_procedure_astar which uses GC for STAR)
        star_pseudo = []
        for proc, boundary, key, t_name in star_candidates:
            weight = great_circle_distance_km(
                boundary.px,
                boundary.py,
                star_conn.airport_node.px,
                star_conn.airport_node.py,
            )
            source_iid = boundary.iid
            if source_iid < 0 or source_iid >= self.num_nodes:
                for node in self.node_list:
                    if node is not None and node.name == boundary.name:
                        source_iid = node.iid
                        break
            star_pseudo.append((source_iid, weight, proc, boundary, key, t_name))

        # A* on mixed graph
        INF = float("inf")
        size = self.num_nodes + 2
        dists = [INF] * size
        prev = [None] * size
        dists[start_iid] = 0.0
        queue = [(0.0, 0.0, start_iid)]

        # Local bindings for hot loop
        node_list = self.node_list
        has_non_t = self._node_has_non_t
        _end_rlat = end_lat * math.pi / 180.0
        _end_rlon = end_lon * math.pi / 180.0
        _ce = math.cos(_end_rlat)
        _R = 6371.0
        forbidden = forbidden_keys
        num_nodes = self.num_nodes

        while queue:
            _f, g_score, curr = heapq.heappop(queue)
            if curr == end_iid:
                break
            if g_score > dists[curr]:
                continue

            # SID pseudo-edges from start node
            if curr == start_iid:
                for target_iid, weight, proc, boundary, key, t_name in sid_pseudo:
                    nd = g_score + weight
                    if nd < dists[target_iid]:
                        dists[target_iid] = nd
                        prev[target_iid] = (curr, "SID", key, proc, t_name, boundary)
                        target_node = node_list[target_iid]
                        _rlat = target_node.px * math.pi / 180.0
                        _rlon = target_node.py * math.pi / 180.0
                        _dlat = _rlat - _end_rlat
                        _dlon = _rlon - _end_rlon
                        _a = (math.sin(_dlat / 2) ** 2
                              + math.cos(_rlat) * _ce * math.sin(_dlon / 2) ** 2)
                        h = 2.0 * math.asin(math.sqrt(min(1.0, _a))) * _R
                        heapq.heappush(queue, (nd + h, nd, target_iid))
                continue

            # Airway edges (only valid airway nodes have 0 <= iid < num_nodes)
            if 0 <= curr < num_nodes:
                curr_node = node_list[curr]
                if curr_node is not None:
                    for edge in curr_node.next_list:
                        nend = edge.nend
                        next_node = node_list[nend]
                        if next_node.node_key() in forbidden:
                            continue
                        ename = edge.name
                        if (ename and ename[0] == "T" and len(ename) > 1
                                and ename[1:].isdigit() and has_non_t[curr]):
                            continue
                        nd = g_score + edge.dist
                        if nd < dists[nend]:
                            dists[nend] = nd
                            prev[nend] = (curr, ename, None, None, None, None)
                            _rlat = next_node.px * math.pi / 180.0
                            _rlon = next_node.py * math.pi / 180.0
                            _dlat = _rlat - _end_rlat
                            _dlon = _rlon - _end_rlon
                            _a = (math.sin(_dlat / 2) ** 2
                                  + math.cos(_rlat) * _ce * math.sin(_dlon / 2) ** 2)
                            h = 2.0 * math.asin(math.sqrt(min(1.0, _a))) * _R
                            heapq.heappush(queue, (nd + h, nd, nend))

            # STAR pseudo-edges to end node
            for source_iid, weight, proc, boundary, key, t_name in star_pseudo:
                if curr == source_iid:
                    nd = g_score + weight
                    if nd < dists[end_iid]:
                        dists[end_iid] = nd
                        prev[end_iid] = (curr, "STAR", key, proc, t_name, boundary)
                        heapq.heappush(queue, (nd, nd, end_iid))

        if dists[end_iid] == INF:
            return None

        # Reconstruct path
        path = []
        curr = end_iid
        while curr != start_iid:
            p = prev[curr]
            if p is None:
                return None
            from_iid, edge_name, key, proc, t_name, boundary = p
            if edge_name == "STAR":
                path.append(("STAR", key, proc, t_name, boundary))
            elif edge_name == "SID":
                path.append(("SID", key, proc, t_name, boundary))
            else:
                node = self.node_list[curr]
                path.append((edge_name, node.name, curr))
            curr = from_iid
        path.reverse()

        # Remove cycles from airway portion (same node visited multiple times)
        seen_iids = set()
        clean_path = []
        for item in path:
            if item[0] in ("SID", "STAR"):
                clean_path.append(item)
                if item[0] == "SID":
                    seen_iids.clear()
            else:
                iid = item[2]
                if iid not in seen_iids:
                    clean_path.append(item)
                    seen_iids.add(iid)
        path = clean_path

        # Extract SID/STAR and airway route
        sid_info = None
        star_info = None
        airway_route = []
        for item in path:
            if item[0] == "SID":
                sid_info = item
            elif item[0] == "STAR":
                star_info = item
            else:
                # Skip SID boundary nodes so _assemble_route doesn't duplicate them
                if sid_info is not None and item[2] == sid_info[4].iid:
                    continue
                airway_route.append(item)

        if sid_info is None or star_info is None:
            return None

        sid_proc = sid_info[2]
        sid_boundary = sid_info[4]
        sid_info[1]
        sid_t_name = sid_info[3]

        star_proc = star_info[2]
        star_boundary = star_info[4]
        star_info[1]
        star_info[3]

        # Get SID transition points
        sid_transition_pts = None
        if sid_proc is not None and sid_t_name is not None:
            for t_name, t_pts in sid_proc.transitions:
                if t_name == sid_t_name:
                    sid_transition_pts = list(t_pts)
                    break

        # Assemble route
        route_list = self._assemble_route(
            sid_conn,
            sid_proc,
            airway_route,
            star_proc,
            star_conn,
            sid_boundary=sid_boundary,
            star_boundary=star_boundary,
            sid_transition_pts=sid_transition_pts,
        )

        dist_km = self._calc_route_distance(route_list, sid_conn, star_conn)
        dist_nm = dist_km / 1.852
        dist_str = f"{dist_nm:.2f} nm / {dist_km:.2f} km"
        route_total = self._sort_route(orig, route_list)
        node_info = self._build_node_info(sid_conn, star_conn, route_list)
        route_segments = self._build_route_segments(sid_conn, route_list)

        sid_node_name = sid_proc.points[-1][0] if sid_proc.points else None
        star_node_name = star_proc.points[0][0] if star_proc.points else None

        sid_route_node_name = None
        if sid_proc and sid_proc.points:
            sid_names = {p[0] for p in sid_proc.points}
            for _, node_name, _ in route_list:
                if node_name in sid_names:
                    sid_route_node_name = node_name

        star_route_node_name = None
        if star_proc and star_proc.points:
            star_names = {p[0] for p in star_proc.points}
            for t_name, t_pts in star_proc.transitions:
                star_names.update(p[0] for p in t_pts)
            for _, node_name, _ in route_list:
                if node_name in star_names:
                    star_route_node_name = node_name
                    break

        route_node_names = {node_name for _, node_name, _ in route_list}
        active_sid_transition = self._find_active_transition(
            sid_proc, route_node_names, is_sid=True
        )
        active_star_transition = self._find_active_transition(
            star_proc, route_node_names, is_sid=False
        )

        time_total = time.time() - timestart
        sttime = "%.2f" % (time_total * 1000)

        return build_route_info(
            self.data_version,
            sttime,
            route_total,
            dist_str,
            node_info,
            sid_conn.procedures,
            star_conn.procedures,
            airport_names,
            active_sid_transition,
            active_star_transition,
            route_segments,
            sid_node_name,
            star_node_name,
            sid_route_node_name,
            star_route_node_name,
        )
