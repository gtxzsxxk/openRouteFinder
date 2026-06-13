# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **Important:** This file and `docs/claude/*.md` are living documentation. Any code change that affects architecture, APIs, data formats, SID/STAR behavior, or testing must also update the relevant documentation here. Do not leave docs out of sync with code.

## Project Overview

OpenRouteFinder is a flight route finder for flight simulation. It finds the shortest airway between two airports using Dijkstra/A* and is the only online service that allows users to select SID/STAR procedures.

- **Backend**: Python 3.10+, FastAPI, A* route engine
- **Frontend**: Vue 3 + TypeScript + Vite + Tailwind CSS + MapLibre GL JS + Pinia
- **Data format**: FlatBuffers (`.fb.zst`) for navigation data; multi-cycle support with hot reload
- **PWA**: Offline-capable, installable

## Development Commands

All commands run from the repository root unless noted.

### Setup
```bash
pip install -r requirements.txt
cd webFinder && npm install
```

### Development (both servers)
```bash
npm run dev              # concurrently starts frontend (:5173) and backend (:9807)
npm run dev:frontend     # Vite dev server only
cd openRouterFinder && uvicorn api:app --reload --port 9807   # backend only
```

### Build & Production
```bash
npm run build            # build frontend (runs vue-tsc + vite build)
cd openRouterFinder && uvicorn api:app --host 0.0.0.0 --port 9807   # production
```

### Testing
```bash
pytest                   # run all tests
pytest tests/test_dijkstra.py -v   # single test file
pytest tests/test_airport.py::test_build_sid_with_filter -v   # single test
PYTHONPATH=. DISABLE_CAPTCHA=true pytest tests/test_integration_routes.py -v
```

### Linting
```bash
ruff check               # lint Python backend
ruff check --fix         # auto-fix Python issues
npm run lint             # lint frontend (cd webFinder && npm run lint)
```

Pre-commit hooks are configured. Run before committing:
```bash
pre-commit run --all-files
```

## Documentation Index

Detailed documentation lives in `docs/claude/`. Read the relevant file before modifying that area:

| Document | Covers | Read When Modifying... |
|----------|--------|----------------------|
| [Backend Architecture](docs/claude/backend.md) | FastAPI endpoints, A* engine, data structures, storage subsystem, utilities | Any Python backend code |
| [SID/STAR Processing](docs/claude/sid-star.md) | `FlatbuffersAirportConnector`, procedure parsing, transition splitting, approach bridges, synthetic marker filtering | `core/airport.py`, any procedure-related logic |
| [Frontend Architecture](docs/claude/frontend.md) | Vue 3 components, composables, Pinia state, MapLibre integration, i18n | Any frontend code |
| [Testing](docs/claude/testing.md) | Test files, running tests, procedure integrity checks, integration tests | Adding or modifying tests |
| [Data Formats](docs/claude/data-formats.md) | Three navdata backends (legacy pickle, FlatBuffers, Fenix), schema, preprocessing | Navdata loading, storage, conversion |
| [API Endpoints](docs/claude/api-endpoints.md) | All REST endpoints, request/response shapes | `api.py`, frontend API calls |

## Architecture

### Backend (`openRouterFinder/`)

**Core data flow**: nav data is stored as zstd-compressed FlatBuffers files in `data/`. At startup, `api.py` loads all `navdata_*.fb.zst` files via `NavDataRegistry`, builds an airport prefix index, and starts a METAR updater thread.

Key modules:

