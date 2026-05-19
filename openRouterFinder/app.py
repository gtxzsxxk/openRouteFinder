"""Uvicorn entry point for OpenRouteFinder."""

import uvicorn

from openRouterFinder.config import settings
from openRouterFinder.api import app


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=settings.listen_port,
    )
