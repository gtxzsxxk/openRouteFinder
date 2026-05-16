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
from openRouterFinder.core.airport import AirportConnection


def _procs_to_dict(procs: dict) -> dict:
    """Convert Procedure objects to JSON-serializable dicts."""
    result = {}
    for key, proc_list in procs.items():
        result[key] = [
            {"name": p.name, "runway": p.runway, "points": p.points}
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
) -> str:
    return json.dumps({
        "data_version": data_version,
        "total_time": total_time,
        "route": route,
        "distance": dist,
        "nodeinformation": node_info,
        "SID": _procs_to_dict(sid),
        "STAR": _procs_to_dict(star),
        "airportName": airport_name,
    })


class RouteEngine:
    """Per-request route calculator. Thread-safe: no shared mutable state."""

    def __init__(
        self,
        node_list: Tuple[Node, ...],
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
    ) -> Optional[str]:
        """Run A* search. Returns JSON string or None."""
        timestart = time.time()

        # Build adjacency map for this search (shared edges + temporary airport edges)
        adjacency = self._build_adjacency(sid_conn, star_conn)

        # A* search
        start_iid = sid_conn.airport_node.iid
        end_iid = star_conn.airport_node.iid

        # Distances array
        INF = float('inf')
        dists = [INF] * (self.num_nodes + 2)  # +2 for temp airport nodes
        dists[start_iid] = 0.0

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
            if current.dist > dists[current.iid]:
                continue

            for edge in adjacency.get(current.iid, []):
                next_node = self._get_node(edge.nend, sid_conn, star_conn)
                if next_node is None:
                    continue

                edge_dist = great_circle_distance_km(
                    current_node.px, current_node.py,
                    next_node.px, next_node.py,
                )
                new_dist = current.dist + edge_dist

                if new_dist < dists[edge.nend]:
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
                None, None, None, None,
            )

        dist_km = target.dist
        dist_nm = dist_km / 1.852
        dist_str = "%.2f nm / %.2f km" % (dist_nm, dist_km)
        route_total = self._sort_route(orig, target.route_list)
        node_info = self._build_node_info(sid_conn, star_conn, target.route_list)

        return build_route_info(
            self.data_version,
            sttime,
            route_total,
            dist_str,
            node_info,
            sid_conn.procedures,
            star_conn.procedures,
            airport_names,
        )

    def _build_adjacency(
        self,
        sid_conn: AirportConnection,
        star_conn: AirportConnection,
    ) -> Dict[int, List[Edge]]:
        """Build adjacency list: shared nodes + temporary airport connections."""
        adj = {}
        for node in self.node_list:
            adj[node.iid] = list(node.next_list)
        # Add SID edges (airport -> network)
        adj[sid_conn.airport_node.iid] = list(sid_conn.connections)
        # Add STAR edges (network -> airport)
        for edge in star_conn.connections:
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
            return self.node_list[iid]
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
