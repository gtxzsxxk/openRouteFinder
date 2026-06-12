"""Data loading and NavGraph singleton."""

import contextlib
import dataclasses
import pickle
import sys
from threading import Lock

from openRouterFinder.config import settings
from openRouterFinder.core.graph import Edge as NewEdge
from openRouterFinder.core.graph import Node as NewNode

# Register pickle compatibility module so old .map files load correctly
if "RouteFinderLib" not in sys.modules:
    from openRouterFinder.core import _compat

    sys.modules["RouteFinderLib"] = _compat


_nav_graph = None
_nav_registry = None


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
                color=old_edge.color if hasattr(old_edge, "color") else (0, 0, 0),
            )
            n.next_list.append(e)
        new_nodes.append(n)
    return new_nodes


class NavGraph:
    """Read-only navigation graph. Singleton, thread-safe."""

    def __init__(self, node_list: list[NewNode], airport_maps: dict, data_version: str):
        # Fix duplicate iids in raw nav data: assign list index to duplicates
        # so node_list[iid] is always the correct node.
        iid_remap: dict[int, int] = {}
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
        self.node_list: tuple[NewNode, ...] = tuple(node_list)
        self.airport_maps = airport_maps
        self.data_version = data_version
        self.num_nodes = len(node_list)

        # Build O(1) node index
        self._node_index: dict[tuple, NewNode] = {}
        for node in node_list:
            self._node_index[node.node_key()] = node

    def find_node(self, name: str, lat: float, lon: float) -> NewNode | None:
        key = (name, round(lat, 6), round(lon, 6))
        return self._node_index.get(key)

    def find_nodes_by_name(self, name: str) -> list[NewNode]:
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
            with open(cycle_path) as f:
                version = f.read().strip()
        else:
            version = "UNKNOWN"

    _nav_graph = NavGraph(node_list, airport_maps, version)
    return _nav_graph


def get_nav_graph() -> NavGraph:
    if _nav_graph is None:
        return load_nav_data()
    return _nav_graph


def _init_registry():
    """Initialize NavDataRegistry from data directory."""
    global _nav_registry
    if _nav_registry is not None:
        return _nav_registry
    from openRouterFinder.core.storage.registry import NavDataRegistry

    data_dir = settings.navdat_full_path.parent
    _nav_registry = NavDataRegistry(data_dir)
    return _nav_registry


def get_nav_registry():
    """Get the NavDataRegistry (initializes on first call)."""
    return _init_registry()


def has_registry() -> bool:
    """Check if NavDataRegistry has any loaded cycles."""
    reg = _init_registry()
    return len(reg) > 0


def get_nav_data(cycle: str | None = None):
    """Get a reference-counted MmappedNavData handle for a specific cycle.

    Returns None if registry is empty.  The caller should use the returned
    object as a context manager, or call .release() when finished, to avoid
    keeping the underlying mmap open longer than necessary.
    """
    reg = _init_registry()
    return reg.get(cycle)


def get_data_version() -> str:
    reg = _init_registry()
    latest = reg.get()
    if latest is None:
        return ""
    with latest:
        return latest.cycle


def get_airport_maps() -> dict:
    return {}


def _opposite_runway(name: str) -> str:
    """Get the opposite runway designator (e.g., 18L -> 36R)."""
    digits = []
    suffix = []
    for c in name:
        if c.isdigit():
            digits.append(c)
        else:
            suffix.append(c)
    num = int("".join(digits)) if digits else 0
    opp_num = num + 18 if num <= 18 else num - 18
    suffix_map = {"L": "R", "R": "L", "C": "C"}
    opp_suffix = suffix_map.get("".join(suffix), "")
    return f"{opp_num:02d}{opp_suffix}"


_LIGHTING_MAP = {
    "0": "none",
    "1": "simple",
    "2": "medium",
    "3": "high",
    "4": "other",
}


def _parse_lighting(code: str) -> str:
    return _LIGHTING_MAP.get(code, code)


