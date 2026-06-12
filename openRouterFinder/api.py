"""FastAPI application with thread-pooled A* route search."""

import asyncio
import contextlib
import json
import os
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from openRouterFinder.config import settings
from openRouterFinder.core.admin import (
    get_stats as get_admin_stats,
)
from openRouterFinder.core.admin import (
    record_error,
    record_request,
    record_route_search,
)
from openRouterFinder.core.data_loader import (
    get_data_version,
    get_nav_data,
    get_nav_registry,
    get_sid_connection,
    get_star_connection,
    search_route,
)
from openRouterFinder.core.storage.builder import build_from_fenix
from openRouterFinder.utils.metar import read_metar, start_metar_updater
from openRouterFinder.utils.validcode import generate_captcha_b64

# --- Procedure response filtering ---


def _filter_runway_all_from_response(data: dict) -> dict:
    """Remove or rename runway='ALL' variants when specific runway variants exist.

    When a procedure name has both an 'ALL' variant and exactly one specific
    runway variant (e.g. KIMMO3 has only 24R), the ALL variant is renamed to
    that specific runway.  This preserves the common-segment points (needed
    for _fill_procedure_gaps and route-segment tests) while showing the correct
    runway label in the frontend.

    When multiple specific runways exist (e.g. ANJLL4 has 24L/24R/25L/25R),
    the ALL variant is dropped — the runway-specific procedures already carry
    the full path via their transitions.

    Operates on API response dicts where procedures are either Procedure objects
    or serialized tuples [name, runway, points, transitions].
    """
    for label in ("SID", "STAR"):
        if label not in data:
            continue
        procs = data[label]
        if not isinstance(procs, dict):
            continue

        # Collect all (name, runway) pairs
        name_runways: dict = {}
        for proc_list in procs.values():
            for proc in proc_list:
                if hasattr(proc, "name"):
                    proc_name = proc.name
                    proc_runway = proc.runway
                else:
                    proc_name = proc[0]
                    proc_runway = proc[1]
                name_runways.setdefault(proc_name, set()).add(proc_runway)

        # Rename ALL to the single specific runway; drop ALL when ambiguous.
        filtered: dict = {}
        for key, proc_list in procs.items():
            filtered_list = []
            for proc in proc_list:
                if hasattr(proc, "name"):
                    proc_name = proc.name
                    proc_runway = proc.runway
                else:
                    proc_name = proc[0]
                    proc_runway = proc[1]

                specific_runways = name_runways.get(proc_name, set()) - {"ALL"}
                if proc_runway == "ALL" and specific_runways:
                    if len(specific_runways) == 1:
                        rw = next(iter(specific_runways))
                        if hasattr(proc, "name"):
                            proc.runway = rw
                            filtered_list.append(proc)
                        else:
                            new_proc = list(proc)
                            new_proc[1] = rw
                            filtered_list.append(tuple(new_proc))
                    # Multiple specific runways: drop the ambiguous ALL variant.
                else:
                    filtered_list.append(proc)
            if filtered_list:
                filtered[key] = filtered_list
        data[label] = filtered

    return data


def _rename_single_runway_all(data: dict) -> dict:
    """Rename runway='ALL' to the single specific runway; keep ALL when ambiguous.

    Unlike _filter_runway_all_from_response, this preserves ALL variants when
    multiple specific runways exist (e.g. MARNR8 with 6 runways).  The entry
    points (VIXOR, TOU, etc.) are needed so starNodeName remains a valid key.

    Operates on API response dicts where procedures are either Procedure objects
    or serialized tuples [name, runway, points, transitions].
    """
    for label in ("SID", "STAR"):
        if label not in data:
            continue
        procs = data[label]
        if not isinstance(procs, dict):
            continue

        name_runways: dict = {}
        for proc_list in procs.values():
            for proc in proc_list:
                if hasattr(proc, "name"):
                    proc_name = proc.name
                    proc_runway = proc.runway
                else:
                    proc_name = proc[0]
                    proc_runway = proc[1]
                name_runways.setdefault(proc_name, set()).add(proc_runway)

        for key, proc_list in procs.items():
            new_list = []
            for proc in proc_list:
                if hasattr(proc, "name"):
                    proc_name = proc.name
                    proc_runway = proc.runway
                else:
                    proc_name = proc[0]
                    proc_runway = proc[1]

                specific_runways = name_runways.get(proc_name, set()) - {"ALL"}
                if proc_runway == "ALL" and len(specific_runways) == 1:
                    rw = next(iter(specific_runways))
                    if hasattr(proc, "name"):
                        proc.runway = rw
                        new_list.append(proc)
                    else:
                        new_proc = list(proc)
                        new_proc[1] = rw
                        new_list.append(tuple(new_proc))
                else:
                    new_list.append(proc)
            procs[key] = new_list

    return data


