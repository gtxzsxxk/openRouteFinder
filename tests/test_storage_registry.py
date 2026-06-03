from pathlib import Path

import pytest

from openRouterFinder.core.storage.builder import build_from_fenix
from openRouterFinder.core.storage.registry import NavDataRegistry


def test_registry():
    """Test multi-version registry."""
    db_path = Path("/tmp/navdata_analysis/fenix_a320_2604/Navdata/nd.db3")
    if not db_path.exists():
        pytest.skip("Fenix sample data not available")

    # Create temp data dir with two cycles
    data_dir = Path("/tmp/test_registry_data")
    data_dir.mkdir(exist_ok=True)

    for cycle in ["2206", "2301"]:
        raw = build_from_fenix(db_path, cycle, "01JAN22", "31JAN22")
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
