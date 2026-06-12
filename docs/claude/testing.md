# Testing

Pure pytest. No `pytest.ini`, `setup.cfg`, or `conftest.py`.

## Running Tests

```bash
pytest                          # all tests
pytest -v                       # verbose
pytest tests/test_dijkstra.py -v                    # single file
pytest tests/test_airport.py::test_build_sid_with_filter -v   # single test
pytest tests/test_procedure_integrity.py -v         # procedure integrity
pytest tests/test_integration_routes.py -v          # HTTP integration

# With captcha disabled (required for integration tests)
PYTHONPATH=. DISABLE_CAPTCHA=true pytest tests/test_integration_routes.py -v
```

## Test Files

| File | Type | What It Tests |
|------|------|---------------|
| `tests/test_graph.py` | Unit | `Node`, `Edge`, `great_circle_distance_km()` |
| `tests/test_dijkstra.py` | Unit | `RouteEngine.search()`, A* correctness, edge cases |
| `tests/test_airport.py` | Unit | `AirportConnector`, `FlatbuffersAirportConnector`, SID/STAR building |
| `tests/test_data_loader.py` | Unit | `NavGraph`, `search_route()` orchestration |
| `tests/test_storage_reader.py` | Unit | `MmappedNavData`, mmap reading, index building |
| `tests/test_storage_registry.py` | Unit | `NavDataRegistry`, multi-cycle management |
| `tests/test_storage_builder.py` | Unit | `build_from_fenix()`, Fenix DB conversion |
| `tests/test_api.py` | Unit | FastAPI endpoint unit tests (mocked) |
| `tests/test_metar_parser.py` | Unit | METAR string parsing |
| `tests/test_metar.py` | Unit | METAR fetcher |
| `tests/test_validcode.py` | Unit | CAPTCHA generation |
| `tests/test_integration_routes.py` | Integration | HTTP API route queries for 17 airport pairs |
| `tests/test_procedure_integrity.py` | Integration | HTTP API + direct `FlatbuffersAirportConnector` integrity checks |

## Test Data Requirements

- All tests require navdata to be available (`data/navdata_2604.fb.zst`)
- Tests skip gracefully via `pytest.skip()` if navdata is unavailable
- Integration tests require `DISABLE_CAPTCHA=true` env var

## Procedure Integrity Tests

`tests/test_procedure_integrity.py` directly instantiates `FlatbuffersAirportConnector` and inspects built procedures for all test airports.

### Test Coverage

| Test | What It Checks |
|------|----------------|
| `test_no_synthetic_markers_in_procedures` | Empty-name markers must not appear as standalone points in any procedure |
| `test_procedure_edge_counts_reasonable` | No isolated nodes (degree 0), no branching within single procedure (degree >2 after dedup) |
| `test_procedure_paths_no_teleportation` | No leg exceeds distance threshold (domestic ≤100nm, international ≤300nm) |
| `test_no_runway_all_with_single_point` | Runway="ALL" must have >1 point |
| `test_sid_runway_endpoint_consistent` | If any SID for a runway starts with DERxx/DExx, all SIDs for that runway must share the same endpoint |
| `test_zbaa_36l_sid_circles_beijing` | 36L northbound SIDs must circle Beijing west (lon < 116.5) |
| `test_star_final_approach_reasonable` | STARs have ≥2 points, no empty-name markers |
| `test_zggg_ikavo3_approach_bridge_exists` | IKAVO3 for runways 19R/20L/20R must have a waypoint between LUPVU and the airport |
| `test_zggg_ikavo3_has_complete_points` | IKAVO3 for all runways must have a complete approach path with >2 points |
| `test_procedure_internal_edges_no_hub_nodes` | Every edge in pooled `internal_edges` must belong to at least one procedure's consecutive point pair |

### Test Airports

```python
TEST_AIRPORTS = [
    "ZBAA", "ZGGG", "ZGHA", "ZJSY", "ZSPD", "ZSSS",
    "RKSI", "RKPC", "ZBAD", "RJTT", "RJBB",
    "KLAX", "KSEA", "KJFK", "TNCM", "ZGSZ",
]
```

### Test Failure Policy

Every test failure is treated as a code or data-pipeline bug, never as "missing navdata". There is no `pytest.skip` or `SKIP_PAIRS` workaround. The only exception is `ZBAA → RKSI`, which is marked as `pytest.mark.xfail` due to a known routing edge case.

### Test Code Modification Policy

**No test code may be modified without explicit user authorization.** This includes:
- Adding `pytest.skip`, `xfail`, or any skip mechanism
- Reducing test coverage or removing test cases
- Weakening assertions or expanding tolerance thresholds
- Any change that makes a failing test pass without fixing the underlying code or data-pipeline bug

If a test fails, find and fix the root cause in the production code (or data pipeline), not in the test.

## Integration Route Tests

`tests/test_integration_routes.py` uses `fastapi.testclient.TestClient` to call actual API endpoints.

### Airport Pairs (17 pairs)

ZBAA→ZGGG, ZBAA→ZGHA, ZGHA→ZJSY, ZBAA→ZSPD, ZBAA→ZSSS, ZBAA→RKSI, ZBAA→RKPC, RKPC→ZBAD, RKPC→RKSI, ZBAA→RJTT, RJTT→RJBB, ZBAA→KLAX, ZBAA→KSEA, KLAX→KSEA, KJFK→KLAX, ZBAA→TNCM, ZBAA→ZGSZ

### Assertions Per Pair

| Test | What It Checks |
|------|----------------|
| `test_route_query_returns_valid_route` | Response status == 200, `route` is not empty, `nodes` has ≥2 elements, `distance` is not "0.00 nm / 0.00 km" |
| `test_route_topology_no_branching` | Route is a simple path (no node visited twice) |
| `test_route_procedure_segments_continuous` | SID/STAR segment nodes are contiguous in the route |
| `test_route_sid_star_node_name_matches_procedure` | `sidNodeName`/`starNodeName` match the best-fit procedure key from route segments |
| `test_frontend_procedure_selection_matches_route` | Simulated frontend `_matchProcedureIndex` + `_matchTransitionIndex` produces a contiguous subsequence of the route |
| `test_all_sid_exits_produce_valid_routes` | Every SID exit for the origin airport produces a valid route to the destination |
| `test_all_star_entries_produce_valid_routes` | Every STAR entry for the destination airport produces a valid route from the origin |
| `test_exhaustive_sid_star_combinations` | All SID × STAR combinations produce valid routes (no 404 or "No result.") |

### Procedure Fetch Tests

For each test airport: `GET /api/airports/{icao}/procedures` must return 200 with at least one SID exit or STAR entry.
