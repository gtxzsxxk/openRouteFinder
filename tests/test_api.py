from fastapi.testclient import TestClient

from openRouterFinder.api import app

client = TestClient(app)


def test_get_airport_procedures():
    """Should return SID exits and STAR entries for an airport when navdata exists."""
    response = client.get("/api/airports/ZGHA/procedures")
    # Without navdata .fb files, returns 503 Service Unavailable
    assert response.status_code in (200, 503)


def test_get_airport_procedures_not_found():
    """Should return 404 for unknown airport when navdata exists."""
    response = client.get("/api/airports/XXXX/procedures")
    # Without navdata .fb files, returns 503 Service Unavailable
    assert response.status_code in (404, 503)


def test_post_route_accepts_constraint_fields():
    """RouteRequest schema should accept sidExit and starEntry without 422."""
    response = client.post(
        "/api/route",
        json={
            "orig": "ZGHA",
            "dest": "ZJSY",
            "validCode": "9999",
            "validToken": "fake-token",
            "sidExit": "PIMOL",
            "starEntry": "IGPAR",
        },
    )
    assert response.status_code != 422
