"""Data loading and NavGraph singleton."""

import pickle
import sys
from typing import Tuple, Dict, Optional, List

from openRouterFinder.config import settings
from openRouterFinder.core.graph import Node as NewNode, Edge as NewEdge

# Register pickle compatibility module so old .map files load correctly
if "RouteFinderLib" not in sys.modules:
    from openRouterFinder.core import _compat
    sys.modules["RouteFinderLib"] = _compat


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
        # Fix duplicate iids in raw nav data: assign list index to duplicates
        # so node_list[iid] is always the correct node.
        iid_remap: Dict[int, int] = {}
        seen_iids: set[int] = set()
        for i, node in enumerate(node_list):
            if node.iid in seen_iids:
                iid_remap[node.iid] = i
                node.iid = i
            else:
                seen_iids.add(node.iid)

        # Update edge references to new iids
        for node in node_list:
            for edge in node.next_list:
                edge.nfrom = iid_remap.get(edge.nfrom, edge.nfrom)
                edge.nend = iid_remap.get(edge.nend, edge.nend)

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


def _opposite_runway(name: str) -> str:
    """Get the opposite runway designator (e.g., 18L -> 36R)."""
    digits = []
    suffix = []
    for c in name:
        if c.isdigit():
            digits.append(c)
        else:
            suffix.append(c)
    num = int(''.join(digits)) if digits else 0
    opp_num = num + 18 if num <= 18 else num - 18
    suffix_map = {'L': 'R', 'R': 'L', 'C': 'C'}
    opp_suffix = suffix_map.get(''.join(suffix), '')
    return f"{opp_num:02d}{opp_suffix}"


_LIGHTING_MAP = {
    '0': 'none',
    '1': 'simple',
    '2': 'medium',
    '3': 'high',
    '4': 'other',
}


def _parse_lighting(code: str) -> str:
    return _LIGHTING_MAP.get(code, code)


def _parse_runways(airport_str: str) -> list:
    """Parse runway data from raw airport string."""
    runways = {}
    lines = airport_str.strip().split('\n')
    for line in lines:
        parts = line.strip().split(',')
        if len(parts) < 10 or parts[0] != 'R':
            continue
        name = parts[1].strip()
        try:
            heading = float(parts[2].strip())
            length = float(parts[3].strip())
            width = float(parts[4].strip())
            lat = float(parts[8].strip())
            lon = float(parts[9].strip())
            elevation = int(float(parts[10].strip())) if len(parts) > 10 else None
            raw_lighting = parts[12].strip() if len(parts) > 12 else ''
            lighting = _parse_lighting(raw_lighting) if raw_lighting in _LIGHTING_MAP else ''
        except (ValueError, IndexError):
            continue

        # Parse ILS info
        ils = []
        if len(parts) > 7 and parts[5].strip() not in ('', '0'):
            try:
                ils.append({
                    'runwayEnd': name,
                    'frequency': parts[6].strip(),
                    'heading': float(parts[7].strip()),
                    'category': 'I',
                })
            except ValueError:
                pass

        runways[name] = {
            'name': name,
            'heading': heading,
            'length': length,
            'width': width,
            'lat': lat,
            'lon': lon,
            'elevation': elevation,
            'lighting': lighting,
            'ils': ils,
        }

    result = []
    paired = set()
    for name, rwy in runways.items():
        if name in paired:
            continue
        opp_name = _opposite_runway(name)
        if opp_name in runways and opp_name not in paired:
            paired.add(name)
            paired.add(opp_name)
            opp = runways[opp_name]
            result.append({
                'name': f"{name}/{opp_name}",
                'thresholds': [
                    {'name': name, 'lat': rwy['lat'], 'lon': rwy['lon'], 'heading': rwy['heading'], 'elevationFt': rwy['elevation']},
                    {'name': opp_name, 'lat': opp['lat'], 'lon': opp['lon'], 'heading': opp['heading'], 'elevationFt': opp['elevation']},
                ],
                'lengthFt': rwy['length'],
                'widthFt': rwy['width'],
                'lighting': rwy.get('lighting', ''),
                'ils': rwy.get('ils', []) + opp.get('ils', []),
            })
        else:
            result.append({
                'name': name,
                'thresholds': [{'name': name, 'lat': rwy['lat'], 'lon': rwy['lon'], 'heading': rwy['heading'], 'elevationFt': rwy['elevation']}],
                'lengthFt': rwy['length'],
                'widthFt': rwy['width'],
                'lighting': rwy.get('lighting', ''),
                'ils': rwy.get('ils', []),
            })
    return result


def _parse_airport_detail(icao: str) -> Optional[dict]:
    """Extract full airport details from raw airport data."""
    graph = get_nav_graph()
    icao = icao.upper()
    if icao not in graph.airport_maps:
        return None

    name = None
    lat = lon = None
    elevation = transition_alt = transition_level = None
    for line in graph.airport_maps[icao].strip().split('\n'):
        if not line.startswith('A,'):
            continue
        parts = line.split(',')
        if len(parts) >= 5:
            name = parts[2].strip()
            try:
                lat = float(parts[3].strip())
                lon = float(parts[4].strip())
            except ValueError:
                pass
        if len(parts) >= 10:
            try:
                elevation = int(float(parts[5].strip()))
                transition_alt = int(float(parts[6].strip()))
                transition_level = int(float(parts[7].strip()))
            except ValueError:
                pass
        break

    runways = _parse_runways(graph.airport_maps[icao])

    return {
        'icao': icao,
        'name': name or icao,
        'lat': lat,
        'lon': lon,
        'elevation': elevation,
        'transitionAltitude': transition_alt,
        'transitionLevel': transition_level,
        'runways': runways,
    }


def search_route(orig: str, dest: str, sid_exit: Optional[str] = None, star_entry: Optional[str] = None) -> Optional[dict]:
    """Thread-safe route search. Each call gets isolated state."""
    from openRouterFinder.core.airport import AirportConnector
    from openRouterFinder.core.dijkstra import RouteEngine

    graph = get_nav_graph()
    orig = orig.upper()
    dest = dest.upper()

    if orig not in graph.airport_maps or dest not in graph.airport_maps:
        return None

    connector = AirportConnector(graph.airport_maps, graph._node_index)

    sid_conn = connector.build_sid(orig, filter_name=sid_exit)
    star_conn = connector.build_star(dest, filter_name=star_entry)

    if sid_conn is None or star_conn is None:
        return None
    if not sid_conn.connections or not star_conn.connections:
        return None

    engine = RouteEngine(graph.node_list, graph.data_version)
    result_json = engine.search(
        orig, dest, sid_conn, star_conn,
        connector.get_airport_names(orig) + connector.get_airport_names(dest),
        sid_exit=sid_exit,
        star_entry=star_entry,
    )

    if result_json is None:
        return None

    import json
    result = json.loads(result_json)

    # Enrich with runway and airport detail data
    if isinstance(result, dict):
        result['origRunways'] = _parse_runways(graph.airport_maps[orig])
        result['destRunways'] = _parse_runways(graph.airport_maps[dest])
        result['origAirportDetail'] = _parse_airport_detail(orig)
        result['destAirportDetail'] = _parse_airport_detail(dest)

    return result
