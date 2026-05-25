"""A* route finding engine with isolated per-request state."""

import heapq
import json
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
    ):
        self.node_list = node_list
        self.data_version = data_version
        self.num_nodes = len(node_list)

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
        """Run A* search. Returns JSON string or None."""
        timestart = time.time()

        # Build adjacency map for this search (shared edges + temporary airport edges)
        adjacency = self._build_adjacency(sid_conn, star_conn)

        # A* search
        start_iid = sid_conn.airport_node.iid
        end_iid = star_conn.airport_node.iid

        # Distances dict (supports negative temp node iids)
        INF = float('inf')
        dists: Dict[int, float] = {start_iid: 0.0}

        # Priority queue: (f_score, counter, node)
        counter = 0
        queue = []

        start_node = SearchingNode(iid=start_iid, name=orig, route=orig)
        end_lat = star_conn.airport_node.px
        end_lon = star_conn.airport_node.py

        heapq.heappush(queue, (0.0, counter, start_node))
        counter += 1

        target = None

        while queue:
            _, _, current = heapq.heappop(queue)
            current_node = self._get_node(current.iid, sid_conn, star_conn)

            if current.iid == end_iid:
                target = current
                break

            # Skip if already found better path
            if current.dist > dists.get(current.iid, INF):
                continue

            for edge in adjacency.get(current.iid, []):
                next_node = self._get_node(edge.nend, sid_conn, star_conn)
                if next_node is None:
                    continue

                edge_dist = great_circle_distance_km(
                    current_node.px, current_node.py,
                    next_node.px, next_node.py,
                )
                # Prefer SID/STAR procedure edges over network shortcuts
                if edge.name in ("SID", "STAR"):
                    edge_dist *= 0.5
                new_dist = current.dist + edge_dist

                if new_dist < dists.get(edge.nend, INF):
                    dists[edge.nend] = new_dist
                    next_search = SearchingNode(
                        iid=edge.nend,
                        name=next_node.name,
                    )
                    next_search.route = (
                        current.route + " " + edge.name + " " + next_node.name
                    )
                    next_search.route_list = list(current.route_list)
                    next_search.route_list.append((edge.name, next_node.name, edge.nend))
                    next_search.dist = new_dist

                    h = heuristic_km(next_node.px, next_node.py, end_lat, end_lon)
                    heapq.heappush(queue, (new_dist + h, counter, next_search))
                    counter += 1

        time_total = time.time() - timestart
        sttime = "%.2f" % time_total

        if target is None:
            return build_route_info(
                self.data_version, sttime,
                "No result.", "0.00 nm / 0.00 km",
                None, {}, {}, [],
            )

        # Post-process: ensure route follows complete procedure paths.
        # A* may skip intermediate procedure nodes when pooled internal_edges
        # contain shortcuts from other procedures (e.g. WAYVE1's EHF->LOPES
        # bypasses KIMMO3's ARVIN/AMONT).  Insert missing nodes so the
        # route reflects the intended procedure topology.
        target.route_list, used_procs = self._fill_procedure_gaps(
            target.route_list, sid_conn, star_conn
        )

        # Recalculate distance after filling procedure gaps.
        dist_km = 0.0
        prev_node = sid_conn.airport_node
        for _, node_name, iid in target.route_list:
            node = self._get_node(iid, sid_conn, star_conn)
            if node is not None:
                dist_km += great_circle_distance_km(
                    prev_node.px, prev_node.py, node.px, node.py
                )
                prev_node = node
        dist_nm = dist_km / 1.852
        dist_str = "%.2f nm / %.2f km" % (dist_nm, dist_km)
        route_total = self._sort_route(orig, target.route_list)
        node_info = self._build_node_info(sid_conn, star_conn, target.route_list)
        route_segments = self._build_route_segments(sid_conn, target.route_list)

        # Detect active transitions from route_list
        active_sid_transition = None
        active_star_transition = None
        route_iids = set(iid for _, _, iid in target.route_list)
        route_node_names = set(node_name for _, node_name, _ in target.route_list)

        for edge in sid_conn.transition_edges:
            if edge.nend in route_iids:
                active_sid_transition = self._find_transition_name(
                    edge, sid_conn, star_conn, is_sid=True,
                    route_node_names=route_node_names,
                )
                if active_sid_transition:
                    break

        for edge in star_conn.transition_edges:
            if edge.nfrom in route_iids:
                active_star_transition = self._find_transition_name(
                    edge, sid_conn, star_conn, is_sid=False,
                    route_node_names=route_node_names,
                )
                if active_star_transition:
                    break

        # Find SID exit node name and STAR entry node name from route.
        # sid_node_name is the procedure key; sid_route_node_name is the
        # actual node in the route that belongs to the procedure (used by
        # the frontend to locate the procedure in the route node list).
        # Prefer the procedure recorded by _fill_procedure_gaps, which knows
        # exactly which procedure the route actually followed.
        sid_node_name = None
        sid_route_node_name = None
        sid_used = used_procs.get("SID")
        if sid_used:
            sid_node_name = sid_used[0]
            # Find the last route node that belongs to this procedure.
            # The frontend excludes nodes *before* sidRouteNodeName, so this
            # must be the boundary between SID and airway (last SID node).
            for _, node_name, _ in reversed(target.route_list):
                if self._node_in_procedure_key(node_name, sid_node_name, sid_conn):
                    sid_route_node_name = node_name
                    break
        else:
            for _, node_name, _ in target.route_list:
                if node_name in sid_conn.procedures:
                    sid_node_name = node_name
                    sid_route_node_name = node_name
                    break
                key = self._find_procedure_key_for_node(node_name, sid_conn)
                if key:
                    sid_node_name = key
                    sid_route_node_name = node_name
                    break

        star_node_name = None
        star_route_node_name = None
        star_used = used_procs.get("STAR")
        if star_used:
            star_node_name = star_used[0]
            # Find the first route node that belongs to this procedure.
            # The frontend excludes nodes *after* starRouteNodeName, so this
            # must be the boundary between airway and STAR (first STAR node).
            for _, node_name, _ in target.route_list:
                if self._node_in_procedure_key(node_name, star_node_name, star_conn):
                    star_route_node_name = node_name
                    break
        else:
            for _, node_name, _ in reversed(target.route_list):
                if node_name in star_conn.procedures:
                    star_node_name = node_name
                    star_route_node_name = node_name
                    break
                key = self._find_procedure_key_for_node(node_name, star_conn)
                if key:
                    star_node_name = key
                    star_route_node_name = node_name
                    break

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

    def _build_adjacency(
        self,
        sid_conn: AirportConnection,
        star_conn: AirportConnection,
    ) -> Dict[int, List[Edge]]:
        """Build adjacency list: shared nodes + temporary airport connections."""
        adj: Dict[int, List[Edge]] = {}
        for node in self.node_list:
            if node is not None:
                adj[node.iid] = list(node.next_list)

        # Add temp nodes
        for node in sid_conn.temp_nodes:
            if node.iid not in adj:
                adj[node.iid] = []
        for node in star_conn.temp_nodes:
            if node.iid not in adj:
                adj[node.iid] = []

        # Add SID edges (airport -> procedure -> network)
        adj[sid_conn.airport_node.iid] = list(sid_conn.connections)
        for edge in sid_conn.internal_edges:
            if edge.nfrom not in adj:
                adj[edge.nfrom] = []
            adj[edge.nfrom].append(edge)
        for edge in sid_conn.transition_edges:
            if edge.nfrom not in adj:
                adj[edge.nfrom] = []
            adj[edge.nfrom].append(edge)
        for edge in sid_conn.bridge_edges:
            if edge.nfrom not in adj:
                adj[edge.nfrom] = []
            adj[edge.nfrom].append(edge)

        # Add STAR edges (network -> procedure -> airport)
        for edge in star_conn.connections:
            if edge.nfrom not in adj:
                adj[edge.nfrom] = []
            adj[edge.nfrom].append(edge)
        for edge in star_conn.internal_edges:
            if edge.nfrom not in adj:
                adj[edge.nfrom] = []
            adj[edge.nfrom].append(edge)
        for edge in star_conn.transition_edges:
            if edge.nfrom not in adj:
                adj[edge.nfrom] = []
            adj[edge.nfrom].append(edge)
        for edge in star_conn.bridge_edges:
            if edge.nfrom not in adj:
                adj[edge.nfrom] = []
            adj[edge.nfrom].append(edge)
        return adj

    def _get_node(
        self,
        iid: int,
        sid_conn: AirportConnection,
        star_conn: AirportConnection,
    ) -> Optional[Node]:
        if iid == sid_conn.airport_node.iid:
            return sid_conn.airport_node
        if iid == star_conn.airport_node.iid:
            return star_conn.airport_node
        if 0 <= iid < self.num_nodes:
            node = self.node_list[iid]
            if node is not None and node.iid == iid:
                return node
        # Check temp nodes
        for node in sid_conn.temp_nodes:
            if node.iid == iid:
                return node
        for node in star_conn.temp_nodes:
            if node.iid == iid:
                return node
        return None

    def _node_in_procedure_key(
        self,
        node_name: str,
        key: str,
        conn: AirportConnection,
    ) -> bool:
        """Return True if node_name appears in any procedure under the given key."""
        for proc in conn.procedures.get(key, []):
            for pt in proc.points:
                if pt[0] == node_name:
                    return True
            for _, t_pts in proc.transitions:
                for pt in t_pts:
                    if pt[0] == node_name:
                        return True
        return False

    def _find_procedure_key_for_node(
        self,
        node_name: str,
        conn: AirportConnection,
    ) -> Optional[str]:
        """Find the procedure key that contains node_name in its points or transitions.

        When A* routes through the interior of a procedure (not its anchor
        point), the node will not match any procedure key directly.  This
        helper walks all procedures to find the key whose points or
        transitions contain the node.
        """
        for key, proc_list in conn.procedures.items():
            for proc in proc_list:
                for pt in proc.points:
                    if pt[0] == node_name:
                        return key
                for _, t_pts in proc.transitions:
                    for pt in t_pts:
                        if pt[0] == node_name:
                            return key
        return None

    def _fill_procedure_gaps(
        self,
        route_list: List[Tuple[str, str, int]],
        sid_conn: AirportConnection,
        star_conn: AirportConnection,
    ) -> Tuple[List[Tuple[str, str, int]], Dict[str, Tuple[str, "Procedure"]]]:
        """Ensure SID/STAR segments follow complete single-procedure paths.

        When pooled internal_edges are shared across all procedures, A* may
        mix segments from different procedures or skip intermediate nodes
        (e.g. KIMMO3's ARVIN and AMONT are bypassed by WAYVE1's EHF->LOPES
        edge, or XACN's XAC->UTIBO is combined with XAC1K's KAIHO->AZURE).

        This post-processor replaces each maximal contiguous run of SID or
        STAR edges with the full path through the single best-matching
        procedure, ensuring the displayed route is a single straight line.
        """

        def _best_proc_for_run(
            node_names: List[str],
            conn: AirportConnection,
            edge_label: str,
        ):
            """Find the best-matching procedure for the run.

            Prefer procedures where the run forms a complete contiguous path
            (starts at first point and ends at last point).  Among incomplete
            matches, prefer the one with the highest score, then the longest
            procedure.
            """
            best_proc = None
            best_key = None
            best_score = 0
            best_is_complete = False

            for key, proc_list in conn.procedures.items():
                for proc in proc_list:
                    proc_names = [p[0] for p in proc.points]
                    score = sum(1 for name in node_names if name in proc_names)
                    if score < 2:
                        continue

                    match_indices = [
                        proc_names.index(name)
                        for name in node_names
                        if name in proc_names
                    ]
                    if len(match_indices) < 2:
                        continue

                    first_idx = min(match_indices)
                    last_idx = max(match_indices)
                    is_complete = (
                        first_idx == 0 and last_idx == len(proc_names) - 1
                    )

                    if is_complete and not best_is_complete:
                        best_proc, best_key, best_score, best_is_complete = (
                            proc, key, score, True
                        )
                    elif is_complete == best_is_complete:
                        if score > best_score:
                            best_proc, best_key, best_score, best_is_complete = (
                                proc, key, score, is_complete
                            )
                        elif (
                            score == best_score
                            and best_proc is not None
                            and len(proc.points) > len(best_proc.points)
                        ):
                            best_proc, best_key, best_score, best_is_complete = (
                                proc, key, score, is_complete
                            )

            return best_proc, best_key, best_score

        used_procs: Dict[str, Tuple[str, Procedure]] = {}

        def _fill_gaps_for_conn(
            route: List[Tuple[str, str, int]],
            conn: AirportConnection,
            edge_label: str,
        ):
            nonlocal used_procs
            result: List[Tuple[str, str, int]] = []
            i = 0
            while i < len(route):
                edge_name, node_name, iid = route[i]

                if edge_name != edge_label:
                    result.append((edge_name, node_name, iid))
                    i += 1
                    continue

                # Collect the entire contiguous run of this edge_label
                run: List[Tuple[str, str, int]] = [
                    (edge_name, node_name, iid)
                ]
                j = i + 1
                while j < len(route) and route[j][0] == edge_label:
                    run.append(route[j])
                    j += 1

                run_node_names = [n[1] for n in run]

                # Also consider the node immediately before the run, as it may
                # be the procedure entry point reached via an airway edge.
                prev_node = route[i - 1] if i > 0 else None
                candidate_names = list(run_node_names)
                if prev_node is not None:
                    candidate_names.insert(0, prev_node[1])

                best_proc, best_key, score = _best_proc_for_run(
                    candidate_names, conn, edge_label
                )

                if best_proc and score >= 2:
                    proc_names = [p[0] for p in best_proc.points]

                    # Find first and last matching node indices in best_proc
                    match_indices = []
                    for name in candidate_names:
                        if name in proc_names:
                            match_indices.append(proc_names.index(name))

                    if len(match_indices) >= 2:
                        first_idx = min(match_indices)
                        last_idx = max(match_indices)

                        # Determine where the procedure path should start/end.
                        # For SID, always extend to the first point (airport side).
                        # For STAR, always extend to the last point (airport side).
                        # This prevents A* from entering/exiting at internal nodes.
                        prev_is_first = (
                            prev_node is not None
                            and prev_node[1] == proc_names[first_idx]
                        )
                        if edge_label == "SID":
                            start_idx = 0
                            end_idx = max(last_idx, len(proc_names) - 1)
                        else:
                            start_idx = first_idx + 1 if prev_is_first else first_idx
                            end_idx = len(proc_names) - 1

                        # Record the procedure actually used for this run so
                        # the caller can report the correct procedure key
                        # instead of guessing via _find_procedure_key_for_node.
                        used_procs[edge_label] = (best_key, best_proc)

                        # Build a lookup for nodes already in the run or prev_node
                        known_iids = {n_name: n_iid for _, n_name, n_iid in run}
                        if prev_node is not None:
                            known_iids[prev_node[1]] = prev_node[2]

                        proc_path: List[Tuple[str, str, int]] = []
                        for k in range(start_idx, end_idx + 1):
                            pt_name = proc_names[k]
                            pt_iid = known_iids.get(pt_name)
                            if pt_iid is None:
                                mid_node = self._get_node_by_name(
                                    pt_name, sid_conn, star_conn
                                )
                                if mid_node is not None:
                                    pt_iid = mid_node.iid
                            if pt_iid is not None:
                                proc_path.append((edge_label, pt_name, pt_iid))

                        # Keep run nodes that are NOT in the procedure but ARE
                        # the airport (e.g. final connection to airport). Drop
                        # all other "alien" nodes from mixed procedures.
                        airport_name = conn.airport_node.name
                        suffix: List[Tuple[str, str, int]] = []
                        for e_name, n_name, n_iid in run:
                            if n_name not in proc_names and n_name == airport_name:
                                suffix.append((e_name, n_name, n_iid))

                        result.extend(proc_path)
                        result.extend(suffix)
                    else:
                        result.extend(run)
                else:
                    result.extend(run)

                i = j

            return result

        route_list = _fill_gaps_for_conn(route_list, sid_conn, "SID")
        route_list = _fill_gaps_for_conn(route_list, star_conn, "STAR")
        return route_list, used_procs

    def _get_node_by_name(
        self,
        name: str,
        sid_conn: AirportConnection,
        star_conn: AirportConnection,
    ) -> Optional[Node]:
        """Find node by name across all known nodes."""
        # Check temp nodes first
        for node in sid_conn.temp_nodes:
            if node.name == name:
                return node
        for node in star_conn.temp_nodes:
            if node.name == name:
                return node
        # Check global node list
        for node in self.node_list:
            if node is not None and node.name == name:
                return node
        return None

    def _find_transition_name(
        self,
        edge: Edge,
        sid_conn: AirportConnection,
        star_conn: AirportConnection,
        is_sid: bool = True,
        route_node_names: Optional[set] = None,
    ) -> Optional[str]:
        """Find transition name from a transition edge by matching endpoint names.

        When route_node_names is provided and multiple transitions share the same
        endpoint, we disambiguate by picking the transition whose procedure's main
        leg points best match the actual route nodes.
        """
        if is_sid:
            end_node = self._get_node(edge.nend, sid_conn, star_conn)
            if not end_node:
                return None
            matches = []
            for proc_list in sid_conn.procedures.values():
                for proc in proc_list:
                    for t_name, t_points in proc.transitions:
                        if t_points and t_points[-1][0] == end_node.name:
                            score = 0
                            if route_node_names:
                                for pt in proc.points:
                                    if pt[0] in route_node_names:
                                        score += 1
                            matches.append((score, t_name))
            if matches:
                matches.sort(key=lambda x: -x[0])
                return matches[0][1]
        else:
            start_node = self._get_node(edge.nfrom, sid_conn, star_conn)
            if not start_node:
                return None
            matches = []
            for proc_list in star_conn.procedures.values():
                for proc in proc_list:
                    for t_name, t_points in proc.transitions:
                        if t_points and t_points[-1][0] == start_node.name:
                            score = 0
                            if route_node_names:
                                for pt in proc.points:
                                    if pt[0] in route_node_names:
                                        score += 1
                            matches.append((score, t_name))
            if matches:
                matches.sort(key=lambda x: -x[0])
                return matches[0][1]
        return None

    def _sort_route(self, orig: str, route_list: List[Tuple[str, str, int]]) -> str:
        """Merge consecutive edges on same airway."""
        stack = []
        for item in route_list:
            if stack and stack[-1][0] == item[0]:
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
