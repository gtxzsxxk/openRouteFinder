import json
import os
import sys
import uuid
import traceback
import threading
import time
import requests
from typing import Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import config
from backend.core.data_loader import (
    get_data_version,
    get_airport_maps,
    search_route,
)

# Valid code storage (in-memory, per-session)
_valid_codes = {}
_metar_data = ""
_metar_lock = threading.Lock()


class MetarKeeper(threading.Thread):
    def run(self):
        global _metar_data
        while True:
            gmt_hr = f"{time.gmtime().tm_hour:02d}"
            print(
                "===="
                + time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
                + " 正在更新 METAR ===="
            )
            try:
                r = requests.get(
                    f"https://tgftp.nws.noaa.gov/data/observations/metar/cycles/{gmt_hr}Z.TXT",
                    headers={
                        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
                    },
                    timeout=30,
                )
                metar_file = os.path.join(
                    os.path.dirname(os.path.dirname(__file__)), "metar.txt"
                )
                with open(metar_file, "w") as f:
                    f.write(r.text)
                with _metar_lock:
                    _metar_data = r.text
                print(f"读取 {gmt_hr}Z.TXT 了 {len(r.text)} 字节")
            except Exception as e:
                print(f"METAR 更新失败: {e}")
            print("============================")
            time.sleep(config.METAR_UPDATE_MINUTE * 60)


def _read_metar(ICAO: str) -> str:
    with _metar_lock:
        data = _metar_data
    if len(data) > 1000:
        idx = data.find(ICAO)
        if idx >= 0:
            end = data.find("\n", idx)
            if end < 0:
                end = len(data)
            return data[idx:end].strip()
    # Fallback: read from file
    metar_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "metar.txt")
    if os.path.exists(metar_file):
        with open(metar_file, "r") as f:
            data = f.read()
        idx = data.find(ICAO)
        if idx >= 0:
            end = data.find("\n", idx)
            if end < 0:
                end = len(data)
            return data[idx:end].strip()
    return f"{ICAO} METAR NOT AVAILABLE"




app = FastAPI(
    title="OpenRouteFinder",
    description="Flight route finder API",
    version="2.0.0",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Pydantic Models ---

class RouteRequest(BaseModel):
    orig: str
    dest: str
    validCode: str
    validToken: str


class RouteResponse(BaseModel):
    data_version: str
    total_time: str
    route: str
    distance: str
    nodes: list
    SID: dict
    STAR: dict
    airportName: list
    weather: list


class AirportInfo(BaseModel):
    icao: str
    name: str
    lat: float
    lon: float


class MetarResponse(BaseModel):
    icao: str
    metar: str


class ValidCodeResponse(BaseModel):
    token: str
    image: str


# --- API Routes ---

@app.get("/api/version")
def get_version():
    """Get navigation data cycle version."""
    return get_data_version()


@app.get("/api/airports")
def get_airports(q: Optional[str] = None):
    """Search airports by ICAO code prefix."""
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
            airports.append({
                "icao": icao,
                "name": name,
                "lat": lat,
                "lon": lon,
            })

    return {"airports": airports[:50]}  # Limit to 50 results


@app.get("/api/airports/{icao}")
def get_airport(icao: str):
    """Get airport details."""
    maps = get_airport_maps()
    icao = icao.upper()

    if icao not in maps:
        raise HTTPException(status_code=404, detail="Airport not found")

    # Parse global data for name/coords
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
def post_route(req: RouteRequest):
    """Calculate route between two airports."""
    # Validate captcha
    if req.validToken not in _valid_codes:
        raise HTTPException(status_code=401, detail="验证码已过期")
    if _valid_codes[req.validToken] != req.validCode:
        raise HTTPException(status_code=401, detail="验证码错误")

    # Remove used valid code
    del _valid_codes[req.validToken]

    try:
        result = search_route(req.orig, req.dest)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Route calculation failed: {str(e)}")

    if result is None:
        raise HTTPException(status_code=404, detail="无法找到航路，请检查机场代码是否正确")

    # Ensure it's a dict
    if isinstance(result, str):
        result = json.loads(result)

    # Map legacy field names to new API schema
    if "nodeinformation" in result:
        raw_nodes = result.pop("nodeinformation")
        # Convert [[name, lat, lon], ...] to [{name, lat, lon}, ...]
        result["nodes"] = [
            {"name": n[0], "lat": n[1], "lon": n[2]}
            for n in raw_nodes
            if len(n) >= 3
        ]

    # Fetch METAR weather
    result["weather"] = [
        _read_metar(req.orig),
        _read_metar(req.dest),
    ]

    return result


@app.get("/api/metar/{icao}")
def get_metar(icao: str):
    """Get METAR weather for an airport."""
    return {"icao": icao.upper(), "metar": _read_metar(icao)}


@app.get("/api/validcode")
def get_valid_code():
    """Get a new valid code image."""
    import random
    import io
    import base64
    from PIL import Image, ImageFont, ImageDraw

    num = random.randint(1000, 9999)
    token = str(uuid.uuid4())
    _valid_codes[token] = str(num)

    # Generate image
    font_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "frontend", "public", "NotoSansHans-Regular.ttf"
    )
    # Fallback to default font if not found
    try:
        font = ImageFont.truetype(font_path, size=26)
    except:
        font = ImageFont.load_default()

    bg = (random.randint(30, 60), random.randint(30, 60), random.randint(30, 60))
    img = Image.new("RGB", (90, 30), bg)
    draw = ImageDraw.Draw(img)
    fg = (random.randint(180, 255), random.randint(180, 255), random.randint(180, 255))
    draw.text((20, 0), str(num), fg, font=font)

    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    img_bytes = buf.getvalue()
    b64 = base64.b64encode(img_bytes).decode("utf-8")

    return {
        "token": token,
        "image": f"data:image/jpeg;base64,{b64}",
    }


@app.get("/health")
def health_check():
    return {"status": "ok"}


# --- Static Files (Production) ---
# Mount frontend/dist as static files
frontend_dist = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "dist")
if os.path.exists(frontend_dist):
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="static")


# --- Startup ---
@app.on_event("startup")
def startup():
    print("OpenRouteFinder API starting...")
    print(f"Nav data version: {get_data_version()}")
    # Start METAR keeper thread
    keeper = MetarKeeper()
    keeper.daemon = True
    keeper.start()
    print("METAR keeper started")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=config.LISTEN_PORT)
