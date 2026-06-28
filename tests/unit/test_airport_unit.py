from openRouterFinder.core.airport import AirportConnector, FlatbuffersAirportConnector


def test_get_airport_coords():
    maps = {
        "GLOBAL": ["A,ZGHA,Changsha Huanghua,28.2000,113.0833\n"],
        "ZGHA": "",
    }
    conn = AirportConnector(maps, {})
    lat, lon = conn._get_airport_coords("ZGHA")
    assert abs(lat - 28.2) < 0.01
    assert abs(lon - 113.0833) < 0.01


def test_get_airport_names():
    maps = {
        "GLOBAL": ["A,ZGHA,Changsha Huanghua,28.2000,113.0833\n"],
    }
    conn = AirportConnector(maps, {})
    names = conn.get_airport_names("ZGHA")
    assert names == ["Changsha Huanghua"]


def test_build_sid_with_filter():
    """build_sid with filter_name only keeps matching exit procedures."""
    from openRouterFinder.core.data_loader import get_nav_data

    nav = get_nav_data()
    if nav is None:
        import pytest

        pytest.skip("Navdata not available")

    conn = FlatbuffersAirportConnector(nav)

    result = conn.build_sid("ZGHA", filter_name="NONEXISTENT")
    assert result is not None
    assert len(result.connections) == 0
    assert len(result.procedures) == 0

    result_all = conn.build_sid("ZGHA")
    assert result_all is not None
    assert len(result_all.connections) > 0 or len(result_all.procedures) > 0


def test_build_star_with_filter():
    """build_star with filter_name only keeps matching entry procedures."""
    from openRouterFinder.core.data_loader import get_nav_data

    nav = get_nav_data()
    if nav is None:
        import pytest

        pytest.skip("Navdata not available")

    conn = FlatbuffersAirportConnector(nav)

    result = conn.build_star("ZJSY", filter_name="NONEXISTENT")
    assert result is not None
    assert len(result.connections) == 0
    assert len(result.procedures) == 0

    result_all = conn.build_star("ZJSY")
    assert result_all is not None
    assert len(result_all.connections) > 0 or len(result_all.procedures) > 0
