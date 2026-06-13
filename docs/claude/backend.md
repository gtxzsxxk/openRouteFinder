# Backend Architecture

Backend lives in `openRouterFinder/`. Python 3.10+, FastAPI, pure pytest.

## Entry Points

- `api.py` — FastAPI app, imported by uvicorn
- `app.py` — Standalone uvicorn entry point (`python -m openRouterFinder.app`)

## Core Data Flow

```
Request → api.py → search_route() (data_loader.py)
    → FlatbuffersAirportConnector.build_sid/build_star (airport.py)
    → RouteEngine.search (dijkstra.py)
    → JSON response → enriched with weather/airport details
```

Navdata is stored as zstd-compressed FlatBuffers files (`navdata_*.fb.zst`) in `data/`. At startup, `api.py` loads all matching files via `NavDataRegistry`, builds an airport prefix index, and starts a METAR updater thread.

---

## api.py — FastAPI Application

### Request/Response Models

```python
class RouteRequest(BaseModel):
    orig: str
    dest: str
    validCode: str
    validToken: str
    sidExit: Optional[str] = None
    starEntry: Optional[str] = None
    cycle: Optional[str] = None
```

### Key Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/version` | Returns navdata cycle string |
| GET | `/api/cycles` | Returns all available cycles + default + disableCaptcha flag |
| GET | `/api/airports?q=` | Airport prefix search (O(1) via prefix index) |
| GET | `/api/airports/{icao}` | Airport basic info (icao, name, lat, lon) |
| GET | `/api/airports/{icao}/procedures` | SID/STAR procedures for airport |
| POST | `/api/route` | Main route calculation |
| GET | `/api/metar/{icao}` | METAR weather for airport |
| GET | `/api/validcode` | CAPTCHA image + token |
| GET | `/health` | Health check |
| GET | `/api/admin` | Admin statistics |
| GET | `/api/admin/navdata` | List navdata cycles with metadata |
| GET | `/api/admin/navdata/{cycle}` | Cycle metadata |
| DELETE | `/api/admin/navdata/{cycle}` | Delete a navdata cycle |
| POST | `/api/admin/navdata/upload` | Upload Fenix A320 nd.db3 zip |
| GET | `/api/admin/navdata/build-progress/{build_id}` | SSE build progress stream |

### Concurrency Model

```python
_dijkstra_pool = ThreadPoolExecutor(max_workers=4)
_build_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="navdata-build")
_route_semaphore = asyncio.Semaphore(4)
```

Route calculation runs in `run_in_executor(_dijkstra_pool, ...)` because the A* engine is synchronous. The semaphore limits concurrent route requests to 4, matching the thread-pool size so extra requests queue without blocking the event loop. Fenix navdata builds run serially in `_build_pool` so only one conversion happens at a time.

### Airport Index

`_airport_prefix_index` maps ICAO code prefixes to airport lists for O(1) autocomplete lookup. Built at startup from FlatBuffers navdata and rebuilt atomically after a cycle is uploaded or deleted via the admin endpoints.

### Admin Endpoints

- Require `x-admin-key` header matching `settings.admin_key`, validated by the shared `verify_admin_key` dependency.
- Upload accepts zip containing Fenix `nd.db3` (max 200 MB compressed, 1 GB decompressed) with path-traversal and compression-bomb checks.
- Background build runs in a separate thread, progress streamed via SSE. The SSE handler checks `request.is_disconnected()` to stop quickly when the client disconnects.

---

## config.py — Settings

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
    listen_port: int = 9807
    metar_update_minutes: int = 15
    bing_maps_key: str = ""
    admin_key: str = ""
    navdat_path: str = "data/navdata_2405.fb.zst"
    apdat_path: str = "data/airport_2405.air"
    navdat_cycle: str = "AUTO"
    local_asdata_path: str = ""
    disable_captcha: bool = False
    airport_connection_cache_size: int = 1000
    metar_path: str = "data/metar.txt"

    @property
    def navdat_full_path(self) -> Path: ...
    @property
    def apdat_full_path(self) -> Path: ...
    @property
    def metar_full_path(self) -> Path: ...
```

`navdat_path`/`apdat_path` accept absolute paths or paths relative to `PROJECT_ROOT`. `.env` file is resolved from `PROJECT_ROOT`.

---

## dijkstra.py — A* Route Engine

```python
class RouteEngine:
    def __init__(self, node_list: Tuple[Node, ...], data_version: str)
    def search(self, orig: str, dest: str,
               sid_conn: Optional[AirportConnection],
               star_conn: Optional[AirportConnection],
               airport_names: List[str],
               sid_exit: Optional[str] = None,
               star_entry: Optional[str] = None) -> str  # JSON string
