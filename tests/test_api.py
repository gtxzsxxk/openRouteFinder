import pytest
from fastapi.testclient import TestClient
from openRouterFinder.api import app

client = TestClient(app)


def test_get_airport_procedures():
    """Should return SID exits and STAR entries for an airport."""
    response = client.get("/api/airports/ZGHA/procedures")
    assert response.status_code == 200
    data = response.json()
    assert data["icao"] == "ZGHA"
    assert "sid" in data
    assert "star" in data
    assert "exits" in data["sid"]
    assert "entries" in data["star"]
    for exit_info in data["sid"]["exits"]:
        assert "name" in exit_info
        assert "procedures" in exit_info
        assert isinstance(exit_info["procedures"], list)


def test_get_airport_procedures_not_found():
    """Should return 404 for unknown airport."""
    response = client.get("/api/airports/XXXX/procedures")
    assert response.status_code == 404


def test_post_route_accepts_constraint_fields():
    """RouteRequest schema should accept sidExit and starEntry without 422."""
    response = client.post("/api/route", json={
        "orig": "ZGHA",
        "dest": "ZJSY",
        "validCode": "9999",
        "validToken": "fake-token",
        "sidExit": "PIMOL",
        "starEntry": "IGPAR",
    })
    assert response.status_code != 422
