"""In-memory admin statistics collection."""

from collections import deque
from datetime import datetime, timezone
from typing import Any

# All deques have maxlen to prevent unbounded memory growth.
_data = {
    "start_time": datetime.now(timezone.utc),
    "total_requests": 0,
    "unique_ips": deque(maxlen=5000),
    "recent_requests": deque(maxlen=200),
    "route_searches": deque(maxlen=200),
    "errors": deque(maxlen=100),
}

# Paths that create noise and should not be logged.
_SKIP_PATHS = frozenset({"/api/validcode", "/api/admin", "/health", "/favicon.ico"})


def _should_log(path: str) -> bool:
    if path in _SKIP_PATHS:
        return False
    return not (path.startswith("/assets/") or path.startswith("/static/"))


def record_request(ip: str, method: str, path: str, status: int, duration_ms: float) -> None:
    if not _should_log(path):
        return
    _data["total_requests"] += 1
    if ip not in _data["unique_ips"]:
        _data["unique_ips"].append(ip)
    entry = {
        "time": datetime.now(timezone.utc).isoformat(),
        "ip": ip,
        "method": method,
        "path": path,
        "status": status,
        "duration_ms": round(duration_ms, 2),
    }
    _data["recent_requests"].append(entry)


def record_route_search(
    orig: str,
    dest: str,
    sid_exit: str | None,
    star_entry: str | None,
    distance: float | None = None,
    nodes_count: int | None = None,
    time_min: float | None = None,
) -> None:
    _data["route_searches"].append(
        {
            "time": datetime.now(timezone.utc).isoformat(),
            "orig": orig,
            "dest": dest,
            "sidExit": sid_exit,
            "starEntry": star_entry,
            "distance": distance,
            "nodesCount": nodes_count,
            "timeMin": time_min,
        }
    )


def record_error(detail: str, path: str = "", method: str = "", status: int = 500) -> None:
    _data["errors"].append(
        {
            "time": datetime.now(timezone.utc).isoformat(),
            "detail": detail,
            "path": path,
            "method": method,
            "status": status,
        }
    )


def get_stats() -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    uptime = round((now - _data["start_time"]).total_seconds())
    return {
        "start_time": _data["start_time"].isoformat(),
        "uptime_seconds": uptime,
        "total_requests": _data["total_requests"],
        "unique_visitors": len(set(_data["unique_ips"])),
        "recent_requests": list(_data["recent_requests"]),
        "route_searches": list(_data["route_searches"]),
        "errors": list(_data["errors"]),
    }
