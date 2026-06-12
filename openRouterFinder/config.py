"""Application configuration using pydantic-settings."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root is parent of openRouterFinder/
PROJECT_ROOT = Path(__file__).parent.parent.resolve()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
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
    disable_captcha: bool = False

    # LRU cache size for built airport SID/STAR connections.
    # Each entry holds the full procedure graph for one airport; large airports
    # can be tens to hundreds of KB. Default 1000 covers ~1000 busy airports.
    airport_connection_cache_size: int = 1000

    @staticmethod
    def _resolve_path(path: str) -> Path:
        p = Path(path)
        return p if p.is_absolute() else PROJECT_ROOT / p

    @property
    def navdat_full_path(self) -> Path:
        return self._resolve_path(self.navdat_path)

    @property
    def apdat_full_path(self) -> Path:
        return self._resolve_path(self.apdat_path)

    @property
    def metar_full_path(self) -> Path:
        return PROJECT_ROOT / "data" / "metar.txt"


settings = Settings()