# --- Concurrency controls ---
_dijkstra_pool = ThreadPoolExecutor(max_workers=4)
_route_semaphore = asyncio.Semaphore(8)

# --- Valid code storage ---

class _TTLCodeStore:
    """Thread-safe captcha token store with TTL and bounded size."""

    def __init__(self, ttl: int = 600, maxsize: int = 10000):
        self._ttl = ttl
        self._maxsize = maxsize
        self._data: dict[str, tuple[str, float]] = {}
        self._lock = threading.Lock()

    def _cleanup(self, now: float):
        expired = [k for k, (_, ts) in self._data.items() if now - ts > self._ttl]
        for k in expired:
            del self._data[k]

    def set(self, token: str, code: str):
        now = time.time()
        with self._lock:
            self._cleanup(now)
            if len(self._data) >= self._maxsize:
                oldest = min(self._data, key=lambda k: self._data[k][1])
                del self._data[oldest]
            self._data[token] = (code, now)

    def pop(self, token: str) -> str | None:
        now = time.time()
        with self._lock:
            item = self._data.get(token)
            if item is None:
                return None
            code, ts = item
            del self._data[token]
            if now - ts > self._ttl:
                return None
            return code


_valid_codes = _TTLCodeStore()

# --- Airport prefix index ---
_airport_prefix_index: dict[str, list] = {}
_airport_list: list = []

# --- Build progress tracking ---
_build_tasks: dict[str, dict] = {}


def _build_airport_index():
    """Build prefix index for O(1) airport autocomplete lookups."""
    global _airport_prefix_index, _airport_list
    airports = []

    nav = get_nav_data()
    if nav is not None:
        with nav:
            for icao in nav.list_airport_icaos():
                ap = nav.get_airport(icao)
                if ap is None:
                    continue
                name = ap.Name()
                name = name.decode("utf-8") if isinstance(name, bytes) else (name or icao)
                airports.append(
                    {"icao": icao, "name": name, "lat": float(ap.Lat()), "lon": float(ap.Lon())}
                )

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
    sidExit: str | None = None
    starEntry: str | None = None
    cycle: str | None = None


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
app.add_middleware(GZipMiddleware, minimum_size=500)


