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
| GET | `/api/version` | Returns navdata cycle info |
| GET | `/api/cycles` | Returns all available cycles + default + disableCaptcha flag |
| GET | `/api/airports?q=` | Airport prefix search (O(1) via prefix index) |
| GET | `/api/airports/{icao}` | Airport details with runways |
| GET | `/api/airports/{icao}/procedures` | SID/STAR procedures for airport |
| POST | `/api/route` | Main route calculation |
| GET | `/api/metar/{icao}` | METAR weather for airport |
| GET | `/api/validcode` | CAPTCHA image + token |
| GET | `/health` | Health check |
| POST | `/api/admin/navdata/upload` | Upload Fenix A320 nd.db3 zip |
| GET | `/api/admin/build/progress/{build_id}` | SSE build progress stream |
| GET | `/api/admin/stats` | Admin statistics |

### Concurrency Model

```python
_dijkstra_pool = ThreadPoolExecutor(max_workers=4)
_route_semaphore = asyncio.Semaphore(8)
```

Route calculation runs in `run_in_executor()` because the A* engine is synchronous. The semaphore limits concurrent requests to 8.

### Airport Index

`_airport_prefix_index` maps ICAO code prefixes to airport lists for O(1) autocomplete lookup. Built at startup from FlatBuffers navdata.

### Admin Endpoints

- Require `x-admin-key` header matching `settings.admin_key`
- Upload accepts zip containing Fenix `nd.db3`
- Background build runs in separate thread, progress streamed via SSE

---

## config.py — Settings

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    listen_port: int = 9807
    metar_update_minutes: int = 15
    bing_maps_key: str = ""
    admin_key: str = ""
    navdat_path: str = "data/navidata_2206.map"
    apdat_path: str = "data/airport_2206.air"
    navdat_cycle: str = "AUTO"
    local_asdata_path: str = ""
    disable_captcha: bool = False

    @property
    def navdat_full_path(self) -> Path: ...
    @property
    def apdat_full_path(self) -> Path: ...
    @property
    def metar_full_path(self) -> Path: ...
```

All paths relative to project root. `.env` file at project root.

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

1. Start node = SID airport node (`iid=-1`), end node = STAR airport node (`iid=-2`)
2. Priority queue ordered by `f_score = g_score + heuristic`
3. Heuristic = great-circle distance to destination (admissible)
4. Edge weight = great-circle distance, with **0.5x multiplier** for SID/STAR edges to prefer procedures
5. Tracks `dists` dict for best-known distances

### SID/STAR Connector Injection

`_build_adjacency()` copies the entire shared network into a new dict per request, then:
- Adds temp nodes from `sid_conn.temp_nodes` and `star_conn.temp_nodes`
- Injects SID edges: airport → connections, internal edges, transition edges
- Injects STAR edges: connections → airport, internal edges, transition edges
- Temp nodes use negative IIDs (starting at -3)

### Transition Detection

`_find_transition_name()` detects active SID/STAR transitions from the actual route by scoring how many procedure leg points appear in the route node set.

### Output

Returns a **JSON string** (not dict) for historical compatibility. Caller in `api.py` parses it with `json.loads()`.

---

## graph.py — Data Structures

```python
@dataclass(slots=True)
class Edge:
    nfrom: int      # source IID
    nend: int       # target IID
    name: str       # airway name (or "SID"/"STAR")
    color: Tuple[int, int, int]  # RGB

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

- `EARTH_RADIUS = 6378.137` km (WGS-84)
- `great_circle_distance_km()` uses Haversine formula

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

Registry is lazily initialized. `get_nav_data()` returns specific cycle or latest (highest cycle number).

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
4. `FlatbuffersAirportConnector(nav)` → `build_sid(orig)` / `build_star(dest)`
5. `RouteEngine(nav.node_list, nav.cycle)` → `engine.search(...)`
6. Parse JSON result
7. Enrich with airport details and runway info
8. Return dict

Thread-safe: creates fresh `RouteEngine` and connectors per call.

---

## storage/ — FlatBuffers Subsystem

### registry.py — NavDataRegistry

Thread-safe registry managing multiple navdata cycles:
- Regex `^navdata_(\d{4})\.(fb|fb\.zst)$` identifies valid files
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
- Nodes: ID converted to 0-based IID (`(row["ID"] or 1) - 1`)
- Runways: pairs ends by base name (e.g., "18L/36R")
- ILS frequency decoded from BCD-like hex encoding
- Procedures: maps Fenix `Proc` field (1=arrival, 2=departure) to schema enum

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
