# Testing

Two-layer pytest suite. Configuration lives in `pyproject.toml`
(`[tool.pytest.ini_options]`); the e2e layer has its own
`tests/e2e/conftest.py` that boots a real server.

## Layers

| Layer | Directory | What it does |
|-------|-----------|--------------|
| **Unit** | `tests/unit/` | Tests functions/objects directly, not through HTTP. Pure-logic tests run always; tests needing navdata or Fenix data skip when those are absent. |
| **E2E** | `tests/e2e/` | Boots a **real uvicorn server** in a subprocess and drives it over HTTP (httpx). Asserts route- and endpoint-level invariants. |

## Running Tests

```bash
PYTHONPATH=. DISABLE_CAPTCHA=true pytest            # everything
pytest tests/unit -v                                # unit layer only
pytest tests/e2e -v                                 # e2e layer only (boots a server)
pytest tests/unit/test_dijkstra.py -v               # single file
pytest tests/unit/test_airport_unit.py::test_build_sid_with_filter -v   # single test
pytest tests/e2e/test_perf_e2e.py -s -m perf        # perf numbers (need -s to print)
```

The e2e layer starts uvicorn with `DISABLE_CAPTCHA=true` set automatically via
the fixture's environment, so the captcha never blocks route queries.

## Unit Layer (`tests/unit/`)

| File | What It Tests | Needs |
|------|---------------|-------|
| `test_graph.py` | `Node`, `Edge`, `great_circle_distance_km()` | — |
| `test_dijkstra.py` | `RouteEngine._sort_route`, `_build_node_info` on synthetic graphs | — |
| `test_airport_unit.py` | legacy `AirportConnector` (dict fixtures); `build_sid/star` filter contract | navdata for filter tests |
| `test_data_loader.py` | `NavGraph` index/immutability on synthetic nodes | — |
| `test_metar_parser.py` / `test_metar.py` | METAR parsing / fetcher | — |
| `test_validcode.py` | CAPTCHA generation | — |
| `test_procedure_integrity.py` | SID/STAR **structural invariants** via `FlatbuffersAirportConnector` introspection | navdata |
| `test_vector_fallback.py` | synthetic radar-vector SID/STAR fallback (CYVR) | navdata |
| `test_build_pipeline.py` | `build_from_fenix` → `MmappedNavData` → `NavDataRegistry` | Fenix `nd.db3` |

Tests that need `data/navdata_2604.fb.zst` or the Fenix `nd.db3` sample
`pytest.skip()` when the data is unavailable — the only sanctioned skip.

### Procedure Structural Invariants (`test_procedure_integrity.py`)

Inspects the in-memory `AirportConnection` graph (procedure points,
transitions, pooled `internal_edges`) — things the HTTP API does not expose.
Coverage is a **curated 20-airport set** (every specifically-named invariant
plus all e2e route-pair airports); builds are memoised per ICAO so the 10 tests
share one build pass.

| Test | Checks |
|------|--------|
| `test_no_empty_name_markers_in_procedures` | No empty-name marker as a standalone point |
| `test_procedure_edge_counts_reasonable` | No isolated node; no branching within one procedure's main path |
| `test_procedure_paths_no_teleportation` | No procedure leg exceeds threshold (domestic ≤100nm, intl ≤300nm) |
| `test_no_runway_all_with_single_point` | `runway="ALL"` must have >1 point |
| `test_sid_runway_endpoint_consistent` | If any SID for a runway starts with DERxx/DExx, all must |
| `test_zbaa_36l_sid_circles_beijing` | ZBAA 36L northbound SIDs circle Beijing west (`lon < 116.5`) |
| `test_star_final_approach_reasonable` | STARs have no empty-name markers |
| `test_zggg_ikavo3_approach_bridge_exists` | IKAVO3 (19R/20L/20R) has a waypoint between LUPVU and the airport |
| `test_zggg_ikavo3_has_complete_points` | IKAVO3 (all runways) has a complete path (>2 points) |
| `test_procedure_internal_edges_no_hub_nodes` | Every pooled `internal_edge` belongs to a procedure's consecutive pair |

## E2E Layer (`tests/e2e/`)

`tests/e2e/conftest.py` provides a session-scoped `base_url`/`client` fixture
that picks a free port, starts `uvicorn openRouterFinder.api:app` in a
subprocess, polls `/health` until ready (60s budget), and tears the process
down at the end. If `data/navdata_2604.fb.zst` is absent the whole e2e layer
skips.