def _parse_runways(airport_str: str) -> list:
    """Parse runway data from raw airport string."""
    runways = {}
    lines = airport_str.strip().split("\n")
    for line in lines:
        parts = line.strip().split(",")
        if len(parts) < 10 or parts[0] != "R":
            continue
        name = parts[1].strip()
        try:
            heading = float(parts[2].strip())
            length = float(parts[3].strip())
            width = float(parts[4].strip())
            lat = float(parts[8].strip())
            lon = float(parts[9].strip())
            elevation = int(float(parts[10].strip())) if len(parts) > 10 else None
            raw_lighting = parts[12].strip() if len(parts) > 12 else ""
            lighting = _parse_lighting(raw_lighting) if raw_lighting in _LIGHTING_MAP else ""
        except (ValueError, IndexError):
            continue

        # Parse ILS info
        ils = []
        if len(parts) > 7 and parts[5].strip() not in ("", "0"):
            with contextlib.suppress(ValueError):
                ils.append(
                    {
                        "runwayEnd": name,
                        "frequency": parts[6].strip(),
                        "heading": float(parts[7].strip()),
                        "category": "I",
                    }
                )

        runways[name] = {
            "name": name,
            "heading": heading,
            "length": length,
            "width": width,
            "lat": lat,
            "lon": lon,
            "elevation": elevation,
            "lighting": lighting,
            "ils": ils,
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
            result.append(
                {
                    "name": f"{name}/{opp_name}",
                    "thresholds": [
                        {
                            "name": name,
                            "lat": rwy["lat"],
                            "lon": rwy["lon"],
                            "heading": rwy["heading"],
                            "elevationFt": rwy["elevation"],
                        },
                        {
                            "name": opp_name,
                            "lat": opp["lat"],
                            "lon": opp["lon"],
                            "heading": opp["heading"],
                            "elevationFt": opp["elevation"],
                        },
                    ],
                    "lengthFt": rwy["length"],
                    "widthFt": rwy["width"],
                    "lighting": rwy.get("lighting", ""),
                    "ils": rwy.get("ils", []) + opp.get("ils", []),
                }
            )
        else:
            result.append(
                {
                    "name": name,
                    "thresholds": [
                        {
                            "name": name,
                            "lat": rwy["lat"],
                            "lon": rwy["lon"],
                            "heading": rwy["heading"],
                            "elevationFt": rwy["elevation"],
                        }
                    ],
                    "lengthFt": rwy["length"],
                    "widthFt": rwy["width"],
                    "lighting": rwy.get("lighting", ""),
                    "ils": rwy.get("ils", []),
                }
            )
    return result


def _parse_airport_detail(icao: str) -> dict | None:
    """Extract full airport details from raw airport data."""
    graph = get_nav_graph()
    icao = icao.upper()
    if icao not in graph.airport_maps:
        return None

    name = None
    lat = lon = None
    elevation = transition_alt = transition_level = None
    for line in graph.airport_maps[icao].strip().split("\n"):
        if not line.startswith("A,"):
            continue
        parts = line.split(",")
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
        "icao": icao,
        "name": name or icao,
        "lat": lat,
        "lon": lon,
        "elevation": elevation,
        "transitionAltitude": transition_alt,
        "transitionLevel": transition_level,
        "runways": runways,
    }


def _get_airport_detail_from_fb(nav, icao: str) -> dict | None:
    """Build airport detail dict from FlatBuffers airport data."""
    ap = nav.get_airport(icao.upper())
    if ap is None:
        return None

    name = ap.Name()
    name = name.decode("utf-8") if isinstance(name, bytes) else (name or icao)

    return {
        "icao": icao.upper(),
        "name": name,
        "lat": float(ap.Lat()),
        "lon": float(ap.Lon()),
        "elevation": int(ap.Elevation()),
        "transitionAltitude": int(ap.TransitionAltitude()),
        "transitionLevel": int(ap.TransitionLevel()),
        "runways": _parse_runways_from_fb(ap),
    }


# Module-level caches for airport connections. AirportConnection objects are
# read-only after construction, so they are safe to share across requests.
_sid_cache: dict = {}
_star_cache: dict = {}
_cache_lock = Lock()


def search_route(
    orig: str,
    dest: str,
    sid_exit: str | None = None,
    star_entry: str | None = None,
    cycle: str | None = None,
) -> dict | None:
    """Thread-safe route search. Each call gets isolated state."""
    from openRouterFinder.core.airport import FlatbuffersAirportConnector
    from openRouterFinder.core.dijkstra import RouteEngine

    orig = orig.upper()
    dest = dest.upper()

    nav = get_nav_data(cycle)
    if nav is None:
        return None

    with nav:
        if nav.get_airport(orig) is None or nav.get_airport(dest) is None:
            return None

        # Use cached AirportConnection when available to avoid rebuilding
        # procedures on every request.
        connector = FlatbuffersAirportConnector(nav)

        # Build unfiltered connections so the engine can fall back to auto-selected
        # procedures when a filtered entry is unreachable via the airway graph.
        sid_key = (cycle, orig)
        with _cache_lock:
            sid_conn = _sid_cache.get(sid_key)
        if sid_conn is None:
            sid_conn = connector.build_sid(orig, filter_name=None)
            with _cache_lock:
                _sid_cache[sid_key] = sid_conn
        else:
            # Each request must have isolated temp_nodes so that post-A* point
            # insertion does not pollute the shared cache.
            sid_conn = dataclasses.replace(sid_conn, temp_nodes=[])

        star_key = (cycle, dest)
        with _cache_lock:
            star_conn = _star_cache.get(star_key)
        if star_conn is None:
            star_conn = connector.build_star(dest, filter_name=None)
            with _cache_lock:
                _star_cache[star_key] = star_conn
        else:
            star_conn = dataclasses.replace(star_conn, temp_nodes=[])

        if sid_conn is None or star_conn is None:
            return None
        if not sid_conn.connections or not star_conn.connections:
            return None

        engine = RouteEngine(nav.node_list, nav.cycle, node_index=nav.node_index)
        result_json = engine.search(
            orig,
            dest,
            sid_conn,
            star_conn,
            connector.get_airport_names(orig) + connector.get_airport_names(dest),
            sid_exit=sid_exit,
            star_entry=star_entry,
        )

        if result_json is None:
            return None

        import json

        result = json.loads(result_json)

        if isinstance(result, dict):
            result["origAirportDetail"] = _get_airport_detail_from_fb(nav, orig)
            result["destAirportDetail"] = _get_airport_detail_from_fb(nav, dest)
            orig_ap = nav.get_airport(orig)
            dest_ap = nav.get_airport(dest)
            result["origRunways"] = _parse_runways_from_fb(orig_ap) if orig_ap else []
            result["destRunways"] = _parse_runways_from_fb(dest_ap) if dest_ap else []

        return result


