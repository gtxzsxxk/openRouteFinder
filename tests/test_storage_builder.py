from pathlib import Path

import pytest

from openRouterFinder.core.storage.builder import build_from_fenix


def test_build_from_sample_fenix():
    """Test builder with the actual Fenix 2604 sample data.

    Note: This imports the full database (~320k nodes, ~160k edges, ~17k airports)
    and may take several minutes."""
    db_path = Path("/tmp/navdata_analysis/fenix_a320_2604/Navdata/nd.db3")
    if not db_path.exists():
        pytest.skip("Fenix sample data not available")

    raw = build_from_fenix(db_path, cycle="2604", effective_from="16APR26", effective_to="13MAY26")
    assert len(raw) > 0

    # Verify by reading back
    from openRouterFinder.core.storage.NavData.NavData import NavData

    nav = NavData.GetRootAs(raw, 0)
    assert nav.Cycle().decode() == "2604"
    assert nav.NodesLength() > 100000
    assert nav.EdgesLength() > 100000
    assert nav.AirportsLength() > 10000