@app.middleware("http")
async def admin_logging(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    duration_ms = (time.time() - start) * 1000
    client_ip = (
        request.headers.get("x-forwarded-for", request.client.host if request.client else "unknown")
        .split(",")[0]
        .strip()
    )
    record_request(client_ip, request.method, request.url.path, response.status_code, duration_ms)
    return response


@app.get("/api/version")
def get_version():
    return {"version": get_data_version()}


@app.get("/api/cycles")
def get_cycles():
    """Return available navdata cycles."""
    reg = get_nav_registry()
    cycles = reg.list_cycles()
    result = []
    for cycle in cycles:
        info = reg.get_cycle_info(cycle)
        if info:
            result.append(
                {
                    "cycle": info["cycle"],
                }
            )
    return {
        "cycles": result,
        "default": result[-1]["cycle"] if result else None,
        "disableCaptcha": settings.disable_captcha,
    }


@app.get("/api/airports")
def get_airports(q: str | None = None):
    q = (q or "").strip()
    if not q:
        return {"airports": _airport_list[:50]}
    return {"airports": _search_airports(q, limit=50)}


@app.get("/api/airports/{icao}")
def get_airport(icao: str, cycle: str | None = None):
    icao = icao.upper()
    nav = get_nav_data(cycle)
    if nav is None:
        raise HTTPException(status_code=503, detail="Navdata not available")
    with nav:
        ap = nav.get_airport(icao)
        if ap is None:
            raise HTTPException(status_code=404, detail="Airport not found")
        name = ap.Name()
        name = name.decode("utf-8") if isinstance(name, bytes) else (name or icao)
        return {
            "icao": icao,
            "name": name,
            "lat": float(ap.Lat()),
            "lon": float(ap.Lon()),
        }


@app.get("/api/airports/{icao}/procedures")
def get_airport_procedures(icao: str, cycle: str | None = None, detail: bool = False):
    icao = icao.upper()

    nav = get_nav_data(cycle)
    if nav is None:
        raise HTTPException(status_code=503, detail="Navdata not available")
    with nav:
        if nav.get_airport(icao) is None:
            raise HTTPException(status_code=404, detail="Airport not found")

        sid_conn = get_sid_connection(nav, icao, cycle)
        star_conn = get_star_connection(nav, icao, cycle)

        sid_exits = []
        if sid_conn and sid_conn.procedures:
            seen = set()
            for exit_name, proc_list in sid_conn.procedures.items():
                if exit_name in seen:
                    continue
                seen.add(exit_name)
                sid_exits.append(
                    {
                        "name": exit_name,
                        "procedures": list(dict.fromkeys(p.name for p in proc_list)),
                    }
                )

        star_entries = []
        if star_conn and star_conn.procedures:
            seen = set()
            for entry_name, proc_list in star_conn.procedures.items():
                if entry_name in seen:
                    continue
                seen.add(entry_name)
                star_entries.append(
                    {
                        "name": entry_name,
                        "procedures": list(dict.fromkeys(p.name for p in proc_list)),
                    }
                )

        result = {
            "icao": icao,
            "sid": {"exits": sid_exits},
            "star": {"entries": star_entries},
        }

        if detail and (sid_conn or star_conn):
            # Return full procedure tuples (same shape as /api/route SID/STAR fields)
            def _proc_tuple(proc):
                return [
                    proc.name,
                    proc.runway,
                    [[p[0], p[1], p[2]] for p in proc.points],
                    [[t[0], [[p[0], p[1], p[2]] for p in t[1]]] for t in proc.transitions],
                ]

            if sid_conn and sid_conn.procedures:
                result["sidDetails"] = {
                    key: [_proc_tuple(p) for p in proc_list]
                    for key, proc_list in sid_conn.procedures.items()
                }
            if star_conn and star_conn.procedures:
                result["starDetails"] = {
                    key: [_proc_tuple(p) for p in proc_list]
                    for key, proc_list in star_conn.procedures.items()
                }

        if detail:
            if "sidDetails" in result:
                result["sidDetails"] = _filter_runway_all_from_response(
                    {"SID": result["sidDetails"]}
                ).get("SID", {})
            if "starDetails" in result:
                result["starDetails"] = _filter_runway_all_from_response(
                    {"STAR": result["starDetails"]}
                ).get("STAR", {})

        return result


@app.post("/api/route")
async def post_route(req: RouteRequest):
    # Validate captcha (skip if disabled via config)
    if not settings.disable_captcha:
        expected_code = _valid_codes.pop(req.validToken)
        if expected_code is None:
            raise HTTPException(status_code=401, detail="验证码已过期")
        if expected_code != req.validCode:
            raise HTTPException(status_code=401, detail="验证码错误")

    try:
        async with _route_semaphore:
            result = await asyncio.get_event_loop().run_in_executor(
                _dijkstra_pool,
                lambda: search_route(
                    req.orig,
                    req.dest,
                    sid_exit=req.sidExit,
                    star_entry=req.starEntry,
                    cycle=req.cycle,
                ),
            )
    except Exception as e:
        record_error(f"Route calculation failed: {e}", "/api/route", "POST", 500)
        raise HTTPException(status_code=500, detail=f"Route calculation failed: {e}") from e

    if result is None:
        record_error(f"No route found: {req.orig} → {req.dest}", "/api/route", "POST", 404)
        raise HTTPException(status_code=404, detail="无法找到航路，请检查机场代码是否正确")

    # Extract stats before mutating result
    distance_raw = result.get("distance", "")
    distance = None
    with contextlib.suppress(ValueError, IndexError):
        # "676.59 nm / 1253.05 km" -> 676.59
        distance = float(distance_raw.split()[0]) if distance_raw else None

    time_min = None
    with contextlib.suppress(ValueError, TypeError):
        time_min = float(result.get("total_time", 0)) / 1000.0

    nodeinformation = result.get("nodeinformation", [])
    nodes_count = len([n for n in nodeinformation if len(n) >= 3]) if nodeinformation else 0

    record_route_search(
        req.orig,
        req.dest,
        req.sidExit,
        req.starEntry,
        distance=distance,
        nodes_count=nodes_count,
        time_min=time_min,
    )

    # Map legacy fields
    if "nodeinformation" in result:
        raw_nodes = result.pop("nodeinformation")
        if raw_nodes:
            result["nodes"] = [
                {"name": n[0], "lat": n[1], "lon": n[2]} for n in raw_nodes if len(n) >= 3
            ]
        else:
            result["nodes"] = []

    result["weather"] = [read_metar(req.orig), read_metar(req.dest)]

    # Enrich with airport details and parsed weather
    from openRouterFinder.utils.metar_parser import parse_metar

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
            "trend": m.trend,
        }

    result["parsedWeather"] = [
        _metar_to_dict(parse_metar(read_metar(req.orig))),
        _metar_to_dict(parse_metar(read_metar(req.dest))),
    ]

    # Rename single-runway ALL variants (e.g. KIMMO3 ALL → 24R) so the
    # frontend shows the correct runway.  Multi-runway ALL variants are
    # kept because their entry-point keys are needed for starNodeName.
    return _rename_single_runway_all(result)



