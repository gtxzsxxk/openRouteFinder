"""Fenix nd.db3 -> FlatBuffers build pipeline tests.

Exercises build_from_fenix -> MmappedNavData -> NavDataRegistry against real
Fenix sample data. Skips when the sample DB is unavailable.
"""

from pathlib import Path

import pytest

from openRouterFinder.core.storage.builder import build_from_fenix
from openRouterFinder.core.storage.reader import MmappedNavData
from openRouterFinder.core.storage.registry import NavDataRegistry

FENIX_DB = Path("/tmp/navdata_analysis/fenix_a320_2604/Navdata/nd.db3")


def test_build_from_sample_fenix():
    """Test builder with the actual Fenix 2604 sample data.

    Note: This imports the full database (~320k nodes, ~160k edges, ~17k airports)
    and may take several minutes."""
    if not FENIX_DB.exists():
        pytest.skip("Fenix sample data not available")

    raw = build_from_fenix(FENIX_DB, cycle="2604", effective_from="16APR26", effective_to="13MAY26")
    assert len(raw) > 0

    # Verify by reading back
    from openRouterFinder.core.storage.NavData.NavData import NavData

    nav = NavData.GetRootAs(raw, 0)
    assert nav.Cycle().decode() == "2604"
    assert nav.NodesLength() > 100000
    assert nav.EdgesLength() > 100000
    assert nav.AirportsLength() > 10000


def test_mmapped_reader():
    """Test reader with actual Fenix data."""
    if not FENIX_DB.exists():
        pytest.skip("Fenix sample data not available")

    # Build a temporary .fb file
    raw = build_from_fenix(FENIX_DB, "2604", "16APR26", "13MAY26")
    tmp_path = Path("/tmp/test_navdata_2604.fb")
    tmp_path.write_bytes(raw)

    with MmappedNavData(tmp_path) as nav:
        assert nav.cycle == "2604"
        assert nav.num_nodes > 100000
        assert nav.num_edges > 100000
        assert nav.num_airports > 10000

        # Test airport lookup
        ap = nav.get_airport("ZBAA")
        assert ap is not None
        icao = ap.Icao()
        assert (icao.decode() if icao else "") == "ZBAA"

        # Test node lookup
        node = nav.find_node("REVLU", 39.866667, 116.096667)
        assert node is not None
        assert node.name == "REVLU"

    tmp_path.unlink()


def test_registry():
    """Test multi-version registry."""
    if not FENIX_DB.exists():
        pytest.skip("Fenix sample data not available")

    # Create temp data dir with two cycles
    data_dir = Path("/tmp/test_registry_data")
    data_dir.mkdir(exist_ok=True)

    for cycle in ["2206", "2301"]:
        raw = build_from_fenix(FENIX_DB, cycle, "01JAN22", "31JAN22")
        (data_dir / f"navdata_{cycle}.fb").write_bytes(raw)

    reg = NavDataRegistry(data_dir)
    assert len(reg) == 2
    assert reg.list_cycles() == ["2206", "2301"]
    assert reg.has_cycle("2206")
    assert not reg.has_cycle("9999")

    # Get latest
    latest = reg.get()
    assert latest.cycle == "2301"

    # Get specific
    nav = reg.get("2206")
    assert nav.cycle == "2206"

    # Unregister
    reg.unregister("2206")
    assert len(reg) == 1

    reg.close_all()

    # Cleanup
    for f in data_dir.glob("*.fb"):
        f.unlink()
    data_dir.rmdir()
