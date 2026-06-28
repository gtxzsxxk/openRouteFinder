from openRouterFinder.utils.metar_parser import parse_metar


def test_parse_metar_basic():
    result = parse_metar("METAR ZBAA 120000Z 35003MPS 9999 FEW040 28/12 Q1012 NOSIG")
    assert result.station == "ZBAA"
    assert result.wind_direction == 350
    assert result.wind_speed == 3
    assert result.wind_speed_unit == "MPS"
    assert result.visibility == "9999"
    assert len(result.clouds) == 1
    assert result.clouds[0].cover == "FEW"
    assert result.clouds[0].base == 4000
    assert result.temperature == 28
    assert result.dewpoint == 12
    assert result.qnh == 1012
    assert result.trend == "NOSIG"


def test_parse_metar_cavok():
    result = parse_metar("METAR ZSSS 120000Z 36005KT CAVOK 25/18 Q1008 NOSIG")
    assert result.station == "ZSSS"
    assert result.wind_direction == 360
    assert result.wind_speed == 5
    assert result.wind_speed_unit == "KT"
    assert result.visibility == "CAVOK"
    assert result.temperature == 25
    assert result.dewpoint == 18
    assert result.qnh == 1008
    assert result.trend == "NOSIG"


def test_parse_metar_negative_temp():
    result = parse_metar("METAR UUEE 120000Z 27008MPS 9999 SCT020 M03/M08 Q1025 R24L/290095 NOSIG")
    assert result.station == "UUEE"
    assert result.temperature == -3
    assert result.dewpoint == -8
    assert result.qnh == 1025
    assert result.trend == "R24L/290095 NOSIG"


def test_parse_metar_knots():
    result = parse_metar("METAR KLAX 120000Z 24010KT 10SM FEW250 22/14 A2995")
    assert result.station == "KLAX"
    assert result.wind_speed == 10
    assert result.wind_speed_unit == "KT"
    assert result.visibility == "10SM"
    assert result.temperature == 22
    assert result.dewpoint == 14


def test_parse_metar_gust():
    result = parse_metar("METAR EGLL 120000Z 27015G25KT 9999 SCT030 15/10 Q1015")
    assert result.wind_speed == 15
    assert result.wind_gust == 25
    assert result.wind_speed_unit == "KT"


def test_parse_metar_vrb():
    result = parse_metar("METAR LFPG 120000Z VRB05KT 9999 BKN015 20/15 Q1010")
    assert result.wind_direction is None
    assert result.wind_speed == 5


def test_parse_metar_multiple_clouds():
    result = parse_metar("METAR RJTT 120000Z 09008KT 9999 FEW030 SCT050 BKN100 30/22 Q1005 NOSIG")
    assert len(result.clouds) == 3
    assert result.clouds[0].cover == "FEW"
    assert result.clouds[0].base == 3000
    assert result.clouds[1].cover == "SCT"
    assert result.clouds[1].base == 5000
    assert result.clouds[2].cover == "BKN"
    assert result.clouds[2].base == 10000


def test_parse_metar_weather_phenomena():
    result = parse_metar("METAR KJFK 120000Z 31012KT 5SM -RA BR FEW010 OVC030 18/16 A2980")
    assert result.visibility == "5SM"
    assert "-RA" in result.weather
    assert "BR" in result.weather


def test_parse_metar_empty():
    result = parse_metar("")
    assert result.raw == ""
    assert result.station is None


def test_parse_metar_not_available():
    result = parse_metar("ZBAA METAR NOT AVAILABLE")
    assert result.station is None
    assert result.raw == "ZBAA METAR NOT AVAILABLE"