```

### A* Search Logic

`RouteEngine.search()` first attempts a **single mixed-graph A\*** over the combined airway + SID/STAR graph. If the mixed search cannot find a valid route that respects the requested SID/STAR constraints, it falls back to a **phase-separated search**: airway-only path between SID exit and STAR entry points, with procedure segments attached separately.

1. **Candidate selection** — For each available SID/STAR procedure, calculate the boundary point's great-circle distance to the opposite airport plus the actual procedure length. Keep the top 50 candidates (sorted by this combined score) and prune the rest. Adding procedure length prevents a long procedure that starts close to the airport from hiding a shorter but slightly farther candidate.
2. **Start/end nodes** — SID airport node (`iid=-1`) and STAR airport node (`iid=-2`)
3. **Priority queue** — Ordered by `f_score = g_score + heuristic`
4. **Heuristic** — Great-circle distance to STAR airport node (admissible; satisfies triangle inequality on sphere).
5. **Edge weight** — Uses precomputed `edge.dist` (great-circle distance in km).
6. **Forbidden-node filtering** — Airway nodes that share **names and coordinates** with SID/STAR procedure points (excluding STAR boundary points) are added to a forbidden set. A* skips edges whose target node is in this set, preventing the airway from revisiting procedure waypoints.
7. **T-route filtering** — Edges on T-routes (`T123`) are skipped when the current node has at least one non-T outgoing edge.
8. **Cycle removal** — After backtracking the optimal path, duplicate airway node IIDs are removed to prevent cycles where the airway re-enters the same node.
9. **Tracks `dists` dict** for best-known distances.

### SID/STAR Connector Injection

`_build_adjacency()` builds a per-request adjacency dict that merges:
- The global airway network (read-only, shared)
- SID temp nodes and edges: airport → boundary, internal edges, transition edges
- STAR temp nodes and edges: boundary → airport, internal edges, transition edges
- Temp nodes use negative IIDs (starting at -3)

Temp node boundary points are mapped to their corresponding airway nodes by `(name, lat, lon)` key via the precomputed `_node_index`, avoiding negative-indexing bugs when the temp node's negative IID is used as a list index.

### Pseudo-Edge Weights

- **SID pseudo-edge** (airport → boundary): weight = `_calc_procedure_distance(proc) + calc_transition_distance(trans)` — follows the actual procedure geometry.
- **STAR pseudo-edge** (boundary → airport): weight = `great_circle_distance_km(boundary, airport)` — uses straight-line distance because STAR paths are often curved and `_calc_procedure_distance` would overestimate.

### Transition Detection

`_find_transition_name()` detects active SID/STAR transitions from the actual route by scoring how many procedure leg points appear in the route node set.

### Output

Returns a **JSON string**. Caller in `api.py` parses it with `json.loads()`.

---

## graph.py — Data Structures

```python
@dataclass(slots=True)
class Edge:
    nfrom: int      # source IID
    nend: int       # target IID
    name: str       # airway name (or "SID"/"STAR")
    color: Tuple[int, int, int]  # RGB
    dist: float = 0.0   # precomputed great-circle distance (km)

@dataclass(slots=True)
class Node:
    iid: int
    name: str
    px: float       # latitude
    py: float       # longitude
    next_list: List[Edge]  # outgoing edges

    def node_key(self) -> Tuple[str, float, float]:
        return (self.name, round(self.px, 6), round(self.py, 6))

@dataclass
class SearchingNode:
    iid: int
    name: str
    route: str
    dist: float
    route_list: List[Tuple[str, str, int]]  # (edge_name, node_name, node_iid)
```

- `EARTH_RADIUS = 6371.0` km (mean Earth radius, aviation standard)
- `great_circle_distance_km()` uses the `atan2(sqrt(a), sqrt(1-a))` form of the Haversine formula for better numerical stability
- `Edge.dist` is precomputed at navdata load time to avoid trigonometric recalculation during every A* edge relaxation

---

## data_loader.py — Data Loading & Orchestration

### NavGraph (Legacy Singleton)

```python
class NavGraph:
    def __init__(self, node_list, airport_maps, data_version)
    def find_node(self, name, lat, lon) -> Optional[Node]  # O(1) via node_key
    def find_nodes_by_name(self, name) -> List[Node]
```

Legacy pickle-based navdata. `_compat.py` is registered as `sys.modules["RouteFinderLib"]` so legacy `.map` files can still load.

### NavDataRegistry (Modern, FlatBuffers)

```python
def get_nav_registry() -> NavDataRegistry