### `test_routes_e2e.py`

One parametrized test per airport pair (20 pairs) calls a single
`validate_route()` helper so all route-level invariants live in one place:

- HTTP 200, `route` not empty / not `"No result."`, ≥2 nodes, non-zero distance
- Simple path (no node visited twice across the assembled airway chain)
- SID and STAR segments each contiguous in `routeSegments`

Enroute airway legs are **not** distance-checked (long oceanic legs are
legitimate); procedure-leg teleportation is covered in the unit layer.
`ZBAA→RKSI` is a normal pair (the former `xfail` was removed once it routed).

### `test_connectivity_e2e.py`

Connectivity **fuzz / discovery** test — the tool for finding region-level
routing bugs (e.g. the CYVR→KSFO regression) that a curated pair list can never
surface. It samples **N random distinct airport pairs from the full navdata
pool** (all ~17k airports, read directly from `navdata_2604.fb.zst` as test
setup) and asserts each routes in **both directions** over real HTTP.

- **No distance gate.** Per CLAUDE.md, a disconnected pair is a route-engine /
  data-pipeline bug, never "an unreachable real-world pair". Long
  intercontinental pairs (e.g. `EDNG→NZCG`) are routable through the global
  airway network and must connect like any other — a human can hand-build the
  path, so `"No result."` is our bug.
- **Bidirectional** catches asymmetric bugs (one direction routes, the reverse
  does not).
- **Reproducible randomness.** Each run uses a fresh seed, printed in the
  failure report. Replay an exact run with `CONN_TEST_SEED=<seed>`. Override the
  sample size with `CONN_TEST_PAIRS` (default 100).
- Failures are **collected and reported together** at the end (full list of
  disconnected `orig → dest` directions plus the replay seed), not failed
  one-at-a-time.

```bash
# Full default run (100 pairs, fresh random seed)
pytest tests/e2e/test_connectivity_e2e.py -v
# Replay a specific failing sample
CONN_TEST_SEED=3490832160 CONN_TEST_PAIRS=10 pytest tests/e2e/test_connectivity_e2e.py -s
```

This test is expected to surface real bugs until the route engine connects every
sampled pair; a red result means "fix the engine", not "weaken the test".

### `test_perf_e2e.py`

**Measurement-only** latency tests (`@pytest.mark.perf`) — they never assert a
time threshold (machine/load dependent, would be flaky) and are always green.
They time real HTTP route queries over the same 20 connected pairs and print
statistics (min/median/mean/p95/max). Run with `-s` to see the numbers.

| Test | Pattern |
|------|---------|
| `test_perf_continuous` | Back-to-back over the pair set, several rounds. Round 1 = cold procedure builds, later rounds = cache-warm. Shows the cache effect. |
| `test_perf_interval_random` | One request per second, random order, biased to the longest (intercontinental) pairs. Models spread-out real traffic on diverse procedures. |

Tunables (env): `PERF_ROUNDS` (default 3), `PERF_INTERVAL_REQUESTS` (default
10), `PERF_INTERVAL_SECONDS` (default 1.0).

### `test_procedures_e2e.py`

Endpoint-output invariants — the `api.py` transformation layer (runway-ALL
filtering/renaming, runway-field sanitization) that only manifests over HTTP:

| Test | Checks |
|------|--------|
| `test_procedures_endpoint` | `GET /api/airports/{icao}/procedures` returns ≥1 SID exit or STAR entry |
| `test_unknown_airport_404` | Unknown airport → 404 |
| `test_no_runway_all_in_procedure_lists` | Frontend lists never show `runway="ALL"` |
| `test_no_runway_all_when_specific_exists` | No procedure name exposes both ALL and specific runways |
| `test_post_route_no_runway_all_when_specific_exists` | `/api/route` renames single-runway ALL variants |
| `test_runway_field_is_valid` | Runway is a real designator, `ALL`, or empty |

## Test Failure Policy

Per CLAUDE.md, every airport pair and procedure represents a real-world route
that **must** be computable. A failure is a code or data-pipeline bug, never
"missing data". The only sanctioned skips are unavailable test data
(`navdata_2604.fb.zst` / Fenix `nd.db3`).

## Test Code Modification Policy

**No test code may be modified without explicit user authorization** — no
`pytest.skip`/`xfail`, no coverage reduction, no weakened assertions, no
widened tolerances that make a failing test pass without fixing the root cause.
