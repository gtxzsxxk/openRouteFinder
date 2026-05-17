"""Application configuration using pydantic-settings."""

import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


# Project root is parent of openRouterFinder/
PROJECT_ROOT = Path(__file__).parent.parent.resolve()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    listen_port: int = 9807
    metar_update_minutes: int = 15
    bing_maps_key: str = ""
    admin_key: str = ""

    navdat_path: str = "data/navidata_2206.map"
    apdat_path: str = "data/airport_2206.air"
    navdat_cycle: str = "AUTO"

    local_asdata_path: str = ""

    @property
    def navdat_full_path(self) -> Path:
        return PROJECT_ROOT / self.navdat_path

    @property
    def apdat_full_path(self) -> Path:
        return PROJECT_ROOT / self.apdat_path

    @property
    def metar_full_path(self) -> Path:
        return PROJECT_ROOT / "data" / "metar.txt"


settings = Settings()
