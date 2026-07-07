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
    admin_key: str = ""

    # Directory containing navdata_*.fb.zst cycle files. The registry discovers
    # every cycle in this directory at runtime.
    navdata_dir: str = "data"

    disable_captcha: bool = False

    # LRU cache size for built airport SID/STAR connections.
    # Each entry holds the full procedure graph for one airport; large airports
    # can be tens to hundreds of KB. Default 1000 covers ~1000 busy airports.
    airport_connection_cache_size: int = 1000

    # METAR file location.
    metar_path: str = "data/metar.txt"

    @staticmethod
    def _resolve_path(path: str) -> Path:
        p = Path(path)
        return p if p.is_absolute() else PROJECT_ROOT / p

    @property
    def navdata_dir_path(self) -> Path:
        return self._resolve_path(self.navdata_dir)

    @property
    def metar_full_path(self) -> Path:
        return self._resolve_path(self.metar_path)


settings = Settings()