- `api.py` — FastAPI app with all endpoints (`/api/route`, `/api/airports`, `/api/airports/{icao}/procedures`, `/api/admin/*`, etc.). Route calculation runs in `_dijkstra_pool` (4 workers) guarded by an `asyncio.Semaphore(4)`. Fenix builds run serially in `_build_pool` (1 worker). Admin endpoints share a `verify_admin_key` dependency. The airport prefix index is rebuilt atomically after a navdata cycle is uploaded or deleted.
- `core/dijkstra.py` — `RouteEngine` uses a **hybrid A\* search**: it first tries a mixed-graph A\* over airway + SID/STAR nodes, then falls back to a phase-separated search when constraints cannot be satisfied. Uses admissible great-circle heuristic, precomputed `edge.dist`, candidate pruning (top 50), and cycle prevention.
- `core/graph.py` — Immutable `Node`/`Edge` dataclasses and great-circle distance utilities. `Edge` carries a precomputed `dist` field.
- `core/airport.py` — `FlatbuffersAirportConnector` builds temporary nodes and edges for SID/STAR procedures from FlatBuffers navdata. Also contains the legacy `AirportConnector` for pickle-based data.
- `core/data_loader.py` — Legacy `NavGraph` singleton (pickle-based) and modern `NavDataRegistry` accessors. `get_nav_registry()` / `get_nav_data()` are lazily initialized in a thread-safe manner. `search_route()` orchestrates the A* search and caches built `AirportConnection` objects in bounded LRU caches keyed by `(cycle, icao)`.
- `core/storage/registry.py` — `NavDataRegistry` manages multiple navdata cycles (thread-safe, hot reload).
- `core/storage/reader.py` — `MmappedNavData` reads `.fb` / `.fb.zst` files via `mmap`.
- `core/storage/builder.py` — `build_from_fenix()` converts Fenix A320 `nd.db3` SQLite files into FlatBuffers navdata.
- `core/storage/NavData/` — Generated FlatBuffers Python classes (do not edit by hand).
- `config.py` — `pydantic-settings` with `.env` file support.

**Nav data formats**: The codebase supports three nav data backends:
1. **Legacy `.map`/`.air` files** — pickle-based, loaded into `NavGraph`.
2. **FlatBuffers `.fb.zst` files** — modern format, mmapped, supports multiple cycles. This is the active path for new features.
3. **Fenix A320 `nd.db3`** — uploaded via admin API, converted to FlatBuffers in a background thread.

**Testing**: Pure pytest, no `pytest.ini` or `setup.cfg`. Tests in `tests/` import directly from `openRouterFinder.*`.

### Frontend (`webFinder/`)

- `vite.config.ts` — Vite dev server on `:5173` with proxy rules for `/api` and `/health` to `localhost:9807`. PWA plugin configured.
- `src/App.vue` — Root layout.
- `src/views/HomeView.vue` — Main search page.
- `src/views/AdminView.vue` — Admin dashboard for navdata upload and stats.
- `src/components/` — Vue components: `SearchForm`, `RouteMap`, `ProcedureSelector`, `WeatherSection`, `SIDSelector`, `STARSelector`, etc.
- `src/composables/` — `useMap.ts` (MapLibre integration, largest file), `useRouteQuery.ts`, `useAdmin.ts`, `useCycles.ts`, etc.
- `src/stores/routeStore.ts` — Pinia store for route state.
- `src/types/index.ts` — TypeScript interfaces shared with backend API responses.

## Data Preprocessing

Navigation data must be preprocessed before use. The raw Aerosoft data on disk is too slow for Dijkstra queries.

1. Set `LOCAL_ASDATA_PATH` in `.env` to the Aerosoft data directory.
2. Run `python openRouterFinder/scripts/pack_data.py`.
3. Answer `y` for airport data (outputs `airport_$(cycle).air`) or `n` for global airways (outputs `navidata_$(cycle).map`).

For Fenix A320 data, use the admin upload API (`POST /api/admin/navdata/upload`) which converts `nd.db3` to `.fb.zst` automatically.

## Environment Configuration

Copy `.env.example` to `.env`:
- `NAVDAT_PATH` / `APDAT_PATH` — paths to nav data files. Absolute paths are used as-is; relative paths are resolved from the project root. Modern FlatBuffers deployments only need `NAVDAT_PATH` pointing at a `navdata_*.fb.zst` file.
- `LOCAL_ASDATA_PATH` — path to raw Aerosoft data (for `pack_data.py`)
- `ADMIN_KEY` — enables admin dashboard and navdata upload
- `METAR_PATH` — METAR cache file location (default `data/metar.txt`)
- `METAR_UPDATE_MINUTES` — METAR refresh interval
- `BING_MAPS_KEY` — optional, for map tiles
- `DISABLE_CAPTCHA` — skip captcha validation (for testing/development)
- `AIRPORT_CONNECTION_CACHE_SIZE` — LRU cache size for built SID/STAR connections (default 1000)