def get_nav_data(cycle: Optional[str] = None) -> Optional[MmappedNavData]

def has_registry() -> bool

def get_data_version() -> str
```

Registry is lazily initialized in a thread-safe manner (`_init_registry()` uses double-checked locking). `get_nav_data()` returns a reference-counted `_NavDataRef` for a specific cycle or the latest (highest cycle number). Callers should use it as a context manager or call `.release()`.

### search_route() — Main Entry Point

```python
def search_route(orig: str, dest: str,
                 sid_exit: Optional[str] = None,
                 star_entry: Optional[str] = None,
                 cycle: Optional[str] = None) -> dict
```

Flow:
1. Uppercase orig/dest
2. Get navdata for cycle (or latest)
3. Validate airports exist
4. `FlatbuffersAirportConnector(nav)` → cached `build_sid(orig)` / `build_star(dest)` via LRU caches
5. `RouteEngine(nav.node_list, nav.cycle)` → `engine.search(...)`
6. Parse JSON result
7. Enrich with airport details and runway info
8. Return dict

Thread-safe: creates fresh `RouteEngine` per call. `AirportConnection` objects are cached and `dataclasses.replace()` is used to give each request isolated `temp_nodes`. Cache size is controlled by `AIRPORT_CONNECTION_CACHE_SIZE`.

---

## storage/ — FlatBuffers Subsystem

### registry.py — NavDataRegistry

Thread-safe registry managing multiple navdata cycles:
- Regex `^navdata_(\d{4})\.((?:fb\.zst)|(?:fb))$` identifies valid files (`.fb.zst` is checked first so it is not mistaken for `.fb`)
- `threading.RLock()` for thread safety
- Hot reload via `_load_cycle()` (closes old mapping before replacing)
- `get(cycle=None)` returns specific or latest cycle
- `register()` / `unregister()` for runtime addition/removal

### reader.py — MmappedNavData

Memory-mapped FlatBuffers reader:
- Transparently decompresses `.fb.zst` to temp file, then mmaps
- Builds O(1) lookup indices: `_node_index`, `_node_by_iid`, `_airport_by_icao`, `_navaid_by_ident`
- `node_list` property builds array indexed by IID
- Context manager support (`__enter__` / `__exit__`)
- `close()` unmaps and deletes temp decompressed file

### builder.py — build_from_fenix()

Converts Fenix A320 `nd.db3` SQLite to FlatBuffers bytes:
- Pre-fetches waypoint names for procedure leg lookup
- Progress callback: `progress(step, current, total)`
- Builds all sections: nodes, edges, airports, navaids, holdings, markers, GLS, grid MORA, airport comms
- Nodes: waypoint `ID` mapped to 0-based IID via an explicit `id_to_iid` dictionary; handles non-consecutive IDs
- Runways: pairs ends by base name (e.g., "18L/36R")
- ILS frequency decoded from BCD-like hex encoding, preserving trailing zeros
- Procedures: maps Fenix `Proc` field (1=arrival, 2=departure) to schema enum; legs are ordered by `SeqNumber` (or `ID` fallback)

### NavData/ — Generated FlatBuffers Python Classes

Auto-generated from `NavData.fbs` schema. **Do not hand-edit.** Includes:
- `NavData.py`, `Node.py`, `Edge.py`, `Airport.py`, `Procedure.py`, `ProcLeg.py`, `ProcTransition.py`, `Runway.py`, etc.

---

## utils/ — Utilities

### metar.py — METAR Fetcher

```python
def fetch_metar() -> str
def read_metar(icao: str) -> str
```

Fetches from NOAA `tgftp.nws.noaa.gov/data/observations/metar/cycles/{HH}Z.TXT` with 3 retries and exponential backoff. Cached in memory and written to `data/metar.txt`.

### validcode.py — CAPTCHA Generation

```python
def generate_captcha(num: int) -> bytes          # JPEG bytes
def generate_captcha_b64(num: int) -> str        # data:image/jpeg;base64,...
```

Uses PIL to generate 90x30 JPEG. Tries `webFinder/public/NotoSansHans-Regular.ttf`, falls back to default font.

### admin.py — In-Memory Admin Stats

```python
def record_request(ip, method, path, status, duration_ms)
def record_route_search(orig, dest, sid_exit, star_entry, distance, nodes_count, time_min)
def record_error(detail, path, method, status)
def get_stats() -> dict
```

All deques have `maxlen` to prevent unbounded growth. Skips noisy paths (`/api/validcode`, `/api/admin`, `/health`, `/favicon.ico`, `/assets/`, `/static/`).
