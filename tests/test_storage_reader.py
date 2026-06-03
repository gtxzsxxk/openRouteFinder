from pathlib import Path

import pytest

from openRouterFinder.core.storage.builder import build_from_fenix
from openRouterFinder.core.storage.reader import MmappedNavData


def test_mmapped_reader():
    """Test reader with actual Fenix data."""
    db_path = Path("/tmp/navdata_analysis/fenix_a320_2604/Navdata/nd.db3")
    if not db_path.exists():
        pytest.skip("Fenix sample data not available")

    # Build a temporary .fb file
    raw = build_from_fenix(db_path, "2604", "16APR26", "13MAY26")
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
