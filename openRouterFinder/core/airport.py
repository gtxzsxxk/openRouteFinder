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


class AirportConnector:
    """Builds temporary airport connections without modifying shared node list."""

    def __init__(self, airport_maps: Dict[str, str], node_index: Dict):
        self.airport_maps = airport_maps
        self.node_index = node_index

    def _find_node(self, name: str, lat: float, lon: float) -> Optional[Node]:
        key = (name, round(lat, 6), round(lon, 6))
        return self.node_index.get(key)

    def build_sid(self, icao: str) -> Optional[AirportConnection]:
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

            # Parse waypoint points (CF, TF, IF lines)
            points = []
            for line in lines:
                if line.startswith("CF,") or line.startswith("TF,") or line.startswith("IF,"):
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

            exit_node = self._find_node(exit_name, exit_lat, exit_lon)

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
                transition_segments.append((proc_name, field2, from_node, exit_node, points))
            elif field2 == 'ALL':
                if exit_node:
                    common_segments[proc_name] = (exit_node, points)
            else:
                if exit_node:
                    runway_segments.append((proc_name, field2, exit_node, points))

        # Phase 2: build connections and transition_edges
        connections = []
        transition_edges = []
        added_exit_nodes = set()

        # Airport -> common exit points
        for proc_name, runway, exit_node, points in runway_segments:
            if exit_node.name not in added_exit_nodes:
                connections.append(Edge(
                    nfrom=airport_node.iid,
                    nend=exit_node.iid,
                    name="SID",
                ))
                added_exit_nodes.add(exit_node.name)

        # Common exit point -> transition waypoints
        for proc_name, trans_name, from_node, to_node, points in transition_segments:
            if from_node and to_node:
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

        return AirportConnection(
            airport_node=airport_node,
            connections=connections,
            procedures=procedures,
            transition_edges=transition_edges,
        )

    def build_star(self, icao: str) -> Optional[AirportConnection]:
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
                if line.startswith("CF,") or line.startswith("TF,") or line.startswith("IF,"):
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
                transition_segments.append((proc_name, field2, entry_node, to_node, points))
            elif field2 == 'ALL':
                if entry_node:
                    common_segments[proc_name] = (entry_node, points)
            else:
                if entry_node:
                    runway_segments.append((proc_name, field2, entry_node, points))

        # Phase 2: build connections and transition_edges
        connections = []
        transition_edges = []
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

        # Transition waypoint -> common entry point
        for proc_name, trans_name, from_node, to_node, points in transition_segments:
            if from_node and to_node:
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

        return AirportConnection(
            airport_node=airport_node,
            connections=connections,
            procedures=procedures,
            transition_edges=transition_edges,
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
