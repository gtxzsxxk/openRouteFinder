"""Airport SID/STAR parsing and temporary connector generation."""

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
        by concatenating them. We try forward split first (when options all
        start with the same point), then fall back to backward split (when
        options all end at the same anchor point).
        """
        if not points:
            return []

        # Forward split: if the first point repeats, each occurrence marks
        # the start of a new option. This handles transitions like IKAVO8
        # where all options start at IKAVO but end at different points.
        first_name = points[0][0]
        if first_name and first_name != anchor_name:
            first_indices = [i for i, p in enumerate(points) if p[0] == first_name]
            if len(first_indices) > 1:
                options = []
                seen = set()
                for i in range(len(first_indices)):
                    start = first_indices[i]
                    end = first_indices[i + 1] if i + 1 < len(first_indices) else len(points)
                    option = points[start:end]
                    if len(option) > 1:
                        opt_tuple = tuple(p[0] for p in option)
                        if opt_tuple not in seen:
                            seen.add(opt_tuple)
                            options.append(option)
                if options:
                    return options

        # Backward split: find occurrences of the anchor from the end.
        # This handles transitions like OMDE2G where options end at the
        # same anchor but start at different runway exits.
        result = []
        seen = set()
        i = len(points) - 1
        while i >= 0:
            if points[i][0] == anchor_name:
                j = i - 1
                while j >= 0 and points[j][0] != anchor_name:
                    j -= 1
                option = points[j + 1 : i + 1]
                if option:
                    opt_tuple = tuple(p[0] for p in option)
                    if opt_tuple not in seen:
                        seen.add(opt_tuple)
                        result.insert(0, option)
                i = j
            else:
                i -= 1
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

            # Collect transitions
            transitions = []
            for j in range(proc.TransitionsLength()):
                trans = proc.Transitions(j)
                trans_name_bytes = trans.Name()
                trans_name = trans_name_bytes.decode("utf-8") if isinstance(trans_name_bytes, bytes) else (trans_name_bytes or "")
                trans_points = self._get_transition_points(trans)
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
                for trans_name, trans_points in transitions:
                    if not trans_points:
                        continue
                    if proc_type == 1:
                        t_anchor_name, t_anchor_lat, t_anchor_lon = trans_points[-1]
                        t_anchor_node = self._resolve_node(t_anchor_name, t_anchor_lat, t_anchor_lon)
                        options = self._split_transition_options(trans_points, t_anchor_name)
                    else:
                        t_anchor_name, t_anchor_lat, t_anchor_lon = trans_points[-1]
                        options = self._split_transition_options(trans_points, t_anchor_name)
                        entry_name, entry_lat, entry_lon = trans_points[0]
                        entry_node = self._resolve_node(entry_name, entry_lat, entry_lon)
                        t_anchor_node = self._resolve_node(t_anchor_name, t_anchor_lat, t_anchor_lon)

                    runway_name = trans_name[2:] if trans_name.startswith("RW") else trans_name
                    for option in options:
                        if proc_type == 1:
                            runway_segments.append((proc_name, runway_name, t_anchor_node, option, [], False))
                        else:
                            runway_segments.append((proc_name, runway_name, entry_node, option, [], False))

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
                    if proc_type == 1:
                        # SID transitions are stored airport->network.
                        # The network-side exit point is the last point; use it to split options.
                        anchor_name, anchor_lat, anchor_lon = trans_points[-1]
                        anchor_node = self._resolve_node(anchor_name, anchor_lat, anchor_lon)
                        options = self._split_transition_options(trans_points, anchor_name)
                    else:
                        # STAR transitions are stored network->airport.
                        # The airport-side entry point is the last point; use it to split options.
                        # Keep network->airport order so internal_edges and display match flight direction.
                        anchor_name, anchor_lat, anchor_lon = trans_points[-1]
                        options = self._split_transition_options(trans_points, anchor_name)
                        # Network-side entry is the first point; use it for connections (A* entry)
                        entry_name, entry_lat, entry_lon = trans_points[0]
                        entry_node = self._resolve_node(entry_name, entry_lat, entry_lon)
                        anchor_node = self._resolve_node(anchor_name, anchor_lat, anchor_lon)
                    # Fenix transition names may have 'RW' prefix (e.g., 'RW36L');
                    # strip it to match actual runway designations.
                    runway_name = trans_name[2:] if trans_name.startswith("RW") else trans_name
                    for option in options:
                        if proc_type == 1:
                            # SID: anchor_node is network-side exit (used for both)
                            runway_segments.append((proc_name, runway_name, anchor_node, option, [], False))
                            transition_segments.append((proc_name, runway_name, anchor_node, option, [], False))
                        else:
                            # STAR: entry_node is network-side entry (for connections),
                            # anchor_node is airport-side entry (for transition edges)
                            runway_segments.append((proc_name, runway_name, entry_node, option, [], False))
                            transition_segments.append((proc_name, runway_name, anchor_node, option, [], False))

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

        # Airport -> runway exit points
        for proc_name, runway, exit_node, points, transitions, is_main in runway_segments:
            if exit_node.name not in added_exit_nodes:
                connections.append(Edge(nfrom=airport_node.iid, nend=exit_node.iid, name="SID"))
                added_exit_nodes.add(exit_node.name)

        # Always connect airport to common exit points too
        for proc_name, (exit_node, points, transitions) in common_segments.items():
            if exit_node.name not in added_exit_nodes:
                connections.append(Edge(nfrom=airport_node.iid, nend=exit_node.iid, name="SID"))
                added_exit_nodes.add(exit_node.name)

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

        # Also connect airport to transition end points (when no runway segments)
        if not runway_segments:
            for proc_name, trans_name, from_node, to_node, t_points in self._flatten_transitions(transition_segments):
                if to_node.name not in added_exit_nodes:
                    connections.append(Edge(nfrom=airport_node.iid, nend=to_node.iid, name="SID"))
                    added_exit_nodes.add(to_node.name)

        # Runway exit -> common exit (match by exact name)
        for proc_name, runway, exit_node, points, transitions, is_main in runway_segments:
            if proc_name in common_segments:
                common_node, common_points, common_trans = common_segments[proc_name]
                if common_node is not None and exit_node is not None:
                    internal_edges.append(Edge(nfrom=exit_node.iid, nend=common_node.iid, name="SID"))

        # Common exit -> transition start (match by exact name)
        for proc_name, trans_name, from_node, to_node, t_points in self._flatten_transitions(transition_segments):
            if proc_name in common_segments:
                common_node, common_points, common_trans = common_segments[proc_name]
                if common_node is not None and from_node is not None:
                    internal_edges.append(Edge(nfrom=common_node.iid, nend=from_node.iid, name="SID"))

        # Transition edges (start -> end)
        for proc_name, trans_name, from_node, to_node, t_points in self._flatten_transitions(transition_segments):
            if from_node is not None and to_node is not None:
                transition_edges.append(Edge(nfrom=from_node.iid, nend=to_node.iid, name="SID"))

        # Build procedures from runway segments.
        # Merge matching common segment points and transitions so the full
        # runway->network path is available for display.
        procedures = {}
        for proc_name, runway, exit_node, points, transitions, is_main in runway_segments:
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
                    if ct not in merged_transitions:
                        merged_transitions.append(ct)

            proc = Procedure(name=proc_name, runway=runway, points=merged_points, transitions=merged_transitions)
            # SID points are airport->network; key by network-side exit point
            key = points[-1][0] if points else exit_node.name
            if key not in procedures:
                procedures[key] = [proc]
            else:
                procedures[key].append(proc)

        # Also register common segment procedures as selectable exits.
        # Only offer for runways covered by this procedure's transitions.
        self._register_common_procedures(common_segments, procedures, lambda pts: pts[-1][0])

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

        # For STAR, common segment connections must use the network-side entry (points[0]),
        # not the airport-side anchor (points[-1]) which _collect_procedures stores.
        common_conn_by_name = {}
        for proc_name, (anchor_node, points, transitions) in common_segments.items():
            conn_node = (
                self._resolve_node(points[0][0], points[0][1], points[0][2])
                if points else anchor_node
            )
            common_conn_by_name[proc_name] = conn_node

        connections = []
        transition_edges = []
        internal_edges = []
        added_entry_nodes = set()

        # Network -> airport (from runway entry points)
        for proc_name, runway, entry_node, points, transitions, is_main in runway_segments:
            if entry_node.name not in added_entry_nodes:
                connections.append(Edge(nfrom=entry_node.iid, nend=airport_node.iid, name="STAR"))
                added_entry_nodes.add(entry_node.name)

        # Always connect common entry points to airport too
        for proc_name, (anchor_node, points, transitions) in common_segments.items():
            conn_node = (
                self._resolve_node(points[0][0], points[0][1], points[0][2])
                if points else anchor_node
            )
            if conn_node.name not in added_entry_nodes:
                connections.append(Edge(nfrom=conn_node.iid, nend=airport_node.iid, name="STAR"))
                added_entry_nodes.add(conn_node.name)

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

        # Also connect transition start points when no runway segments
        if not runway_segments:
            for proc_name, trans_name, from_node, to_node, t_points in self._flatten_transitions(transition_segments):
                if from_node.name not in added_entry_nodes:
                    connections.append(Edge(nfrom=from_node.iid, nend=airport_node.iid, name="STAR"))
                    added_entry_nodes.add(from_node.name)

        # Transition end -> common entry (match by exact name)
        # Use network-side entry node, not airport-side anchor.
        for proc_name, trans_name, from_node, to_node, t_points in self._flatten_transitions(transition_segments):
            if proc_name in common_conn_by_name:
                conn_node = common_conn_by_name[proc_name]
                if to_node is not None and conn_node is not None:
                    internal_edges.append(Edge(nfrom=to_node.iid, nend=conn_node.iid, name="STAR"))

        # Common entry -> runway entry (match by exact name)
        # Use network-side entry node, not airport-side anchor.
        for proc_name, runway, entry_node, points, transitions, is_main in runway_segments:
            if proc_name in common_conn_by_name:
                conn_node = common_conn_by_name[proc_name]
                if conn_node is not None and entry_node is not None:
                    internal_edges.append(Edge(nfrom=conn_node.iid, nend=entry_node.iid, name="STAR"))

        # Transition edges: STAR transitions are normalized airport->network,
        # but flight direction is network->airport, so reverse the edge.
        for proc_name, trans_name, from_node, to_node, t_points in self._flatten_transitions(transition_segments):
            if from_node is not None and to_node is not None:
                transition_edges.append(Edge(nfrom=to_node.iid, nend=from_node.iid, name="STAR"))

        # Build procedures from runway segments.
        # Merge matching common segment points and transitions so the full
        # network->airport path is available for display.
        procedures = {}
        for proc_name, runway, entry_node, points, transitions, is_main in runway_segments:
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
                    if ct not in merged_transitions:
                        merged_transitions.append(ct)
            for p in points:
                if p[0] not in seen:
                    merged_points.append(p)
                    seen.add(p[0])

            proc = Procedure(name=proc_name, runway=runway, points=merged_points, transitions=merged_transitions)
            # STAR main-legs are network->airport (key=points[0]); transitions-only are network->airport (key=points[0])
            if points:
                key = points[0][0]
            else:
                key = entry_node.name
            if key not in procedures:
                procedures[key] = [proc]
            else:
                procedures[key].append(proc)

        # Also register common segment procedures as selectable entries.
        # Only offer for runways covered by this procedure's transitions.
        self._register_common_procedures(common_segments, procedures, lambda pts: pts[0][0])

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
