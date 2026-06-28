"""E2E fixtures: boot a real uvicorn server in a subprocess and talk HTTP to it."""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
NAVDATA = REPO_ROOT / "data" / "navdata_2604.fb.zst"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def base_url():
    """Start a real uvicorn process, wait for /health, yield base URL, tear down."""
    if not NAVDATA.exists():
        pytest.skip("navdata_2604.fb.zst not available — e2e requires real navdata")

    port = _free_port()
    env = {**os.environ, "DISABLE_CAPTCHA": "true", "PYTHONPATH": str(REPO_ROOT)}
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "openRouterFinder.api:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.time() + 60  # navdata load can take a while
        while time.time() < deadline:
            if proc.poll() is not None:
                out = proc.stdout.read().decode(errors="replace") if proc.stdout else ""
                pytest.fail(f"uvicorn exited early (code {proc.returncode}):\n{out}")
            try:
                r = httpx.get(f"{url}/health", timeout=2.0)
                if r.status_code == 200:
                    break
            except httpx.TransportError:
                pass
            time.sleep(0.5)
        else:
            proc.terminate()
            pytest.fail("uvicorn did not become healthy within 60s")
        yield url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture(scope="session")
def client(base_url):
    with httpx.Client(base_url=base_url, timeout=60.0) as c:
        yield c
