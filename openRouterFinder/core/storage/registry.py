"""Multi-version navigation data registry with hot reload support."""

import contextlib
import re
import sys
import threading
import weakref
from pathlib import Path

from openRouterFinder.core.storage.reader import MmappedNavData


class _NavDataRef:
    """Reference-counted wrapper around MmappedNavData.

    Holds the underlying mapping open until release() is called.  All attribute
    access is forwarded to the wrapped MmappedNavData instance.

    A weakref.finalize fallback guarantees the reference count is decremented
    even if a caller forgets to use the context manager or call release().
    """

    __slots__ = ("__weakref__", "_cache", "_cycle", "_finalizer", "_nav", "_registry", "_released")

    def __init__(self, nav: MmappedNavData, cycle: str, registry: "NavDataRegistry"):
        self._nav = nav
        self._cycle = cycle
        self._registry = registry
        self._released = False
        self._cache = {}
        # Finalizer holds a weak reference to self via a ref object, so it does
        # not keep the wrapper alive.  It resurrects self briefly only to call
        # release() if that has not already happened.
        self._finalizer = weakref.finalize(
            self,
            _NavDataRef._finalize,
            weakref.ref(self),
        )

    def __getattr__(self, name: str):
        if self._released:
            raise ValueError("NavData reference has been released")
        return getattr(self._nav, name)

    def release(self):
        if self._released:
            return
        self._released = True
        # Prevent the finalizer from running once we have explicitly released.
        self._finalizer.detach()
        self._registry._release(self._cycle)

    @staticmethod
    def _finalize(ref: weakref.ref) -> None:
        if sys.is_finalizing():
            return
        obj = ref()
        if obj is None or obj._released:
            return
        obj._released = True
        with contextlib.suppress(Exception):
            # During interpreter shutdown the registry may already be gone.
            obj._registry._release(obj._cycle)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()


class NavDataRegistry:
    """Thread-safe registry of mmapped navdata versions."""

    _FILENAME_RE = re.compile(r"^navdata_(\d{4})\.(fb|fb\.zst)$")

    def __init__(self, data_dir: Path):
        self._data_dir = data_dir
        self._versions: dict[str, MmappedNavData] = {}
        self._ref_counts: dict[str, int] = {}
        self._pending_delete: set[str] = set()
        self._pending_reload: dict[str, MmappedNavData] = {}
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
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
            old_nav = self._versions.get(cycle)
            self._versions[cycle] = MmappedNavData(path)
            self._ref_counts[cycle] = self._ref_counts.get(cycle, 0)
            if cycle in self._pending_delete:
                self._pending_delete.remove(cycle)
            # If the old version is still in use, delay closing it until all
            # references are released.  Otherwise close it immediately.
            if old_nav is not None:
                if self._ref_counts.get(cycle, 0) == 0:
                    old_nav.close()
                else:
                    self._pending_reload[cycle] = old_nav
            print(f"Loaded navdata cycle {cycle} from {path}")

    def get(self, cycle: str | None = None) -> _NavDataRef | None:
        """Get navdata for a specific cycle, or the latest if None."""
        with self._lock:
            if cycle is None or cycle == "":
                if not self._versions:
                    return None
                # Return highest cycle number
                latest = max(self._versions.keys())
                cycle = latest
            nav = self._versions.get(cycle)
            if nav is None:
                return None
            if cycle in self._pending_delete:
                return None
            self._ref_counts[cycle] = self._ref_counts.get(cycle, 0) + 1
            return _NavDataRef(nav, cycle, self)

    def _release(self, cycle: str):
        with self._lock:
            count = self._ref_counts.get(cycle, 0)
            if count > 0:
                count -= 1
                self._ref_counts[cycle] = count
            # Close old version after a reload, or delete after unregister,
            # once no references remain.
            if count == 0:
                old_nav = self._pending_reload.pop(cycle, None)
                if old_nav is not None:
                    old_nav.close()
                if cycle in self._pending_delete:
                    self._ref_counts.pop(cycle, None)
                    for ext in ("fb.zst", "fb"):
                        path = self._data_dir / f"navdata_{cycle}.{ext}"
                        try:
                            if path.exists():
                                path.unlink()
                        except OSError as e:
                            print(f"Failed to delete {path}: {e}")
                    self._pending_delete.remove(cycle)
                    self._condition.notify_all()

    def _do_close_and_delete(self, cycle: str):
        nav = self._versions.pop(cycle, None)
        if nav is None:
            nav = self._pending_reload.pop(cycle, None)
        if nav is not None:
            nav.close()
        self._ref_counts.pop(cycle, None)
        for ext in ("fb.zst", "fb"):
            path = self._data_dir / f"navdata_{cycle}.{ext}"
            try:
                if path.exists():
                    path.unlink()
            except OSError as e:
                print(f"Failed to delete {path}: {e}")
        print(f"Closed and deleted navdata cycle {cycle}")

    def list_cycles(self) -> list[str]:
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
        """Unregister and close a cycle when no references remain."""
        with self._lock:
            if cycle not in self._versions:
                return
            # Remove from active versions immediately so list_cycles/has_cycle
            # reflect the deletion, even if references are still outstanding.
            nav = self._versions.pop(cycle)
            self._pending_delete.add(cycle)
            if self._ref_counts.get(cycle, 0) == 0:
                nav.close()
                for ext in ("fb.zst", "fb"):
                    path = self._data_dir / f"navdata_{cycle}.{ext}"
                    try:
                        if path.exists():
                            path.unlink()
                    except OSError as e:
                        print(f"Failed to delete {path}: {e}")
                self._pending_delete.remove(cycle)
                self._ref_counts.pop(cycle, None)
                self._condition.notify_all()
            else:
                # Hold the old mapping open until the last reference releases.
                self._pending_reload[cycle] = nav

    def get_cycle_info(self, cycle: str) -> dict | None:
        """Get summary info for a cycle."""
        with self._lock:
            nav = self._versions.get(cycle)
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
            for nav in self._pending_reload.values():
                nav.close()
            self._versions.clear()
            self._ref_counts.clear()
            self._pending_delete.clear()
            self._pending_reload.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._versions)