@app.get("/api/metar/{icao}")
def get_metar(icao: str):
    return {"icao": icao.upper(), "metar": read_metar(icao)}


@app.get("/api/validcode")
def get_valid_code():
    import random

    num = random.randint(1000, 9999)
    token = str(uuid.uuid4())
    _valid_codes.set(token, str(num))
    return {
        "token": token,
        "image": generate_captcha_b64(num),
    }


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/api/admin")
def get_admin(x_admin_key: str = Header(default="")):
    if not settings.admin_key or settings.admin_key == "set_yourself":
        raise HTTPException(status_code=403, detail="Admin not configured")
    if x_admin_key != settings.admin_key:
        raise HTTPException(status_code=403, detail="Invalid key")
    return get_admin_stats()


@app.get("/api/admin/navdata")
def list_navdata_cycles(x_admin_key: str = Header(default="")):
    if not settings.admin_key or settings.admin_key == "set_yourself":
        raise HTTPException(status_code=403, detail="Admin not configured")
    if x_admin_key != settings.admin_key:
        raise HTTPException(status_code=403, detail="Invalid key")
    reg = get_nav_registry()
    cycles = reg.list_cycles()
    result = []
    for cycle in cycles:
        info = reg.get_cycle_info(cycle)
        if info:
            result.append(info)
    return {"cycles": result}


@app.get("/api/admin/navdata/builds")
def list_active_builds(x_admin_key: str = Header(default="")):
    if not settings.admin_key or settings.admin_key == "set_yourself":
        raise HTTPException(status_code=403, detail="Admin not configured")
    if x_admin_key != settings.admin_key:
        raise HTTPException(status_code=403, detail="Invalid key")

    active = [
        {"build_id": bid, **task}
        for bid, task in _build_tasks.items()
        if task.get("status") == "building"
    ]
    return {"builds": active}


@app.get("/api/admin/navdata/{cycle}")
def get_navdata_cycle_info(cycle: str, x_admin_key: str = Header(default="")):
    if not settings.admin_key or settings.admin_key == "set_yourself":
        raise HTTPException(status_code=403, detail="Admin not configured")
    if x_admin_key != settings.admin_key:
        raise HTTPException(status_code=403, detail="Invalid key")
    reg = get_nav_registry()
    info = reg.get_cycle_info(cycle)
    if info is None:
        raise HTTPException(status_code=404, detail="Cycle not found")
    return info


@app.delete("/api/admin/navdata/{cycle}")
def delete_navdata_cycle(cycle: str, x_admin_key: str = Header(default="")):
    if not settings.admin_key or settings.admin_key == "set_yourself":
        raise HTTPException(status_code=403, detail="Admin not configured")
    if x_admin_key != settings.admin_key:
        raise HTTPException(status_code=403, detail="Invalid key")
    reg = get_nav_registry()
    if not reg.has_cycle(cycle):
        raise HTTPException(status_code=404, detail="Cycle not found")
    reg.unregister(cycle)
    return {"success": True, "cycle": cycle}


