"""Multi-version navigation data registry with hot reload support."""

import os
import re
import threading
from pathlib import Path
from typing import Dict, List, Optional

from openRouterFinder.core.storage.reader import MmappedNavData


class NavDataRegistry:
    """Thread-safe registry of mmapped navdata versions."""

    _FILENAME_RE = re.compile(r"^navdata_(\d{4})\.(fb|fb\.zst)$")

    def __init__(self, data_dir: Path):
        self._data_dir = data_dir
        self._versions: Dict[str, MmappedNavData] = {}
        self._lock = threading.RLock()
        self._scan_and_load()

    def _scan_and_load(self):
        """Scan data directory and load all .fb files."""
        if not self._data_dir.exists():
            return
        for entry in sorted(self._data_dir.iterdir()):
            match = self._FILENAME_RE.match(entry.name)
            if match and entry.is_file():
                cycle = match.group(1)
                try:
                    self._load_cycle(cycle, entry)
                except Exception as e:
                    print(f"Failed to load {entry.name}: {e}")

    def _load_cycle(self, cycle: str, path: Path):
        with self._lock:
            if cycle in self._versions:
                self._versions[cycle].close()
            self._versions[cycle] = MmappedNavData(path)
            print(f"Loaded navdata cycle {cycle} from {path}")

    def get(self, cycle: Optional[str] = None) -> Optional[MmappedNavData]:
        """Get navdata for a specific cycle, or the latest if None."""
        with self._lock:
            if cycle is None:
                if not self._versions:
                    return None
                # Return highest cycle number
                latest = max(self._versions.keys())
                return self._versions[latest]
            return self._versions.get(cycle)

    def list_cycles(self) -> List[str]:
        """Return sorted list of available cycle numbers."""
        with self._lock:
            return sorted(self._versions.keys())

    def has_cycle(self, cycle: str) -> bool:
        with self._lock:
            return cycle in self._versions

    def register(self, cycle: str, path: Path):
        """Register a new cycle (used after import completes)."""
        self._load_cycle(cycle, path)

    def unregister(self, cycle: str):
        """Unregister and close a cycle."""
        with self._lock:
            if cycle in self._versions:
                self._versions[cycle].close()
                del self._versions[cycle]

    def get_cycle_info(self, cycle: str) -> Optional[dict]:
        """Get summary info for a cycle."""
        nav = self.get(cycle)
        if nav is None:
            return None
        # Prefer .fb.zst if present, fall back to .fb
        path = self._data_dir / f"navdata_{cycle}.fb.zst"
        if not path.exists():
            path = self._data_dir / f"navdata_{cycle}.fb"
        return {
            "cycle": cycle,
            "file_size_mb": round(path.stat().st_size / (1024 * 1024), 1),
            "node_count": nav.num_nodes,
            "edge_count": nav.num_edges,
            "airport_count": nav.num_airports,
            "procedure_count": sum(
                nav.get_airport(icao).ProceduresLength()
                for icao in nav.list_airport_icaos()
                if nav.get_airport(icao)
            ),
        }

    def close_all(self):
        """Close all mmapped files. Call on shutdown."""
        with self._lock:
            for nav in self._versions.values():
                nav.close()
            self._versions.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._versions)
