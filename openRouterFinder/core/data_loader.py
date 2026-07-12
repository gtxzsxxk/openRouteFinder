"""Data loading and NavGraph singleton."""

import contextlib
import dataclasses
import threading
from collections import OrderedDict
from threading import Lock

from openRouterFinder.config import settings
from openRouterFinder.core.airport import AirportConnection
from openRouterFinder.core.graph import Node as NewNode

_nav_registry = None
_registry_lock = threading.Lock()


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


def _init_registry():
    """Initialize NavDataRegistry from data directory. Thread-safe."""
    global _nav_registry
    if _nav_registry is not None:
        return _nav_registry
    with _registry_lock:
        if _nav_registry is not None:
            return _nav_registry
        from openRouterFinder.core.storage.registry import NavDataRegistry

        data_dir = settings.navdata_dir_path
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


_LIGHTING_MAP = {
    "0": "none",
    "1": "simple",
    "2": "medium",
    "3": "high",
    "4": "other",
}


def _parse_lighting(code: str) -> str:
    return _LIGHTING_MAP.get(code, code)


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


_MISSING = object()


class _LRUCache:
    """Thread-safe LRU cache with explicit maxsize.

    Uses an OrderedDict so long-running processes do not grow without bound.
    Size is controlled via ``settings.airport_connection_cache_size``.
    """

    def __init__(self, lock: Lock):
        self._lock = lock
        self._data: OrderedDict = OrderedDict()

    def get(self, key):
        with self._lock:
            value = self._data.get(key, _MISSING)
            if value is _MISSING:
                return _MISSING
            self._data.move_to_end(key)
            return value

    def set(self, key, value) -> None:
        with self._lock:
            self._data[key] = value
            self._data.move_to_end(key)
            max_size = settings.airport_connection_cache_size
            while len(self._data) > max_size:
                self._data.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


_cache_lock = Lock()
_sid_cache = _LRUCache(_cache_lock)
_star_cache = _LRUCache(_cache_lock)


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
        resolved_cycle = nav.cycle
        if nav.get_airport(orig) is None or nav.get_airport(dest) is None:
            return None

        # Use cached AirportConnection when available to avoid rebuilding
        # procedures on every request.  Resolve cycle=None to the concrete
        # latest cycle so a later hot-load does not hit stale cache entries.
        sid_conn = _get_airport_connection(nav, orig, 1, resolved_cycle)
        if sid_conn is not None:
            # Each request must have isolated temp_nodes so that post-A* point
            # insertion does not pollute the shared cache.
            sid_conn = dataclasses.replace(sid_conn, temp_nodes=[])

        star_conn = _get_airport_connection(nav, dest, 2, resolved_cycle)
        if star_conn is not None:
            star_conn = dataclasses.replace(star_conn, temp_nodes=[])

        if sid_conn is None or star_conn is None:
            return None
        if not sid_conn.connections or not star_conn.connections:
            return None

        connector = FlatbuffersAirportConnector(nav)
        engine = RouteEngine(
            nav.node_list,
            nav.cycle,
            node_index=nav.node_index,
            cache=nav._cache,
        )
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
    route endpoints do not rebuild procedures on every request.  A ``cycle`` of
    ``None``/"" is resolved to the concrete cycle identifier of ``nav`` so cache
    keys remain stable across hot reloads.  The caches are LRU-bounded to
    ``settings.airport_connection_cache_size`` entries per type.
    """
    from openRouterFinder.core.airport import FlatbuffersAirportConnector

    resolved_cycle = cycle or nav.cycle
    cache = _sid_cache if proc_type == 1 else _star_cache
    key = (resolved_cycle, icao)
    conn = cache.get(key)
    if conn is not _MISSING:
        return conn

    connector = FlatbuffersAirportConnector(nav)
    conn = connector.build_sid(icao) if proc_type == 1 else connector.build_star(icao)

    if conn is not None:
        cache.set(key, conn)
    return conn


def get_sid_connection(nav, icao: str, cycle: str | None = None) -> "AirportConnection | None":
    """Cached SID connection for an airport."""
    return _get_airport_connection(nav, icao, 1, cycle)


def get_star_connection(nav, icao: str, cycle: str | None = None) -> "AirportConnection | None":
    """Cached STAR connection for an airport."""
    return _get_airport_connection(nav, icao, 2, cycle)


def clear_airport_connection_caches() -> None:
    """Clear module-level SID/STAR connection caches.

    Called after navdata cycles are deleted or uploaded so cached
    AirportConnection objects (which reference node IIDs/mmaps) are not
    reused across different navdata versions.
    """
    _sid_cache.clear()
    _star_cache.clear()


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
