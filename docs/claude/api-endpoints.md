# API Endpoints Reference

Base URL: `http://localhost:9807` (backend dev server)

All JSON responses. Frontend proxy forwards `/api/*` and `/health` from `:5173` to `:9807`.

---

## Route Calculation

### POST `/api/route`

Main route calculation endpoint.

**Request Body:**
```json
{
  "orig": "ZBAA",
  "dest": "ZGGG",
  "validCode": "1234",
  "validToken": "uuid-token",
  "sidExit": null,
  "starEntry": null,
  "cycle": null
}
```

- `sidExit` / `starEntry`: Optional procedure filter waypoint names. `null` = auto-select.
- `cycle`: Optional navdata cycle string. `null` = use latest.
- `validCode` / `validToken`: CAPTCHA (skipped if `DISABLE_CAPTCHA=true`).

**Response (200):**
```json
{
  "route": "ZBAA ... ZGGG",
  "distance": "1234.56 nm / 2286.41 km",
  "total_time": "2h 34m",
  "data_version": "2604",
  "nodes": [
    { "name": "ZBAA", "lat": 40.08, "lon": 116.58 },
    { "name": "AA111", "lat": 40.2, "lon": 116.4 }
  ],
  "route_segments": [
    { "from": "ZBAA", "to": "AA111", "airway": "SID" }
  ],
  "sid": {
    "exits": ["AA111", "AA112"],
    "procedures": {
      "AA111": [["RUSDO", "36L", [[...]], [[...]]]]
    }
  },
  "star": {
    "entries": ["GG001"],
    "procedures": {
      "GG001": [["IDKEX", "02L", [[...]], [[...]]]]
    }
  },
  "activeSIDTransition": "AA113",
  "activeSTARTransition": null,
  "airportDetails": {
    "orig": { "icao": "ZBAA", "name": "...", "lat": 40.08, "lon": 116.58 },
    "dest": { "icao": "ZGGG", "name": "...", "lat": 23.4, "lon": 113.3 }
  },
  "origRunways": [...],
  "destRunways": [...],
  "weather": ["METAR ZBAA ...", "METAR ZGGG ..."],
  "parsedWeather": [{...}, {...}]
}
```

**Response (401):** CAPTCHA validation failed.

**Response (404):** Airport not found or navdata unavailable.

**Response (500):** Route calculation error.

---

## Airport Queries

### GET `/api/airports?q={query}`

Airport search with prefix matching.

**Query Parameters:**
- `q`: Search string (ICAO prefix or airport name)

**Response (200):**
```json
{
  "airports": [
    { "icao": "ZBAA", "name": "Beijing Capital", "lat": 40.08, "lon": 116.58 }
  ]
}
```

Uses O(1) prefix index for ICAO codes, falls back to name search.

---

### GET `/api/airports/{icao}`

Airport basic info.

**Response (200):**
```json
{
  "icao": "ZBAA",
  "name": "Beijing Capital International",
  "lat": 40.08,
  "lon": 116.58
}
```

Runways and elevation are available from `/api/airports/{icao}/procedures?detail=true` or `/api/route`.

---

### GET `/api/airports/{icao}/procedures`

SID/STAR procedures for an airport.

**Query Parameters:**
- `cycle`: Optional navdata cycle

**Response (200):**
```json
{
  "sid": {
    "exits": ["AA111", "AA112", ...],
    "procedures": {
      "AA111": [
        ["RUSDO", "36L", [["DE36L", 40.08, 116.58], ["AA111", 40.2, 116.4]], []],
        ...
      ]
    }
  },
  "star": {
    "entries": ["GG001", ...],
    "procedures": {
      "GG001": [
        ["IDKEX", "02L", [["GG001", 23.2, 113.3], ["GG002", 23.3, 113.2]], []],
        ...
      ]
    }
  }
}
```

Procedure tuple format: `[name, runway, points, transitions]`
- `points`: `[[name, lat, lon], ...]`
- `transitions`: `[[name, [[name, lat, lon], ...]], ...]`

---

## Navdata & Version

### GET `/api/version`

Returns current navdata cycle.

**Response (200):**
```json
{ "version": "2604" }
```

---

### GET `/api/cycles`

Returns all available navdata cycles.

**Response (200):**
```json
{
  "cycles": [{ "cycle": "2604" }],
  "default": "2604",
  "disableCaptcha": false
}
```

---

## Weather

### GET `/api/metar/{icao}`

METAR weather for an airport.

**Response (200):**
```json
{ "metar": "METAR ZBAA 121200Z 32004MPS ..." }
```

Fetches from cached NOAA data. Updated every `METAR_UPDATE_MINUTES` (default 15).

---

## CAPTCHA

### GET `/api/validcode`

Generates a new CAPTCHA.

**Response (200):**
```json
{
  "token": "uuid-token",
  "image": "data:image/jpeg;base64,/9j/4AAQ..."
}
```

---

## Health

### GET `/health`

Health check.

**Response (200):**
```json
{ "status": "ok" }
```

---

## Admin (Protected)

All admin endpoints require `x-admin-key` header matching `settings.admin_key`.

### GET `/api/admin`

Admin statistics.

**Response (200):**
```json
{
  "start_time": "2026-05-21T10:00:00+00:00",
  "uptime_seconds": 3600,
  "total_requests": 1234,
  "unique_visitors": 42,
  "recent_requests": [...],
  "route_searches": [...],
  "errors": [...]
}
```

---

### GET `/api/admin/navdata`

List all navdata cycles with metadata.

**Response (200):**
```json
{
  "cycles": [
    {
      "cycle": "2604",
      "file_size_mb": 22.5,
      "node_count": 318000,
      "edge_count": 420000,
      "airport_count": 17000,
      "procedure_count": 120000
    }
  ]
}
```

---

### GET `/api/admin/navdata/{cycle}`

Metadata for a single cycle.

**Response (200):** Same object as an entry in `/api/admin/navdata`.

**Response (404):** Cycle not found.

---

### DELETE `/api/admin/navdata/{cycle}`

Delete a navdata cycle.

**Response (200):**
```json
{ "success": true, "cycle": "2604" }
```

---

### POST `/api/admin/navdata/upload`

Upload Fenix A320 navdata zip.

**Request:** `multipart/form-data` with `file` field (zip containing `nd.db3`)

**Response (200):**
```json
{ "build_id": "uuid", "status": "building", "cycle": "2604" }
```

---

### GET `/api/admin/navdata/build-progress/{build_id}`

SSE stream for real-time build progress.

**Response:** `text/event-stream`

Events:
```
event: progress
data: {"status": "building", "step": "nodes", "current": 100, "total": 5000}

event: done
data: {"status": "done", "cycle": "2604", "info": {...}}

event: error
data: {"status": "error", "detail": "..."}
```

The stream removes finished tasks after delivery so `_build_tasks` does not grow without bound.