def _validate_fenix_db(db_path: Path) -> dict:
    """Validate Fenix A320 nd.db3 and extract cycle info.

    Returns dict with cycle, effective_from, effective_to.
    Raises ValueError if validation fails.
    """
    import sqlite3

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Check required tables exist
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cursor.fetchall()}
    required = {"config", "Waypoints", "Airports", "TerminalLegs", "Terminals"}
    missing = required - tables
    if missing:
        conn.close()
        raise ValueError(
            f"Missing required tables: {', '.join(missing)}. Not a valid Fenix A320 navdata."
        )

    # Extract cycle info from config table — column names vary by Fenix version
    cursor.execute("PRAGMA table_info(config)")
    cols = {row[1].lower() for row in cursor.fetchall()}
    key_col = next((c for c in cols if c == "key" or c == "name"), None)
    val_col = next((c for c in cols if c in ("value", "val", "data")), None)
    if not key_col or not val_col:
        conn.close()
        raise ValueError(f"Config table has unexpected schema: columns={cols}")

    in_clause = "'CycleName', 'CycleStartDate', 'CycleEndDate'"
    cursor.execute(f"SELECT {key_col}, {val_col} FROM config WHERE {key_col} IN ({in_clause})")
    config = {row[0]: row[1] for row in cursor.fetchall()}
    conn.close()

    cycle = config.get("CycleName", "").strip()
    effective_from = config.get("CycleStartDate", "").strip()
    effective_to = config.get("CycleEndDate", "").strip()

    if not cycle:
        raise ValueError("Could not parse cycle number from config table")

    return {
        "cycle": cycle,
        "effective_from": effective_from,
        "effective_to": effective_to,
    }


def _do_build_navdata(
    build_id: str,
    db_path: Path,
    data_dir: Path,
    cycle: str,
    effective_from: str,
    effective_to: str,
    tmp_dir: str,
) -> None:
    """Run FlatBuffers build in background thread and update progress."""

    def progress(step: str, current: int, total: int) -> None:
        _build_tasks[build_id] = {
            "status": "building",
            "step": step,
            "current": current,
            "total": total,
            "percent": int((current / total) * 100) if total else 0,
        }

    try:
        raw = build_from_fenix(
            db_path,
            cycle=cycle,
            effective_from=effective_from,
            effective_to=effective_to,
            progress=progress,
        )
        import zstandard as zstd

        cctx = zstd.ZstdCompressor(level=12)
        compressed = cctx.compress(raw)
        fb_path = data_dir / f"navdata_{cycle}.fb.zst"
        fb_path.write_bytes(compressed)
        reg = get_nav_registry()
        reg.register(cycle, fb_path)
        info = reg.get_cycle_info(cycle)
        _build_tasks[build_id] = {
            "status": "done",
            "cycle": cycle,
            "info": info,
        }
        size_mb = len(compressed) / 1024 / 1024
        raw_mb = len(raw) / 1024 / 1024
        print(
            f"[build {build_id}] done: cycle={cycle}, fb={fb_path} "
            f"({size_mb:.1f}MB / {raw_mb:.1f}MB)"
        )
    except Exception as e:
        import traceback

        detail = f"{type(e).__name__}: {e}"
        print(f"[build {build_id}] error: {detail}")
        traceback.print_exc()
        _build_tasks[build_id] = {
            "status": "error",
            "detail": detail,
        }
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# Upload limits for navdata zip files
_MAX_UPLOAD_SIZE = 200 * 1024 * 1024  # 200 MB
_MAX_DECOMPRESSED_SIZE = 1024 * 1024 * 1024  # 1 GB


def _is_path_traversal(name: str) -> bool:
    """Detect archive members that escape the extraction directory."""
    return name.startswith("/") or ".." in Path(name).parts


