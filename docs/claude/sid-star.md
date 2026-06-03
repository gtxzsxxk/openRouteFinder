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
11. `_ensure_continuous_paths()` — add missing edges for consecutive points in merged procedures
12. `_add_network_bridges()` — bridge isolated exit nodes to nearest airway-connected node
13. Deduplicate `internal_edges`

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
12. **Fallback**: when no STAR procedures exist (and no filter is active), create virtual STAR procedures from approach bridges
13. `_ensure_continuous_paths()` — add missing edges for consecutive points in merged procedures
14. `_add_network_bridges()` — bridge isolated entry nodes from nearest airway-connected node
15. Deduplicate `internal_edges`

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

## Network Bridges

Terminal waypoints (SID exits, STAR entries) are frequently not part of the airway network in Fenix data. Without a bridge, A* reaches the waypoint and then has no outgoing edges to continue.

```python
def _add_network_bridges(self, conn: AirportConnection, proc_type: int)
```

- **SID**: for each unique exit node, if it has zero outgoing edges, find the nearest navdata node with `next_list > 0` and add `exit -> connected_node`
- **STAR**: for each unique entry node, if it has zero outgoing edges, add `connected_node -> entry`
- Bridges are added to `bridge_edges` (not `internal_edges`) so they do not pollute the pooled procedure graph used for integrity checks
- Bridge edges carry precomputed `dist` like all other edges

## Continuous Path Guarantee

When Fenix separators split a transition into disconnected segments, consecutive points in the merged procedure may lack an internal edge. `_ensure_continuous_paths()` walks every procedure's points (and transitions) and adds missing edges.

```python
def _ensure_continuous_paths(self, conn: AirportConnection, label: str)
```

- Checks every consecutive pair in `proc.points` and `proc.transitions`
- Skips duplicates using an `(nfrom, nend)` set
- Label is `"SID"` or `"STAR"`

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
2. **internal_edges is pooled**: Edge counts must be deduplicated before per-procedure analysis. Both `build_sid` and `build_star` now deduplicate automatically.
3. **Runway "ALL"**: Procedures without specific runway assignment get `runway="ALL"`. These must still have >1 point. Single-point common segments are now skipped in `_register_common_procedures()`.
4. **Transition splitting creates single-point options**: Some split results are just a runway marker (e.g., `DE01L`). Single-point runway endpoints before `(0,0)` separators are now merged into the following segment so the full runway→network path is preserved.
5. **Isolated terminal waypoints**: SID/STAR waypoints (e.g., KJFK's `CRI`, KLAX's `ANJLL`) often have no airway network connections. `_add_network_bridges()` finds the nearest connected node and creates a temporary bridge edge so A* can route through them.
6. **Airports without STAR procedures**: Small airports like TNCM have approaches but no type=2 STARs. `build_star()` now falls back to approach bridges (when no filter is active) so routing can still terminate at the airport.
7. **Split transition segments without connecting edges**: When Fenix separators break a transition into disconnected segments (e.g., `[PONAE]` and `[DEEZZ, HEERO]`), `_ensure_continuous_paths()` adds the missing connecting edges so every consecutive pair in procedure points has an internal edge.
