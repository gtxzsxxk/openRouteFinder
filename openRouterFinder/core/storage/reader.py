"""mmap-based FlatBuffers reader for NavData files."""

import contextlib
import mmap
import os
import sys
import tempfile
from pathlib import Path

import zstandard as zstd

# FlatBuffers generated code uses absolute imports like "from NavData.Node import Node"
_storage_dir = Path(__file__).parent
if str(_storage_dir) not in sys.path:
    sys.path.insert(0, str(_storage_dir))

from openRouterFinder.core.graph import Edge as GraphEdge
from openRouterFinder.core.graph import Node as GraphNode
from openRouterFinder.core.storage.NavData.Airport import Airport as FBAirport
from openRouterFinder.core.storage.NavData.NavData import NavData


class MmappedNavData:
    """Read-only navigation data loaded via mmap.

    Supports plain .fb files and zstd-compressed .fb.zst files.
    Compressed files are transparently decompressed to a temp file on init.
    """

    def __init__(self, fb_path: Path):
        self._path = fb_path
        self._tmp_path: Path | None = None
        self._file = None
        self._mmap = None
        self._nav = None
        self._node_index: dict[tuple, GraphNode] = {}
        self._node_by_iid: dict[int, GraphNode] = {}
        self._airport_by_icao: dict[str, int] = {}
        self._navaid_by_ident: dict[str, list[int]] = {}
        # Process-lifetime cache for derived structures that are pure functions
        # of this immutable navdata (spatial index, T-route skip table, edge
        # distance backfill flag). Lives on the shared MmappedNavData — NOT on
        # the per-request _NavDataRef wrapper — so it is built once per cycle and
        # reused across every request instead of being rebuilt each query.
        self._cache: dict = {}

        actual_path = fb_path
        if str(fb_path).endswith(".fb.zst"):
            # Decompress to a temp file for mmap
            tmp_fd, tmp_name = tempfile.mkstemp(suffix=".fb", prefix="navdata_")
            try:
                dctx = zstd.ZstdDecompressor()
                with open(fb_path, "rb") as zst_in, dctx.stream_reader(zst_in) as reader:
                    while True:
                        chunk = reader.read(1024 * 1024)
                        if not chunk:
                            break
                        os.write(tmp_fd, chunk)
            finally:
                os.close(tmp_fd)
            actual_path = Path(tmp_name)
            self._tmp_path = actual_path

        try:
            self._file = open(actual_path, "rb")  # noqa: SIM115
            self._mmap = mmap.mmap(self._file.fileno(), 0, access=mmap.ACCESS_READ)
            self._nav = NavData.GetRootAs(self._mmap, 0)
            self._build_indices()
        except Exception:
            # Ensure temp files and file handles are released even if mmap or
            # index building fails.
            self.close()
            raise

    def _build_indices(self):
        # Node index by (name, lat, lon)
        for i in range(self._nav.NodesLength()):
            n = self._nav.Nodes(i)
            iid = n.Iid()
            if iid in self._node_by_iid:
                existing = self._node_by_iid[iid]
                print(
                    f"Warning: duplicate IID {iid} in navdata "
                    f"(existing={existing.name!r}, new={n.Name()!r}); keeping first"
                )
                continue
            gn = GraphNode(
                iid=iid,
                name=n.Name().decode("utf-8") if n.Name() else "",
                px=n.Lat(),
                py=n.Lon(),
            )
            self._node_index[gn.node_key()] = gn
            self._node_by_iid[iid] = gn

        # Attach edges to nodes
        for i in range(self._nav.EdgesLength()):
            e = self._nav.Edges(i)
            nfrom = e.Nfrom()
            nend = e.Nend()
            if nfrom in self._node_by_iid and nend in self._node_by_iid:
                name = e.Name().decode("utf-8") if e.Name() else ""
                ge = GraphEdge(
                    nfrom=nfrom,
                    nend=nend,
                    name=name,
                )
                self._node_by_iid[nfrom].next_list.append(ge)

        # Build node_list array once and cache it
        if self._node_by_iid:
            max_iid = max(self._node_by_iid.keys())
            arr: list[GraphNode | None] = [None] * (max_iid + 1)
            for iid, node in self._node_by_iid.items():
                arr[iid] = node
            self._node_list_cache = tuple(arr)
        else:
            self._node_list_cache = ()

        # Airport index by ICAO
        for i in range(self._nav.AirportsLength()):
            ap = self._nav.Airports(i)
            icao = ap.Icao().decode("utf-8") if ap.Icao() else ""
            if icao:
                self._airport_by_icao[icao] = i

        # Navaid index by ident
        for i in range(self._nav.NavaidsLength()):
            nav = self._nav.Navaids(i)
            ident = nav.Ident().decode("utf-8") if nav.Ident() else ""
            if ident:
                self._navaid_by_ident.setdefault(ident, []).append(i)

    @property
    def cycle(self) -> str:
        c = self._nav.Cycle()
        return c.decode("utf-8") if c else ""

    @property
    def effective_from(self) -> str:
        s = self._nav.EffectiveFrom()
        return s.decode("utf-8") if s else ""

    @property
    def effective_to(self) -> str:
        s = self._nav.EffectiveTo()
        return s.decode("utf-8") if s else ""

    @property
    def num_nodes(self) -> int:
        return self._nav.NodesLength()

    @property
    def num_edges(self) -> int:
        return self._nav.EdgesLength()

    @property
    def num_airports(self) -> int:
        return self._nav.AirportsLength()

    @property
    def num_navaids(self) -> int:
        return self._nav.NavaidsLength()

    @property
    def num_holdings(self) -> int:
        return self._nav.HoldingsLength()

    @property
    def num_markers(self) -> int:
        return self._nav.MarkersLength()

    @property
    def num_gls(self) -> int:
        return self._nav.GlsLength()

    @property
    def num_grid_mora(self) -> int:
        return self._nav.GridMoraLength()

    @property
    def num_airport_comms(self) -> int:
        return self._nav.AirportCommsLength()

    def get_airport(self, icao: str) -> FBAirport | None:
        """Get airport by ICAO code."""
        icao = icao.upper()
        idx = self._airport_by_icao.get(icao)
        if idx is not None:
            return self._nav.Airports(idx)
        return None

    def list_airport_icaos(self) -> list[str]:
        """Return sorted list of all airport ICAO codes."""
        return sorted(self._airport_by_icao.keys())

    def get_navaids(self, ident: str) -> list:
        """Get navaid(s) by ident."""
        indices = self._navaid_by_ident.get(ident, [])
        return [self._nav.Navaids(i) for i in indices]

    def find_node(self, name: str, lat: float, lon: float) -> GraphNode | None:
        key = (name, round(lat, 6), round(lon, 6))
        return self._node_index.get(key)

    def find_nodes_by_name(self, name: str) -> list[GraphNode]:
        return [n for n in self._node_by_iid.values() if n.name == name]

    @property
    def node_list(self) -> tuple[GraphNode | None, ...]:
        return self._node_list_cache

    @property
    def node_index(self) -> dict[tuple, GraphNode]:
        return self._node_index

    def close(self):
        """Release mmap/file handles and remove decompressed temp files.

        Idempotent: safe to call multiple times.
        """
        if self._mmap is not None:
            with contextlib.suppress(ValueError, OSError):
                self._mmap.close()
            self._mmap = None
        if self._file is not None:
            with contextlib.suppress(ValueError, OSError):
                self._file.close()
            self._file = None
        if self._tmp_path is not None:
            with contextlib.suppress(OSError):
                if self._tmp_path.exists():
                    os.unlink(self._tmp_path)
            self._tmp_path = None

    def __enter__(self):
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