def _get_airport_connection(
    nav,
    icao: str,
    proc_type: int,
    cycle: str | None,
) -> "AirportConnection | None":
    """Return a cached or freshly-built airport connection for the given proc type.

    proc_type: 1 for SID, 2 for STAR.  Reuses the module-level caches so API and
    route endpoints do not rebuild procedures on every request.
    """
    from openRouterFinder.core.airport import FlatbuffersAirportConnector

    cache = _sid_cache if proc_type == 1 else _star_cache
    key = (cycle, icao)
    with _cache_lock:
        conn = cache.get(key)
    if conn is None:
        connector = FlatbuffersAirportConnector(nav)
        conn = connector.build_sid(icao) if proc_type == 1 else connector.build_star(icao)
        with _cache_lock:
            cache[key] = conn
    return conn


def get_sid_connection(nav, icao: str, cycle: str | None = None) -> "AirportConnection | None":
    """Cached SID connection for an airport."""
    return _get_airport_connection(nav, icao, 1, cycle)


def get_star_connection(nav, icao: str, cycle: str | None = None) -> "AirportConnection | None":
    """Cached STAR connection for an airport."""
    return _get_airport_connection(nav, icao, 2, cycle)


def _parse_runways_from_fb(ap) -> list:
    """Parse runway data from FlatBuffers Airport object."""
    if ap is None:
        return []
    result = []
    for i in range(ap.RunwaysLength()):
        rw = ap.Runways(i)
        name_bytes = rw.Name()
        name = name_bytes.decode("utf-8") if isinstance(name_bytes, bytes) else (name_bytes or "")

        thresholds = []
        for j in range(rw.EndsLength()):
            end = rw.Ends(j)
            end_name_bytes = end.Name()
            end_name = (
                end_name_bytes.decode("utf-8")
                if isinstance(end_name_bytes, bytes)
                else (end_name_bytes or "")
            )
            try:
                thresholds.append(
                    {
                        "name": end_name,
                        "lat": float(end.Lat()),
                        "lon": float(end.Lon()),
                        "heading": float(end.Heading()),
                        "elevationFt": int(end.ElevationFt()),
                    }
                )
            except (ValueError, TypeError):
                continue

        ils_list = []
        for j in range(rw.IlsLength()):
            ils = rw.Ils(j)
            ident_bytes = ils.Ident()
            ident = (
                ident_bytes.decode("utf-8")
                if isinstance(ident_bytes, bytes)
                else (ident_bytes or "")
            )
            freq_bytes = ils.Frequency()
            freq = (
                freq_bytes.decode("utf-8") if isinstance(freq_bytes, bytes) else (freq_bytes or "")
            )
            cat_bytes = ils.Category()
            cat = cat_bytes.decode("utf-8") if isinstance(cat_bytes, bytes) else (cat_bytes or "")
            rw_end_bytes = ils.RunwayEnd()
            rw_end = (
                rw_end_bytes.decode("utf-8")
                if isinstance(rw_end_bytes, bytes)
                else (rw_end_bytes or "")
            )
            try:
                ils_list.append(
                    {
                        "runwayEnd": rw_end,
                        "ident": ident,
                        "frequency": freq,
                        "heading": float(ils.Heading()),
                        "category": cat,
                    }
                )
            except (ValueError, TypeError):
                continue

        lighting = ""
        with contextlib.suppress(ValueError, TypeError):
            lighting = _parse_lighting(str(rw.Lighting())) if rw.Lighting() else ""

        result.append(
            {
                "name": name,
                "thresholds": thresholds,
                "lengthFt": float(rw.LengthFt()) if rw.LengthFt() else 0.0,
                "widthFt": float(rw.WidthFt()) if rw.WidthFt() else 0.0,
                "lighting": lighting,
                "ils": ils_list,
            }
        )
    return result
