"""Airport SID/STAR parsing and temporary connector generation."""

import heapq
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field

from openRouterFinder.core.graph import Edge, Node, _haversine_a, great_circle_distance_km

_RUNWAY_ENDPOINT_RE = re.compile(r"^DER\d{2}[LCR]?$|^DE\d{2}[LCR]?$")


@dataclass
class Procedure:
    """SID or STAR procedure definition."""

    name: str
    runway: str
    points: list[tuple[str, float, float]]  # (name, lat, lon)
    transitions: list[tuple[str, list[tuple[str, float, float]]]] = field(default_factory=list)


@dataclass
class AirportConnection:
    """Temporary airport connection for a single search."""

    airport_node: Node
    connections: list[Edge]  # edges FROM airport TO network (SID) or FROM network TO airport (STAR)
    procedures: dict[str, list[Procedure]]  # anchor_point -> [Procedure, ...]
    transition_edges: list[Edge] = field(default_factory=list)
    temp_nodes: list[Node] = field(
        default_factory=list
    )  # temp nodes for waypoints not in nav network
    internal_edges: list[Edge] = field(default_factory=list)  # edges within procedures
    bridge_edges: list[Edge] = field(
        default_factory=list
    )  # bridge edges from isolated nodes to network


class _ConnectedNodeIndex:
    """Spatial index over airway-connected nodes for fast nearest-neighbor lookup.

    Fenix navdata contains ~320k nodes but only about half have outgoing edges.
    Boundary-bridge queries repeatedly need the nearest connected node; scanning
    the full list for each boundary node dominates build time for large airports.
    A 1-degree lat/lon grid plus best-first expansion reduces each lookup to a
    small number of cells.
    """

    def __init__(self, node_list, cell_deg: float = 1.0):
        self._cell_deg = cell_deg
        self._cells: dict[tuple[int, int], list[Node]] = {}
        self.nodes_with_inbound: set = set()
        for node in node_list:
            if node is None:
                continue
            if node.next_list:
                key = (int(math.floor(node.px / cell_deg)), int(math.floor(node.py / cell_deg)))
                self._cells.setdefault(key, []).append(node)
            for e in node.next_list:
                self.nodes_with_inbound.add(e.nend)

    @staticmethod
    def _nearest_point_in_cell(lat: float, lon: float, cx: int, cy: int, cell_deg: float):
        lat0 = cx * cell_deg
        lat1 = (cx + 1) * cell_deg
        lon0 = cy * cell_deg
        lon1 = (cy + 1) * cell_deg
        return max(lat0, min(lat, lat1)), max(lon0, min(lon, lon1))

    def find_nearest(
        self,
        lat: float,
        lon: float,
        exclude_iid: int | None = None,
        exclude_iids: set | None = None,
        valid_iids: set | None = None,
    ) -> Node | None:
        cx = int(math.floor(lat / self._cell_deg))
        cy = int(math.floor(lon / self._cell_deg))
        heap = [(0.0, 0, cx, cy)]
        visited: set[tuple[int, int]] = set()
        best: Node | None = None
        best_a = float("inf")

        while heap:
            cell_a, _, x, y = heapq.heappop(heap)
            if cell_a >= best_a:
                break
            if (x, y) in visited:
                continue
            visited.add((x, y))

            cell = self._cells.get((x, y))
            if cell:
                for node in cell:
                    if exclude_iid is not None and node.iid == exclude_iid:
                        continue
                    if exclude_iids is not None and node.iid in exclude_iids:
                        continue
                    if valid_iids is not None and node.iid not in valid_iids:
                        continue
                    a = _haversine_a(lat, lon, node.px, node.py)
                    if a < best_a:
                        best_a = a
                        best = node

            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = x + dx, y + dy
                if (nx, ny) in visited:
                    continue
                nlat, nlon = self._nearest_point_in_cell(lat, lon, nx, ny, self._cell_deg)
                heapq.heappush(heap, (_haversine_a(lat, lon, nlat, nlon), abs(nx - cx) + abs(ny - cy), nx, ny))

        return best