@app.post("/api/admin/navdata/upload")
async def upload_navdata(
    x_admin_key: str = Header(default=""),
    file: UploadFile = File(...),
):
    if not settings.admin_key or settings.admin_key == "set_yourself":
        raise HTTPException(status_code=403, detail="Admin not configured")
    if x_admin_key != settings.admin_key:
        raise HTTPException(status_code=403, detail="Invalid key")

    import tempfile
    import zipfile

    data_dir = settings.navdat_full_path.parent
    tmp_dir = tempfile.mkdtemp()
    db_path = None

    try:
        # Save uploaded file with size limit
        upload_path = Path(tmp_dir) / "upload.zip"
        total_size = 0
        with open(upload_path, "wb") as f:
            while True:
                chunk = file.file.read(8192)
                if not chunk:
                    break
                total_size += len(chunk)
                if total_size > _MAX_UPLOAD_SIZE:
                    raise HTTPException(status_code=413, detail="Upload too large")
                f.write(chunk)

        if not zipfile.is_zipfile(upload_path):
            raise HTTPException(status_code=400, detail="Uploaded file is not a valid zip archive")

        # Extract zip with decompression-bomb and path-traversal protection
        with zipfile.ZipFile(upload_path, "r") as zf:
            decompressed_total = sum(info.file_size for info in zf.infolist())
            if decompressed_total > _MAX_DECOMPRESSED_SIZE:
                raise HTTPException(status_code=413, detail="Zip contents too large")

            for info in zf.infolist():
                if _is_path_traversal(info.filename):
                    raise HTTPException(
                        status_code=400, detail=f"Invalid archive member: {info.filename}"
                    )

            zf.extractall(tmp_dir)

        # Find .db3 file (Fenix navdata)
        db3_files = []
        for root, _dirs, files in os.walk(tmp_dir):
            for name in files:
                if name.lower().endswith(".db3"):
                    db3_files.append(Path(root) / name)

        if len(db3_files) == 0:
            record_error(
                "Upload failed: no .db3 file found in zip", "/api/admin/navdata/upload", "POST", 400
            )
            raise HTTPException(status_code=400, detail="No .db3 file found in uploaded zip")
        if len(db3_files) > 1:
            raise HTTPException(status_code=400, detail="Multiple .db3 files found in uploaded zip")
        db_path = db3_files[0]

        # Validate and extract cycle info from db
        try:
            cycle_info = _validate_fenix_db(db_path)
        except ValueError as e:
            record_error(f"Upload validation failed: {e}", "/api/admin/navdata/upload", "POST", 400)
            raise HTTPException(status_code=400, detail=str(e)) from e

        cycle = cycle_info["cycle"]

        # Check if cycle already exists
        reg = get_nav_registry()
        if reg.has_cycle(cycle):
            raise HTTPException(status_code=409, detail=f"Cycle {cycle} already exists")

        # Start background build
        build_id = str(uuid.uuid4())
        _build_tasks[build_id] = {
            "status": "building",
            "step": "starting",
            "current": 0,
            "total": 1,
            "percent": 0,
        }

        loop = asyncio.get_event_loop()
        loop.run_in_executor(
            None,
            _do_build_navdata,
            build_id,
            db_path,
            data_dir,
            cycle,
            cycle_info["effective_from"],
            cycle_info["effective_to"],
            tmp_dir,
        )

        return {"build_id": build_id, "status": "building", "cycle": cycle}

    except HTTPException:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise
    except Exception as e:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        record_error(f"Upload failed: {e}", "/api/admin/navdata/upload", "POST", 500)
        raise HTTPException(status_code=500, detail=f"Upload processing failed: {e}") from e


@app.get("/api/admin/navdata/build-progress/{build_id}")
async def build_progress(build_id: str, x_admin_key: str = Query(default="")):
    if not settings.admin_key or settings.admin_key == "set_yourself":
        raise HTTPException(status_code=403, detail="Admin not configured")
    if x_admin_key != settings.admin_key:
        raise HTTPException(status_code=403, detail="Invalid key")

    from fastapi.responses import StreamingResponse

    async def event_stream():
        while True:
            task = _build_tasks.get(build_id)
            if task is None:
                yield f"event: error\ndata: {json.dumps({'detail': 'Build not found'})}\n\n"
                break

            data = json.dumps(task)
            if task["status"] == "done":
                yield f"event: done\ndata: {data}\n\n"
                break
            elif task["status"] == "error":
                yield f"event: error\ndata: {data}\n\n"
                break
            else:
                yield f"event: progress\ndata: {data}\n\n"

            await asyncio.sleep(1)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


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
