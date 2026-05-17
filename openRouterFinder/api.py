"""FastAPI application with thread-pooled A* route search."""

import asyncio
import uuid
import json
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from openRouterFinder.config import settings
from openRouterFinder.core.data_loader import (
    get_data_version,
    get_airport_maps,
    search_route,
)
from openRouterFinder.utils.metar import read_metar, start_metar_updater
from openRouterFinder.utils.validcode import generate_captcha_b64

# --- Concurrency controls ---
_dijkstra_pool = ThreadPoolExecutor(max_workers=4)
_route_semaphore = asyncio.Semaphore(8)

# --- Valid code storage ---
_valid_codes: dict[str, str] = {}

# --- Airport prefix index ---
_airport_prefix_index: dict[str, list] = {}
_airport_list: list = []


def _build_airport_index():
    """Build prefix index for O(1) airport autocomplete lookups."""
    global _airport_prefix_index, _airport_list
    maps = get_airport_maps()
    global_dat = maps.get("GLOBAL", [])
    airports = []

    for line in global_dat:
        parts = line.strip().split(",")
        if len(parts) < 5 or parts[0] != "A":
            continue
        try:
            lat = float(parts[3].strip())
            lon = float(parts[4].strip())
        except ValueError:
            continue
        airports.append({"icao": parts[1].strip(), "name": parts[2].strip(), "lat": lat, "lon": lon})

    _airport_list = airports

    # Build prefix index for ICAO codes
    for ap in airports:
        icao = ap["icao"]
        for i in range(1, len(icao) + 1):
            prefix = icao[:i]
            if prefix not in _airport_prefix_index:
                _airport_prefix_index[prefix] = []
            _airport_prefix_index[prefix].append(ap)

    print(f"Airport index built: {len(airports)} airports, {len(_airport_prefix_index)} prefixes")


def _search_airports(q: str, limit: int = 50) -> list:
    """O(1) airport search using prefix index, fallback to name search."""
    q_upper = q.upper()

    # Fast path: ICAO prefix match via index
    if q_upper in _airport_prefix_index:
        return _airport_prefix_index[q_upper][:limit]

    # Fallback: name substring search (for Chinese/non-ICAO queries)
    results = []
    for ap in _airport_list:
        if q_upper in ap["name"].upper():
            results.append(ap)
            if len(results) >= limit:
                break
    return results


# --- Pydantic Models ---

class RouteRequest(BaseModel):
    orig: str
    dest: str
    validCode: str
    validToken: str
    sidExit: Optional[str] = None
    starEntry: Optional[str] = None


# --- FastAPI App ---