class FlatbuffersAirportConnector:
    """Builds temporary airport connections from structured FlatBuffers navdata."""

    def __init__(self, nav_data):
        self.nav_data = nav_data
        self._temp_nodes: dict[str, Node] = {}
        self._next_temp_iid = -3
        cache = getattr(nav_data, "_cache", None)
        if cache is None:
            self._connected_index = _ConnectedNodeIndex(nav_data.node_list)
        else:
            key = "_connected_index"
            if key not in cache:
                cache[key] = _ConnectedNodeIndex(nav_data.node_list)
            self._connected_index = cache[key]

    def _find_node(self, name: str, lat: float, lon: float) -> Node | None:
        return self.nav_data.find_node(name, lat, lon)

    def _get_or_create_temp(self, name: str, lat: float, lon: float) -> Node:
        if name not in self._temp_nodes:
            self._temp_nodes[name] = Node(
                iid=self._next_temp_iid,
                name=name,
                px=lat,
                py=lon,
            )
            self._next_temp_iid -= 1
        return self._temp_nodes[name]

    def _find_nearest_connected_node(
        self,
        lat: float,
        lon: float,
        exclude_iid: int | None = None,
        exclude_iids: set | None = None,
        valid_iids: set | None = None,
    ) -> Node | None:
        """Find the nearest navdata node that has at least one outgoing edge."""
        return self._connected_index.find_nearest(
            lat,
            lon,
            exclude_iid=exclude_iid,
            exclude_iids=exclude_iids,
            valid_iids=valid_iids,
        )

    def _ensure_continuous_paths(self, conn: AirportConnection, label: str):
        """Add missing internal_edges so every consecutive pair in procedure.

        points and transitions is connected.
        """
        existing = {(e.nfrom, e.nend) for e in conn.internal_edges}
        for _key, proc_list in conn.procedures.items():
            for proc in proc_list:
                # Main procedure points
                pts = proc.points
                for i in range(len(pts) - 1):
                    from_node = self._resolve_node(pts[i][0], pts[i][1], pts[i][2])
                    to_node = self._resolve_node(pts[i + 1][0], pts[i + 1][1], pts[i + 1][2])
                    if (from_node.iid, to_node.iid) not in existing:
                        conn.internal_edges.append(
                            Edge(nfrom=from_node.iid, nend=to_node.iid, name=label)
                        )
                        existing.add((from_node.iid, to_node.iid))
                # Transition points
                for _t_name, t_pts in proc.transitions:
                    for i in range(len(t_pts) - 1):
                        from_node = self._resolve_node(t_pts[i][0], t_pts[i][1], t_pts[i][2])
                        to_node = self._resolve_node(
                            t_pts[i + 1][0], t_pts[i + 1][1], t_pts[i + 1][2]
                        )
                        if (from_node.iid, to_node.iid) not in existing:
                            conn.internal_edges.append(
                                Edge(nfrom=from_node.iid, nend=to_node.iid, name=label)
                            )
                            existing.add((from_node.iid, to_node.iid))

    def _node_by_iid(self, iid: int, conn: AirportConnection) -> Node | None:
        """Look up a node by IID in the network or temp nodes."""
        if conn.airport_node.iid == iid:
            return conn.airport_node
        if 0 <= iid < len(self.nav_data.node_list):
            node = self.nav_data.node_list[iid]
            if node is not None and node.iid == iid:
                return node
        for node in conn.temp_nodes:
            if node.iid == iid:
                return node
        return None

    def _add_boundary_bridges(self, conn: AirportConnection, proc_type: int):
        """Add bridge edges for isolated boundary nodes (SID exits / STAR entries).

        Some procedure boundary waypoints exist in the navdata but have no
        airway connections.  Without a bridge, A* cannot leave (SID) or reach
        (STAR) these nodes.  This method only checks boundary nodes—not every
        internal procedure point—so it is fast and general.

        Bridge targets exclude ALL nodes that appear in any procedure for this
        airport to prevent backward shortcuts (e.g. SAUGS → WAYVE when the
        procedure order is WAYVE → SAUGS).
        """
        nodes_with_inbound = self._connected_index.nodes_with_inbound

        # Collect every node IID that appears in any procedure for this airport
        proc_node_iids: set = set()
        for _key, proc_list in conn.procedures.items():
            for proc in proc_list:
                for pt in proc.points:
                    n = self._resolve_node(pt[0], pt[1], pt[2])
                    proc_node_iids.add(n.iid)
                for _t_name, t_pts in proc.transitions:
                    for pt in t_pts:
                        n = self._resolve_node(pt[0], pt[1], pt[2])
                        proc_node_iids.add(n.iid)

        if proc_type == 1:  # SID
            seen: set = set()
            for e in conn.connections:
                node = self._node_by_iid(e.nend, conn)
                if node is None or node.iid in seen:
                    continue
                seen.add(node.iid)
                if not node.next_list:
                    bridge = self._find_nearest_connected_node(
                        node.px,
                        node.py,
                        exclude_iid=node.iid,
                        exclude_iids=proc_node_iids,
                    )
                    if bridge:
                        conn.bridge_edges.append(Edge(nfrom=node.iid, nend=bridge.iid, name="SID"))
        else:  # STAR
            seen: set = set()
            for e in conn.connections:
                node = self._node_by_iid(e.nfrom, conn)
                if node is None or node.iid in seen:
                    continue
                seen.add(node.iid)
                if node.iid not in nodes_with_inbound:
                    bridge = self._find_nearest_connected_node(
                        node.px,
                        node.py,
                        exclude_iid=node.iid,
                        exclude_iids=proc_node_iids,
                    )
                    if bridge:
                        conn.bridge_edges.append(Edge(nfrom=bridge.iid, nend=node.iid, name="STAR"))

    def _leg_to_point(self, leg) -> tuple[str, float, float] | None:
        """Convert a FlatBuffers ProcLeg to (name, lat, lon).

        Fenix navdata stores all procedure waypoints in the Waypoints table;
        D-prefixed identifiers (e.g. D321Y) are real waypoints, not synthetic
        heading+distance markers.  No name-based filtering is applied.
        """
        name = leg.Name()
        if name is None:
            return None
        name = name.decode("utf-8") if isinstance(name, bytes) else name
        if not name:
            return None
        if _RUNWAY_ENDPOINT_RE.match(name):
            return (name, float(leg.Lat()), float(leg.Lon()))
        return (name, float(leg.Lat()), float(leg.Lon()))

    def _get_leg_points(self, procedure) -> list[tuple[str, float, float]]:
        """Extract (name, lat, lon) points from procedure legs."""
        points = []
        for i in range(procedure.LegsLength()):
            leg = procedure.Legs(i)
            pt = self._leg_to_point(leg)
            if pt:
                # Skip consecutive duplicates (Fenix stores each waypoint twice)
                if points and points[-1][0] == pt[0]:
                    continue
                points.append(pt)
        return points

    def _get_transition_points(self, trans) -> list[tuple[str, float, float]]:
        """Extract (name, lat, lon) points from transition legs."""
        points = []
        for i in range(trans.LegsLength()):
            leg = trans.Legs(i)
            pt = self._leg_to_point(leg)
            if pt:
                # Skip consecutive duplicates (Fenix stores each waypoint twice)
                if points and points[-1][0] == pt[0]:
                    continue
                points.append(pt)
        return points

    @staticmethod
    def _is_runway_endpoint(name: str) -> bool:
        return bool(_RUNWAY_ENDPOINT_RE.match(name))

    def _extract_transition_segments(
        self, trans, proc_type: int = 0, transition_name: str = ""
    ) -> list[list[tuple[str, float, float]]]:
        """Extract transition segments, splitting on (0,0) separator legs.

        Fenix sometimes stores multiple disconnected segments in a single
        transition. Each segment is deduplicated and returned independently.

        For SID (proc_type == 1), if a segment ends with a runway endpoint
        marker (DERxx / DExx), that marker belongs to the next segment
        (SID legs are airport->network, so the runway end should be at the
        start of a segment, not the end).

        For STAR (proc_type == 2), we do NOT split on separators because
        STAR transitions represent a continuous network->airport path;
        separators are often internal format markers (e.g. transition from
        STAR to approach) that should not break the path.

        Runway-specific transitions (names starting with "RW") describe a
        continuous runway->common path; the unnamed (0,0) legs in them are
        runway threshold / climb points, not separators, so they must NOT be
        split.
        """
        if proc_type == 2:
            # STAR: treat as continuous path, ignore (0,0) separators
            points = []
            for i in range(trans.LegsLength()):
                pt = self._leg_to_point(trans.Legs(i))
                if pt:
                    points.append(pt)
            return [self._dedup_consecutive(points)]

        # Runway-specific transitions: never split — (0,0) legs are runway
        # threshold / climb points, not segment separators.
        if transition_name.startswith("RW"):
            points = []
            for i in range(trans.LegsLength()):
                pt = self._leg_to_point(trans.Legs(i))
                if pt:
                    points.append(pt)
            return [self._dedup_consecutive(points)]

        segments = []
        current = []
        pending = []  # runway endpoint to prepend to next segment (SID only)
        for i in range(trans.LegsLength()):
            leg = trans.Legs(i)
            name_bytes = leg.Name()
            name = (
                name_bytes.decode("utf-8") if isinstance(name_bytes, bytes) else (name_bytes or "")
            )
            lat = float(leg.Lat())
            lon = float(leg.Lon())
            if lat == 0.0 and lon == 0.0 and not name:
                # Segment separator
                if current:
                    # For SID, if segment ends with runway endpoint marker,
                    # move it to the next segment (it is the next segment's start).
                    # A single-point runway endpoint (e.g. [DER01L]) should also
                    # be prepended to the following segment so the full runway->
                    # network path is preserved.
                    if (
                        proc_type == 1
                        and len(current) >= 1
                        and self._is_runway_endpoint(current[-1][0])
                    ):
                        pending = [current.pop()]
                    segments.append(self._dedup_consecutive(current))
                    current = list(pending)
                    pending = []
            elif lat != 0.0 or lon != 0.0:
                pt = self._leg_to_point(leg)
                if pt:
                    current.append(pt)
        if current:
            segments.append(self._dedup_consecutive(current))
        return segments

    RUNWAY_RE = re.compile(r"^(0[1-9]|[12]\d|3[0-6])[LRC]?$")

    @staticmethod
    def _infer_runway_from_points(points: list[tuple[str, float, float]], default: str = "") -> str:
        """Infer runway from DERxx / DExx markers in segment points."""
        for name, _, _ in points:
            if name.startswith("DER"):
                rwy = name[3:]
                if FlatbuffersAirportConnector.RUNWAY_RE.match(rwy):
                    return rwy
            elif name.startswith("DE"):
                rwy = name[2:]
                if FlatbuffersAirportConnector.RUNWAY_RE.match(rwy):
                    return rwy
        return default

    def _infer_runway_from_location(self, lat: float, lon: float, ap) -> str:
        """Infer the nearest runway from a geographic location.

        Used as a last-resort fallback when no runway-specific transitions,
        DER/DE markers, or approach bridges are available.

        Compares against each runway end individually so that opposite ends
        of the same physical runway (e.g. 13L vs 31R) are treated as
        separate candidates and the closest end wins.
        """
        best_runway = ""
        best_dist = float("inf")
        for i in range(ap.RunwaysLength()):
            rw = ap.Runways(i)
            for j in range(rw.EndsLength()):
                end = rw.Ends(j)
                end_name_bytes = end.Name()
                end_name = (
                    end_name_bytes.decode("utf-8")
                    if isinstance(end_name_bytes, bytes)
                    else (end_name_bytes or "")
                )
                if not end_name:
                    continue
                end_lat = float(end.Lat()) if end.Lat() else 0.0
                end_lon = float(end.Lon()) if end.Lon() else 0.0
                if end_lat == 0.0 and end_lon == 0.0:
                    continue
                dist = great_circle_distance_km(lat, lon, end_lat, end_lon)
                if dist < best_dist:
                    best_dist = dist
                    best_runway = end_name
        return best_runway

    def _resolve_node(self, name: str, lat: float, lon: float) -> Node:
        """Find node in network or create temp node."""
        node = self._find_node(name, lat, lon)
        if node is None:
            node = self._get_or_create_temp(name, lat, lon)
        return node

    def _split_transition_options(
        self, points: list[tuple[str, float, float]], anchor_name: str
    ) -> list[list[tuple[str, float, float]]]:
        """Split a concatenated Fenix transition into unique route options.

        Fenix sometimes stores multiple route options in a single transition
        by concatenating them. We first try backward split on the anchor
        (options ending at the same point), then forward split on any
        remaining segments (options starting at the same point but ending
        elsewhere). Options containing duplicate waypoint names are filtered
        out as they indicate a concatenation artefact.
        """
        if not points:
            return []

        def _has_dup_names(option):
            """A valid option should not repeat waypoint names."""
            names = [p[0] for p in option]
            return len(names) != len(set(names))

        def _backward_split(pts, anchor):
            """Extract options ending at anchor, working backward."""
            result = []
            seen = set()
            i = len(pts) - 1
            while i >= 0:
                if pts[i][0] == anchor:
                    j = i - 1
                    while j >= 0 and pts[j][0] != anchor:
                        j -= 1
                    option = pts[j + 1 : i + 1]
                    if option and not _has_dup_names(option):
                        opt_tuple = tuple(p[0] for p in option)
                        if opt_tuple not in seen:
                            seen.add(opt_tuple)
                            result.insert(0, option)
                    i = j
                else:
                    i -= 1
            return result

        def _forward_split(pts):
            """Extract options starting at the same first point."""
            if not pts:
                return []
            first_name = pts[0][0]
            if not first_name:
                return []
            first_indices = [i for i, p in enumerate(pts) if p[0] == first_name]
            if len(first_indices) <= 1:
                return []
            options = []
            seen = set()
            for i in range(len(first_indices)):
                start = first_indices[i]
                end = first_indices[i + 1] if i + 1 < len(first_indices) else len(pts)
                option = pts[start:end]
                if len(option) > 1 and not _has_dup_names(option):
                    opt_tuple = tuple(p[0] for p in option)
                    if opt_tuple not in seen:
                        seen.add(opt_tuple)
                        options.append(option)
            return options

        # Phase 1: backward split on anchor
        b_options = _backward_split(points, anchor_name)

        # Phase 2: remove backward-split options from points, then forward split remainder
        remaining = list(points)
        for opt in reversed(b_options):
            opt_names = [p[0] for p in opt]
            opt_len = len(opt)
            for i in range(len(remaining) - opt_len, -1, -1):
                if [p[0] for p in remaining[i : i + opt_len]] == opt_names:
                    remaining = remaining[:i]
                    break

        f_options = _forward_split(remaining)

        # Combine and deduplicate
        all_options = f_options + b_options
        result = []
        seen = set()
        for opt in all_options:
            key = tuple(p[0] for p in opt)
            if key not in seen:
                seen.add(key)
                result.append(opt)

        return result

    def _collect_procedures(self, icao: str, proc_type: int):
        """Collect all procedures of a given type for an airport.

        Returns:
            (runway_segments, common_segments, transition_segments)
            runway_segments: list of (proc_name, runway, anchor_node, points,
                transitions, is_main_legs)
            common_segments: dict of proc_name -> (anchor_node, points, transitions)
            transition_segments: list of (proc_name, runway, anchor_node, points,
                transitions, is_main_legs)
        """
        ap = self.nav_data.get_airport(icao)
        if ap is None:
            return [], {}, []

        runway_segments = []
        common_segments = {}
        transition_segments = []

        for i in range(ap.ProceduresLength()):
            proc = ap.Procedures(i)
            if proc.Type() != proc_type:
                continue

            name_bytes = proc.Name()
            proc_name = (
                name_bytes.decode("utf-8") if isinstance(name_bytes, bytes) else (name_bytes or "")
            )
            rwy_bytes = proc.Runway()
            runway = (
                rwy_bytes.decode("utf-8") if isinstance(rwy_bytes, bytes) else (rwy_bytes or "")
            )

            points = self._get_leg_points(proc)

            # Collect and split transitions. Fenix sometimes concatenates
            # multiple route options inside a single transition; we split them
            # here so downstream code never sees concatenated data.
            # We also split on (0,0) segment separators so disconnected
            # segments (e.g. different runways) are processed independently.
            transitions = []
            for j in range(proc.TransitionsLength()):
                trans = proc.Transitions(j)
                trans_name_bytes = trans.Name()
                trans_name = (
                    trans_name_bytes.decode("utf-8")
                    if isinstance(trans_name_bytes, bytes)
                    else (trans_name_bytes or "")
                )
                segments = self._extract_transition_segments(trans, proc_type, trans_name)
                for segment in segments:
                    seg_points = [(n, lat, lon) for n, lat, lon in segment if n]
                    if not seg_points:
                        continue
                    t_anchor_name = seg_points[-1][0]
                    options = self._split_transition_options(seg_points, t_anchor_name)
                    for option in options:
                        transitions.append((trans_name, option))

            if points:
                # Main legs exist: use as common/runway segment
                # Fenix stores SID legs airport->network and STAR legs network->airport.
                # Anchor (exit/entry node) is the airport-side point:
                #   SID: points[-1] = network-side exit (last in airport->network order)
                #   STAR: points[-1] = airport-side entry (last in network->airport order)
                anchor_name, anchor_lat, anchor_lon = points[-1]
                anchor_node = self._resolve_node(anchor_name, anchor_lat, anchor_lon)

                if not runway:
                    # Common segment (Fenix uses Rwy="" for common, not "ALL")
                    common_segments[proc_name] = (anchor_node, points, transitions)
                else:
                    # Runway-specific segment
                    # Skip runway-heading SIDs (single DERxx/DExx point) — they have
                    # no meaningful route structure and steal A* selection from
                    # real SID procedures that share the same runway endpoint.
                    if (
                        proc_type == 1
                        and len(points) <= 1
                        and _RUNWAY_ENDPOINT_RE.match(points[0][0])
                    ):
                        pass  # Drop runway-heading SID
                    else:
                        runway_segments.append(
                            (proc_name, runway, anchor_node, points, transitions, True)
                        )

                # Also generate runway segments from transitions so the full
                # runway->network path is available for display and edge building.
                # Transitions are already split into clean options above.
                # Only RWxx transitions become runway segments; non-RW transitions
                # are enroute transitions and must remain attached to the common
                # segment so they don't spawn bogus runway-grouped procedures.
                for trans_name, trans_points in transitions:
                    if not trans_points:
                        continue
                    if not trans_name.startswith("RW"):
                        continue
                    default_runway = trans_name[2:]
                    runway_name = self._infer_runway_from_points(trans_points, default_runway)
                    if proc_type == 1:
                        t_anchor_name, t_anchor_lat, t_anchor_lon = trans_points[-1]
                        t_anchor_node = self._resolve_node(
                            t_anchor_name, t_anchor_lat, t_anchor_lon
                        )
                        runway_segments.append(
                            (proc_name, runway_name, t_anchor_node, trans_points, [], False)
                        )
                    else:
                        entry_name, entry_lat, entry_lon = trans_points[0]
                        entry_node = self._resolve_node(entry_name, entry_lat, entry_lon)
                        runway_segments.append(
                            (proc_name, runway_name, entry_node, trans_points, [], False)
                        )

                # For SID, reverse transitions so they're runway->common
                # (consistent with transition-only SIDs below)
                if proc_type == 1:
                    transitions = [(t[0], list(reversed(t[1]))) for t in transitions]

                # Add to transition_segments for edge building
                transition_segments.append(
                    (proc_name, runway, anchor_node, points, transitions, True)
                )

            elif transitions:
                # No main legs but has transitions: each transition is a runway segment
                # (Fenix stores some airports' SID/STAR legs entirely in transitions)
                # For SID transitions, legs are stored network->airport, so the
                # airway anchor is the FIRST point. For STAR, it's the LAST point.
                for trans_name, trans_points in transitions:
                    if not trans_points:
                        continue
                    # Fallback to transition name for grouping
                    # (runway is validated at display time).
                    runway_name = trans_name[2:] if trans_name.startswith("RW") else trans_name
                    if proc_type == 1:
                        # SID transitions are stored airport->network.
                        # The network-side exit point is the last point.
                        anchor_name, anchor_lat, anchor_lon = trans_points[-1]
                        anchor_node = self._resolve_node(anchor_name, anchor_lat, anchor_lon)
                        runway_segments.append(
                            (proc_name, runway_name, anchor_node, trans_points, [], False)
                        )
                        transition_segments.append(
                            (proc_name, runway_name, anchor_node, trans_points, [], False)
                        )
                    else:
                        # STAR transitions are stored network->airport.
                        # The airport-side entry point is the last point.
                        # Keep network->airport order so internal_edges
                        # and display match flight direction.
                        anchor_name, anchor_lat, anchor_lon = trans_points[-1]
                        anchor_node = self._resolve_node(anchor_name, anchor_lat, anchor_lon)
                        # Network-side entry is the first point; use it for connections (A* entry)
                        entry_name, entry_lat, entry_lon = trans_points[0]
                        entry_node = self._resolve_node(entry_name, entry_lat, entry_lon)
                        runway_segments.append(
                            (proc_name, runway_name, entry_node, trans_points, [], False)
                        )
                        transition_segments.append(
                            (proc_name, runway_name, anchor_node, trans_points, [], False)
                        )

        return runway_segments, common_segments, transition_segments

    def _apply_filter(
        self,
        filter_name: str | None,
        runway_segments,
        common_segments,
        transition_segments,
        proc_type: int,
    ):
        """Filter procedures by exit point (SID) or entry point (STAR)."""
        if not filter_name:
            return runway_segments, common_segments, transition_segments

        def _matches_filter(points):
            if not points:
                return False
            if proc_type == 1:  # SID: match exit point (last point)
                return points[-1][0] == filter_name
            # STAR: match entry point (first point)
            return points[0][0] == filter_name

        target_procs = set()
        for proc_name, _runway, _anchor_node, points, _transitions, _is_main in runway_segments:
            if _matches_filter(points):
                target_procs.add(proc_name)
        for proc_name, (_anchor_node, points, _transitions) in common_segments.items():
            if _matches_filter(points):
                target_procs.add(proc_name)
        for proc_name, _runway, _anchor_node, points, _transitions, _is_main in transition_segments:
            if _matches_filter(points):
                target_procs.add(proc_name)

        runway_segments = [
            (proc_name, runway, anchor_node, points, transitions, is_main)
            for proc_name, runway, anchor_node, points, transitions, is_main in runway_segments
            if proc_name in target_procs
        ]
        common_segments = {k: v for k, v in common_segments.items() if k in target_procs}
        transition_segments = [
            (proc_name, runway, anchor_node, points, transitions, is_main)
            for proc_name, runway, anchor_node, points, transitions, is_main in transition_segments
            if proc_name in target_procs
        ]
        return runway_segments, common_segments, transition_segments

    @staticmethod
    def _deduplicate_procedures(
        procedures: dict[str, list[Procedure]],
    ) -> dict[str, list[Procedure]]:
        """Deduplicate procedures by (name, runway), keeping the one with the most points."""
        result: dict[str, list[Procedure]] = {}
        for key, proc_list in procedures.items():
            seen: dict[tuple[str, str], Procedure] = {}
            for proc in proc_list:
                ident = (proc.name, proc.runway)
                if ident not in seen or len(proc.points) > len(seen[ident].points):
                    seen[ident] = proc
            if seen:
                result[key] = list(seen.values())
        return result

    @staticmethod
    def _filter_runway_all_conflicts(
        procedures: dict[str, list[Procedure]],
    ) -> dict[str, list[Procedure]]:
        """Remove runway='ALL' variants when specific runway variants exist for the same name.

        Prevents the frontend from showing duplicate entries (Cartesian product of
        procedure x runway) when the same procedure name has both an 'ALL' variant
        and runway-specific variants.
        """
        name_runways: dict[str, set[str]] = {}
        for proc_list in procedures.values():
            for proc in proc_list:
                name_runways.setdefault(proc.name, set()).add(proc.runway)

        for key, proc_list in list(procedures.items()):
            filtered = [
                p
                for p in proc_list
                if not (p.runway == "ALL" and len(name_runways.get(p.name, set())) > 1)
            ]
            if filtered:
                procedures[key] = filtered
            else:
                del procedures[key]
        return procedures

    def _base_name(self, proc_name: str) -> str:
        """Extract alphabetic prefix for matching common/runway procedure variants.

        Fenix uses suffixes like digits+letters (RUSD2G, RUSD9Z) or just digits
        (BOVMA8, CHINS5). The base name is the leading alphabetic portion.
        """
        i = 0
        while i < len(proc_name) and proc_name[i].isalpha():
            i += 1
        return proc_name[:i] if i > 0 else proc_name

    def _register_common_procedures(
        self,
        common_segments,
        procedures,
        key_from_points,
        approach_bridges: dict[tuple[str, str], list[tuple[str, float, float]]] | None = None,
        ap=None,
        runway_endpoints: dict[str, tuple[str, float, float]] | None = None,
    ):
        """Register common segment procedures for runways covered by their transitions.

        key_from_points: callable(points) -> str, extracts the dict key from
        the common segment's main-leg points (e.g. lambda pts: pts[-1][0] for SID).

        When no transitions exist and approach_bridges is provided (STAR case),
        runway is inferred from which runways have approach bridges starting from
        this segment's final point. This avoids falling back to runway="ALL".

        As a last resort, when an airport object (ap) is provided and no runway
        can be inferred, the runway is guessed from the geographic location of
        the segment's final point so the frontend never sees "ALL".

        When runway_endpoints is provided and the inferred runway has a known
        endpoint marker, the marker is prepended to the procedure points so
        that all procedures for the same runway share the same starting point.
        This prevents pooled-edge branching in the internal_edges graph.

        Single-point common segments (after filtering synthetic markers) are
        skipped because they provide no meaningful path.
        """
        for proc_name, (anchor_node, points, transitions) in common_segments.items():
            # Skip single-point common segments -- they provide no navigable path.
            if len(points) < 2 and not transitions:
                continue

            merged_points = list(points)
            key = key_from_points(points) if points else anchor_node.name

            rwy_names_from_trans = set()
            for trans_name, _ in transitions:
                if trans_name.startswith("RW"):
                    rwy_name = trans_name[2:]
                    if rwy_name:
                        rwy_names_from_trans.add(rwy_name)

            if rwy_names_from_trans:
                for rwy_name in sorted(rwy_names_from_trans):
                    proc = Procedure(
                        name=proc_name,
                        runway=rwy_name,
                        points=merged_points,
                        transitions=transitions,
                    )
                    if key not in procedures:
                        procedures[key] = [proc]
                    else:
                        procedures[key].append(proc)
            elif approach_bridges is not None:
                # Infer runways from approach bridges for this segment's final point
                final_point = points[-1][0] if points else anchor_node.name
                rwy_names_from_bridges = set()
                for (rwy, entry), _bridge in approach_bridges.items():
                    if entry == final_point:
                        rwy_names_from_bridges.add(rwy)

                if rwy_names_from_bridges:
                    for rwy_name in sorted(rwy_names_from_bridges):
                        proc = Procedure(
                            name=proc_name,
                            runway=rwy_name,
                            points=merged_points,
                            transitions=transitions,
                        )
                        if key not in procedures:
                            procedures[key] = [proc]
                        else:
                            procedures[key].append(proc)
                elif ap is not None and points:
                    _name, _lat, _lon = points[-1]
                    inferred = self._infer_runway_from_location(_lat, _lon, ap)
                    if inferred and runway_endpoints and inferred in runway_endpoints:
                        re_name, re_lat, re_lon = runway_endpoints[inferred]
                        if not merged_points or merged_points[0][0] not in (
                            f"DER{inferred}",
                            f"DE{inferred}",
                        ):
                            merged_points = [(re_name, re_lat, re_lon), *list(merged_points)]
                    proc = Procedure(
                        name=proc_name,
                        runway=inferred if inferred else "ALL",
                        points=merged_points,
                        transitions=transitions,
                    )
                    if key not in procedures:
                        procedures[key] = [proc]
                    else:
                        procedures[key].append(proc)
                else:
                    proc = Procedure(
                        name=proc_name, runway="ALL", points=merged_points, transitions=transitions
                    )
                    if key not in procedures:
                        procedures[key] = [proc]
                    else:
                        procedures[key].append(proc)
            elif ap is not None and points:
                _name, _lat, _lon = points[-1]
                inferred = self._infer_runway_from_location(_lat, _lon, ap)
                if inferred and runway_endpoints and inferred in runway_endpoints:
                    re_name, re_lat, re_lon = runway_endpoints[inferred]
                    if not merged_points or merged_points[0][0] not in (
                        f"DER{inferred}",
                        f"DE{inferred}",
                    ):
                        merged_points = [(re_name, re_lat, re_lon), *list(merged_points)]
                proc = Procedure(
                    name=proc_name,
                    runway=inferred if inferred else "ALL",
                    points=merged_points,
                    transitions=transitions,
                )
                if key not in procedures:
                    procedures[key] = [proc]
                else:
                    procedures[key].append(proc)
            else:
                proc = Procedure(
                    name=proc_name, runway="ALL", points=merged_points, transitions=transitions
                )
                if key not in procedures:
                    procedures[key] = [proc]
                else:
                    procedures[key].append(proc)

    def _airport_side_node(self, proc_type: int, points, anchor_node: Node, is_main: bool) -> Node:
        """Return the node on the airport side of a segment.

        For STAR main-leg segments the stored anchor is already the airport-side
        point (last point, network->airport). For SID main-leg segments the
        stored anchor is the network-side point (last point), so we must use
        the first point instead.

        For transition-generated segments we pick the runway end: first point
        for SID (airport->network) or last point for STAR (network->airport).
        """
        if is_main:
            if proc_type == 1 and points:  # SID main: airport side is first point
                return self._resolve_node(points[0][0], points[0][1], points[0][2])
            # STAR main: anchor_node is already airport side (last point)
            return anchor_node
        if not points:
            return anchor_node
        if proc_type == 1:  # SID transition: airport side is the first point
            return self._resolve_node(points[0][0], points[0][1], points[0][2])
        # STAR transition: airport side is the last point
        return self._resolve_node(points[-1][0], points[-1][1], points[-1][2])

    def build_sid(self, icao: str, filter_name: str | None = None) -> AirportConnection | None:
        """Build departure (SID) connections for an airport."""
        icao = icao.upper()
        ap = self.nav_data.get_airport(icao)
        if ap is None:
            return None

        ap_lat = float(ap.Lat())
        ap_lon = float(ap.Lon())
        airport_node = Node(iid=-1, name=icao, px=ap_lat, py=ap_lon)

        runway_segments, common_segments, transition_segments = self._collect_procedures(icao, 1)
        runway_segments, common_segments, transition_segments = self._apply_filter(
            filter_name, runway_segments, common_segments, transition_segments, 1
        )

        # --- Prepend runway endpoints to SID segments that lack them ---
        # Fenix sometimes stores SID legs (main or transition) without the
        # runway endpoint marker (DERxx / DExx) as the first point.  When
        # multiple procedures share the same runway, the pooled internal_edges
        # then show branching at the first transition point instead of at the
        # runway end.  We scan all segments to find each runway's endpoint
        # and prepend it to any segment that lacks it.
        runway_endpoints: dict[str, tuple[str, float, float]] = {}
        for _proc_name, runway, _exit_node, points, _transitions, _is_main in runway_segments:
            if not runway or not points:
                continue
            for name, lat, lon in points:
                if name == f"DER{runway}":
                    runway_endpoints[runway] = (name, lat, lon)
                    break
                if name == f"DE{runway}" and runway not in runway_endpoints:
                    runway_endpoints[runway] = (name, lat, lon)
            # If we found DER, stop scanning this runway (DER preferred over DE)
            if runway in runway_endpoints and runway_endpoints[runway][0] == f"DER{runway}":
                continue

        fixed_runway_segments = []
        for proc_name, runway, anchor_node, points, transitions, is_main in runway_segments:
            if runway in runway_endpoints:
                re_name, re_lat, re_lon = runway_endpoints[runway]
                if not points or points[0][0] not in (f"DER{runway}", f"DE{runway}"):
                    new_points = [(re_name, re_lat, re_lon), *list(points)]
                    fixed_runway_segments.append(
                        (proc_name, runway, anchor_node, new_points, transitions, is_main)
                    )
                else:
                    fixed_runway_segments.append(
                        (proc_name, runway, anchor_node, points, transitions, is_main)
                    )
            else:
                fixed_runway_segments.append(
                    (proc_name, runway, anchor_node, points, transitions, is_main)
                )
        runway_segments = fixed_runway_segments

        # In the mixed-graph approach, only the airport and SID exit points
        # participate in routing.  Internal procedure points and transitions
        # are display-only (frontend draws them from procedures data).
        connections = []

        # Build procedures from runway segments.
        # Merge matching common segment points and transitions so the full
        # runway->network path is available for display.
        # For transition-only procedures (no main legs), merge all options of
        # the same (name, runway) into one Procedure with transitions so each
        # option remains selectable in the frontend.
        from collections import defaultdict

        runway_groups = defaultdict(list)
        for proc_name, runway, exit_node, points, transitions, is_main in runway_segments:
            runway_groups[(proc_name, runway)].append((exit_node, points, transitions, is_main))

        # Collect candidate runways per proc_name from RWxx transitions.
        sid_proc_name_candidates: dict[str, set[str]] = {}
        for proc_name, runway, _exit_node, _points, _transitions, _is_main in runway_segments:
            if self.RUNWAY_RE.match(runway):
                sid_proc_name_candidates.setdefault(proc_name, set()).add(runway)
        for proc_name, (_anchor_node, _points, common_trans) in common_segments.items():
            for trans_name, _ in common_trans:
                if trans_name.startswith("RW"):
                    rwy = trans_name[2:]
                    if self.RUNWAY_RE.match(rwy):
                        sid_proc_name_candidates.setdefault(proc_name, set()).add(rwy)

        # For transition-only procedures, merge non-RW transition groups into
        # valid-runway groups as transitions. This prevents enroute transitions
        # from being spawned as separate bogus procedures with inferred runways.
        proc_name_to_valid_runways: dict[str, list[str]] = {}
        proc_name_to_invalid_runways: dict[str, list[str]] = {}
        for proc_name, runway in runway_groups:
            if self.RUNWAY_RE.match(runway):
                proc_name_to_valid_runways.setdefault(proc_name, []).append(runway)
            else:
                proc_name_to_invalid_runways.setdefault(proc_name, []).append(runway)
        for proc_name, invalid_runways in proc_name_to_invalid_runways.items():
            valid_runways = proc_name_to_valid_runways.get(proc_name)
            if not valid_runways:
                continue
            extra_transitions = []
            for rw in invalid_runways:
                group = runway_groups[(proc_name, rw)]
                for _exit_node, points, _transitions, _is_main in group:
                    if points:
                        extra_transitions.append((rw, list(points)))
            for rw in valid_runways:
                group = runway_groups[(proc_name, rw)]
                new_group = []
                for exit_node, points, transitions, is_main in group:
                    merged_trans = list(transitions)
                    for et in extra_transitions:
                        if et not in merged_trans:
                            merged_trans.append(et)
                    new_group.append((exit_node, points, merged_trans, is_main))
                runway_groups[(proc_name, rw)] = new_group
            for rw in invalid_runways:
                del runway_groups[(proc_name, rw)]

        procedures = {}
        for (proc_name, runway), group in runway_groups.items():
            # Prefer option whose points contain the current runway endpoint
            # marker (DERxx / DExx). Fallback to an option that does NOT
            # contain any other runway marker, avoiding cross-runway pollution
            # when Fenix mixes multiple runway segments in one transition.
            best_exit, best_points, best_trans, best_is_main = group[0]
            for exit_node, points, transitions, is_main in group:
                point_names = [p[0] for p in points]
                der_match = (
                    f"DER{runway}"
                    if f"DER{runway}" in point_names
                    else (f"DE{runway}" if f"DE{runway}" in point_names else None)
                )
                if der_match:
                    idx = point_names.index(der_match)
                    # For SID, runway endpoint marker should be near the start
                    # (airport side). If it appears in the second half, it likely
                    # belongs to a different runway segment that wasn't cleanly
                    # separated by Fenix.
                    if idx < len(point_names) * 0.5:
                        best_exit, best_points, best_trans, best_is_main = (
                            exit_node,
                            points,
                            transitions,
                            is_main,
                        )
                        break
            else:
                for exit_node, points, transitions, is_main in group:
                    point_names = [p[0] for p in points]
                    has_other = any(
                        (n.startswith("DER") and n[3:] != runway)
                        or (n.startswith("DE") and n[2:] != runway)
                        for n in point_names
                    )
                    if not has_other:
                        best_exit, best_points, best_trans, best_is_main = (
                            exit_node,
                            points,
                            transitions,
                            is_main,
                        )
                        break

            exit_node, points, transitions, is_main = (
                best_exit,
                best_points,
                best_trans,
                best_is_main,
            )
            merged_points = list(points)
            merged_transitions = list(transitions)

            if proc_name in common_segments:
                _common_node, common_points, common_trans = common_segments[proc_name]
                seen = {p[0] for p in merged_points}
                for cp in common_points:
                    if cp[0] not in seen:
                        merged_points.append(cp)
                        seen.add(cp[0])
                for ct in common_trans:
                    if ct[0].startswith("RW"):
                        ct_runway = ct[0][2:]
                        if ct_runway == runway and ct not in merged_transitions:
                            merged_transitions.append(ct)
                    else:
                        # Non-RW transitions (enroute transitions) apply to all runways
                        if ct not in merged_transitions:
                            merged_transitions.append(ct)

            # Transition-only: collect remaining options as transitions
            all_trans_only = all(not m for _, _, _, m in group)
            if all_trans_only and len(group) > 1:
                seen_trans = {tuple(p[0] for p in merged_points)}
                for _, opt_points, _, _ in group[1:]:
                    t_key = tuple(p[0] for p in opt_points)
                    if t_key not in seen_trans:
                        seen_trans.add(t_key)
                        t_name = opt_points[0][0] if opt_points else runway
                        merged_transitions.append((t_name, list(opt_points)))

            candidate_runways = sid_proc_name_candidates.get(proc_name, set())
            if not self.RUNWAY_RE.match(runway) and candidate_runways:
                display_runway = sorted(candidate_runways)[0]
            elif not self.RUNWAY_RE.match(runway):
                # Fallback: infer runway from the geographic location of the first point.
                if merged_points:
                    _name, _lat, _lon = merged_points[0]
                    inferred = self._infer_runway_from_location(_lat, _lon, ap)
                    display_runway = inferred if inferred else "ALL"
                else:
                    display_runway = "ALL"
            else:
                display_runway = runway
            proc = Procedure(
                name=proc_name,
                runway=display_runway,
                points=merged_points,
                transitions=merged_transitions,
            )
            # SID points are airport->network; key by merged network-side exit point
            key = merged_points[-1][0] if merged_points else exit_node.name
            if key not in procedures:
                procedures[key] = [proc]
            else:
                procedures[key].append(proc)

        # Also register common segment procedures as selectable exits.
        # Only offer for runways covered by this procedure's transitions.
        self._register_common_procedures(
            common_segments,
            procedures,
            lambda pts: pts[-1][0],
            ap=ap,
            runway_endpoints=runway_endpoints,
        )

        procedures = self._deduplicate_procedures(procedures)

        # Build connections from airport to each procedure's exit point.
        # Include both the common-segment end AND every transition end so
        # A* can evaluate which boundary gives the shortest total route.
        added_exit_nodes: set = set()
        for key, proc_list in procedures.items():
            for proc in proc_list:
                # Common-segment exit
                if proc.points:
                    last_name, last_lat, last_lon = proc.points[-1]
                    if last_name and last_name not in added_exit_nodes:
                        last_node = self._resolve_node(last_name, last_lat, last_lon)
                        connections.append(
                            Edge(nfrom=airport_node.iid, nend=last_node.iid, name="SID")
                        )
                        added_exit_nodes.add(last_name)
                # Transition exits — only add as connections when the transition
                # end is actually connected to the airway network.  Dead-end
                # transition ends (e.g. UPRAL) should not receive bridge edges,
                # otherwise A* shortcuts through them instead of using valid
                # enroute exits like SHTLE.
                for t_name, t_pts in proc.transitions:
                    if t_pts:
                        t_last_name, t_last_lat, t_last_lon = t_pts[-1]
                        if t_last_name and t_last_name not in added_exit_nodes:
                            t_last_node = self._resolve_node(t_last_name, t_last_lat, t_last_lon)
                            if t_last_node.next_list:
                                connections.append(
                                    Edge(nfrom=airport_node.iid, nend=t_last_node.iid, name="SID")
                                )
                                added_exit_nodes.add(t_last_name)

        result = AirportConnection(
            airport_node=airport_node,
            connections=connections,
            procedures=procedures,
            transition_edges=[],
            temp_nodes=list(self._temp_nodes.values()),
            internal_edges=[],
        )
        self._add_boundary_bridges(result, 1)
        return result

    def _collect_approach_bridges(
        self, icao: str
    ) -> dict[tuple[str, str], list[tuple[str, float, float]]]:
        """Collect Type=3 approach procedures and build (runway, entry_point) -> path mapping.

        Returns a dict mapping (runway, entry_point_name) to a list of points
        representing the full approach path from entry_point to the runway.
        Missed approach / go-around legs are truncated.
        """
        ap = self.nav_data.get_airport(icao)
        if ap is None:
            return {}

        # Build runway end coordinate lookup
        runway_coords: dict[str, tuple[float, float]] = {}
        for i in range(ap.RunwaysLength()):
            rw = ap.Runways(i)
            for j in range(rw.EndsLength()):
                end = rw.Ends(j)
                end_name = (
                    end.Name().decode("utf-8")
                    if isinstance(end.Name(), bytes)
                    else (end.Name() or "")
                )
                if end_name:
                    runway_coords[end_name] = (float(end.Lat()), float(end.Lon()))

        bridges: dict[tuple[str, str], list[tuple[str, float, float]]] = {}

        for i in range(ap.ProceduresLength()):
            proc = ap.Procedures(i)
            if proc.Type() != 3:
                continue

            (
                proc.Name().decode("utf-8")
                if isinstance(proc.Name(), bytes)
                else (proc.Name() or "")
            )
            runway = (
                proc.Runway().decode("utf-8")
                if isinstance(proc.Runway(), bytes)
                else (proc.Runway() or "")
            )
            if not runway:
                continue

            rwy_lat_lon = runway_coords.get(runway)
            if rwy_lat_lon is None:
                continue

            # Collect raw main points including unnamed points (skip (0,0) placeholders)
            raw_main: list[tuple[str, float, float]] = []
            for j in range(proc.LegsLength()):
                leg = proc.Legs(j)
                name_bytes = leg.Name()
                name = (
                    name_bytes.decode("utf-8")
                    if isinstance(name_bytes, bytes)
                    else (name_bytes or "")
                )
                lat = float(leg.Lat())
                lon = float(leg.Lon())
                if lat == 0.0 and lon == 0.0:
                    continue
                raw_main.append((name, lat, lon))
            raw_main = self._dedup_consecutive(raw_main)

            # Filtered main points for transition merging (without unnamed points)
            main_points = self._get_leg_points(proc)
            approach_main = []
            for p in main_points:
                approach_main.append(p)
                if p[0].startswith(("FI", "FF")):
                    break

            # Process transitions (feeder routes).
            # Fenix sometimes stores multiple disconnected segments in a single
            # transition, separated by unnamed (0,0) legs. For approaches, these
            # may be genuine feeder-route splits (e.g. I33-Y NLG vs NLG30) or
            # missed-approach separators (e.g. I19LY). We first try segment split,
            # but if a segment yields no valid options (because the anchor changed
            # after splitting), fall back to the full transition points.
            for j in range(proc.TransitionsLength()):
                trans = proc.Transitions(j)
                (
                    trans.Name().decode("utf-8")
                    if isinstance(trans.Name(), bytes)
                    else (trans.Name() or "")
                )

                segments = self._extract_transition_segments(trans, proc_type=3)
                full_points = self._get_transition_points(trans)

                for seg_idx, segment in enumerate(segments):
                    if not segment:
                        continue

                    trans_points = [(n, lat, lon) for n, lat, lon in segment if n]
                    if not trans_points:
                        continue

                    # Split concatenated transitions. For approaches, transitions are
                    # stored entry_point -> IAF, so the anchor is the last point (IAF).
                    anchor_name = trans_points[-1][0] if trans_points else ""
                    options = self._split_transition_options(trans_points, anchor_name)

                    # Fallback: if the segment split changed the anchor (e.g. missed
                    # approach cut off the IAF), use the full transition instead.
                    if not options and seg_idx == 0 and len(segments) > 1 and full_points:
                        anchor_name = full_points[-1][0] if full_points else ""
                        options = self._split_transition_options(full_points, anchor_name)

                    for option in options:
                        if not option:
                            continue

                        # Build raw full path: raw transition + raw main
                        raw_full = list(option)
                        seen = {p[0] for p in raw_full}
                        for p in raw_main:
                            if p[0] not in seen:
                                raw_full.append(p)
                                seen.add(p[0])

                        # Truncate at runway / missed approach point
                        truncated = self._truncate_approach_path(raw_full, rwy_lat_lon)

                        # Filter out unnamed points for the final bridge
                        filtered = [(n, lat, lon) for n, lat, lon in truncated if n]
                        if not filtered:
                            continue

                        # Register full bridge and all sub-bridges
                        for k in range(len(filtered)):
                            sub_path = filtered[k:]
                            sub_entry = sub_path[0][0]
                            key = (runway, sub_entry)
                            if key not in bridges or len(sub_path) > len(bridges[key]):
                                bridges[key] = sub_path

            # If no transitions, use main legs directly
            if proc.TransitionsLength() == 0 and raw_main:
                truncated = self._truncate_approach_path(raw_main, rwy_lat_lon)
                filtered = [(n, lat, lon) for n, lat, lon in truncated if n]
                if filtered:
                    entry_name = filtered[0][0]
                    key = (runway, entry_name)
                    if key not in bridges or len(filtered) > len(bridges[key]):
                        bridges[key] = filtered

        return bridges

    def build_star(self, icao: str, filter_name: str | None = None) -> AirportConnection | None:
        """Build arrival (STAR) connections for an airport."""
        icao = icao.upper()
        ap = self.nav_data.get_airport(icao)
        if ap is None:
            return None

        ap_lat = float(ap.Lat())
        ap_lon = float(ap.Lon())
        airport_node = Node(iid=-2, name=icao, px=ap_lat, py=ap_lon)

        runway_segments, common_segments, transition_segments = self._collect_procedures(icao, 2)
        runway_segments, common_segments, transition_segments = self._apply_filter(
            filter_name, runway_segments, common_segments, transition_segments, 2
        )

        # Collect approach bridges (Type=3) to extend STAR paths to the runway.
        approach_bridges = self._collect_approach_bridges(icao)

        # In the mixed-graph approach, only the STAR entry points and airport
        # participate in routing.  Internal procedure points and transitions
        # are display-only (frontend draws them from procedures data).

        # Build procedures from runway segments.
        # Merge matching common segment points and transitions so the full
        # network->airport path is available for display.
        # For transition-only procedures (no main legs), merge all options of
        # the same (name, runway) into one Procedure with transitions so each
        # option remains selectable in the frontend.
        runway_groups = defaultdict(list)
        for proc_name, runway, entry_node, points, transitions, is_main in runway_segments:
            runway_groups[(proc_name, runway)].append((entry_node, points, transitions, is_main))

        # Collect candidate runways per proc_name from approach bridges and RWxx transitions.
        proc_name_candidate_runways: dict[str, set[str]] = {}
        for proc_name, runway, _entry_node, _points, _transitions, _is_main in runway_segments:
            if self.RUNWAY_RE.match(runway):
                proc_name_candidate_runways.setdefault(proc_name, set()).add(runway)
        for proc_name, (_anchor_node, points, common_trans) in common_segments.items():
            if points and approach_bridges:
                final_point = points[-1][0]
                for (rwy, entry), _bridge in approach_bridges.items():
                    if entry == final_point:
                        proc_name_candidate_runways.setdefault(proc_name, set()).add(rwy)
            for trans_name, _ in common_trans:
                if trans_name.startswith("RW"):
                    rwy = trans_name[2:]
                    if self.RUNWAY_RE.match(rwy):
                        proc_name_candidate_runways.setdefault(proc_name, set()).add(rwy)

        procedures = {}
        for (proc_name, runway), group in runway_groups.items():
            # Prefer the option whose last point has a matching approach bridge.
            # This avoids selecting transition options that end at waypoints
            # with no defined final approach path for the target runway.
            best_entry, best_points, best_trans, best_is_main = group[0]
            for entry_node, points, transitions, is_main in group:
                if points and (runway, points[-1][0]) in approach_bridges:
                    best_entry, best_points, best_trans, best_is_main = (
                        entry_node,
                        points,
                        transitions,
                        is_main,
                    )
                    break

            entry_node, points, transitions, is_main = (
                best_entry,
                best_points,
                best_trans,
                best_is_main,
            )
            merged_points = []
            seen = set()
            merged_transitions = list(transitions)

            if proc_name in common_segments:
                _common_node, common_points, common_trans = common_segments[proc_name]
                # Determine correct merge order for STAR:
                # - Enroute transitions end at common path start
                #   (e.g. PGS -> ... -> BASET, common = BASET -> DOWNE -> REEDR)
                #   -> transition + common so flight direction is network -> airport.
                # - Final approach transitions start at common path end
                #   (e.g. RW06L = REEDR -> SMO, common = BASET -> DOWNE -> REEDR)
                #   -> common + transition so flight direction is network -> airport.
                if points and common_points and points[-1][0] == common_points[0][0]:
                    merged_points = list(points)
                    seen = {p[0] for p in merged_points}
                    for cp in common_points:
                        if cp[0] not in seen:
                            merged_points.append(cp)
                            seen.add(cp[0])
                else:
                    for cp in common_points:
                        if cp[0] not in seen:
                            merged_points.append(cp)
                            seen.add(cp[0])
                    for p in points:
                        if p[0] not in seen:
                            merged_points.append(p)
                            seen.add(p[0])
                for ct in common_trans:
                    if ct[0].startswith("RW"):
                        ct_runway = ct[0][2:]
                        if ct_runway == runway and ct not in merged_transitions:
                            merged_transitions.append(ct)
                    else:
                        # Non-RW transitions (enroute transitions) apply to all runways
                        if ct not in merged_transitions:
                            merged_transitions.append(ct)
            else:
                for p in points:
                    merged_points.append(p)
                    seen.add(p[0])

            # Transition-only: collect remaining options as transitions
            all_trans_only = all(not m for _, _, _, m in group)
            if all_trans_only and len(group) > 1:
                seen_trans = {tuple(p[0] for p in merged_points)}
                for _, opt_points, _, _ in group[1:]:
                    t_key = tuple(p[0] for p in opt_points)
                    if t_key not in seen_trans:
                        seen_trans.add(t_key)
                        t_name = opt_points[-1][0] if opt_points else runway
                        merged_transitions.append((t_name, list(opt_points)))

            candidate_runways = proc_name_candidate_runways.get(proc_name, set())
            if not self.RUNWAY_RE.match(runway) and candidate_runways:
                # Prefer candidate runway whose approach bridge matches this endpoint.
                best_runway = runway
                for cr in sorted(candidate_runways):
                    if points and (cr, points[-1][0]) in approach_bridges:
                        best_runway = cr
                        break
                else:
                    best_runway = sorted(candidate_runways)[0]
                display_runway = best_runway
            elif not self.RUNWAY_RE.match(runway):
                # Fallback: infer runway from the geographic location of the last point.
                if merged_points:
                    _name, _lat, _lon = merged_points[-1]
                    inferred = self._infer_runway_from_location(_lat, _lon, ap)
                    display_runway = inferred if inferred else "ALL"
                else:
                    display_runway = "ALL"
            else:
                display_runway = runway
            proc = Procedure(
                name=proc_name,
                runway=display_runway,
                points=merged_points,
                transitions=merged_transitions,
            )
            # STAR main-legs are network->airport; key by merged network-side entry point.
            key = merged_points[0][0] if merged_points else entry_node.name
            if key not in procedures:
                procedures[key] = [proc]
            else:
                procedures[key].append(proc)

        # Also register common segment procedures as selectable entries.
        # Only offer for runways covered by this procedure's transitions.
        # For common segments without transitions, infer runway from approach bridges.
        self._register_common_procedures(
            common_segments, procedures, lambda pts: pts[0][0], approach_bridges, ap=ap
        )

        procedures = self._deduplicate_procedures(procedures)

        # Merge approach bridges (Type=3) into STAR procedures so the full
        # path from STAR endpoint to runway is available for display and routing.
        # Pre-compute entry point -> [(runway, bridge_points)] for ALL-variant matching.
        entry_to_bridges: dict[str, list[tuple[str, list[tuple[str, float, float]]]]] = {}
        for (rwy, entry), bridge_points in approach_bridges.items():
            entry_to_bridges.setdefault(entry, []).append((rwy, bridge_points))

        used_bridges: set = set()
        for key, proc_list in procedures.items():
            for proc in proc_list:
                if not proc.points:
                    continue
                entry_point = proc.points[-1][0]
                bridge_key = (proc.runway, entry_point)
                if bridge_key in approach_bridges:
                    bridge_points = approach_bridges[bridge_key]
                    seen = {p[0] for p in proc.points}
                    for bp in bridge_points:
                        if bp[0] not in seen:
                            proc.points.append(bp)
                            seen.add(bp[0])
                    used_bridges.add(bridge_key)
                elif proc.runway == "ALL" and entry_point in entry_to_bridges:
                    bridges = entry_to_bridges[entry_point]
                    best_runway, best_bridge = bridges[0]
                    if len(bridges) > 1:
                        candidates = proc_name_candidate_runways.get(proc.name, set())
                        for rwy, bp in bridges:
                            if rwy in candidates:
                                best_runway, best_bridge = rwy, bp
                                break
                    seen = {p[0] for p in proc.points}
                    for bp in best_bridge:
                        if bp[0] not in seen:
                            proc.points.append(bp)
                            seen.add(bp[0])
                    proc.runway = best_runway
                    used_bridges.add((best_runway, entry_point))

        # Build connections from each procedure's entry point to the airport.
        # Include both the common-segment start AND every transition start so
        # A* can evaluate which boundary gives the shortest total route.
        connections: list[Edge] = []
        added_entry_nodes: set = set()
        for key, proc_list in procedures.items():
            for proc in proc_list:
                # Common-segment entry
                if proc.points:
                    first_name, first_lat, first_lon = proc.points[0]
                    if first_name and first_name not in added_entry_nodes:
                        first_node = self._resolve_node(first_name, first_lat, first_lon)
                        connections.append(
                            Edge(nfrom=first_node.iid, nend=airport_node.iid, name="STAR")
                        )
                        added_entry_nodes.add(first_name)
                # Transition entries
                for t_name, t_pts in proc.transitions:
                    if t_pts:
                        t_first_name, t_first_lat, t_first_lon = t_pts[0]
                        if t_first_name and t_first_name not in added_entry_nodes:
                            t_first_node = self._resolve_node(
                                t_first_name, t_first_lat, t_first_lon
                            )
                            connections.append(
                                Edge(nfrom=t_first_node.iid, nend=airport_node.iid, name="STAR")
                            )
                            added_entry_nodes.add(t_first_name)

        # Fallback: when no STAR procedures exist but approach bridges do,
        # create virtual STAR procedures from the approach bridges.
        filter_matches_bridge = False
        if filter_name and approach_bridges:
            filter_matches_bridge = any(
                entry_name == filter_name for (runway, entry_name), _ in approach_bridges.items()
            )

        if not procedures and approach_bridges and (not filter_name or filter_matches_bridge):
            for (runway, entry_name), bridge_points in approach_bridges.items():
                if filter_name and entry_name != filter_name:
                    continue
                proc = Procedure(
                    name=f"APPR_{runway}",
                    runway=runway,
                    points=list(bridge_points),
                    transitions=[],
                )
                if entry_name not in procedures:
                    procedures[entry_name] = [proc]
                else:
                    procedures[entry_name].append(proc)
                first_name, first_lat, first_lon = bridge_points[0]
                if first_name and first_name not in added_entry_nodes:
                    first_node = self._resolve_node(first_name, first_lat, first_lon)
                    connections.append(
                        Edge(nfrom=first_node.iid, nend=airport_node.iid, name="STAR")
                    )
                    added_entry_nodes.add(first_name)

        result = AirportConnection(
            airport_node=airport_node,
            connections=connections,
            procedures=procedures,
            transition_edges=[],
            temp_nodes=list(self._temp_nodes.values()),
            internal_edges=[],
        )
        self._add_boundary_bridges(result, 2)
        return result

    def _flatten_transitions(self, transition_segments):
        """Flatten transition segments into tuples.

        (proc_name, trans_name, from_node, to_node, points)
        """
        result = []
        for proc_name, _runway, _anchor_node, _points, transitions, _is_main in transition_segments:
            for trans_name, t_points in transitions:
                if not t_points:
                    continue
                from_name, from_lat, from_lon = t_points[0]
                to_name, to_lat, to_lon = t_points[-1]
                from_node = self._resolve_node(from_name, from_lat, from_lon)
                to_node = self._resolve_node(to_name, to_lat, to_lon)
                result.append((proc_name, trans_name, from_node, to_node, t_points))
        return result

    def get_airport_names(self, icao: str) -> list[str]:
        """Get airport name(s) from navdata."""
        ap = self.nav_data.get_airport(icao.upper())
        if ap is None:
            return []
        name = ap.Name()
        if name is None:
            return []
        decoded = name.decode("utf-8") if isinstance(name, bytes) else name
        return [decoded] if decoded else []

    def _get_runway_names(self, icao: str) -> list[str]:
        """Extract runway end names from airport data."""
        ap = self.nav_data.get_airport(icao.upper())
        if ap is None:
            return []
        names = []
        for i in range(ap.RunwaysLength()):
            rw = ap.Runways(i)
            for j in range(rw.EndsLength()):
                end = rw.Ends(j)
                end_name = end.Name()
                if end_name:
                    names.append(
                        end_name.decode("utf-8") if isinstance(end_name, bytes) else end_name
                    )
        return names

    def _get_airport_coords(self, icao: str) -> tuple[float | None, float | None]:
        """Get airport coordinates from navdata."""
        ap = self.nav_data.get_airport(icao.upper())
        if ap is None:
            return None, None
        return float(ap.Lat()), float(ap.Lon())

    def _get_runway_coords(self, icao: str, runway: str) -> tuple[float, float] | None:
        """Get coordinates for a specific runway end."""
        ap = self.nav_data.get_airport(icao.upper())
        if ap is None:
            return None
        for i in range(ap.RunwaysLength()):
            rw = ap.Runways(i)
            for j in range(rw.EndsLength()):
                end = rw.Ends(j)
                end_name = (
                    end.Name().decode("utf-8")
                    if isinstance(end.Name(), bytes)
                    else (end.Name() or "")
                )
                if end_name == runway:
                    return float(end.Lat()), float(end.Lon())
        return None

    @staticmethod
    def _dedup_consecutive(
        points: list[tuple[str, float, float]],
    ) -> list[tuple[str, float, float]]:
        """Remove consecutive duplicate points."""
        result: list[tuple[str, float, float]] = []
        for p in points:
            if result and result[-1][0] == p[0] and result[-1][1] == p[1] and result[-1][2] == p[2]:
                continue
            result.append(p)
        return result

    def _truncate_approach_path(
        self,
        points: list[tuple[str, float, float]],
        runway_coords: tuple[float, float],
    ) -> list[tuple[str, float, float]]:
        """Truncate approach path at the runway, excluding missed approach legs.

        Strategy (in order):
        1. Unnamed point matching runway threshold coords -> truncate before it.
        2. First MA*/MD* point -> truncate before it.
        3. Point closest to runway -> truncate after it (include it).
        """
        if not points:
            return []

        rwy_lat, rwy_lon = runway_coords
        RUNWAY_MATCH_THRESHOLD = 0.0002  # degrees, ~22 meters

        # Strategy 1: unnamed runway threshold marker
        for i, (name, lat, lon) in enumerate(points):
            if not name:
                dist = ((lat - rwy_lat) ** 2 + (lon - rwy_lon) ** 2) ** 0.5
                if dist <= RUNWAY_MATCH_THRESHOLD:
                    return points[:i]

        # Strategy 2: explicit missed approach point
        for i, (name, _lat, _lon) in enumerate(points):
            if name.startswith(("MA", "MD")):
                return points[:i]

        # Strategy 3: closest point to runway
        min_dist = float("inf")
        min_idx = 0
        for i, (_name, lat, lon) in enumerate(points):
            dist = ((lat - rwy_lat) ** 2 + (lon - rwy_lon) ** 2) ** 0.5
            if dist < min_dist:
                min_dist = dist
                min_idx = i

        return points[: min_idx + 1]


