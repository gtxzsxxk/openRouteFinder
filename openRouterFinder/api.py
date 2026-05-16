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

# --- Pydantic Models ---

class RouteRequest(BaseModel):
    orig: str
    dest: str
    validCode: str
    validToken: str


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
    maps = get_airport_maps()
    global_dat = maps.get("GLOBAL", [])
    airports = []
    q_upper = (q or "").upper()

    for line in global_dat:
        parts = line.strip().split(",")
        if len(parts) < 5 or parts[0] != "A":
            continue
        icao = parts[1].strip()
        name = parts[2].strip()
        try:
            lat = float(parts[3].strip())
            lon = float(parts[4].strip())
        except ValueError:
            continue
        if not q_upper or icao.startswith(q_upper) or q_upper in name.upper():
            airports.append({"icao": icao, "name": name, "lat": lat, "lon": lon})

    return {"airports": airports[:50]}


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
                lambda: search_route(req.orig, req.dest),
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Route calculation failed: {e}")

    if result is None:
        raise HTTPException(status_code=404, detail="无法找到航路，请检查机场代码是否正确")

    # Map legacy fields
    if "nodeinformation" in result:
        raw_nodes = result.pop("nodeinformation")
        result["nodes"] = [
            {"name": n[0], "lat": n[1], "lon": n[2]}
            for n in raw_nodes
            if len(n) >= 3
        ]

    result["weather"] = [read_metar(req.orig), read_metar(req.dest)]
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
    start_metar_updater()
    print("METAR keeper started")
