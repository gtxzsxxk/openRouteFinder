"""Airport SID/STAR parsing and temporary connector generation."""

from collections import defaultdict
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional

from openRouterFinder.core.graph import Node, Edge


@dataclass
class Procedure:
    """SID or STAR procedure definition."""
    name: str
    runway: str
    points: List[Tuple[str, float, float]]  # (name, lat, lon)
    transitions: List[Tuple[str, List[Tuple[str, float, float]]]] = field(default_factory=list)


@dataclass
class AirportConnection:
    """Temporary airport connection for a single search."""
    airport_node: Node
    connections: List[Edge]  # edges FROM airport TO network (SID) or FROM network TO airport (STAR)
    procedures: Dict[str, List[Procedure]]  # anchor_point -> [Procedure, ...]
    transition_edges: List[Edge] = field(default_factory=list)
    temp_nodes: List[Node] = field(default_factory=list)  # temp nodes for waypoints not in nav network
    internal_edges: List[Edge] = field(default_factory=list)  # edges within procedures


class FlatbuffersAirportConnector:
    """Builds temporary airport connections from structured FlatBuffers navdata."""

    def __init__(self, nav_data):
        self.nav_data = nav_data
        self._temp_nodes: Dict[str, Node] = {}
        self._next_temp_iid = -3

    def _find_node(self, name: str, lat: float, lon: float) -> Optional[Node]:
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

    def _leg_to_point(self, leg) -> Optional[Tuple[str, float, float]]:
        """Convert a FlatBuffers ProcLeg to (name, lat, lon)."""
        name = leg.Name()
        if name is None:
            return None
        name = name.decode("utf-8") if isinstance(name, bytes) else name
        if not name:
            return None
        return (name, float(leg.Lat()), float(leg.Lon()))

    def _get_leg_points(self, procedure) -> List[Tuple[str, float, float]]:
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

    def _get_transition_points(self, trans) -> List[Tuple[str, float, float]]:
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

    def _resolve_node(self, name: str, lat: float, lon: float) -> Node:
        """Find node in network or create temp node."""
        node = self._find_node(name, lat, lon)
        if node is None:
            node = self._get_or_create_temp(name, lat, lon)
        return node

    def _split_transition_options(self, points: List[Tuple[str, float, float]], anchor_name: str) -> List[List[Tuple[str, float, float]]]:
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
                if [p[0] for p in remaining[i:i + opt_len]] == opt_names:
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
            runway_segments: list of (proc_name, runway, anchor_node, points, transitions, is_main_legs)
            common_segments: dict of proc_name -> (anchor_node, points, transitions)
            transition_segments: list of (proc_name, runway, anchor_node, points, transitions, is_main_legs)
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
            proc_name = name_bytes.decode("utf-8") if isinstance(name_bytes, bytes) else (name_bytes or "")
            rwy_bytes = proc.Runway()
            runway = rwy_bytes.decode("utf-8") if isinstance(rwy_bytes, bytes) else (rwy_bytes or "")

            points = self._get_leg_points(proc)

            # Collect and split transitions. Fenix sometimes concatenates
            # multiple route options inside a single transition; we split them
            # here so downstream code never sees concatenated data.
            transitions = []
            for j in range(proc.TransitionsLength()):
                trans = proc.Transitions(j)
                trans_name_bytes = trans.Name()
                trans_name = trans_name_bytes.decode("utf-8") if isinstance(trans_name_bytes, bytes) else (trans_name_bytes or "")
                trans_points = self._get_transition_points(trans)
                if trans_points:
                    t_anchor_name = trans_points[-1][0]
                    options = self._split_transition_options(trans_points, t_anchor_name)
                    for option in options:
                        transitions.append((trans_name, option))
                else:
                    transitions.append((trans_name, trans_points))

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
                    runway_segments.append((proc_name, runway, anchor_node, points, transitions, True))

                # Also generate runway segments from transitions so the full
                # runway->network path is available for display and edge building.
                # Transitions are already split into clean options above.
                for trans_name, trans_points in transitions:
                    if not trans_points:
                        continue
                    runway_name = trans_name[2:] if trans_name.startswith("RW") else trans_name
                    if proc_type == 1:
                        t_anchor_name, t_anchor_lat, t_anchor_lon = trans_points[-1]
                        t_anchor_node = self._resolve_node(t_anchor_name, t_anchor_lat, t_anchor_lon)
                        runway_segments.append((proc_name, runway_name, t_anchor_node, trans_points, [], False))
                    else:
                        entry_name, entry_lat, entry_lon = trans_points[0]
                        entry_node = self._resolve_node(entry_name, entry_lat, entry_lon)
                        runway_segments.append((proc_name, runway_name, entry_node, trans_points, [], False))

                # For SID, reverse transitions so they're runway->common
                # (consistent with transition-only SIDs below)
                if proc_type == 1:
                    transitions = [(t[0], list(reversed(t[1]))) for t in transitions]

                # Add to transition_segments for edge building
                transition_segments.append((proc_name, runway, anchor_node, points, transitions, True))

            elif transitions:
                # No main legs but has transitions: each transition is a runway segment
                # (Fenix stores some airports' SID/STAR legs entirely in transitions)
                # For SID transitions, legs are stored network->airport, so the
                # airway anchor is the FIRST point. For STAR, it's the LAST point.
                for trans_name, trans_points in transitions:
                    if not trans_points:
                        continue
                    runway_name = trans_name[2:] if trans_name.startswith("RW") else trans_name
                    if proc_type == 1:
                        # SID transitions are stored airport->network.
                        # The network-side exit point is the last point.
                        anchor_name, anchor_lat, anchor_lon = trans_points[-1]
                        anchor_node = self._resolve_node(anchor_name, anchor_lat, anchor_lon)
                        runway_segments.append((proc_name, runway_name, anchor_node, trans_points, [], False))
                        transition_segments.append((proc_name, runway_name, anchor_node, trans_points, [], False))
                    else:
                        # STAR transitions are stored network->airport.
                        # The airport-side entry point is the last point.
                        # Keep network->airport order so internal_edges and display match flight direction.
                        anchor_name, anchor_lat, anchor_lon = trans_points[-1]
                        anchor_node = self._resolve_node(anchor_name, anchor_lat, anchor_lon)
                        # Network-side entry is the first point; use it for connections (A* entry)
                        entry_name, entry_lat, entry_lon = trans_points[0]
                        entry_node = self._resolve_node(entry_name, entry_lat, entry_lon)
                        runway_segments.append((proc_name, runway_name, entry_node, trans_points, [], False))
                        transition_segments.append((proc_name, runway_name, anchor_node, trans_points, [], False))

        return runway_segments, common_segments, transition_segments

    def _apply_filter(self, filter_name: Optional[str], runway_segments, common_segments, transition_segments, proc_type: int):
        """Filter procedures by any waypoint name in the procedure."""
        if not filter_name:
            return runway_segments, common_segments, transition_segments

        def _contains_filter(points, transitions):
            for p in points:
                if p[0] == filter_name:
                    return True
            for _, t_points in transitions:
                for p in t_points:
                    if p[0] == filter_name:
                        return True
            return False

        target_procs = set()
        for proc_name, runway, anchor_node, points, transitions, is_main in runway_segments:
            if _contains_filter(points, transitions):
                target_procs.add(proc_name)
        for proc_name, (anchor_node, points, transitions) in common_segments.items():
            if _contains_filter(points, transitions):
                target_procs.add(proc_name)

        runway_segments = [
            (proc_name, runway, anchor_node, points, transitions, is_main)
            for proc_name, runway, anchor_node, points, transitions, is_main in runway_segments
            if proc_name in target_procs
        ]
        common_segments = {
            k: v for k, v in common_segments.items()
            if k in target_procs
        }
        transition_segments = [
            (proc_name, runway, anchor_node, points, transitions, is_main)
            for proc_name, runway, anchor_node, points, transitions, is_main in transition_segments
            if proc_name in target_procs
        ]
        return runway_segments, common_segments, transition_segments

    @staticmethod
    def _deduplicate_procedures(procedures: Dict[str, List[Procedure]]) -> Dict[str, List[Procedure]]:
        """Deduplicate procedures by (name, runway), keeping the one with the most points."""
        result: Dict[str, List[Procedure]] = {}
        for key, proc_list in procedures.items():
            seen: Dict[Tuple[str, str], Procedure] = {}
            for proc in proc_list:
                ident = (proc.name, proc.runway)
                if ident not in seen:
                    seen[ident] = proc
                elif len(proc.points) > len(seen[ident].points):
                    seen[ident] = proc
            if seen:
                result[key] = list(seen.values())
        return result

    def _base_name(self, proc_name: str) -> str:
        """Extract alphabetic prefix for matching common/runway procedure variants.

        Fenix uses suffixes like digits+letters (RUSD2G, RUSD9Z) or just digits
        (BOVMA8, CHINS5). The base name is the leading alphabetic portion.
        """
        i = 0
        while i < len(proc_name) and proc_name[i].isalpha():
            i += 1
        return proc_name[:i] if i > 0 else proc_name

    def _register_common_procedures(self, common_segments, procedures, key_from_points):
        """Register common segment procedures for runways covered by their transitions.

        key_from_points: callable(points) -> str, extracts the dict key from
        the common segment's main-leg points (e.g. lambda pts: pts[-1][0] for SID).
        """
        for proc_name, (anchor_node, points, transitions) in common_segments.items():
            merged_points = list(points)
            key = key_from_points(points) if points else anchor_node.name

            rwy_names_from_trans = set()
            for trans_name, _ in transitions:
                rwy_name = trans_name[2:] if trans_name.startswith("RW") else trans_name
                if rwy_name:
                    rwy_names_from_trans.add(rwy_name)

            if rwy_names_from_trans:
                for rwy_name in sorted(rwy_names_from_trans):
                    proc = Procedure(name=proc_name, runway=rwy_name, points=merged_points, transitions=transitions)
                    if key not in procedures:
                        procedures[key] = [proc]
                    else:
                        procedures[key].append(proc)
            else:
                proc = Procedure(name=proc_name, runway="ALL", points=merged_points, transitions=transitions)
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
        else:  # STAR transition: airport side is the last point
            return self._resolve_node(points[-1][0], points[-1][1], points[-1][2])

    def build_sid(self, icao: str, filter_name: Optional[str] = None) -> Optional[AirportConnection]:
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

        connections = []
        transition_edges = []
        internal_edges = []
        added_exit_nodes = set()

        # Determine which procedures have transition-generated runway segments.
        # When transitions exist, the airport must connect to the transition
        # start points (runway side), not to the main/common segment.
        procs_with_transitions = set()
        for proc_name, runway, exit_node, points, transitions, is_main in runway_segments:
            if not is_main:
                procs_with_transitions.add(proc_name)

        # Airport -> runway exit points (first point of the path for transition options)
        for proc_name, runway, exit_node, points, transitions, is_main in runway_segments:
            if is_main and proc_name in procs_with_transitions:
                continue
            conn_target = self._airport_side_node(1, points, exit_node, is_main)
            if conn_target.name not in added_exit_nodes:
                connections.append(Edge(nfrom=airport_node.iid, nend=conn_target.iid, name="SID"))
                added_exit_nodes.add(conn_target.name)

        # Create internal edges along main legs for SID.
        # Fenix stores SID legs airport->network; points are already in that order.
        for proc_name, runway, exit_node, points, transitions, is_main in runway_segments:
            for i in range(len(points) - 1):
                from_node = self._resolve_node(points[i][0], points[i][1], points[i][2])
                to_node = self._resolve_node(points[i + 1][0], points[i + 1][1], points[i + 1][2])
                internal_edges.append(Edge(nfrom=from_node.iid, nend=to_node.iid, name="SID"))
        for proc_name, (exit_node, points, transitions) in common_segments.items():
            for i in range(len(points) - 1):
                from_node = self._resolve_node(points[i][0], points[i][1], points[i][2])
                to_node = self._resolve_node(points[i + 1][0], points[i + 1][1], points[i + 1][2])
                internal_edges.append(Edge(nfrom=from_node.iid, nend=to_node.iid, name="SID"))

        # Fallback: connect airport to common/transition points when no runway segments
        if not runway_segments:
            for proc_name, (exit_node, points, transitions) in common_segments.items():
                if exit_node.name not in added_exit_nodes:
                    connections.append(Edge(nfrom=airport_node.iid, nend=exit_node.iid, name="SID"))
                    added_exit_nodes.add(exit_node.name)
            for proc_name, trans_name, from_node, to_node, t_points in self._flatten_transitions(transition_segments):
                if from_node.name not in added_exit_nodes:
                    connections.append(Edge(nfrom=airport_node.iid, nend=from_node.iid, name="SID"))
                    added_exit_nodes.add(from_node.name)

        # Note: internal edges from common_segments and runway_segments already
        # form continuous paths because the segments share endpoints. Explicit
        # connecting edges are unnecessary and can create duplicates/cycles.

        # Transition edges (start -> end)
        for proc_name, trans_name, from_node, to_node, t_points in self._flatten_transitions(transition_segments):
            if from_node is not None and to_node is not None:
                transition_edges.append(Edge(nfrom=from_node.iid, nend=to_node.iid, name="SID"))

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

        procedures = {}
        for (proc_name, runway), group in runway_groups.items():
            exit_node, points, transitions, is_main = group[0]
            merged_points = list(points)
            merged_transitions = list(transitions)

            if proc_name in common_segments:
                common_node, common_points, common_trans = common_segments[proc_name]
                seen = {p[0] for p in merged_points}
                for cp in common_points:
                    if cp[0] not in seen:
                        merged_points.append(cp)
                        seen.add(cp[0])
                for ct in common_trans:
                    ct_runway = ct[0][2:] if ct[0].startswith("RW") else ct[0]
                    if ct_runway == runway and ct not in merged_transitions:
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

            proc = Procedure(name=proc_name, runway=runway, points=merged_points, transitions=merged_transitions)
            # SID points are airport->network; key by merged network-side exit point
            key = merged_points[-1][0] if merged_points else exit_node.name
            if key not in procedures:
                procedures[key] = [proc]
            else:
                procedures[key].append(proc)

        # Also register common segment procedures as selectable exits.
        # Only offer for runways covered by this procedure's transitions.
        self._register_common_procedures(common_segments, procedures, lambda pts: pts[-1][0])

        procedures = self._deduplicate_procedures(procedures)

        return AirportConnection(
            airport_node=airport_node,
            connections=connections,
            procedures=procedures,
            transition_edges=transition_edges,
            temp_nodes=list(self._temp_nodes.values()),
            internal_edges=internal_edges,
        )

    def _collect_approach_bridges(self, icao: str) -> Dict[Tuple[str, str], List[Tuple[str, float, float]]]:
        """Collect Type=3 approach procedures and build (runway, entry_point) -> path mapping.

        Returns a dict mapping (runway, entry_point_name) to a list of points
        representing the full approach path from entry_point to the FAF.
        """
        ap = self.nav_data.get_airport(icao)
        if ap is None:
            return {}

        bridges: Dict[Tuple[str, str], List[Tuple[str, float, float]]] = {}

        for i in range(ap.ProceduresLength()):
            proc = ap.Procedures(i)
            if proc.Type() != 3:
                continue

            proc_name = proc.Name().decode("utf-8") if isinstance(proc.Name(), bytes) else (proc.Name() or "")
            runway = proc.Runway().decode("utf-8") if isinstance(proc.Runway(), bytes) else (proc.Runway() or "")
            if not runway:
                continue

            # Main legs: keep up to and including the FAF (FIxx/FFxx).
            # Points after the FAF are missed approach / go-around.
            main_points = self._get_leg_points(proc)
            approach_main = []
            for p in main_points:
                approach_main.append(p)
                if p[0].startswith(("FI", "FF")):
                    break

            # Process transitions (feeder routes)
            for j in range(proc.TransitionsLength()):
                trans = proc.Transitions(j)
                trans_name = trans.Name().decode("utf-8") if isinstance(trans.Name(), bytes) else (trans.Name() or "")
                trans_points = self._get_transition_points(trans)
                if not trans_points:
                    continue

                # Split concatenated transitions. For approaches, transitions are
                # stored entry_point -> IAF, so the anchor is the last point (IAF).
                anchor_name = trans_points[-1][0] if trans_points else ""
                options = self._split_transition_options(trans_points, anchor_name)

                for option in options:
                    if not option:
                        continue
                    entry_name = option[0][0]
                    # Combine transition + main legs, avoiding duplicate IAF
                    full_path = list(option)
                    seen = {p[0] for p in full_path}
                    for p in approach_main:
                        if p[0] not in seen:
                            full_path.append(p)
                            seen.add(p[0])
                    # Register full bridge and all sub-bridges so a STAR that
                    # ends at any intermediate fix can join the approach there.
                    for i in range(len(full_path)):
                        sub_path = full_path[i:]
                        sub_entry = sub_path[0][0]
                        key = (runway, sub_entry)
                        if key not in bridges or len(sub_path) > len(bridges[key]):
                            bridges[key] = sub_path

            # If no transitions, use main legs directly
            if proc.TransitionsLength() == 0 and approach_main:
                entry_name = approach_main[0][0]
                key = (runway, entry_name)
                if key not in bridges or len(approach_main) > len(bridges[key]):
                    bridges[key] = list(approach_main)

        return bridges

    def build_star(self, icao: str, filter_name: Optional[str] = None) -> Optional[AirportConnection]:
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

        transition_edges = []
        internal_edges = []

        # Create internal edges along main legs and transition options for STAR.
        # Fenix stores STAR legs network->airport; iterate forward to match flight direction.
        for proc_name, runway, entry_node, points, transitions, is_main in runway_segments:
            for i in range(len(points) - 1):
                from_node = self._resolve_node(points[i][0], points[i][1], points[i][2])
                to_node = self._resolve_node(points[i + 1][0], points[i + 1][1], points[i + 1][2])
                internal_edges.append(Edge(nfrom=from_node.iid, nend=to_node.iid, name="STAR"))
        for proc_name, (entry_node, points, transitions) in common_segments.items():
            for i in range(len(points) - 1):
                from_node = self._resolve_node(points[i][0], points[i][1], points[i][2])
                to_node = self._resolve_node(points[i + 1][0], points[i + 1][1], points[i + 1][2])
                internal_edges.append(Edge(nfrom=from_node.iid, nend=to_node.iid, name="STAR"))

        # Note: internal edges from common_segments and runway_segments already
        # form continuous paths because the segments share endpoints. Explicit
        # connecting edges are unnecessary and can create duplicates/cycles.

        # Transition edges: STAR transitions are normalized airport->network,
        # but flight direction is network->airport, so reverse the edge.
        for proc_name, trans_name, from_node, to_node, t_points in self._flatten_transitions(transition_segments):
            if from_node is not None and to_node is not None:
                transition_edges.append(Edge(nfrom=to_node.iid, nend=from_node.iid, name="STAR"))

        # Build procedures from runway segments.
        # Merge matching common segment points and transitions so the full
        # network->airport path is available for display.
        # For transition-only procedures (no main legs), merge all options of
        # the same (name, runway) into one Procedure with transitions so each
        # option remains selectable in the frontend.
        runway_groups = defaultdict(list)
        for proc_name, runway, entry_node, points, transitions, is_main in runway_segments:
            runway_groups[(proc_name, runway)].append((entry_node, points, transitions, is_main))

        procedures = {}
        for (proc_name, runway), group in runway_groups.items():
            entry_node, points, transitions, is_main = group[0]
            merged_points = []
            seen = set()
            merged_transitions = list(transitions)

            if proc_name in common_segments:
                common_node, common_points, common_trans = common_segments[proc_name]
                for cp in common_points:
                    if cp[0] not in seen:
                        merged_points.append(cp)
                        seen.add(cp[0])
                for ct in common_trans:
                    ct_runway = ct[0][2:] if ct[0].startswith("RW") else ct[0]
                    if ct_runway == runway and ct not in merged_transitions:
                        merged_transitions.append(ct)
            for p in points:
                if p[0] not in seen:
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

            proc = Procedure(name=proc_name, runway=runway, points=merged_points, transitions=merged_transitions)
            # STAR main-legs are network->airport; key by merged network-side entry point.
            if merged_points:
                key = merged_points[0][0]
            else:
                key = entry_node.name
            if key not in procedures:
                procedures[key] = [proc]
            else:
                procedures[key].append(proc)

        # Also register common segment procedures as selectable entries.
        # Only offer for runways covered by this procedure's transitions.
        self._register_common_procedures(common_segments, procedures, lambda pts: pts[0][0])

        procedures = self._deduplicate_procedures(procedures)

        # Merge approach bridges (Type=3) into STAR procedures so the full
        # path from STAR endpoint to runway is available for display and routing.
        used_bridges: set = set()
        for key, proc_list in procedures.items():
            for proc in proc_list:
                if proc.points:
                    bridge_key = (proc.runway, proc.points[-1][0])
                    if bridge_key in approach_bridges:
                        bridge_points = approach_bridges[bridge_key]
                        seen = {p[0] for p in proc.points}
                        for bp in bridge_points:
                            if bp[0] not in seen:
                                proc.points.append(bp)
                                seen.add(bp[0])
                        used_bridges.add(bridge_key)

        # Build connections from each procedure's last point to the airport.
        # This ensures that when an approach bridge extends the path, the
        # connection originates from the final approach fix rather than the
        # STAR endpoint, forcing A* to follow the full approach path.
        connections: List[Edge] = []
        added_entry_nodes: set = set()
        for key, proc_list in procedures.items():
            for proc in proc_list:
                if proc.points:
                    last_name, last_lat, last_lon = proc.points[-1]
                    if last_name and last_name not in added_entry_nodes:
                        last_node = self._resolve_node(last_name, last_lat, last_lon)
                        connections.append(Edge(nfrom=last_node.iid, nend=airport_node.iid, name="STAR"))
                        added_entry_nodes.add(last_name)

        # Add internal edges for used approach bridges
        for bridge_key in used_bridges:
            bridge_points = approach_bridges[bridge_key]
            for i in range(len(bridge_points) - 1):
                from_node = self._resolve_node(bridge_points[i][0], bridge_points[i][1], bridge_points[i][2])
                to_node = self._resolve_node(bridge_points[i + 1][0], bridge_points[i + 1][1], bridge_points[i + 1][2])
                internal_edges.append(Edge(nfrom=from_node.iid, nend=to_node.iid, name="STAR"))

        return AirportConnection(
            airport_node=airport_node,
            connections=connections,
            procedures=procedures,
            transition_edges=transition_edges,
            temp_nodes=list(self._temp_nodes.values()),
            internal_edges=internal_edges,
        )

    def _flatten_transitions(self, transition_segments):
        """Flatten transition segments into (proc_name, trans_name, from_node, to_node, points) tuples."""
        result = []
        for proc_name, runway, anchor_node, points, transitions, is_main in transition_segments:
            for trans_name, t_points in transitions:
                if not t_points:
                    continue
                from_name, from_lat, from_lon = t_points[0]
                to_name, to_lat, to_lon = t_points[-1]
                from_node = self._resolve_node(from_name, from_lat, from_lon)
                to_node = self._resolve_node(to_name, to_lat, to_lon)
                result.append((proc_name, trans_name, from_node, to_node, t_points))
        return result

    def get_airport_names(self, icao: str) -> List[str]:
        """Get airport name(s) from navdata."""
        ap = self.nav_data.get_airport(icao.upper())
        if ap is None:
            return []
        name = ap.Name()
        if name is None:
            return []
        decoded = name.decode("utf-8") if isinstance(name, bytes) else name
        return [decoded] if decoded else []

    def _get_runway_names(self, icao: str) -> List[str]:
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
                    names.append(end_name.decode("utf-8") if isinstance(end_name, bytes) else end_name)
        return names

    def _get_airport_coords(self, icao: str) -> Tuple[Optional[float], Optional[float]]:
        """Get airport coordinates from navdata."""
        ap = self.nav_data.get_airport(icao.upper())
        if ap is None:
            return None, None
        return float(ap.Lat()), float(ap.Lon())


