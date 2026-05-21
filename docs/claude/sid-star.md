# SID/STAR Processing

This is the most complex part of the backend. All SID/STAR logic lives in `openRouterFinder/core/airport.py`.

## Data Structures

```python
@dataclass
class Procedure:
    name: str
    runway: str
    points: List[Tuple[str, float, float]]  # (name, lat, lon)
    transitions: List[Tuple[str, List[Tuple[str, float, float]]]]  # (name, points)

@dataclass
class AirportConnection:
    airport_node: Node          # temp node (IID -1 for SID, -2 for STAR)
    connections: List[Edge]     # airport ↔ network edges
    procedures: Dict[str, List[Procedure]]  # anchor_point -> list of procedures
    transition_edges: List[Edge]
    temp_nodes: List[Node]      # off-network waypoints (negative IIDs)
    internal_edges: List[Edge]  # edges within procedures (pooled across ALL procedures)
```

**Important:** `internal_edges` is pooled across ALL procedures for an airport, not per-procedure. Shared common-segment nodes naturally have >2 edges. Deduplication is required for meaningful edge-count checks.

## FlatbuffersAirportConnector

```python
class FlatbuffersAirportConnector:
    def __init__(self, nav_data: MmappedNavData)
    def build_sid(self, icao: str, filter_name: Optional[str] = None) -> Optional[AirportConnection]
    def build_star(self, icao: str, filter_name: Optional[str] = None) -> Optional[AirportConnection]
```

### build_sid() Flow

1. Get airport from navdata, create airport node (IID=-1)
2. `_collect_procedures(icao, proc_type=1)` — collect all SID procedures
3. `_apply_filter(filter_name, ...)` — keep only procedures containing the filter waypoint
4. Build connections: airport → runway exit points (first point of path)
5. Build internal edges along procedure legs (airport→network order)
6. Build transition edges between transition start/end
7. Merge runway segments with common segments and transitions into `Procedure` objects
8. Key procedures by network-side exit point (`merged_points[-1][0]`)
9. Register common procedures for runways covered by their transitions
10. Deduplicate by `(name, runway)`, keeping the one with most points

### build_star() Flow

1. Get airport, create airport node (IID=-2)
2. `_collect_procedures(icao, proc_type=2)` — collect all STAR procedures
3. `_apply_filter(filter_name, ...)`
4. `_collect_approach_bridges(icao)` — collect Type=3 approach procedures to extend STAR paths to runway
5. Build internal edges along procedure legs (network→airport order)
6. Build transition edges (reversed: network→airport)
7. Merge runway segments with common segments; prefer options with matching approach bridges
8. Key procedures by network-side entry point (`merged_points[0][0]`)
9. Merge approach bridges into STAR procedures so full path to runway is available
10. Build connections from each procedure's last point to airport
11. Add internal edges for used approach bridges

---

## Procedure Collection (`_collect_procedures`)

The core of SID/STAR parsing. Returns three things:

```python
(
    runway_segments: Dict[str, List[Tuple[str, float, float]]],   # runway -> points
    common_segments: Dict[str, List[Tuple[str, float, float]]],   # name -> points
    transition_segments: Dict[str, Dict[str, List[Tuple[str, float, float]]]]  # name -> {transition_name -> points}
)
```

Fenix navdata stores procedures with:
- Main legs (Transition="ALL")
- Transition legs (Transition=specific name)
- Segment separators: consecutive legs with identical coordinates `(0, 0)`
- Runway endpoint markers: names matching `DER\d+[A-Z]?$` or `DE\d+[A-Z]?$`

### STAR Transition Handling

STAR transitions are treated as **continuous paths** (no split on separators). The `_extract_transition_segments()` function handles Fenix's segment format and returns complete transition paths.

### Transition Option Splitting (`_split_transition_options`)

Fenix sometimes concatenates multiple route options into a single transition. This function splits them using:
- **Backward split** on anchor point name
- **Forward split** on first point

Returns unique route options deduplicated by their point sequence.

---

## Synthetic Marker Filtering (`_leg_to_point`)

Heading+distance markers matching `^D\d+[A-Z]?$` (e.g., `D091M`, `D123`, `D194Q`) must **never** appear as standalone points. They are filtered out in `_leg_to_point()`.

```python
def _leg_to_point(self, leg) -> Optional[Tuple[str, float, float]]:
    name = leg.Name()
    if name is None:
        return None
    name = name.decode("utf-8") if isinstance(name, bytes) else name
    if not name:
        return None
    if _RUNWAY_ENDPOINT_RE.match(name):
        return (name, float(leg.Lat()), float(leg.Lon()))
    # Filter synthetic markers
    if len(name) >= 2 and name[0] == "D" and name[1:].isdigit():
        return None
    if len(name) >= 3 and name[0] == "D" and name[1:-1].isdigit() and name[-1].isalpha():
        return None
    return (name, float(leg.Lat()), float(leg.Lon()))
```

Runway endpoint markers (`DER01L`, `DE36L`, etc.) are **preserved**.

---

## Approach Bridges (STAR only)

Type=3 procedures (approaches) are collected separately and merged into STARs to provide the full path from network → runway.

```python
def _collect_approach_bridges(self, icao: str) -> Dict[str, List[Tuple[str, float, float]]]
```

- Common segments without transitions infer runway from approach bridges
- `_register_common_procedures()` avoids falling back to "ALL" runways when bridge data is available

---

## Temp Node Management

```python
def _get_or_create_temp(self, name: str, lat: float, lon: float) -> Node:
    # Creates temp node with decrementing negative IID
    # Starts at -3 and goes down
```

Temp nodes are created for off-network waypoints that don't exist in the global nav graph. They are per-request and use negative IIDs to avoid collisions.

---

## Known Edge Cases & Gotchas

1. **Fenix duplicates waypoints**: Some waypoints appear twice consecutively — deduplicated in `_get_leg_points()`
2. **internal_edges is pooled**: Edge counts must be deduplicated before per-procedure analysis
3. **Runway "ALL"**: Procedures without specific runway assignment get `runway="ALL"`. These must still have >1 point.
4. **Transition splitting creates single-point options**: Some split results are just a runway marker (e.g., `DE01L`). These can cause isolated nodes.
5. **KLAX STAR GOATZ2**: Known to have 3 edges on a single node due to incorrect edge pooling from LEENA8 transition edges.
6. **ZBAA DOTR5Y 36L**: Genuinely missing westward points — transition splitting bug.