## Important Notes

- The project root must be on `PYTHONPATH` when running Python directly (e.g., `PYTHONPATH=. python -m pytest`). The `npm run dev:backend` script runs from `openRouterFinder/` which works because uvicorn resolves the module path.
- `docs/superpowers/` and `.superpowers/` are in `.gitignore` and should not be committed.
- The frontend dev proxy only works when the backend is on `localhost:9807`. Use `start.bash` for a convenience script that starts both, rebuilds the frontend dist, and cleans caches.
- `core/storage/NavData/` contains auto-generated FlatBuffers code. Do not hand-edit these files.
- The `_compat.py` module is registered as `sys.modules["RouteFinderLib"]` so legacy pickle `.map` files can still load.

## Development Principles

### SID/STAR Symmetry and Unification

`build_sid()` and `build_star()` in `core/airport.py` are symmetric: one constructs departure procedures, the other arrival procedures. When modifying either, the other **must** receive the corresponding structural fix (reversed logic). Do not copy-paste code between them; extract shared helpers (e.g., `_register_common_procedures()`) instead.

### Empty-Name Marker Filtering

Fenix navdata stores all procedure waypoints in the `Waypoints` table. D-prefixed identifiers (e.g., `D321Y`) are real waypoints in this data set, not synthetic heading+distance markers, so `_leg_to_point()` does **not** filter them by name. Only legs whose decoded `Name()` is empty or `None` are filtered out. If an empty-name marker appears as a standalone point in a built procedure, it indicates a parsing or merging bug.

### Procedure Quality Invariants

All built procedures should satisfy these invariants (enforced by `tests/test_procedure_integrity.py`):

- **No isolated nodes**: Every point in a multi-point procedure must participate in at least one `internal_edge`.
- **No branching within a single procedure**: After deduplicating `internal_edges`, no node belonging to exactly one procedure should have more than 2 edges.
- **No teleportation**: Consecutive waypoints in a procedure should be geographically reasonable (domestic ≤ ~100 nm, international ≤ ~300 nm per leg).
- **Runway "ALL" must have a path**: Procedures with `runway="ALL"` must contain more than one point.
- **No hub nodes in pooled internal_edges**: Every edge in `internal_edges` must belong to at least one procedure's consecutive point pair. Bridge edges for isolated nodes belong in `bridge_edges`, not `internal_edges`, so they do not pollute the pooled procedure graph.

### Test Code Modification Policy

**No test code may be modified without explicit user authorization.** This includes adding `pytest.skip`, `xfail`, reducing test coverage, weakening assertions, or any other change that makes a failing test pass without fixing the underlying code or data-pipeline bug. If a test fails, find and fix the root cause in the production code.

### ZBAA 36L Northbound SIDs

36L northbound departures from Beijing Capital (ZBAA) **must circle the city to the west** (lon < 116.5°), never fly straight north through the city. This is a user-confirmed geographic invariant.

### Test Failure = Our Bug, Not "Missing Data"

**Never assume a test failure is caused by missing navdata, an unreachable airport pair in the real world, or a Fenix data gap.** Every airport pair in `AIRPORT_PAIRS` and every procedure in the test suite represents a real-world route that **must** be computable. If a test fails:

1. **Find the root cause in our code or data pipeline** — builder logic, edge creation, approach bridge fallback, transition merging, etc.
2. **Do not skip, silence, or work around the failure** — no `pytest.skip`, no `SKIP_PAIRS` additions, no "this airport doesn't have STAR so ignore it".
3. **Do not blame the source navdata** — Fenix `nd.db3` is the source of truth; if it contains the data but our builder loses it, that's our bug.

If a route query returns `"No result."`, HTTP 404, or an empty procedure list for a real-world airport, treat it as a **data-pipeline or algorithm bug** that must be fixed. Do not add skip logic or reduce test coverage to make tests pass.

### Documentation Sync Rule

**Any code change that affects architecture, APIs, data formats, SID/STAR behavior, or testing invariants must also update the relevant `docs/claude/*.md` file and/or `CLAUDE.md`.** Do not leave documentation out of sync with code. When in doubt, update it.
