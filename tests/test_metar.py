from openRouterFinder.utils.metar import read_metar


def test_read_metar_not_available():
    result = read_metar("XXXX")
    assert "METAR NOT AVAILABLE" in result
