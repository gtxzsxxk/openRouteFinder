"""E2E: /api/airports/{icao}/procedures and route endpoint-output invariants.

These assert the API transformation layer (runway-ALL filtering / renaming,
runway-field sanitization) that lives in api.py and only manifests over HTTP —
the connector graph does not expose it, so these belong in the e2e layer.
"""

import re

import pytest

# Curated representative airports (mirrors tests/unit/test_procedure_integrity).
PROC_AIRPORTS = [
    "ZBAA",
    "ZGGG",
    "ZGHA",
    "ZJSY",
    "ZSPD",
    "ZSSS",
    "RKSI",
    "RKPC",
    "ZBAD",
    "RJTT",
    "RJBB",
    "KLAX",
    "KSEA",
    "KJFK",
    "TNCM",
    "ZGSZ",
    "VHHH",
    "RCTP",
    "CYVR",
    "KSFO",
]

# Routes covering airports with known ALL+specific runway conflicts.
RUNWAY_ALL_CHECK_PAIRS = [
    ("ZBAA", "KLAX"),  # KIMMO3: ALL + 24R
    ("ZBAA", "KSEA"),  # BASET5 / BIGBR3: ALL + multiple runways
    ("KJFK", "KLAX"),  # ANJLL4 / DIRBY2: ALL + multiple runways
]

RUNWAY_RE = re.compile(r"^\d+[LRC]?$")


def _get_procedures(client, icao):
    resp = client.get(f"/api/airports/{icao}/procedures?detail=true&cycle=2604")
    assert resp.status_code == 200, f"{icao}: procedures endpoint returned {resp.status_code}"
    data = resp.json()
    assert data.get("icao") == icao, f"{icao}: unexpected response shape"
    return data


def _all_procedure_tuples(data):
    """Yield (label, key, proc) for every detailed procedure tuple.

    proc tuple shape: [name, runway, points, transitions].
    """
    for label in ("SID", "STAR"):
        section = data.get(f"{label.lower()}Details", {})
        for key, proc_list in section.items():
            for proc in proc_list:
                yield label, key, proc


def _post_route(client, orig, dest):
    return client.post(
        "/api/route",
        json={
            "orig": orig,
            "dest": dest,
            "validCode": "",
            "validToken": "",
            "sidExit": "",
            "starEntry": "",
            "cycle": "2604",
        },
    )


# ---------------------------------------------------------------------------
# Endpoint availability
# ---------------------------------------------------------------------------


@pytest.mark.e2e
@pytest.mark.parametrize("icao", PROC_AIRPORTS)
def test_procedures_endpoint(client, icao):
    """Every test airport must expose at least one SID exit or STAR entry."""
    resp = client.get(f"/api/airports/{icao}/procedures?detail=true&cycle=2604")
    assert resp.status_code == 200, f"{icao}: {resp.status_code}"
    data = resp.json()
    assert data.get("icao") == icao, f"{icao}: unexpected shape"
    sids = data.get("sid", {}).get("exits", [])
    stars = data.get("star", {}).get("entries", [])
    assert sids or stars, f"{icao}: no SID exits and no STAR entries"


@pytest.mark.e2e
def test_unknown_airport_404(client):
    resp = client.get("/api/airports/XXXX/procedures?detail=true&cycle=2604")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Runway-ALL filtering (api.py transformation layer)
# ---------------------------------------------------------------------------


@pytest.mark.e2e
@pytest.mark.parametrize("icao", PROC_AIRPORTS)
def test_no_runway_all_in_procedure_lists(client, icao):
    """Frontend procedure dropdowns must never show runway='ALL'.

    A procedure with runway='ALL' means the data pipeline failed to associate
    the procedure with a real runway — a data-pipeline or algorithm bug that
    must be fixed, not worked around with frontend filters.
    """
    data = _get_procedures(client, icao)
    failures = []
    for label, key, proc in _all_procedure_tuples(data):
        if proc[1] == "ALL":
            failures.append(
                f"{icao} {label} {proc[0]}: runway='ALL' "
                f"(key={key}, points={[p[0] for p in proc[2]]})"
            )
    assert not failures, "Procedures with runway='ALL' found:\n" + "\n".join(failures)


@pytest.mark.e2e
@pytest.mark.parametrize("icao", PROC_AIRPORTS)
def test_no_runway_all_when_specific_exists(client, icao):
    """No procedure name may expose both runway='ALL' and runway-specific variants."""
    data = _get_procedures(client, icao)
    for label in ("SID", "STAR"):
        section = data.get(f"{label.lower()}Details", {})
        name_runways: dict = {}
        for _key, proc_list in section.items():
            for proc in proc_list:
                name_runways.setdefault(proc[0], set()).add(proc[1])

        failures = []
        for proc_name, runways in name_runways.items():
            if "ALL" in runways and len(runways) > 1:
                failures.append(
                    f"{icao} {label}: {proc_name} has both runway='ALL' and specific "
                    f"runways {sorted(r for r in runways if r != 'ALL')}"
                )
        assert not failures, "Procedures with conflicting runway values:\n" + "\n".join(failures)


@pytest.mark.e2e
@pytest.mark.parametrize("orig,dest", RUNWAY_ALL_CHECK_PAIRS)
def test_post_route_no_runway_all_when_specific_exists(client, orig, dest):
    """POST /api/route must not return runway='ALL' alongside a single specific runway.

    Regression: the old code filtered ALL only in get_airport_procedures, so
    post_route still exposed e.g. KIMMO3 - ALL in the STAR field.
    """
    resp = _post_route(client, orig, dest)
    assert resp.status_code == 200, f"{orig}->{dest}: {resp.status_code}"
    data = resp.json()
    assert data.get("route") != "No result.", f"{orig}->{dest}: no route found"

    for label, field_name in (("SID", "SID"), ("STAR", "STAR")):
        procs = data.get(field_name, {})
        name_runways: dict = {}
        for proc_list in procs.values():
            for proc in proc_list:
                name_runways.setdefault(proc[0], set()).add(proc[1])

        failures = []
        for proc_name, runways in name_runways.items():
            specific = runways - {"ALL"}
            # Only single-runway ALL variants must be renamed; multi-runway ALL
            # variants are kept because their entry-point keys are needed.
            if "ALL" in runways and len(specific) == 1:
                failures.append(
                    f"{orig}->{dest} {label}: {proc_name} has runway='ALL' but only one "
                    f"specific runway {sorted(specific)} — should be renamed"
                )
        assert not failures, "Procedures with conflicting runway values:\n" + "\n".join(failures)


@pytest.mark.e2e
@pytest.mark.parametrize("icao", PROC_AIRPORTS)
def test_runway_field_is_valid(client, icao):
    """Runway must be a real designator (e.g. 16L, 34R, 07), 'ALL', or empty.

    Non-RW transition names (e.g. VIXOR, EHF, PDT) are entry/exit points, not
    runways, and must never leak into the runway field.
    """
    data = _get_procedures(client, icao)
    failures = []
    for label, key, proc in _all_procedure_tuples(data):
        runway = proc[1]
        if runway in ("ALL", ""):
            continue
        if not RUNWAY_RE.match(runway):
            failures.append(
                f"{icao} {label} key={key} {proc[0]}: runway={runway!r} is not a valid designator"
            )
    assert not failures, "Invalid runway values:\n" + "\n".join(failures)
