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
| `tests/test_procedure_integrity.py` | Integration | Direct `FlatbuffersAirportConnector` integrity checks |

## Test Data Requirements

- All tests require navdata to be available (`data/navdata_2604.fb.zst`)
- Tests skip gracefully via `pytest.skip()` if navdata is unavailable
- Integration tests require `DISABLE_CAPTCHA=true` env var

## Procedure Integrity Tests

`tests/test_procedure_integrity.py` directly instantiates `FlatbuffersAirportConnector` and inspects built procedures for all test airports.

### Test Coverage

| Test | What It Checks |
|------|----------------|
| `test_no_synthetic_markers_in_procedures` | D#### markers must not appear in any procedure |
| `test_procedure_edge_counts_reasonable` | No isolated nodes (degree 0), no branching within single procedure (degree >2 after dedup) |
| `test_procedure_paths_no_teleportation` | No leg exceeds distance threshold (domestic ≤100nm, international ≤250nm) |
| `test_no_runway_all_with_single_point` | Runway="ALL" must have >1 point |
| `test_zbaa_36l_sid_circles_beijing` | 36L northbound SIDs must circle Beijing west (lon < 116.5) |
| `test_star_final_approach_reasonable` | STARs have ≥2 points, no synthetic markers |

### Test Airports

```python
TEST_AIRPORTS = [
    "ZBAA", "ZGGG", "ZGHA", "ZJSY", "ZSPD", "ZSSS",
    "RKSI", "RKPC", "ZBAD", "RJTT", "RJBB",
    "KLAX", "KSEA", "KJFK", "TNCM", "ZGSZ",
]
```

### Known Navdata Gaps

```python
SKIP_PAIRS = {("KJFK", "KLAX")}  # No airway connectivity
```

Some pairs are skipped at runtime if navdata lacks SID/STAR for them.

## Integration Route Tests

`tests/test_integration_routes.py` uses `fastapi.testclient.TestClient` to call actual API endpoints.

### Airport Pairs (17 pairs)

ZBAA→ZGGG, ZBAA→ZGHA, ZGHA→ZJSY, ZBAA→ZSPD, ZBAA→ZSSS, ZBAA→RKSI, ZBAA→RKPC, RKPC→ZBAD, RKPC→RKSI, ZBAA→RJTT, RJTT→RJBB, ZBAA→KLAX, ZBAA→KSEA, KLAX→KSEA, KJFK→KLAX, ZBAA→TNCM, ZBAA→ZGSZ

### Assertions Per Pair

- Response status == 200
- `route` is not empty and not "No result."
- `nodes` has ≥2 elements
- `distance` is not "0.00 nm / 0.00 km"

### Procedure Fetch Tests

For each test airport: `GET /api/airports/{icao}/procedures` must return 200 with at least one SID exit or STAR entry.
