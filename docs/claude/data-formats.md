# Data Formats

The codebase supports three navdata backends.

## 1. Legacy Pickle Files (`.map` / `.air`)

- `navidata_2206.map` — Global airways (pickle of `RouteFinderLib` objects)
- `airport_2206.air` — Airport data (pickle)
- Loaded by `NavGraph` in `data_loader.py`
- `_compat.py` registered as `sys.modules["RouteFinderLib"]` for backward compatibility
- **Deprecated** but still supported

## 2. FlatBuffers (`.fb.zst`) — Modern, Active

Zstd-compressed FlatBuffers files. This is the active path.

### Schema (`openRouterFinder/core/storage/NavData.fbs`)

Key tables:
- `NavData` — root table containing all vectors
- `Node` — navigation node: ID, Name, Lat, Lon, next_edges (indices into Edge vector)
- `Edge` — airway edge: From, To, Name, Level (B/H/L enum), Color (RGB)
- `Airport` — ICAO, Name, Lat, Lon, Elevation, runways, terminals, ILS, comms
- `Runway` — Name, Length, Width, Surface, ends (2× RunwayEnd)
- `RunwayEnd` — Name, Lat, Lon, Threshold, Heading, ILS index, GLS index, Displaced
- `Procedure` — Type (SID=1, STAR=2, Approach=3), Name, Airport, Runway, legs, transitions
- `ProcLeg` — Name, Type, Overfly, Lat, Lon, Altitude1/2, SpeedLimit, Course, Distance, Time
- `ProcTransition` — Name, legs
- `Navaid` — Type, Ident, Name, Lat, Lon, Frequency, Range, MagVar
- `Holding` — Name, Lat, Lon, InboundCourse, LegLength, TurnDirection, Altitude1/2
- `Marker` — Name, Lat, Lon, Type
- `GLS` — Name, Lat, Lon, Frequency, Slope, Course, MagVar, Range
- `GridMora` — Lat, Lon, Mora
- `AirportComm` — Type, Frequency, Name

### File Format

- Binary FlatBuffers, optionally zstd-compressed (`.fb.zst`)
- Cycle identifier embedded in filename: `navdata_2604.fb.zst`
- Multiple cycles can coexist in `data/`; registry auto-detects all valid files

### Reading (`MmappedNavData`)

1. If `.fb.zst`: decompress to temp file via `zstandard`
2. Memory-map the (decompressed) file
3. Build O(1) lookup indices:
   - `_node_index`: dict keyed by `(name, lat, lon)` tuple
   - `_node_by_iid`: dict keyed by internal integer ID
   - `_airport_by_icao`: ICAO → index in airports vector
   - `_navaid_by_ident`: ident → list of indices
4. Attach edges to nodes (populate `GraphNode.next_list`)

### Multi-Cycle Support (`NavDataRegistry`)

```python
class NavDataRegistry:
    def get(self, cycle: Optional[str] = None) -> Optional[MmappedNavData]
    def get_cycle_info(self) -> List[dict]  # metadata per cycle
    def register(self, cycle: str, path: Path)
    def unregister(self, cycle: str)
```

- Thread-safe via `threading.RLock()`
- Hot reload: close old mapping, load new one
- `get()` with no cycle returns latest (highest cycle number)

## 3. Fenix A320 `nd.db3` — Upload & Convert

Uploaded via admin API, converted to FlatBuffers in background thread.

### Upload Flow

1. `POST /api/admin/navdata/upload` — accepts zip file
2. Zip extracted to temp directory
3. `_validate_fenix_db()` validates SQLite schema
4. `_do_build_navdata()` runs in background thread
5. `build_from_fenix()` converts to FlatBuffers bytes
6. Bytes compressed with zstandard
7. Written to `data/navdata_{cycle}.fb.zst`
8. Registry auto-detects new file on next scan

### Conversion Details

- Nodes: ID converted to 0-based IID (`(row["ID"] or 1) - 1`)
- Edges: joins `AirwayLegs` + `Airways`, maps level string to `AirwayLevel` enum
- Airports: batch-queries runways, ILS, terminals in single queries
- Runways: pairs ends by base name (e.g., "18L/36R")
- ILS frequency: decoded from BCD-like hex encoding
- Procedures: maps Fenix `Proc` field (1=arrival, 2=departure) to schema enum
- Procedure legs: `Transition="ALL"` = main legs, named = transitions

## Preprocessing (Legacy)

For raw Aerosoft data:

```bash
# Set in .env
LOCAL_ASDATA_PATH="/path/to/aerosoft/data"

# Run preprocessor
python openRouterFinder/scripts/pack_data.py
# Answer y for airport data → airport_$(cycle).air
# Answer n for global airways → navidata_$(cycle).map
```

Note: Preprocessing may take several minutes.

## Data Directory (`data/`)

```
data/
├── navdata_2604.fb.zst    # Modern FlatBuffers navdata
├── metar.txt              # Cached METAR data
└── (other .fb.zst files)  # Multiple cycles supported
```

`.gitignore`: ignores everything in `data/` except `*.fb.zst` files.
