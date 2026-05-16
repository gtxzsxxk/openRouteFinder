from openRouterFinder.core.airport import AirportConnector


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