app = FastAPI(
    title="OpenRouteFinder",
    description="Flight route finder API",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/version")
def get_version():
    return {"version": get_data_version()}


@app.get("/api/airports")
def get_airports(q: Optional[str] = None):
    q = (q or "").strip()
    if not q:
        return {"airports": _airport_list[:50]}
    return {"airports": _search_airports(q, limit=50)}


@app.get("/api/airports/{icao}")
def get_airport(icao: str):
    maps = get_airport_maps()
    icao = icao.upper()
    if icao not in maps:
        raise HTTPException(status_code=404, detail="Airport not found")
    global_dat = maps.get("GLOBAL", [])
    for line in global_dat:
        parts = line.strip().split(",")
        if len(parts) >= 5 and parts[0] == "A" and parts[1].strip() == icao:
            return {
                "icao": icao,
                "name": parts[2].strip(),
                "lat": float(parts[3].strip()),
                "lon": float(parts[4].strip()),
            }
    raise HTTPException(status_code=404, detail="Airport not found")


@app.get("/api/airports/{icao}/procedures")
def get_airport_procedures(icao: str):
    maps = get_airport_maps()
    icao = icao.upper()
    if icao not in maps:
        raise HTTPException(status_code=404, detail="Airport not found")

    from openRouterFinder.core.data_loader import get_nav_graph
    from openRouterFinder.core.airport import AirportConnector
    graph = get_nav_graph()
    connector = AirportConnector(maps, graph._node_index)

    sid_conn = connector.build_sid(icao)
    star_conn = connector.build_star(icao)

    sid_exits = []
    if sid_conn and sid_conn.procedures:
        seen = set()
        for exit_name, proc_list in sid_conn.procedures.items():
            if exit_name in seen:
                continue
            seen.add(exit_name)
            sid_exits.append({
                "name": exit_name,
                "procedures": list(dict.fromkeys(p.name for p in proc_list)),
            })

    star_entries = []
    if star_conn and star_conn.procedures:
        seen = set()
        for entry_name, proc_list in star_conn.procedures.items():
            if entry_name in seen:
                continue
            seen.add(entry_name)
            star_entries.append({
                "name": entry_name,
                "procedures": list(dict.fromkeys(p.name for p in proc_list)),
            })

    return {
        "icao": icao,
        "sid": {"exits": sid_exits},
        "star": {"entries": star_entries},
    }


@app.post("/api/route")
async def post_route(req: RouteRequest):
    # Validate captcha
    if req.validToken not in _valid_codes:
        raise HTTPException(status_code=401, detail="验证码已过期")
    if _valid_codes[req.validToken] != req.validCode:
        raise HTTPException(status_code=401, detail="验证码错误")
    del _valid_codes[req.validToken]

    try:
        async with _route_semaphore:
            result = await asyncio.get_event_loop().run_in_executor(
                _dijkstra_pool,
                lambda: search_route(req.orig, req.dest, sid_exit=req.sidExit, star_entry=req.starEntry),
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Route calculation failed: {e}")

    if result is None:
        raise HTTPException(status_code=404, detail="无法找到航路，请检查机场代码是否正确")

    # Map legacy fields
    if "nodeinformation" in result:
        raw_nodes = result.pop("nodeinformation")
        if raw_nodes:
            result["nodes"] = [
                {"name": n[0], "lat": n[1], "lon": n[2]}
                for n in raw_nodes
                if len(n) >= 3
            ]
        else:
            result["nodes"] = []

    result["weather"] = [read_metar(req.orig), read_metar(req.dest)]

    # Enrich with airport details and parsed weather
    from openRouterFinder.utils.metar_parser import parse_metar, translate_trend

    result["airportDetails"] = {
        "orig": result.pop("origAirportDetail", None),
        "dest": result.pop("destAirportDetail", None),
    }

    def _metar_to_dict(m):
        return {
            "raw": m.raw,
            "station": m.station,
            "issue_time": m.issue_time,
            "windDirection": m.wind_direction,
            "windSpeed": m.wind_speed,
            "windSpeedUnit": m.wind_speed_unit,
            "windGust": m.wind_gust,
            "visibility": m.visibility,
            "weather": m.weather,
            "clouds": [{"cover": c.cover, "base": c.base} for c in m.clouds],
            "temperature": m.temperature,
            "dewpoint": m.dewpoint,
            "qnh": m.qnh,
            "trend": translate_trend(m.trend) if m.trend else None,
        }

    result["parsedWeather"] = [
        _metar_to_dict(parse_metar(read_metar(req.orig))),
        _metar_to_dict(parse_metar(read_metar(req.dest))),
    ]

    return result


@app.get("/api/metar/{icao}")
def get_metar(icao: str):
    return {"icao": icao.upper(), "metar": read_metar(icao)}


@app.get("/api/validcode")
def get_valid_code():
    import random
    num = random.randint(1000, 9999)
    token = str(uuid.uuid4())
    _valid_codes[token] = str(num)
    return {
        "token": token,
        "image": generate_captcha_b64(num),
    }


@app.get("/health")
def health_check():
    return {"status": "ok"}


# Static files
frontend_dist = settings.navdat_full_path.parent.parent / "webFinder" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="static")


@app.on_event("startup")
def startup():
    print("OpenRouteFinder API starting...")
    print(f"Nav data version: {get_data_version()}")
    _build_airport_index()
    start_metar_updater()
    print("METAR keeper started")
