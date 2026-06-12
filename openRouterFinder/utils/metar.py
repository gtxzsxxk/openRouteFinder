"""METAR weather data fetcher."""

import threading
import time

import requests

from openRouterFinder.config import settings

_metar_data = ""
_metar_lock = threading.Lock()
_metar_stop_event = threading.Event()
_metar_thread: threading.Thread | None = None


def fetch_metar() -> str:
    """Fetch latest METAR data from NOAA with retry."""
    gmt_hr = f"{time.gmtime().tm_hour:02d}"
    url = f"https://tgftp.nws.noaa.gov/data/observations/metar/cycles/{gmt_hr}Z.TXT"

    for attempt in range(1, 4):
        try:
            r = requests.get(
                url,
                headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"},
                timeout=(5, 15),
            )
            with open(settings.metar_full_path, "w") as f:
                f.write(r.text)
            with _metar_lock:
                global _metar_data
                _metar_data = r.text
            return r.text
        except Exception as e:
            print(f"METAR update attempt {attempt}/3 failed: {e}")
            if attempt < 3:
                time.sleep(2**attempt)

    print("METAR update failed after 3 attempts, using cached data if available")
    return ""


def read_metar(icao: str) -> str:
    """Read METAR for a specific airport."""
    with _metar_lock:
        data = _metar_data

    if len(data) > 1000:
        idx = data.find(icao.upper())
        if idx >= 0:
            end = data.find("\n", idx)
            if end < 0:
                end = len(data)
            return data[idx:end].strip()

    # Fallback: read from file
    if settings.metar_full_path.exists():
        with open(settings.metar_full_path) as f:
            data = f.read()
        idx = data.find(icao.upper())
        if idx >= 0:
            end = data.find("\n", idx)
            if end < 0:
                end = len(data)
            return data[idx:end].strip()

    return f"{icao.upper()} METAR NOT AVAILABLE"


def start_metar_updater():
    """Start background METAR update thread."""
    global _metar_thread

    _metar_stop_event.clear()

    def loop():
        while not _metar_stop_event.is_set():
            print(f"==== {time.strftime('%Y-%m-%d %H:%M:%S')} Updating METAR ====")
            fetch_metar()
            print("============================")
            _metar_stop_event.wait(settings.metar_update_minutes * 60)

    _metar_thread = threading.Thread(target=loop, daemon=True)
    _metar_thread.start()
    return _metar_thread


def stop_metar_updater():
    """Signal the METAR updater thread to stop and wait briefly."""
    global _metar_thread
    _metar_stop_event.set()
    t = _metar_thread
    _metar_thread = None
    if t is not None and t.is_alive():
        t.join(timeout=2.0)
