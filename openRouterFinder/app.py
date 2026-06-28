"""Uvicorn entry point for OpenRouteFinder."""

import uvicorn

from openRouterFinder.api import app
from openRouterFinder.config import settings

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=settings.listen_port,
        proxy_headers=True,
        server_header=False,
    )
