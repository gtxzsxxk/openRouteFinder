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


@dataclass
class AirportConnection:
    """Temporary airport connection for a single search."""
    airport_node: Node
    connections: List[Edge]  # edges FROM airport TO network (SID) or FROM network TO airport (STAR)
    procedures: Dict[str, List[Procedure]]  # anchor_point -> [Procedure, ...]


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

        # Airport node is temporary (not in shared node_list)
        airport_node = Node(iid=-1, name=icao, px=ap_lat, py=ap_lon)
        connections = []
        procedures = {}
        added_nodes = set()

        for segment in datasource.split("\n\n"):
            lines = segment.strip().split("\n")
            if not lines or not lines[0].startswith("SID,"):
                continue

            parts = lines[0].split(",")
            proc_name = parts[1] if len(parts) > 1 else ""
            runway = parts[2] if len(parts) > 2 else ""

            # Last line has exit point
            last_line = lines[-1]
            last_parts = last_line.split(",")
            if len(last_parts) < 4:
                continue
            exit_name = last_parts[1].strip()
            exit_lat = float(last_parts[2])
            exit_lon = float(last_parts[3])

            exit_node = self._find_node(exit_name, exit_lat, exit_lon)
            if exit_node is None:
                continue

            if exit_name not in added_nodes:
                connections.append(Edge(
                    nfrom=airport_node.iid,
                    nend=exit_node.iid,
                    name="SID",
                ))
                added_nodes.add(exit_name)

            # Parse procedure points
            points = []
            for line in lines:
                if line.startswith("CF,") or line.startswith("TF,"):
                    pp = line.split(",")
                    if len(pp) >= 4:
                        points.append((pp[1], float(pp[2]), float(pp[3])))

            proc = Procedure(name=proc_name, runway=runway, points=points)
            if exit_node.name not in procedures:
                procedures[exit_node.name] = [proc]
            else:
                procedures[exit_node.name].append(proc)

        return AirportConnection(
            airport_node=airport_node,
            connections=connections,
            procedures=procedures,
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
        connections = []
        procedures = {}
        added_nodes = set()

        for segment in datasource.split("\n\n"):
            lines = segment.strip().split("\n")
            if not lines or not lines[0].startswith("STAR,"):
                continue

            parts = lines[0].split(",")
            proc_name = parts[1] if len(parts) > 1 else ""
            runway = parts[2] if len(parts) > 2 else ""

            # First data line has entry point
            if len(lines) < 2:
                continue
            first_data = lines[1].split(",")
            if len(first_data) < 4:
                continue
            entry_name = first_data[1].strip()
            entry_lat = float(first_data[2])
            entry_lon = float(first_data[3])

            entry_node = self._find_node(entry_name, entry_lat, entry_lon)
            if entry_node is None:
                continue

            if entry_name not in added_nodes:
                connections.append(Edge(
                    nfrom=entry_node.iid,
                    nend=airport_node.iid,
                    name="STAR",
                ))
                added_nodes.add(entry_name)

            points = []
            for line in lines:
                if line.startswith("CF,") or line.startswith("TF,"):
                    pp = line.split(",")
                    if len(pp) >= 4:
                        points.append((pp[1], float(pp[2]), float(pp[3])))

            proc = Procedure(name=proc_name, runway=runway, points=points)
            if entry_node.name not in procedures:
                procedures[entry_node.name] = [proc]
            else:
                procedures[entry_node.name].append(proc)

        return AirportConnection(
            airport_node=airport_node,
            connections=connections,
            procedures=procedures,
        )

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