class AirportConnector:
    """Builds temporary airport connections without modifying shared node list."""

    def __init__(self, airport_maps: Dict[str, str], node_index: Dict):
        self.airport_maps = airport_maps
        self.node_index = node_index
        self._temp_nodes: Dict[str, Node] = {}
        self._next_temp_iid = -3

    def _find_node(self, name: str, lat: float, lon: float) -> Optional[Node]:
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

    def build_sid(self, icao: str, filter_name: Optional[str] = None) -> Optional[AirportConnection]:
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
        runway_segments = []   # [(proc_name, runway, exit_node, points)]
        common_segments = {}   # {proc_name: (exit_node, points)}
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
            elif field2 == 'ALL':
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
            common_segments = {
                k: v for k, v in common_segments.items()
                if k in target_procs
            }
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
                connections.append(Edge(
                    nfrom=airport_node.iid,
                    nend=exit_node.iid,
                    name="SID",
                ))
                added_exit_nodes.add(exit_node.name)

        # Fallback: if no runway segments, connect airport to common/transition exit points
        if not runway_segments:
            for proc_name, (exit_node, points) in common_segments.items():
                if exit_node.name not in added_exit_nodes:
                    connections.append(Edge(
                        nfrom=airport_node.iid,
                        nend=exit_node.iid,
                        name="SID",
                    ))
                    added_exit_nodes.add(exit_node.name)
            for proc_name, trans_name, from_node, to_node, points in transition_segments:
                if to_node.name not in added_exit_nodes:
                    connections.append(Edge(
                        nfrom=airport_node.iid,
                        nend=to_node.iid,
                        name="SID",
                    ))
                    added_exit_nodes.add(to_node.name)

        # Runway exit -> common exit
        for proc_name, runway, exit_node, points in runway_segments:
            if proc_name in common_segments:
                common_node, common_points = common_segments[proc_name]
                if common_node is not None and exit_node is not None:
                    internal_edges.append(Edge(
                        nfrom=exit_node.iid,
                        nend=common_node.iid,
                        name="SID",
                    ))

        # Common exit -> transition start
        for proc_name, trans_name, from_node, to_node, points in transition_segments:
            if proc_name in common_segments:
                common_node, common_points = common_segments[proc_name]
                if common_node is not None and from_node is not None:
                    internal_edges.append(Edge(
                        nfrom=common_node.iid,
                        nend=from_node.iid,
                        name="SID",
                    ))

        # Transition edges (start -> end)
        for proc_name, trans_name, from_node, to_node, points in transition_segments:
            if from_node is not None and to_node is not None:
                transition_edges.append(Edge(
                    nfrom=from_node.iid,
                    nend=to_node.iid,
                    name="SID",
                ))

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

            proc = Procedure(name=proc_name, runway=runway, points=merged_points, transitions=transitions)
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
                base_procs[proc_name] = Procedure(name=proc_name, runway='ALL', points=merged_points, transitions=transitions)

            for proc_name, trans_name, from_node, to_node, points in transition_segments:
                if proc_name not in base_procs:
                    transitions = [(trans_name, points)]
                    base_procs[proc_name] = Procedure(name=proc_name, runway='ALL', points=points, transitions=transitions)

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

    def build_star(self, icao: str, filter_name: Optional[str] = None) -> Optional[AirportConnection]:
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
            elif field2 == 'ALL':
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
            common_segments = {
                k: v for k, v in common_segments.items()
                if k in target_procs
            }
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
                connections.append(Edge(
                    nfrom=entry_node.iid,
                    nend=airport_node.iid,
                    name="STAR",
                ))
                added_entry_nodes.add(entry_node.name)

        # Fallback: if no runway segments, connect common/transition entry points to airport
        if not runway_segments:
            for proc_name, (entry_node, points) in common_segments.items():
                if entry_node.name not in added_entry_nodes:
                    connections.append(Edge(
                        nfrom=entry_node.iid,
                        nend=airport_node.iid,
                        name="STAR",
                    ))
                    added_entry_nodes.add(entry_node.name)
            for proc_name, trans_name, from_node, to_node, points in transition_segments:
                if from_node.name not in added_entry_nodes:
                    connections.append(Edge(
                        nfrom=from_node.iid,
                        nend=airport_node.iid,
                        name="STAR",
                    ))
                    added_entry_nodes.add(from_node.name)

        # Transition end -> common entry
        for proc_name, trans_name, from_node, to_node, points in transition_segments:
            if proc_name in common_segments:
                common_node, common_points = common_segments[proc_name]
                if to_node is not None and common_node is not None:
                    internal_edges.append(Edge(
                        nfrom=to_node.iid,
                        nend=common_node.iid,
                        name="STAR",
                    ))

        # Common entry -> runway entry
        for proc_name, runway, entry_node, points in runway_segments:
            if proc_name in common_segments:
                common_node, common_points = common_segments[proc_name]
                if common_node is not None and entry_node is not None:
                    internal_edges.append(Edge(
                        nfrom=common_node.iid,
                        nend=entry_node.iid,
                        name="STAR",
                    ))

        # Transition edges
        for proc_name, trans_name, from_node, to_node, points in transition_segments:
            if from_node is not None and to_node is not None:
                transition_edges.append(Edge(
                    nfrom=from_node.iid,
                    nend=to_node.iid,
                    name="STAR",
                ))

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

            proc = Procedure(name=proc_name, runway=runway, points=merged_points, transitions=transitions)
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
                base_procs[proc_name] = Procedure(name=proc_name, runway='ALL', points=merged_points, transitions=transitions)

            for proc_name, trans_name, from_node, to_node, points in transition_segments:
                if proc_name not in base_procs:
                    transitions = [(trans_name, points)]
                    base_procs[proc_name] = Procedure(name=proc_name, runway='ALL', points=points, transitions=transitions)

            # Register by common entry node
            for proc_name, (entry_node, points) in common_segments.items():
                proc = base_procs[proc_name]
                if entry_node.name not in procedures:
                    procedures[entry_node.name] = [proc]
                else:
                    procedures[entry_node.name].append(proc)

            # Register by transition start node (from_node) — A* may route from_node -> airport directly
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

    def _get_runway_names(self, icao: str) -> List[str]:
        """Extract runway end names from airport raw data."""
        if icao not in self.airport_maps:
            return []
        names = []
        for line in self.airport_maps[icao].strip().split("\n"):
            parts = line.strip().split(",")
            if len(parts) >= 2 and parts[0].strip() == "R":
                names.append(parts[1].strip())
        return names

    def _get_airport_coords(self, icao: str) -> Tuple[Optional[float], Optional[float]]:
        global_dat = self.airport_maps.get("GLOBAL", [])
        for line in global_dat:
            parts = line.split(",")
            if len(parts) >= 5 and parts[0].strip() == "A" and parts[1].strip() == icao:
                try:
                    return float(parts[3].strip()), float(parts[4].strip())
                except ValueError:
                    continue
        return None, None

    def get_airport_names(self, icao: str) -> List[str]:
        """Get airport name(s) from global data."""
        icao = icao.upper()
        names = []
        global_dat = self.airport_maps.get("GLOBAL", [])
        for line in global_dat:
            parts = line.split(",")
            if len(parts) >= 3 and parts[0].strip() == "A" and parts[1].strip() == icao:
                names.append(parts[2].strip())
        return names
