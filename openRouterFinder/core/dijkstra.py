"""A* route finding engine with isolated per-request state."""

import heapq
import json
import math
import time
from typing import List, Dict, Tuple, Optional

from openRouterFinder.core.graph import (
    Node,
    Edge,
    SearchingNode,
    great_circle_distance_km,
    heuristic_km,
)
from openRouterFinder.core.airport import AirportConnection, Procedure


def _procs_to_dict(procs: dict) -> dict:
    """Convert Procedure objects to JSON-serializable tuples [name, runway, points, transitions]."""
    result = {}
    for key, proc_list in procs.items():
        result[key] = [
            [p.name, p.runway, p.points, [[t[0], t[1]] for t in p.transitions]]
            for p in proc_list
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
    active_sid_transition: str = None,
    active_star_transition: str = None,
    route_segments: list = None,
    sid_node_name: str = None,
    star_node_name: str = None,
    sid_route_node_name: str = None,
    star_route_node_name: str = None,
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
    return json.dumps(result)


class RouteEngine:
    """Per-request route calculator. Thread-safe: no shared mutable state."""

    def __init__(
        self,
        node_list: Tuple[Optional[Node], ...],
        data_version: str,
        node_index: Optional[Dict[Tuple[str, float, float], Node]] = None,
    ):
        self.node_list = node_list
        self.data_version = data_version
        self.num_nodes = len(node_list)
        # Safe negative IID range for transition nodes inserted post-A*
        self._next_temp_iid = -1000000

        # O(1) node lookup by (name, lat, lon) for procedure assembly
        if node_index is not None:
            self._node_index = node_index
        else:
            self._node_index: Dict[Tuple[str, float, float], Node] = {}
            for node in node_list:
                if node is not None:
                    self._node_index[node.node_key()] = node

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

    def _select_best_sid(self, sid_conn: AirportConnection, dest_node: Node) -> List[Edge]:
        """Select best SID connection(s) by bearing from airport to destination.

        If a single SID connection exists, return it. Otherwise pick the one
        whose exit direction best aligns with the great-circle route.
        """
        connections = sid_conn.connections
        if len(connections) <= 1:
            return list(connections)

        ap_lat, ap_lon = sid_conn.airport_node.px, sid_conn.airport_node.py
        target_bearing = self._bearing(ap_lat, ap_lon, dest_node.px, dest_node.py)

        best_edge = None
        best_score = float('inf')
        for edge in connections:
            exit_node = self._get_node(edge.nend, sid_conn, None)
            if exit_node is None:
                continue
            exit_bearing = self._bearing(ap_lat, ap_lon, exit_node.px, exit_node.py)
            score = abs(self._angle_diff(target_bearing, exit_bearing))
            if score < best_score:
                best_score = score
                best_edge = edge

        return [best_edge] if best_edge else list(connections)

    def _select_best_star(self, star_conn: AirportConnection, orig_node: Node) -> List[Edge]:
        """Select best STAR connection(s) by bearing from origin to airport.

        If a single STAR connection exists, return it. Otherwise pick the one
        whose entry direction best aligns with the great-circle route.
        """
        connections = star_conn.connections
        if len(connections) <= 1:
            return list(connections)

        ap_lat, ap_lon = star_conn.airport_node.px, star_conn.airport_node.py
        target_bearing = self._bearing(orig_node.px, orig_node.py, ap_lat, ap_lon)

        best_edge = None
        best_score = float('inf')
        for edge in connections:
            entry_node = self._get_node(edge.nfrom, None, star_conn)
            if entry_node is None:
                continue
            entry_bearing = self._bearing(entry_node.px, entry_node.py, ap_lat, ap_lon)
            score = abs(self._angle_diff(target_bearing, entry_bearing))
            if score < best_score:
                best_score = score
                best_edge = edge

        return [best_edge] if best_edge else list(connections)

    def search(
        self,
        orig: str,
        dest: str,
        sid_conn: AirportConnection,
        star_conn: AirportConnection,
        airport_names: List[str],
        sid_exit: Optional[str] = None,
        star_entry: Optional[str] = None,
    ) -> Optional[str]:
        """Run mixed-graph A* search. Returns JSON string or None."""
        timestart = time.time()

        # Use ALL connections and ALL bridges — let A* evaluate every
        # SID/STAR combination and pick the shortest total path.
        route_list = self._mixed_astar(
            sid_conn.airport_node.iid,
            star_conn.airport_node.iid,
            sid_conn, star_conn,
        )

        if route_list is None:
            return build_route_info(
                self.data_version, "0.00",
                "No result.", "0.00 nm / 0.00 km",
                None, {}, {}, [],
            )

        # Detect SID/STAR boundaries from edge names in route_list
        sid_route_node_name = None
        star_route_node_name = None

        # SID boundary: scan from start for consecutive "SID" edges
        for i, (edge_name, node_name, _) in enumerate(route_list):
            if edge_name == "SID":
                sid_route_node_name = node_name
            else:
                break

        # STAR boundary: scan from end for consecutive "STAR" edges
        star_items = []
        for i in range(len(route_list) - 1, -1, -1):
            edge_name, node_name, _ = route_list[i]
            if edge_name == "STAR":
                star_items.append((i, node_name))
            else:
                break

        if len(star_items) >= 2:
            # At least entry->airport, possibly with bridge before entry
            star_route_node_name = star_items[1][1]
            if len(star_items) >= 3:
                star_route_node_name = star_items[2][1]
        elif len(star_items) == 1:
            # Only the airport has a "STAR" incoming edge (no bridge).
            # The entry point is the node immediately before the airport.
            if len(route_list) >= 2:
                star_route_node_name = route_list[-2][1]

        # sidNodeName / starNodeName are the procedure keys (common
        # segment exit/entry) used by the frontend to look up the
        # selected procedure.  sidRouteNodeName / starRouteNodeName are
        # the actual boundary nodes used by A* (may be transition
        # endpoints).
        sid_node_name = self._find_procedure_key(
            sid_conn, sid_route_node_name, is_sid=True
        )
        star_node_name = self._find_procedure_key(
            star_conn, star_route_node_name, is_sid=False
        )

        # Active transitions: determine which transition endpoint A* selected
        # by searching the matched procedure for a transition whose boundary
        # point matches the node used in the mixed-graph route.
        active_sid_transition = self._find_active_transition(
            sid_conn, sid_node_name, sid_route_node_name, is_sid=True
        )
        active_star_transition = self._find_active_transition(
            star_conn, star_node_name, star_route_node_name, is_sid=False
        )

        # Keep the original A* route for distance calculation so procedure
        # internal points do not participate in routing distance.
        original_route_list = list(route_list)

        # Insert full procedure paths for display.  A* routed on a simplified
        # graph; we reconstruct the complete procedure path so tests and the
        # frontend receive every waypoint.
        if sid_node_name:
            route_list = self._insert_procedure_points(
                route_list,
                sid_conn,
                sid_node_name,
                active_sid_transition,
                sid_route_node_name,
                is_sid=True,
            )
        if star_node_name:
            route_list = self._insert_procedure_points(
                route_list,
                star_conn,
                star_node_name,
                active_star_transition,
                star_route_node_name,
                is_sid=False,
            )

        # Build display outputs from the augmented route
        node_info = self._build_node_info(sid_conn, star_conn, route_list)
        route_segments = self._build_route_segments(sid_conn, route_list)
        route_total = self._sort_route(orig, route_list)

        # Distance is computed from the original A* path only
        dist_km = self._calc_route_distance(original_route_list, sid_conn, star_conn)
        dist_nm = dist_km / 1.852
        dist_str = "%.2f nm / %.2f km" % (dist_nm, dist_km)

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

    @staticmethod
    def _is_excluded_airway(name: str) -> bool:
        """Check if an airway is a T-route (terminal route) that should be
        excluded from enroute A*.

        T-routes are low-altitude terminal routes that provide shortcuts in
        terminal areas but fragment the enroute airway graph, causing A* to
        deviate from standard high-altitude routes.
        """
        if not name:
            return False
        return name[0] == 'T' and len(name) > 1 and name[1:].isdigit()

    def _should_skip_edge(self, curr_node, edge_name: str) -> bool:
        """Determine whether to skip an edge during A* traversal.

        T-routes are excluded only when the current node has non-T
        alternatives. This allows departure from terminal-only nodes
        (e.g. WUMOX) while preventing T-route shortcuts in the enroute
        core where J/V/Q airways are available.
        """
        if not self._is_excluded_airway(edge_name):
            return False
        has_non_t = any(
            not self._is_excluded_airway(e.name) for e in curr_node.next_list
        )
        return has_non_t

    @staticmethod
    def _edge_sort_key(name: str) -> tuple:
        """Sort key for airway names to ensure deterministic tie-breaking.

        Extracts alphabetic prefix and numeric suffix so that J70 sorts
        before J106 (70 < 106).
        """
        prefix = ''
        num_str = ''
        for c in name:
            if c.isalpha() and not num_str:
                prefix += c
            elif c.isdigit():
                num_str += c
            else:
                break
        return (prefix, int(num_str) if num_str else 999999, name)

    def _get_neighbors(
        self,
        iid: int,
        sid_conn: AirportConnection,
        star_conn: AirportConnection,
    ) -> List[Tuple[int, str]]:
        """Return list of (neighbor_iid, edge_name) for a node in the mixed graph."""
        neighbors = []

        # Airway edges from network nodes
        node = self._get_node(iid, sid_conn, star_conn)
        if node is not None and hasattr(node, 'next_list'):
            for e in node.next_list:
                neighbors.append((e.nend, e.name))

        # SID connections: airport -> exit nodes
        if iid == sid_conn.airport_node.iid:
            for e in sid_conn.connections:
                neighbors.append((e.nend, e.name))

        # STAR connections: entry nodes -> airport
        for e in star_conn.connections:
            if e.nfrom == iid:
                neighbors.append((e.nend, e.name))

        # Boundary bridges: isolated SID exits / STAR entries -> network
        for e in sid_conn.bridge_edges:
            if e.nfrom == iid:
                neighbors.append((e.nend, e.name))
        for e in star_conn.bridge_edges:
            if e.nfrom == iid:
                neighbors.append((e.nend, e.name))

        # Deterministic ordering
        neighbors.sort(key=lambda x: self._edge_sort_key(x[1]))
        return neighbors

    def _mixed_astar(
        self,
        start_iid: int,
        end_iid: int,
        sid_conn: AirportConnection,
        star_conn: AirportConnection,
    ) -> Optional[List[Tuple[str, str, int]]]:
        """A* on mixed graph (airway + airport + connections + bridges).

        Returns route_list of (edge_name, node_name, node_iid) or None.
        """
        INF = float('inf')
        dists: Dict[int, float] = {}
        prev_edge: Dict[int, Tuple[int, str]] = {}

        start_node = self._get_node(start_iid, sid_conn, star_conn)
        end_node = self._get_node(end_iid, sid_conn, star_conn)
        if start_node is None or end_node is None:
            return None

        end_lat, end_lon = end_node.px, end_node.py
        dists[start_iid] = 0.0

        queue = []
        heapq.heappush(queue, (0.0, 0.0, start_iid))

        while queue:
            f_score, g_score, curr = heapq.heappop(queue)

            if curr == end_iid:
                break

            curr_dist = dists.get(curr, INF)
            if curr_dist == INF:
                continue
            if curr_dist < g_score:
                continue

            curr_node = self._get_node(curr, sid_conn, star_conn)
            if curr_node is None:
                continue

            for next_iid, edge_name in self._get_neighbors(curr, sid_conn, star_conn):
                next_node = self._get_node(next_iid, sid_conn, star_conn)
                if next_node is None:
                    continue

                # T-route exclusion
                if self._should_skip_edge(curr_node, edge_name):
                    continue

                nd = curr_dist + great_circle_distance_km(
                    curr_node.px, curr_node.py,
                    next_node.px, next_node.py,
                )

                if nd < dists.get(next_iid, INF):
                    dists[next_iid] = nd
                    prev_edge[next_iid] = (curr, edge_name)
                    h = heuristic_km(next_node.px, next_node.py, end_lat, end_lon)
                    heapq.heappush(queue, (nd + h, nd, next_iid))

        if dists.get(end_iid, INF) == INF:
            return None

        # Backtrack
        route = []
        curr = end_iid
        while curr != start_iid and curr in prev_edge:
            prev_iid, edge_name = prev_edge[curr]
            node = self._get_node(curr, sid_conn, star_conn)
            if node is not None:
                route.append((edge_name, node.name, curr))
            curr = prev_iid
        route.reverse()
        return route

    @staticmethod
    def _select_best_transition(
        proc: Procedure,
        boundary_name: Optional[str],
        is_sid: bool,
    ) -> Optional[List[Tuple[str, float, float]]]:
        """Select the transition that matches the boundary node A* used.

        If *boundary_name* is provided, prefer the transition whose endpoint
        matches it (SID: last point, STAR: first point).  Otherwise fall back
        to the transition with the most points.
        """
        if boundary_name:
            for t_name, t_pts in proc.transitions:
                if not t_pts:
                    continue
                if is_sid:
                    if t_pts[-1][0] == boundary_name:
                        return t_pts
                else:
                    if t_pts[0][0] == boundary_name:
                        return t_pts
        # Fallback: best-scoring transition
        best_trans = None
        best_score = -1
        for t_name, t_pts in proc.transitions:
            if not t_pts:
                continue
            point_names = {p[0] for p in t_pts}
            score = len(point_names) * 1000 + len(t_pts)
            if score > best_score:
                best_score = score
                best_trans = t_pts
        return best_trans

    @staticmethod
    def _select_best_procedure_variant(
        proc_list: list,
        active_transition: Optional[str],
        boundary_name: Optional[str],
        is_sid: bool,
    ) -> Procedure:
        """Select the procedure variant that the frontend would display.

        Scores each variant by the same logic the frontend uses in
        _matchProcedureIndex: count how many of the variant's points appear in
        the final route segment, with a tie-breaker for more main points.
        """
        best_proc = proc_list[0]
        best_score = -1

        for proc in proc_list:
            main_points = proc.points
            main_names = {p[0] for p in main_points}

            # Main points score: all main points will be in the segment after
            # insertion, so this is just len(main_points).
            main_score = len(main_names)

            # Transition score: consider the best-matching transition for this
            # variant, not only the active one.
            best_trans_score = 0
            for t_name, t_pts in proc.transitions:
                trans_names = {p[0] for p in t_pts}
                score = len(trans_names)
                if score > best_trans_score:
                    best_trans_score = score

            # If an active transition is specified, boost variants that have
            # it and whose boundary point matches.
            has_matching_transition = False
            if active_transition and boundary_name:
                for t_name, t_pts in proc.transitions:
                    if t_name == active_transition:
                        if is_sid:
                            if t_pts and t_pts[-1][0] == boundary_name:
                                has_matching_transition = True
                        else:
                            if t_pts and t_pts[0][0] == boundary_name:
                                has_matching_transition = True
                        break

            # Score formula mirrors the frontend's _matchProcedureIndex:
            # max(main_score, best_trans_score) * 1000 + len(main_points)
            score = max(main_score, best_trans_score) * 1000 + len(main_points)
            # Slight boost for variants whose active transition actually matches
            # the boundary node, so we don't pick a different runway variant
            # when the active transition clearly belongs to one of them.
            if has_matching_transition:
                score += 500

            if score > best_score:
                best_score = score
                best_proc = proc

        # When multiple variants share the same matching transition, prefer the
        # one with the fewest main points.  A* only traversed the boundary node,
        # so inserting a long runway-specific prefix that wasn't in the A* path
        # can cause the frontend's transition-scoring to pick a different
        # transition than the one A* actually used.
        if active_transition and boundary_name:
            matching = [
                proc
                for proc in proc_list
                if any(
                    t_name == active_transition
                    and (
                        (is_sid and t_pts and t_pts[-1][0] == boundary_name)
                        or (not is_sid and t_pts and t_pts[0][0] == boundary_name)
                    )
                    for t_name, t_pts in proc.transitions
                )
            ]
            if len(matching) > 1:
                matching.sort(key=lambda p: len(p.points))
                if len(matching[0].points) < len(best_proc.points):
                    best_proc = matching[0]

        return best_proc

    def _insert_procedure_points(
        self,
        route_list: List[Tuple[str, str, int]],
        conn: AirportConnection,
        procedure_key: Optional[str],
        active_transition: Optional[str],
        boundary_name: Optional[str],
        is_sid: bool,
    ) -> List[Tuple[str, str, int]]:
        """Insert the full procedure path into route_list for display.

        A* routes on a simplified graph (airport->boundary and boundary->airport).
        This method reconstructs the complete procedure path so the route
        response contains every waypoint for display and test validation.

        For SID: replaces the single SID boundary node with the full
        runway->exit->transition path.
        For STAR: inserts the full transition->common->runway path before the
        airport node.
        """
        if not procedure_key or procedure_key not in conn.procedures:
            return route_list

        proc_list = conn.procedures[procedure_key]
        if not proc_list:
            return route_list

        # Select the procedure variant that the frontend would display.
        # When multiple variants share the same key (e.g. DEEZZ6 for different
        # runways), proc_list[0] is arbitrary.  We score each variant by the
        # same logic the frontend uses: count how many of its points would
        # appear in the final route segment, with a tie-breaker for more main
        # points.
        proc = self._select_best_procedure_variant(
            proc_list, active_transition, boundary_name, is_sid
        )

        # Build full path points
        full_path: List[Tuple[str, float, float]] = []

        # Select the transition to insert.
        # For SID we use the same scoring the frontend uses so that the
        # inserted path always matches what the frontend would draw.  For STAR
        # we keep the boundary-node-based active_transition because tests
        # explicitly check activeSTARTransition.
        trans_points: List[Tuple[str, float, float]] = []
        if is_sid:
            selected_trans = self._select_best_transition(proc, boundary_name, is_sid=True)
            if selected_trans is not None:
                trans_points = list(selected_trans)
        elif active_transition:
            for t_name, t_pts in proc.transitions:
                if t_name == active_transition:
                    if boundary_name:
                        if t_pts and t_pts[0][0] == boundary_name:
                            trans_points = list(t_pts)
                    else:
                        trans_points = list(t_pts)
                    break

        if is_sid:
            # SID: common segment (runway -> exit) then transition (exit -> airway)
            full_path = list(proc.points)
            if trans_points:
                # If transition's first point matches the last common point,
                # append transition tail (skip duplicate exit point).
                if full_path and full_path[-1][0] == trans_points[0][0]:
                    full_path.extend(trans_points[1:])
                # If the transition is already a prefix of the common segment,
                # just use the common segment.
                elif (
                    len(trans_points) <= len(full_path)
                    and all(
                        trans_points[i][0] == full_path[i][0]
                        for i in range(len(trans_points))
                    )
                ):
                    pass  # already included
                elif trans_points:
                    full_path.extend(trans_points)
        else:
            # STAR: transition (airway -> entry) then common segment (entry -> runway)
            if trans_points:
                # If the transition's last point is the first common point,
                # prepend transition and skip duplicate entry point.
                if proc.points and trans_points[-1][0] == proc.points[0][0]:
                    full_path = list(trans_points)
                    full_path.extend(proc.points[1:])
                # If the transition is already a prefix of the common segment,
                # just use the common segment.
                elif (
                    proc.points
                    and len(trans_points) <= len(proc.points)
                    and all(
                        trans_points[i][0] == proc.points[i][0]
                        for i in range(len(trans_points))
                    )
                ):
                    full_path = list(proc.points)
                else:
                    full_path = list(trans_points)
                    full_path.extend(proc.points)
            else:
                full_path = list(proc.points)

        if not full_path:
            return route_list

        # Helper to resolve or create a node for a point
        def _resolve_point(pt: Tuple[str, float, float]) -> Tuple[str, int]:
            name, lat, lon = pt
            node = self._node_index.get((name, lat, lon))
            if node is None:
                for n in conn.temp_nodes:
                    if n.name == name and abs(n.px - lat) < 1e-6 and abs(n.py - lon) < 1e-6:
                        node = n
                        break
            if node is None:
                existing_iids = {n.iid for n in conn.temp_nodes}
                while self._next_temp_iid in existing_iids:
                    self._next_temp_iid -= 1
                node = Node(iid=self._next_temp_iid, name=name, px=lat, py=lon)
                self._next_temp_iid -= 1
                conn.temp_nodes.append(node)
            return node.name, node.iid

        full_path_names = {pt[0] for pt in full_path}

        if is_sid:
            # SID: replace the first item (boundary node) with the full path
            if not route_list or route_list[0][0] != "SID":
                return route_list

            # A* may have traversed network edges between procedure points.
            # Remove all consecutive nodes from the start that belong to the
            # procedure so we don't create duplicates when inserting the full path.
            first_non_proc_idx = 0
            while first_non_proc_idx < len(route_list) and route_list[first_non_proc_idx][1] in full_path_names:
                first_non_proc_idx += 1

            new_items = [("SID", *_resolve_point(pt)) for pt in full_path]
            return new_items + route_list[first_non_proc_idx:]
        else:
            # STAR: insert before the last item (airport)
            if not route_list or route_list[-1][0] != "STAR":
                return route_list

            # Scan backwards from before the airport and remove all nodes that
            # belong to the procedure path (A* may have used network edges
            # between procedure points as shortcuts).  Stop at the boundary
            # node so the airway edge that reached it is preserved.
            last_non_proc_idx = len(route_list) - 2
            boundary_name = full_path[0][0] if full_path else None
            while (
                last_non_proc_idx >= 0
                and route_list[last_non_proc_idx][1] in full_path_names
                and route_list[last_non_proc_idx][1] != boundary_name
            ):
                last_non_proc_idx -= 1

            insert_idx = len(route_list) - 1
            # Skip the first full-path point if it is already the node
            # immediately before the airport edge.
            start_offset = 0
            if (
                full_path
                and last_non_proc_idx >= 0
                and route_list[last_non_proc_idx][1] == full_path[0][0]
            ):
                start_offset = 1
            # Skip the last full-path point if it is already the node
            # immediately before the airport edge (can happen when A*
            # went through the common-segment end rather than bypassing it).
            end_offset = len(full_path)
            if (
                full_path
                and last_non_proc_idx >= 0
                and route_list[last_non_proc_idx][1] == full_path[-1][0]
            ):
                end_offset = len(full_path) - 1

            new_items = [("STAR", *_resolve_point(pt)) for pt in full_path[start_offset:end_offset]]
            return route_list[:last_non_proc_idx + 1] + new_items + route_list[insert_idx:]

    @staticmethod
    def _find_procedure_key(
        conn: AirportConnection,
        boundary_name: Optional[str],
        is_sid: bool,
    ) -> Optional[str]:
        """Return the procedures dict key that owns the given boundary node.

        For SID: boundary_name is the exit node.  The procedure key is the
        common-segment exit point.  If boundary_name itself is a key, return
        it directly.  Otherwise search all procedures for one whose main
        points or transitions end at boundary_name.
        For STAR: boundary_name is the entry node.  The procedure key is the
        common-segment entry point.  Same lookup logic reversed.
        """
        if not boundary_name:
            return None
        # Direct match — boundary node is itself a procedure key
        # (common-segment exit/entry).
        if boundary_name in conn.procedures:
            return boundary_name
        # Search all procedures for one that contains boundary_name as its
        # common-segment endpoint or as a transition endpoint.
        for key, proc_list in conn.procedures.items():
            for proc in proc_list:
                if is_sid:
                    if proc.points and proc.points[-1][0] == boundary_name:
                        return key
                else:
                    if proc.points and proc.points[0][0] == boundary_name:
                        return key
                for _t_name, t_pts in proc.transitions:
                    if not t_pts:
                        continue
                    if is_sid:
                        if t_pts[-1][0] == boundary_name:
                            return key
                    else:
                        if t_pts[0][0] == boundary_name:
                            return key
        # Fallback: return boundary_name itself so callers can still use it
        # even if no procedure was found.
        return boundary_name

    @staticmethod
    def _find_active_transition(
        conn: AirportConnection,
        procedure_key: Optional[str],
        boundary_name: Optional[str],
        is_sid: bool,
    ) -> Optional[str]:
        """Find the transition name whose endpoint matches the boundary node.

        Searches only within the procedure identified by *procedure_key* so
        that transitions from unrelated procedures are never matched.

        For SID: boundary_name is the exit node; search transitions whose
        last point name equals boundary_name.
        For STAR: boundary_name is the entry node; search transitions whose
        first point name equals boundary_name.
        Returns None when no matching transition is found (e.g. common segment
        exit/entry was used instead of a transition).
        """
        if not boundary_name or not procedure_key:
            return None
        proc_list = conn.procedures.get(procedure_key, [])
        for proc in proc_list:
            for t_name, t_pts in proc.transitions:
                if not t_pts:
                    continue
                if is_sid:
                    if t_pts[-1][0] == boundary_name:
                        return t_name
                else:
                    if t_pts[0][0] == boundary_name:
                        return t_name
        return None

    def _calc_route_distance(
        self,
        route_list: List[Tuple[str, str, int]],
        sid_conn: AirportConnection,
        star_conn: AirportConnection,
    ) -> float:
        """Calculate total distance in km."""
        dist_km = 0.0
        prev_node = sid_conn.airport_node
        for _, _, iid in route_list:
            node = self._get_node(iid, sid_conn, star_conn)
            if node is not None:
                dist_km += great_circle_distance_km(
                    prev_node.px, prev_node.py,
                    node.px, node.py,
                )
                prev_node = node
        return dist_km

    def _get_node(
        self,
        iid: int,
        sid_conn: Optional[AirportConnection],
        star_conn: Optional[AirportConnection],
    ) -> Optional[Node]:
        if sid_conn is not None and iid == sid_conn.airport_node.iid:
            return sid_conn.airport_node
        if star_conn is not None and iid == star_conn.airport_node.iid:
            return star_conn.airport_node
        if 0 <= iid < self.num_nodes:
            node = self.node_list[iid]
            if node is not None and node.iid == iid:
                return node
        if sid_conn is not None:
            for node in sid_conn.temp_nodes:
                if node.iid == iid:
                    return node
        if star_conn is not None:
            for node in star_conn.temp_nodes:
                if node.iid == iid:
                    return node
        return None

    def _sort_route(self, orig: str, route_list: List[Tuple[str, str, int]]) -> str:
        """Merge consecutive edges on same airway."""
        stack = []
        for item in route_list:
            if (
                stack
                and stack[-1][0] == item[0]
                and item[0] not in ("SID", "STAR")
            ):
                stack[-1] = item
                continue
            stack.append(item)
        parts = [orig]
        for edge_name, node_name, _ in stack:
            parts.extend([edge_name, node_name])
        return " ".join(parts)

    def _build_node_info(
        self,
        sid_conn: AirportConnection,
        star_conn: AirportConnection,
        route_list: List[Tuple[str, str, int]],
    ) -> List[List]:
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
        route_list: List[Tuple[str, str, int]],
    ) -> List[dict]:
        """Build list of route segments with airway names."""
        segments = []
        prev_name = sid_conn.airport_node.name
        for edge_name, node_name, _ in route_list:
            segments.append({
                "from": prev_name,
                "to": node_name,
                "airway": edge_name,
            })
            prev_name = node_name
        return segments
