"""Data loading and NavGraph singleton."""

import pickle
from typing import Tuple, Dict, Optional, List

from openRouterFinder.config import settings
from openRouterFinder.core.graph import Node as NewNode, Edge as NewEdge


_nav_graph = None


def _convert_old_nodes(old_nodes):
    """Convert RouteFinderLib pickle objects to new graph objects."""
    new_nodes = []
    for old in old_nodes:
        n = NewNode(iid=old.iid, name=old.name, px=old.px, py=old.py)
        for old_edge in old.nextList:
            e = NewEdge(
                nfrom=old_edge.nfrom,
                nend=old_edge.nend,
                name=old_edge.name,
                color=old_edge.color if hasattr(old_edge, 'color') else (0, 0, 0),
            )
            n.next_list.append(e)
        new_nodes.append(n)
    return new_nodes


class NavGraph:
    """Read-only navigation graph. Singleton, thread-safe."""

    def __init__(self, node_list: List[NewNode], airport_maps: dict, data_version: str):
        # Convert to tuple for immutability
        self.node_list: Tuple[NewNode, ...] = tuple(node_list)
        self.airport_maps = airport_maps
        self.data_version = data_version
        self.num_nodes = len(node_list)

        # Build O(1) node index
        self._node_index: Dict[tuple, NewNode] = {}
        for node in node_list:
            self._node_index[node.node_key()] = node

    def find_node(self, name: str, lat: float, lon: float) -> Optional[NewNode]:
        key = (name, round(lat, 6), round(lon, 6))
        return self._node_index.get(key)

    def find_nodes_by_name(self, name: str) -> List[NewNode]:
        return [n for n in self.node_list if n.name == name]


def load_nav_data() -> NavGraph:
    """Load navigation data. Idempotent."""
    global _nav_graph
    if _nav_graph is not None:
        return _nav_graph

    with open(settings.navdat_full_path, "rb") as f:
        old_nodes = pickle.load(f)

    node_list = _convert_old_nodes(old_nodes)

    with open(settings.apdat_full_path, "rb") as f:
        airport_maps = pickle.load(f)

    # Resolve data version
    version = settings.navdat_cycle
    if version == "AUTO":
        import os
        cycle_path = os.path.join(settings.local_asdata_path, "Cycle.txt")
        if os.path.exists(cycle_path):
            with open(cycle_path, "r") as f:
                version = f.read().strip()
        else:
            version = "UNKNOWN"

    _nav_graph = NavGraph(node_list, airport_maps, version)
    return _nav_graph


def get_nav_graph() -> NavGraph:
    if _nav_graph is None:
        return load_nav_data()
    return _nav_graph


def get_data_version() -> str:
    return get_nav_graph().data_version


def get_airport_maps() -> dict:
    return get_nav_graph().airport_maps


def search_route(orig: str, dest: str) -> Optional[dict]:
    """Thread-safe route search. Each call gets isolated state."""
    from openRouterFinder.core.airport import AirportConnector
    from openRouterFinder.core.dijkstra import RouteEngine

    graph = get_nav_graph()
    orig = orig.upper()
    dest = dest.upper()

    if orig not in graph.airport_maps or dest not in graph.airport_maps:
        return None

    connector = AirportConnector(graph.airport_maps, graph._node_index)

    sid_conn = connector.build_sid(orig)
    star_conn = connector.build_star(dest)

    if sid_conn is None or star_conn is None:
        return None

    engine = RouteEngine(graph.node_list, graph.data_version)
    result_json = engine.search(
        orig, dest, sid_conn, star_conn,
        connector.get_airport_names(orig) + connector.get_airport_names(dest),
    )

    if result_json is None:
        return None

    import json
    return json.loads(result_json)