class AirportConnector:
    """Builds temporary airport connections without modifying shared node list."""

    def __init__(self, airport_maps: dict[str, str], node_index: dict):
        self.airport_maps = airport_maps
        self.node_index = node_index
        self._temp_nodes: dict[str, Node] = {}
        self._next_temp_iid = -3

    def _find_node(self, name: str, lat: float, lon: float) -> Node | None:
        key = (name, round(lat, 6), round(lon, 6))
        return self.node_index.get(key)

    def _get_or_create_temp(self, name: str, lat: float, lon: float) -> Node:
        """Get existing temp node or create new one for off-network waypoints."""
        if name not in self._temp_nodes:
            self._temp_nodes[name] = Node(
                iid=self._next_temp_iid,
                name=name,
                px=lat,
                py=lon,
            )
            self._next_temp_iid -= 1
        return self._temp_nodes[name]

    @staticmethod
    def _has_waypoint_data(line: str) -> bool:
        """Check if a line contains waypoint name + lat/lon data."""
        return line.startswith(("CF,", "TF,", "IF,", "DF,"))

    def build_sid(self, icao: str, filter_name: str | None = None) -> AirportConnection | None:
        """Build departure (SID) connections for an airport."""
        icao = icao.upper()
        if icao not in self.airport_maps:
            return None

        datasource = self.airport_maps[icao]
        ap_lat, ap_lon = self._get_airport_coords(icao)
        if ap_lat is None:
            return None

        airport_node = Node(iid=-1, name=icao, px=ap_lat, py=ap_lon)

        # Phase 1: collect all segment types
        runway_segments = []  # [(proc_name, runway, exit_node, points)]
        common_segments = {}  # {proc_name: (exit_node, points)}
        transition_segments = []  # [(proc_name, trans_name, from_node, to_node, points)]

        for segment in datasource.split("\n\n"):
            lines = segment.strip().split("\n")
            if not lines or not lines[0].startswith("SID,"):
                continue

            parts = lines[0].split(",")
            proc_name = parts[1] if len(parts) > 1 else ""
            field2 = parts[2] if len(parts) > 2 else ""
            stage = int(parts[3].strip()) if len(parts) > 3 and parts[3].strip().isdigit() else 0

            # Parse waypoint points (CF, TF, IF, DF lines)
            points = []
            for line in lines:
                if self._has_waypoint_data(line):
                    pp = line.split(",")
                    if len(pp) >= 4:
                        points.append((pp[1], float(pp[2]), float(pp[3])))

            # Parse exit point from last line
            last_line = lines[-1]
            last_parts = last_line.split(",")
            if len(last_parts) < 4:
                continue
            exit_name = last_parts[1].strip()
            try:
                exit_lat = float(last_parts[2])
                exit_lon = float(last_parts[3])
            except ValueError:
                continue

            # Find in network or create temp node
            exit_node = self._find_node(exit_name, exit_lat, exit_lon)
            if exit_node is None:
                exit_node = self._get_or_create_temp(exit_name, exit_lat, exit_lon)

            if stage in (3, 6):
                # Transition segment: from = second line (IF point)
                if len(lines) < 2:
                    continue
                first_data = lines[1].split(",")
                if len(first_data) < 4:
                    continue
                from_name = first_data[1].strip()
                try:
                    from_lat = float(first_data[2])
                    from_lon = float(first_data[3])
                except ValueError:
                    continue
                from_node = self._find_node(from_name, from_lat, from_lon)
                if from_node is None:
                    from_node = self._get_or_create_temp(from_name, from_lat, from_lon)
                transition_segments.append((proc_name, field2, from_node, exit_node, points))
            elif field2 == "ALL":
                common_segments[proc_name] = (exit_node, points)
            else:
                runway_segments.append((proc_name, field2, exit_node, points))

        # Apply filter if specified: find all procedure names containing the target waypoint,
        # then keep all segments belonging to those procedures.
        if filter_name:
            target_procs = set()
            for proc_name, runway, exit_node, points in runway_segments:
                if exit_node.name == filter_name:
                    target_procs.add(proc_name)
            for proc_name, (exit_node, points) in common_segments.items():
                if exit_node.name == filter_name:
                    target_procs.add(proc_name)
            for proc_name, trans_name, from_node, to_node, points in transition_segments:
                if to_node.name == filter_name:
                    target_procs.add(proc_name)

            runway_segments = [
                (proc_name, runway, exit_node, points)
                for proc_name, runway, exit_node, points in runway_segments
                if proc_name in target_procs
            ]
            common_segments = {k: v for k, v in common_segments.items() if k in target_procs}
            transition_segments = [
                (proc_name, trans_name, from_node, to_node, points)
                for proc_name, trans_name, from_node, to_node, points in transition_segments
                if proc_name in target_procs
            ]

        # Phase 2: build connections and internal edges
        connections = []
        transition_edges = []
        internal_edges = []
        added_exit_nodes = set()

        # Airport -> runway exit points
        for proc_name, runway, exit_node, points in runway_segments:
            if exit_node.name not in added_exit_nodes:
                connections.append(
                    Edge(
                        nfrom=airport_node.iid,
                        nend=exit_node.iid,
                        name="SID",
                    )
                )
                added_exit_nodes.add(exit_node.name)

        # Fallback: if no runway segments, connect airport to common/transition exit points
        if not runway_segments:
            for proc_name, (exit_node, points) in common_segments.items():
                if exit_node.name not in added_exit_nodes:
                    connections.append(
                        Edge(
                            nfrom=airport_node.iid,
                            nend=exit_node.iid,
                            name="SID",
                        )
                    )
                    added_exit_nodes.add(exit_node.name)
            for proc_name, trans_name, from_node, to_node, points in transition_segments:
                if to_node.name not in added_exit_nodes:
                    connections.append(
                        Edge(
                            nfrom=airport_node.iid,
                            nend=to_node.iid,
                            name="SID",
                        )
                    )
                    added_exit_nodes.add(to_node.name)

        # Runway exit -> common exit
        for proc_name, runway, exit_node, points in runway_segments:
            if proc_name in common_segments:
                common_node, common_points = common_segments[proc_name]
                if common_node is not None and exit_node is not None:
                    internal_edges.append(
                        Edge(
                            nfrom=exit_node.iid,
                            nend=common_node.iid,
                            name="SID",
                        )
                    )

        # Common exit -> transition start
        for proc_name, trans_name, from_node, to_node, points in transition_segments:
            if proc_name in common_segments:
                common_node, common_points = common_segments[proc_name]
                if common_node is not None and from_node is not None:
                    internal_edges.append(
                        Edge(
                            nfrom=common_node.iid,
                            nend=from_node.iid,
                            name="SID",
                        )
                    )

        # Transition edges (start -> end)
        for proc_name, trans_name, from_node, to_node, points in transition_segments:
            if from_node is not None and to_node is not None:
                transition_edges.append(
                    Edge(
                        nfrom=from_node.iid,
                        nend=to_node.iid,
                        name="SID",
                    )
                )

        # Phase 3: build procedures with merged common segments and transitions
        procedures = {}
        for proc_name, runway, exit_node, points in runway_segments:
            # SID: runway points first, then common points (runway -> common)
            merged_points = list(points)
            if proc_name in common_segments:
                common_node, common_points = common_segments[proc_name]
                seen = {p[0] for p in merged_points}
                for cp in common_points:
                    if cp[0] not in seen:
                        merged_points.append(cp)

            # Collect transitions for this procedure
            transitions = []
            for tp in transition_segments:
                if tp[0] == proc_name:
                    transitions.append((tp[1], tp[4]))

            proc = Procedure(
                name=proc_name, runway=runway, points=merged_points, transitions=transitions
            )
            if exit_node.name not in procedures:
                procedures[exit_node.name] = [proc]
            else:
                procedures[exit_node.name].append(proc)

        # Fallback: build procedures from common/transition when no runway segments
        if not runway_segments:
            # Build base procedures first
            base_procs = {}

            for proc_name, (exit_node, points) in common_segments.items():
                merged_points = list(points)
                seen = {p[0] for p in merged_points}
                transitions = []
                for tp in transition_segments:
                    if tp[0] == proc_name:
                        transitions.append((tp[1], tp[4]))
                        for p in tp[4]:
                            if p[0] not in seen:
                                merged_points.append(p)
                                seen.add(p[0])
                base_procs[proc_name] = Procedure(
                    name=proc_name, runway="ALL", points=merged_points, transitions=transitions
                )

            for proc_name, trans_name, from_node, to_node, points in transition_segments:
                if proc_name not in base_procs:
                    transitions = [(trans_name, points)]
                    base_procs[proc_name] = Procedure(
                        name=proc_name, runway="ALL", points=points, transitions=transitions
                    )

            # Register by common exit node
            for proc_name, (exit_node, points) in common_segments.items():
                proc = base_procs[proc_name]
                if exit_node.name not in procedures:
                    procedures[exit_node.name] = [proc]
                else:
                    procedures[exit_node.name].append(proc)

            # Register by transition end node (to_node) — A* may route airport -> to_node directly
            seen_keys = set()
            for proc_name, trans_name, from_node, to_node, points in transition_segments:
                proc = base_procs[proc_name]
                key = (to_node.name, proc_name)
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                if to_node.name not in procedures:
                    procedures[to_node.name] = [proc]
                else:
                    procedures[to_node.name].append(proc)

        return AirportConnection(
            airport_node=airport_node,
            connections=connections,
            procedures=procedures,
            transition_edges=transition_edges,
            temp_nodes=list(self._temp_nodes.values()),
            internal_edges=internal_edges,
        )

    def build_star(self, icao: str, filter_name: str | None = None) -> AirportConnection | None:
        """Build arrival (STAR) connections for an airport."""
        icao = icao.upper()
        if icao not in self.airport_maps:
            return None

        datasource = self.airport_maps[icao]
        ap_lat, ap_lon = self._get_airport_coords(icao)
        if ap_lat is None:
            return None

        airport_node = Node(iid=-2, name=icao, px=ap_lat, py=ap_lon)

        # Phase 1: collect all segment types
        runway_segments = []
        common_segments = {}
        transition_segments = []

        for segment in datasource.split("\n\n"):
            lines = segment.strip().split("\n")
            if not lines or not lines[0].startswith("STAR,"):
                continue

            parts = lines[0].split(",")
            proc_name = parts[1] if len(parts) > 1 else ""
            field2 = parts[2] if len(parts) > 2 else ""
            stage = int(parts[3].strip()) if len(parts) > 3 and parts[3].strip().isdigit() else 0

            # Parse waypoint points
            points = []
            for line in lines:
                if self._has_waypoint_data(line):
                    pp = line.split(",")
                    if len(pp) >= 4:
                        points.append((pp[1], float(pp[2]), float(pp[3])))

            # Parse entry point from first data line
            if len(lines) < 2:
                continue
            first_data = lines[1].split(",")
            if len(first_data) < 4:
                continue
            entry_name = first_data[1].strip()
            try:
                entry_lat = float(first_data[2])
                entry_lon = float(first_data[3])
            except ValueError:
                continue

            entry_node = self._find_node(entry_name, entry_lat, entry_lon)
            if entry_node is None:
                entry_node = self._get_or_create_temp(entry_name, entry_lat, entry_lon)

            if stage in (1, 4):
                # Transition segment: to = last line exit point, from = entry point
                last_line = lines[-1]
                last_parts = last_line.split(",")
                if len(last_parts) < 4:
                    continue
                to_name = last_parts[1].strip()
                try:
                    to_lat = float(last_parts[2])
                    to_lon = float(last_parts[3])
                except ValueError:
                    continue
                to_node = self._find_node(to_name, to_lat, to_lon)
                if to_node is None:
                    to_node = self._get_or_create_temp(to_name, to_lat, to_lon)
                transition_segments.append((proc_name, field2, entry_node, to_node, points))
            elif field2 == "ALL":
                common_segments[proc_name] = (entry_node, points)
            else:
                runway_segments.append((proc_name, field2, entry_node, points))

        # Apply filter if specified: find all procedure names containing the target waypoint,
        # then keep all segments belonging to those procedures.
        if filter_name:
            target_procs = set()
            for proc_name, runway, entry_node, points in runway_segments:
                if entry_node.name == filter_name:
                    target_procs.add(proc_name)
            for proc_name, (entry_node, points) in common_segments.items():
                if entry_node.name == filter_name:
                    target_procs.add(proc_name)
            for proc_name, trans_name, from_node, to_node, points in transition_segments:
                if from_node.name == filter_name:
                    target_procs.add(proc_name)

            runway_segments = [
                (proc_name, runway, entry_node, points)
                for proc_name, runway, entry_node, points in runway_segments
                if proc_name in target_procs
            ]
            common_segments = {k: v for k, v in common_segments.items() if k in target_procs}
            transition_segments = [
                (proc_name, trans_name, from_node, to_node, points)
                for proc_name, trans_name, from_node, to_node, points in transition_segments
                if proc_name in target_procs
            ]

        # Phase 2: build connections and internal edges
        connections = []
        transition_edges = []
        internal_edges = []
        added_entry_nodes = set()

        # Network -> airport (from runway entry points)
        for proc_name, runway, entry_node, points in runway_segments:
            if entry_node.name not in added_entry_nodes:
                connections.append(
                    Edge(
                        nfrom=entry_node.iid,
                        nend=airport_node.iid,
                        name="STAR",
                    )
                )
                added_entry_nodes.add(entry_node.name)

        # Fallback: if no runway segments, connect common/transition entry points to airport
        if not runway_segments:
            for proc_name, (entry_node, points) in common_segments.items():
                if entry_node.name not in added_entry_nodes:
                    connections.append(
                        Edge(
                            nfrom=entry_node.iid,
                            nend=airport_node.iid,
                            name="STAR",
                        )
                    )
                    added_entry_nodes.add(entry_node.name)
            for proc_name, trans_name, from_node, to_node, points in transition_segments:
                if from_node.name not in added_entry_nodes:
                    connections.append(
                        Edge(
                            nfrom=from_node.iid,
                            nend=airport_node.iid,
                            name="STAR",
                        )
                    )
                    added_entry_nodes.add(from_node.name)

        # Transition end -> common entry
        for proc_name, trans_name, from_node, to_node, points in transition_segments:
            if proc_name in common_segments:
                common_node, common_points = common_segments[proc_name]
                if to_node is not None and common_node is not None:
                    internal_edges.append(
                        Edge(
                            nfrom=to_node.iid,
                            nend=common_node.iid,
                            name="STAR",
                        )
                    )

        # Common entry -> runway entry
        for proc_name, runway, entry_node, points in runway_segments:
            if proc_name in common_segments:
                common_node, common_points = common_segments[proc_name]
                if common_node is not None and entry_node is not None:
                    internal_edges.append(
                        Edge(
                            nfrom=common_node.iid,
                            nend=entry_node.iid,
                            name="STAR",
                        )
                    )

        # Transition edges
        for proc_name, trans_name, from_node, to_node, points in transition_segments:
            if from_node is not None and to_node is not None:
                transition_edges.append(
                    Edge(
                        nfrom=from_node.iid,
                        nend=to_node.iid,
                        name="STAR",
                    )
                )

        # Phase 3: build procedures
        procedures = {}
        for proc_name, runway, entry_node, points in runway_segments:
            # STAR: common points first, then runway points (common -> runway)
            merged_points = []
            seen = set()
            if proc_name in common_segments:
                common_node, common_points = common_segments[proc_name]
                for cp in common_points:
                    if cp[0] not in seen:
                        merged_points.append(cp)
                        seen.add(cp[0])
            for p in points:
                if p[0] not in seen:
                    merged_points.append(p)
                    seen.add(p[0])

            # Collect transitions for this procedure
            transitions = []
            for tp in transition_segments:
                if tp[0] == proc_name:
                    transitions.append((tp[1], tp[4]))

            proc = Procedure(
                name=proc_name, runway=runway, points=merged_points, transitions=transitions
            )
            if entry_node.name not in procedures:
                procedures[entry_node.name] = [proc]
            else:
                procedures[entry_node.name].append(proc)

        # Fallback: build procedures from common/transition when no runway segments
        if not runway_segments:
            # Build base procedures first
            base_procs = {}

            for proc_name, (entry_node, points) in common_segments.items():
                merged_points = []
                seen = set()
                for p in points:
                    if p[0] not in seen:
                        merged_points.append(p)
                        seen.add(p[0])
                transitions = []
                for tp in transition_segments:
                    if tp[0] == proc_name:
                        transitions.append((tp[1], tp[4]))
                        for p in tp[4]:
                            if p[0] not in seen:
                                merged_points.append(p)
                                seen.add(p[0])
                base_procs[proc_name] = Procedure(
                    name=proc_name, runway="ALL", points=merged_points, transitions=transitions
                )

            for proc_name, trans_name, from_node, to_node, points in transition_segments:
                if proc_name not in base_procs:
                    transitions = [(trans_name, points)]
                    base_procs[proc_name] = Procedure(
                        name=proc_name, runway="ALL", points=points, transitions=transitions
                    )

            # Register by common entry node
            for proc_name, (entry_node, points) in common_segments.items():
                proc = base_procs[proc_name]
                if entry_node.name not in procedures:
                    procedures[entry_node.name] = [proc]
                else:
                    procedures[entry_node.name].append(proc)

            # Register by transition start node (from_node).
            # A* may route from_node -> airport directly.
            seen_keys = set()
            for proc_name, trans_name, from_node, to_node, points in transition_segments:
                proc = base_procs[proc_name]
                key = (from_node.name, proc_name)
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                if from_node.name not in procedures:
                    procedures[from_node.name] = [proc]
                else:
                    procedures[from_node.name].append(proc)

        return AirportConnection(
            airport_node=airport_node,
            connections=connections,
            procedures=procedures,
            transition_edges=transition_edges,
            temp_nodes=list(self._temp_nodes.values()),
            internal_edges=internal_edges,
        )

    def _get_runway_names(self, icao: str) -> list[str]:
        """Extract runway end names from airport raw data."""
        if icao not in self.airport_maps:
            return []
        names = []
        for line in self.airport_maps[icao].strip().split("\n"):
            parts = line.strip().split(",")
            if len(parts) >= 2 and parts[0].strip() == "R":
                names.append(parts[1].strip())
        return names

    def _get_airport_coords(self, icao: str) -> tuple[float | None, float | None]:
        global_dat = self.airport_maps.get("GLOBAL", [])
        for line in global_dat:
            parts = line.split(",")
            if len(parts) >= 5 and parts[0].strip() == "A" and parts[1].strip() == icao:
                try:
                    return float(parts[3].strip()), float(parts[4].strip())
                except ValueError:
                    continue
        return None, None

    def get_airport_names(self, icao: str) -> list[str]:
        """Get airport name(s) from global data."""
        icao = icao.upper()
        names = []
        global_dat = self.airport_maps.get("GLOBAL", [])
        for line in global_dat:
            parts = line.split(",")
            if len(parts) >= 3 and parts[0].strip() == "A" and parts[1].strip() == icao:
                names.append(parts[2].strip())
        return names
