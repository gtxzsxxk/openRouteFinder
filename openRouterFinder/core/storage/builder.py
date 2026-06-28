"""Build FlatBuffers NavData from Fenix SQLite db3."""

import sqlite3
from collections.abc import Callable
from pathlib import Path

import flatbuffers

from openRouterFinder.core.storage.NavData.Airport import (
    AirportAddElevation,
    AirportAddIcao,
    AirportAddLat,
    AirportAddLon,
    AirportAddName,
    AirportAddProcedures,
    AirportAddRunways,
    AirportAddSpeedLimit,
    AirportAddSpeedLimitAltitude,
    AirportAddTransitionAltitude,
    AirportAddTransitionLevel,
    AirportEnd,
    AirportStart,
    AirportStartProceduresVector,
    AirportStartRunwaysVector,
)
from openRouterFinder.core.storage.NavData.AirportComm import (
    AirportCommAddAirportIcao,
    AirportCommAddAreaCode,
    AirportCommAddCallsign,
    AirportCommAddCommType,
    AirportCommAddFrequency,
    AirportCommAddFrequencyUnits,
    AirportCommAddIcaoCode,
    AirportCommAddLat,
    AirportCommAddLon,
    AirportCommAddServiceIndicator,
    AirportCommEnd,
    AirportCommStart,
)
from openRouterFinder.core.storage.NavData.AirwayLevel import AirwayLevel
from openRouterFinder.core.storage.NavData.Edge import (
    EdgeAddLevel,
    EdgeAddName,
    EdgeAddNend,
    EdgeAddNfrom,
    EdgeEnd,
    EdgeStart,
)
from openRouterFinder.core.storage.NavData.GLS import (
    GLSAddAirportIcao,
    GLSAddApproachBearing,
    GLSAddApproachSlope,
    GLSAddAreaCode,
    GLSAddCategory,
    GLSAddChannel,
    GLSAddIcaoCode,
    GLSAddMagneticVariation,
    GLSAddRefPathIdent,
    GLSAddRunway,
    GLSAddStationElevation,
    GLSAddStationIdent,
    GLSAddStationLat,
    GLSAddStationLon,
    GLSAddStationType,
    GLSEnd,
    GLSStart,
)
from openRouterFinder.core.storage.NavData.GridMora import (
    GridMoraAddMoraValues,
    GridMoraAddStartLat,
    GridMoraAddStartLon,
    GridMoraEnd,
    GridMoraStart,
    GridMoraStartMoraValuesVector,
)
from openRouterFinder.core.storage.NavData.Holding import (
    HoldingAddAreaCode,
    HoldingAddDuplicateIdentifier,
    HoldingAddHoldingName,
    HoldingAddIcaoCode,
    HoldingAddInboundCourse,
    HoldingAddLat,
    HoldingAddLegLengthNm,
    HoldingAddLegTimeMin,
    HoldingAddLon,
    HoldingAddMaxAltitude,
    HoldingAddMinAltitude,
    HoldingAddRegionCode,
    HoldingAddSpeedLimit,
    HoldingAddTurnDirection,
    HoldingAddWaypointIdentifier,
    HoldingEnd,
    HoldingStart,
)
from openRouterFinder.core.storage.NavData.ILS import (
    ILSAddCategory,
    ILSAddCrossingHeight,
    ILSAddElevation,
    ILSAddFrequency,
    ILSAddGsAngle,
    ILSAddHasDme,
    ILSAddHeading,
    ILSAddIdent,
    ILSAddLat,
    ILSAddLon,
    ILSAddRunwayEnd,
    ILSEnd,
    ILSStart,
)
from openRouterFinder.core.storage.NavData.Marker import (
    MarkerAddAirportIcao,
    MarkerAddLat,
    MarkerAddLlzIdent,
    MarkerAddLon,
    MarkerAddMarkerIdent,
    MarkerAddMarkerType,
    MarkerAddRunwayName,
    MarkerEnd,
    MarkerStart,
)
from openRouterFinder.core.storage.NavData.Navaid import (
    NavaidAddChannel,
    NavaidAddElevation,
    NavaidAddFrequency,
    NavaidAddIdent,
    NavaidAddLat,
    NavaidAddLon,
    NavaidAddMagneticVariation,
    NavaidAddName,
    NavaidAddRangeNm,
    NavaidAddSlavedVar,
    NavaidAddType,
    NavaidAddUsage,
    NavaidEnd,
    NavaidStart,
)
from openRouterFinder.core.storage.NavData.NavData import (
    NavDataAddAirportComms,
    NavDataAddAirports,
    NavDataAddCycle,
    NavDataAddEdges,
    NavDataAddEffectiveFrom,
    NavDataAddEffectiveTo,
    NavDataAddGls,
    NavDataAddGridMora,
    NavDataAddHoldings,
    NavDataAddMarkers,
    NavDataAddNavaids,
    NavDataAddNodes,
    NavDataEnd,
    NavDataStart,
    NavDataStartAirportCommsVector,
    NavDataStartAirportsVector,
    NavDataStartEdgesVector,
    NavDataStartGlsVector,
    NavDataStartGridMoraVector,
    NavDataStartHoldingsVector,
    NavDataStartMarkersVector,
    NavDataStartNavaidsVector,
    NavDataStartNodesVector,
)
from openRouterFinder.core.storage.NavData.Node import (
    NodeAddIid,
    NodeAddLat,
    NodeAddLon,
    NodeAddName,
    NodeEnd,
    NodeStart,
)
from openRouterFinder.core.storage.NavData.Procedure import (
    ProcedureAddLegs,
    ProcedureAddName,
    ProcedureAddRunway,
    ProcedureAddTransitions,
    ProcedureAddType,
    ProcedureEnd,
    ProcedureStart,
    ProcedureStartLegsVector,
    ProcedureStartTransitionsVector,
)
from openRouterFinder.core.storage.NavData.ProcLeg import (
    ProcLegAddAltRestriction,
    ProcLegAddArcRadius,
    ProcLegAddCenterLat,
    ProcLegAddCenterLon,
    ProcLegAddCourse,
    ProcLegAddDistanceNm,
    ProcLegAddIsFlyOver,
    ProcLegAddLat,
    ProcLegAddLon,
    ProcLegAddName,
    ProcLegAddNavBearing,
    ProcLegAddNavDistance,
    ProcLegAddNavLat,
    ProcLegAddNavLon,
    ProcLegAddNavReference,
    ProcLegAddPathTerminator,
    ProcLegAddSpeedLimit,
    ProcLegAddTurnDirection,
    ProcLegEnd,
    ProcLegStart,
)
from openRouterFinder.core.storage.NavData.ProcTransition import (
    ProcTransitionAddLegs,
    ProcTransitionAddName,
    ProcTransitionEnd,
    ProcTransitionStart,
)
from openRouterFinder.core.storage.NavData.Runway import (
    RunwayAddEnds,
    RunwayAddIls,
    RunwayAddLengthFt,
    RunwayAddName,
    RunwayAddSurface,
    RunwayAddWidthFt,
    RunwayEnd,
    RunwayStart,
    RunwayStartEndsVector,
    RunwayStartIlsVector,
)
from openRouterFinder.core.storage.NavData.RunwayEnd import (
    RunwayEndAddElevationFt,
    RunwayEndAddHeading,
    RunwayEndAddLat,
    RunwayEndAddLon,
    RunwayEndAddName,
    RunwayEndEnd,
    RunwayEndStart,
)

# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

ProgressCallback = Callable[[str, int, int], None] | None


def _count_table(cursor, table: str) -> int:
    try:
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        return cursor.fetchone()[0]
    except Exception:
        return 0


def build_from_fenix(
    db_path: Path,
    cycle: str,
    effective_from: str,
    effective_to: str,
    progress: ProgressCallback = None,
) -> bytes:
    """Read Fenix nd.db3 and return serialized FlatBuffers bytes."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()

        builder = flatbuffers.Builder(16 * 1024 * 1024)

        # Pre-fetch waypoint names for procedure leg lookup
        cursor.execute("SELECT ID, Ident FROM Waypoints")
        wp_names: dict[int, str] = {row["ID"]: row["Ident"] or "" for row in cursor.fetchall()}

        # Count rows for progress tracking
        counts = {
            "waypoints": _count_table(cursor, "Waypoints"),
            "airways": _count_table(cursor, "AirwayLegs"),
            "airports": _count_table(cursor, "Airports"),
            "navaids": _count_table(cursor, "Navaids"),
            "holdings": _count_table(cursor, "Holdings"),
            "markers": _count_table(cursor, "Markers"),
            "gls": _count_table(cursor, "GLS"),
            "grid_mora": _count_table(cursor, "GridMora"),
            "airport_comms": _count_table(cursor, "AirportComms"),
        }
        processed = 0

        def _progress(step: str, current: int, total: int) -> None:
            if progress:
                try:
                    progress(step, current, total)
                except Exception as e:
                    print(f"Progress callback error: {e}")

        # Build all tables
        nodes, id_to_iid = _build_nodes(cursor, builder, lambda c, t: _progress("waypoints", c, t))
        processed += counts["waypoints"]
        _progress("waypoints", counts["waypoints"], counts["waypoints"])

        edges = _build_edges(cursor, builder, id_to_iid, lambda c, t: _progress("airways", c, t))
        processed += counts["airways"]
        _progress("airways", counts["airways"], counts["airways"])

        airports = _build_airports(
            cursor, builder, wp_names, lambda c, t: _progress("airports", c, t)
        )
        processed += counts["airports"]
        _progress("airports", counts["airports"], counts["airports"])

        navaids = _build_navaids(cursor, builder, lambda c, t: _progress("navaids", c, t))
        processed += counts["navaids"]
        _progress("navaids", counts["navaids"], counts["navaids"])

        holdings = _build_holdings(cursor, builder, lambda c, t: _progress("holdings", c, t))
        processed += counts["holdings"]
        _progress("holdings", counts["holdings"], counts["holdings"])

        markers = _build_markers(cursor, builder, lambda c, t: _progress("markers", c, t))
        processed += counts["markers"]
        _progress("markers", counts["markers"], counts["markers"])

        gls_list = _build_gls(cursor, builder, lambda c, t: _progress("gls", c, t))
        processed += counts["gls"]
        _progress("gls", counts["gls"], counts["gls"])

        grid_mora = _build_grid_mora(cursor, builder, lambda c, t: _progress("grid_mora", c, t))
        processed += counts["grid_mora"]
        _progress("grid_mora", counts["grid_mora"], counts["grid_mora"])

        airport_comms = _build_airport_comms(
            cursor, builder, lambda c, t: _progress("airport_comms", c, t)
        )
        processed += counts["airport_comms"]
        _progress("airport_comms", counts["airport_comms"], counts["airport_comms"])

        # Serialization phase
        _progress("serialization", 0, 1)

        # Create string fields for root
        cycle_off = builder.CreateString(cycle)
        from_off = builder.CreateString(effective_from)
        to_off = builder.CreateString(effective_to)

        # Build root vectors
        NavDataStartNodesVector(builder, len(nodes))
        for n in reversed(nodes):
            builder.PrependUOffsetTRelative(n)
        nodes_vec = builder.EndVector()

        NavDataStartEdgesVector(builder, len(edges))
        for e in reversed(edges):
            builder.PrependUOffsetTRelative(e)
        edges_vec = builder.EndVector()

        NavDataStartAirportsVector(builder, len(airports))
        for a in reversed(airports):
            builder.PrependUOffsetTRelative(a)
        airports_vec = builder.EndVector()

        NavDataStartNavaidsVector(builder, len(navaids))
        for n in reversed(navaids):
            builder.PrependUOffsetTRelative(n)
        navaids_vec = builder.EndVector()

        NavDataStartHoldingsVector(builder, len(holdings))
        for h in reversed(holdings):
            builder.PrependUOffsetTRelative(h)
        holdings_vec = builder.EndVector()

        NavDataStartMarkersVector(builder, len(markers))
        for m in reversed(markers):
            builder.PrependUOffsetTRelative(m)
        markers_vec = builder.EndVector()

        NavDataStartGlsVector(builder, len(gls_list))
        for g in reversed(gls_list):
            builder.PrependUOffsetTRelative(g)
        gls_vec = builder.EndVector()

        NavDataStartGridMoraVector(builder, len(grid_mora))
        for g in reversed(grid_mora):
            builder.PrependUOffsetTRelative(g)
        grid_mora_vec = builder.EndVector()

        NavDataStartAirportCommsVector(builder, len(airport_comms))
        for c in reversed(airport_comms):
            builder.PrependUOffsetTRelative(c)
        airport_comms_vec = builder.EndVector()

        # Build root table
        NavDataStart(builder)
        NavDataAddCycle(builder, cycle_off)
        NavDataAddEffectiveFrom(builder, from_off)
        NavDataAddEffectiveTo(builder, to_off)
        NavDataAddNodes(builder, nodes_vec)
        NavDataAddEdges(builder, edges_vec)
        NavDataAddAirports(builder, airports_vec)
        NavDataAddNavaids(builder, navaids_vec)
        NavDataAddHoldings(builder, holdings_vec)
        NavDataAddMarkers(builder, markers_vec)
        NavDataAddGls(builder, gls_vec)
        NavDataAddGridMora(builder, grid_mora_vec)
        NavDataAddAirportComms(builder, airport_comms_vec)
        root = NavDataEnd(builder)

        builder.Finish(root)
        _progress("serialization", 1, 1)
        return bytes(builder.Output())
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


def _build_nodes(cursor, builder, progress=None) -> tuple[list[int], dict[int, int]]:
    cursor.execute("SELECT ID, Ident, Latitude, Longtitude FROM Waypoints ORDER BY ID")
    rows = cursor.fetchall()
    total = len(rows)
    nodes = []
    id_to_iid: dict[int, int] = {}
    for i, row in enumerate(rows):
        name = builder.CreateString(row["Ident"] or "")
        iid = i
        id_to_iid[row["ID"]] = iid
        NodeStart(builder)
        NodeAddIid(builder, iid)
        NodeAddName(builder, name)
        NodeAddLat(builder, row["Latitude"] or 0.0)
        NodeAddLon(builder, row["Longtitude"] or 0.0)
        nodes.append(NodeEnd(builder))
        if progress and i % 1000 == 0:
            progress(i, total)
    if progress:
        progress(total, total)
    return nodes, id_to_iid


# ---------------------------------------------------------------------------
# Edges
# ---------------------------------------------------------------------------


def _build_edges(cursor, builder, id_to_iid: dict[int, int], progress=None) -> list[int]:
    cursor.execute("""
        SELECT al.Waypoint1ID, al.Waypoint2ID, aw.Ident, al.Level
        FROM AirwayLegs al
        JOIN Airways aw ON al.AirwayID = aw.ID
    """)
    rows = cursor.fetchall()
    total = len(rows)
    edges = []
    for i, row in enumerate(rows):
        name = builder.CreateString(row["Ident"] or "")
        level_str = (row["Level"] or "B").upper()
        level = {"B": AirwayLevel.Both, "H": AirwayLevel.High, "L": AirwayLevel.Low}.get(
            level_str, AirwayLevel.Both
        )
        nfrom = id_to_iid.get(row["Waypoint1ID"], -1)
        nend = id_to_iid.get(row["Waypoint2ID"], -1)
        EdgeStart(builder)
        EdgeAddNfrom(builder, nfrom)
        EdgeAddNend(builder, nend)
        EdgeAddName(builder, name)
        EdgeAddLevel(builder, level)
        edges.append(EdgeEnd(builder))
        if progress and i % 1000 == 0:
            progress(i, total)
    if progress:
        progress(total, total)
    return edges


# ---------------------------------------------------------------------------
# Airports
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Airports (batch-queried to avoid N+1)
# ---------------------------------------------------------------------------


def _build_airports(cursor, builder, wp_names: dict[int, str], progress=None) -> list[int]:
    # 1. Fetch all airports
    cursor.execute("""
        SELECT ID, ICAO, Name, Latitude, Longtitude, Elevation,
               TransitionAltitude, TransitionLevel, SpeedLimit, SpeedLimitAltitude
        FROM Airports
    """)
    airport_rows = cursor.fetchall()
    total = len(airport_rows)

    # 2. Fetch all runways in one query
    cursor.execute("""
        SELECT ID, AirportID, Ident, Length, Width, Surface, TrueHeading,
               Latitude, Longtitude, Elevation
        FROM Runways
    """)
    runways_by_airport: dict[int, list] = {}
    for row in cursor.fetchall():
        runways_by_airport.setdefault(row["AirportID"], []).append(row)

    # 3. Fetch all ILS in one query
    cursor.execute("""
        SELECT Freq, LocCourse, Category, GsAngle, Latitude, Longtitude,
               Elevation, CrossingHeight, HasDme, Ident, RunwayID
        FROM ILSes
    """)
    ils_by_runway: dict[int, list] = {}
    for row in cursor.fetchall():
        ils_by_runway.setdefault(row["RunwayID"], []).append(row)

    # 4. Fetch all terminals in one query
    cursor.execute("""
        SELECT ID, AirportID, Name, FullName, Proc, Rwy FROM Terminals
    """)
    terminals_by_airport: dict[int, list] = {}
    for row in cursor.fetchall():
        terminals_by_airport.setdefault(row["AirportID"], []).append(row)

    # 5. Fetch all terminal legs in one query
    # Determine available ordering column (SeqNumber preferred, fall back to ID)
    cursor.execute("PRAGMA table_info(TerminalLegs)")
    terminal_legs_columns = {col["name"] for col in cursor.fetchall()}
    seq_col = "SeqNumber" if "SeqNumber" in terminal_legs_columns else "tl.ID"
    cursor.execute(f"""
        SELECT tl.ID, tl.TerminalID, tl.WptID, tl.WptLat, tl.WptLon,
               tl.Transition, tl.Course, tl.Distance, tl.Alt, tl.Vnav,
               tl.TurnDir, tl.Type, tl.TrackCode, tl.NavID, tl.NavLat,
               tl.NavLon, tl.NavBear, tl.NavDist, tl.CenterID,
               tl.CenterLat, tl.CenterLon, tl.WptDescCode, tle.IsFlyOver,
               tle.SpeedLimit
        FROM TerminalLegs tl
        LEFT JOIN TerminalLegsEx tle ON tl.ID = tle.ID
        ORDER BY tl.TerminalID, {seq_col}
    """)
    # Rows arrive already ordered by the SQL ORDER BY (TerminalID, seq_col),
    # so per-terminal grouping preserves that order — no re-sort needed.
    legs_by_terminal: dict[int, list] = {}
    for row in cursor.fetchall():
        legs_by_terminal.setdefault(row["TerminalID"], []).append(row)

    # 6. Fetch all transitions in one query
    cursor.execute("""
        SELECT DISTINCT TerminalID, Transition FROM TerminalLegs
        WHERE Transition IS NOT NULL AND Transition != '' AND Transition != 'ALL'
    """)
    transitions_by_terminal: dict[int, list[str]] = {}
    for row in cursor.fetchall():
        transitions_by_terminal.setdefault(row["TerminalID"], []).append(row["Transition"])

    airports = []
    for i, row in enumerate(airport_rows):
        ap_id = row["ID"]
        icao = builder.CreateString(row["ICAO"] or "")
        name = builder.CreateString(row["Name"] or "")
        runways = _build_runways_for_airport(
            builder, runways_by_airport.get(ap_id, []), ils_by_runway
        )
        procedures = _build_procedures_for_airport(
            builder,
            terminals_by_airport.get(ap_id, []),
            legs_by_terminal,
            transitions_by_terminal,
            wp_names,
        )

        AirportStart(builder)
        AirportAddIcao(builder, icao)
        AirportAddName(builder, name)
        AirportAddLat(builder, row["Latitude"] or 0.0)
        AirportAddLon(builder, row["Longtitude"] or 0.0)
        AirportAddElevation(builder, int(row["Elevation"] or 0))
        AirportAddTransitionAltitude(builder, int(row["TransitionAltitude"] or 0))
        AirportAddTransitionLevel(builder, int(row["TransitionLevel"] or 0))
        AirportAddSpeedLimit(builder, int(row["SpeedLimit"] or 0))
        AirportAddSpeedLimitAltitude(builder, int(row["SpeedLimitAltitude"] or 0))
        if runways:
            AirportAddRunways(builder, runways)
        if procedures:
            AirportAddProcedures(builder, procedures)
        airports.append(AirportEnd(builder))
        if progress and i % 100 == 0:
            progress(i, total)
    if progress:
        progress(total, total)
    return airports


def _build_runways_for_airport(builder, runway_rows: list, ils_by_runway: dict[int, list]) -> int:
    if not runway_rows:
        return 0

    ends_map: dict[str, list[int]] = {}
    ils_map: dict[str, list[int]] = {}

    for row in runway_rows:
        end_name = builder.CreateString(row["Ident"] or "")
        RunwayEndStart(builder)
        RunwayEndAddName(builder, end_name)
        RunwayEndAddLat(builder, row["Latitude"] or 0.0)
        RunwayEndAddLon(builder, row["Longtitude"] or 0.0)
        RunwayEndAddHeading(builder, row["TrueHeading"] or 0.0)
        RunwayEndAddElevationFt(builder, int(row["Elevation"] or 0))
        end_off = RunwayEndEnd(builder)

        base_name = _runway_base_name(row["Ident"] or "")
        ends_map.setdefault(base_name, []).append(end_off)

        # Load ILS from pre-fetched map
        ils_rows = ils_by_runway.get(row["ID"], [])
        if ils_rows:
            ils_list = []
            for ils_row in ils_rows:
                runway_end = builder.CreateString(row["Ident"] or "")
                ident = builder.CreateString(ils_row["Ident"] or "")
                raw_freq = ils_row["Freq"]
                freq_str = _decode_ils_freq(raw_freq)
                freq = builder.CreateString(freq_str)
                cat = builder.CreateString(ils_row["Category"] or "")
                ILSStart(builder)
                ILSAddRunwayEnd(builder, runway_end)
                ILSAddIdent(builder, ident)
                ILSAddFrequency(builder, freq)
                ILSAddHeading(builder, ils_row["LocCourse"] or 0.0)
                ILSAddCategory(builder, cat)
                ILSAddGsAngle(builder, ils_row["GsAngle"] or 0.0)
                ILSAddLat(builder, ils_row["Latitude"] or 0.0)
                ILSAddLon(builder, ils_row["Longtitude"] or 0.0)
                ILSAddElevation(builder, int(ils_row["Elevation"] or 0))
                ILSAddCrossingHeight(builder, int(ils_row["CrossingHeight"] or 0))
                ILSAddHasDme(builder, bool(ils_row["HasDme"]))
                ils_list.append(ILSEnd(builder))
            ils_map.setdefault(base_name, []).extend(ils_list)

    runway_offsets = []
    for base_name in sorted(ends_map.keys()):
        ends = ends_map[base_name]
        RunwayStartEndsVector(builder, len(ends))
        for e in reversed(ends):
            builder.PrependUOffsetTRelative(e)
        ends_vec = builder.EndVector()

        ils = ils_map.get(base_name, [])
        ils_vec = 0
        if ils:
            RunwayStartIlsVector(builder, len(ils))
            for i in reversed(ils):
                builder.PrependUOffsetTRelative(i)
            ils_vec = builder.EndVector()

        name = builder.CreateString(base_name)
        first_row = next(
            (r for r in runway_rows if _runway_base_name(r["Ident"] or "") == base_name), None
        )
        surface = builder.CreateString(first_row["Surface"] if first_row else "")

        RunwayStart(builder)
        RunwayAddName(builder, name)
        RunwayAddEnds(builder, ends_vec)
        if first_row:
            RunwayAddLengthFt(builder, first_row["Length"] or 0.0)
            RunwayAddWidthFt(builder, first_row["Width"] or 0.0)
        RunwayAddSurface(builder, surface)
        if ils_vec:
            RunwayAddIls(builder, ils_vec)
        runway_offsets.append(RunwayEnd(builder))

    if not runway_offsets:
        return 0
    AirportStartRunwaysVector(builder, len(runway_offsets))
    for r in reversed(runway_offsets):
        builder.PrependUOffsetTRelative(r)
    return builder.EndVector()


def _runway_base_name(ident: str) -> str:
    """Get paired runway name, e.g. '18L' -> '18L/36R'."""
    if not ident:
        return ""
    num_str = ""
    suffix = ""
    for c in ident:
        if c.isdigit():
            num_str += c
        else:
            suffix += c
    if not num_str:
        return ident
    num = int(num_str)
    opp_num = num + 18 if num <= 18 else num - 18
    suffix_map = {"L": "R", "R": "L", "C": "C"}
    # Preserve non-standard suffixes (e.g. T, W) instead of dropping them.
    opp_suffix = suffix_map.get(suffix, suffix)
    opp = f"{opp_num:02d}{opp_suffix}"
    if num < opp_num or (num == opp_num and suffix in ("L", "C")):
        return f"{ident}/{opp}"
    return f"{opp}/{ident}"


def _decode_ils_freq(raw_freq) -> str:
    """Decode Fenix ILS frequency from BCD-like hex encoding.

    Fenix stores ILS frequency as an integer whose low 5 hexadecimal digits
    represent the frequency in BCD with two implied decimal places.
    Examples: 0x01085000 (17321984) -> 108.50 MHz,
              0x01115500 (17913088) -> 111.55 MHz,
              0x01100000 (17825792) -> 110.00 MHz.
    """
    if not raw_freq:
        return ""
    try:
        # Format to at least 5 hex digits; the low 5 digits are the BCD frequency.
        hex_str = f"{int(raw_freq):010X}"
        digits = hex_str[-5:]
        if not digits or digits == "00000":
            return ""
        freq = int(digits) / 100.0
        return f"{freq:.2f} MHz"
    except (ValueError, TypeError):
        return str(raw_freq)


# ---------------------------------------------------------------------------
# Procedures (batch-queried to avoid N+1)
# ---------------------------------------------------------------------------


def _build_procedures_for_airport(
    builder,
    terminal_rows: list,
    legs_by_terminal: dict[int, list],
    transitions_by_terminal: dict[int, list[str]],
    wp_names: dict[int, str],
) -> int:
    proc_offsets = []
    for row in terminal_rows:
        name = builder.CreateString(row["FullName"] or row["Name"] or "")
        rwy_val = row["Rwy"] or ""
        if rwy_val == "ALL":
            rwy_val = ""
        runway = builder.CreateString(rwy_val)
        # Fenix Proc: 1=arrival (STAR), 2=departure (SID)
        # FlatBuffers schema: SID=1, STAR=2
        fenix_proc = int(row["Proc"] or 0)
        if fenix_proc == 1:
            proc_type = 2  # STAR
        elif fenix_proc == 2:
            proc_type = 1  # SID
        else:
            proc_type = fenix_proc
        legs = _build_procedure_legs(
            builder, legs_by_terminal.get(row["ID"], []), wp_names, is_main=True
        )
        transitions = _build_procedure_transitions(
            builder, row["ID"], legs_by_terminal, transitions_by_terminal, wp_names
        )

        ProcedureStart(builder)
        ProcedureAddName(builder, name)
        ProcedureAddType(builder, proc_type)
        ProcedureAddRunway(builder, runway)
        if legs:
            ProcedureAddLegs(builder, legs)
        if transitions:
            ProcedureAddTransitions(builder, transitions)
        proc_offsets.append(ProcedureEnd(builder))

    if not proc_offsets:
        return 0
    AirportStartProceduresVector(builder, len(proc_offsets))
    for p in reversed(proc_offsets):
        builder.PrependUOffsetTRelative(p)
    return builder.EndVector()


def _build_procedure_legs(
    builder,
    leg_rows: list,
    wp_names: dict[int, str],
    is_main: bool = True,
    transition_name: str | None = None,
) -> int:
    leg_offsets = []
    for row in leg_rows:
        trans = row["Transition"] or ""
        # Fenix database: Transition='ALL' means main procedure legs;
        # named transitions (e.g. 'RW27') are actual transitions.
        if is_main:
            if trans and trans != "ALL":
                continue  # skip named transitions
        else:
            if not trans or trans == "ALL":
                continue  # skip main legs
            if transition_name and trans != transition_name:
                continue  # skip legs belonging to other transitions

        # Waypoint name from WptID lookup only (NavID is an internal integer ID)
        wpt_id = row["WptID"]
        wpt_name = wp_names.get(wpt_id, "") if wpt_id else ""
        name = builder.CreateString(wpt_name)
        alt = builder.CreateString(row["Alt"] or "")
        speed = builder.CreateString(str(row["SpeedLimit"] or ""))
        pt = builder.CreateString(row["TrackCode"] or "")
        td = builder.CreateString(row["TurnDir"] or "")
        nav_ref = builder.CreateString(str(row["NavID"] or ""))

        ProcLegStart(builder)
        ProcLegAddName(builder, name)
        ProcLegAddLat(builder, row["WptLat"] or 0.0)
        ProcLegAddLon(builder, row["WptLon"] or 0.0)
        ProcLegAddAltRestriction(builder, alt)
        ProcLegAddSpeedLimit(builder, speed)
        ProcLegAddPathTerminator(builder, pt)
        ProcLegAddCourse(builder, row["Course"] or 0.0)
        ProcLegAddDistanceNm(builder, row["Distance"] or 0.0)
        ProcLegAddTurnDirection(builder, td)
        ProcLegAddIsFlyOver(builder, bool(row["IsFlyOver"]))
        ProcLegAddNavReference(builder, nav_ref)
        ProcLegAddNavLat(builder, row["NavLat"] or 0.0)
        ProcLegAddNavLon(builder, row["NavLon"] or 0.0)
        ProcLegAddNavBearing(builder, row["NavBear"] or 0.0)
        ProcLegAddNavDistance(builder, row["NavDist"] or 0.0)
        ProcLegAddArcRadius(builder, 0.0)
        ProcLegAddCenterLat(builder, row["CenterLat"] or 0.0)
        ProcLegAddCenterLon(builder, row["CenterLon"] or 0.0)
        leg_offsets.append(ProcLegEnd(builder))

    if not leg_offsets:
        return 0
    ProcedureStartLegsVector(builder, len(leg_offsets))
    for offset in reversed(leg_offsets):
        builder.PrependUOffsetTRelative(offset)
    return builder.EndVector()


def _build_procedure_transitions(
    builder,
    terminal_id: int,
    legs_by_terminal: dict[int, list],
    transitions_by_terminal: dict[int, list[str]],
    wp_names: dict[int, str],
) -> int:
    trans_names = transitions_by_terminal.get(terminal_id, [])
    if not trans_names:
        return 0

    # Pre-group legs by transition name once, avoiding O(T * L) scans.
    terminal_legs = legs_by_terminal.get(terminal_id, [])
    legs_by_trans_name: dict[str, list] = {}
    for row in terminal_legs:
        trans = row["Transition"] or ""
        if not trans or trans == "ALL":
            continue
        legs_by_trans_name.setdefault(trans, []).append(row)

    trans_offsets = []
    for trans_name in trans_names:
        legs = _build_procedure_legs(
            builder,
            legs_by_trans_name.get(trans_name, []),
            wp_names,
            is_main=False,
            transition_name=trans_name,
        )
        if legs == 0:
            continue
        name = builder.CreateString(trans_name)
        ProcTransitionStart(builder)
        ProcTransitionAddName(builder, name)
        ProcTransitionAddLegs(builder, legs)
        trans_offsets.append(ProcTransitionEnd(builder))

    if not trans_offsets:
        return 0
    ProcedureStartTransitionsVector(builder, len(trans_offsets))
    for t in reversed(trans_offsets):
        builder.PrependUOffsetTRelative(t)
    return builder.EndVector()


# ---------------------------------------------------------------------------
# Navaids
# ---------------------------------------------------------------------------


def _build_navaids(cursor, builder, progress=None) -> list[int]:
    cursor.execute("""
        SELECT Ident, Name, Type, Freq, Channel, Latitude, Longtitude,
               Elevation, Range, Usage, SlavedVar, MagneticVariation
        FROM Navaids
    """)
    rows = cursor.fetchall()
    total = len(rows)
    navaids = []
    for i, row in enumerate(rows):
        ident = builder.CreateString(row["Ident"] or "")
        name = builder.CreateString(row["Name"] or "")
        type_str = builder.CreateString(str(row["Type"] or ""))
        freq = builder.CreateString(str(row["Freq"] or ""))
        channel = builder.CreateString(row["Channel"] or "")
        usage = builder.CreateString(row["Usage"] or "")
        NavaidStart(builder)
        NavaidAddIdent(builder, ident)
        NavaidAddName(builder, name)
        NavaidAddType(builder, type_str)
        NavaidAddFrequency(builder, freq)
        NavaidAddChannel(builder, channel)
        NavaidAddLat(builder, row["Latitude"] or 0.0)
        NavaidAddLon(builder, row["Longtitude"] or 0.0)
        NavaidAddElevation(builder, int(row["Elevation"] or 0))
        NavaidAddRangeNm(builder, int(row["Range"] or 0))
        NavaidAddUsage(builder, usage)
        NavaidAddSlavedVar(builder, row["SlavedVar"] or 0.0)
        NavaidAddMagneticVariation(builder, row["MagneticVariation"] or 0.0)
        navaids.append(NavaidEnd(builder))
        if progress and i % 500 == 0:
            progress(i, total)
    if progress:
        progress(total, total)
    return navaids


# ---------------------------------------------------------------------------
# Holdings
# ---------------------------------------------------------------------------


def _build_holdings(cursor, builder, progress=None) -> list[int]:
    cursor.execute("""
        SELECT area_code, region_code, icao_code, waypoint_identifier,
               holding_name, waypoint_latitude, waypoint_longitude,
               duplicate_identifier, inbound_holding_course, turn_direction,
               leg_length, leg_time, minimum_altitude, maximum_altitude,
               holding_speed
        FROM Holdings
    """)
    rows = cursor.fetchall()
    total = len(rows)
    holdings = []
    for i, row in enumerate(rows):
        area = builder.CreateString(row["area_code"] or "")
        region = builder.CreateString(row["region_code"] or "")
        icao = builder.CreateString(row["icao_code"] or "")
        wpt = builder.CreateString(row["waypoint_identifier"] or "")
        hname = builder.CreateString(row["holding_name"] or "")
        td = builder.CreateString(row["turn_direction"] or "")
        HoldingStart(builder)
        HoldingAddAreaCode(builder, area)
        HoldingAddRegionCode(builder, region)
        HoldingAddIcaoCode(builder, icao)
        HoldingAddWaypointIdentifier(builder, wpt)
        HoldingAddHoldingName(builder, hname)
        HoldingAddLat(builder, row["waypoint_latitude"] or 0.0)
        HoldingAddLon(builder, row["waypoint_longitude"] or 0.0)
        HoldingAddDuplicateIdentifier(builder, int(row["duplicate_identifier"] or 0))
        HoldingAddInboundCourse(builder, row["inbound_holding_course"] or 0.0)
        HoldingAddTurnDirection(builder, td)
        HoldingAddLegLengthNm(builder, row["leg_length"] or 0.0)
        HoldingAddLegTimeMin(builder, row["leg_time"] or 0.0)
        HoldingAddMinAltitude(builder, int(row["minimum_altitude"] or 0))
        HoldingAddMaxAltitude(builder, int(row["maximum_altitude"] or 0))
        HoldingAddSpeedLimit(builder, int(row["holding_speed"] or 0))
        holdings.append(HoldingEnd(builder))
        if progress and i % 100 == 0:
            progress(i, total)
    if progress:
        progress(total, total)
    return holdings


# ---------------------------------------------------------------------------
# Markers
# ---------------------------------------------------------------------------


def _build_markers(cursor, builder, progress=None) -> list[int]:
    cursor.execute("""
        SELECT m.MarkerIdent, m.Type, m.Latitude, m.Longitude,
               r.Ident as runway_ident, a.ICAO as airport_icao, llz.Ident as llz_ident
        FROM Markers m
        JOIN Runways r ON m.RunwayID = r.ID
        JOIN Airports a ON r.AirportID = a.ID
        LEFT JOIN ILSes llz ON m.LLZIdent = llz.Ident
    """)
    rows = cursor.fetchall()
    total = len(rows)
    markers = []
    for i, row in enumerate(rows):
        ap = builder.CreateString(row["airport_icao"] or "")
        rwy = builder.CreateString(row["runway_ident"] or "")
        llz = builder.CreateString(row["llz_ident"] or "")
        mident = builder.CreateString(row["MarkerIdent"] or "")
        m_type = row["Type"]
        mtype_str = {1: "IM", 2: "MM", 3: "OM"}.get(m_type, str(m_type))
        mt = builder.CreateString(mtype_str)
        MarkerStart(builder)
        MarkerAddAirportIcao(builder, ap)
        MarkerAddRunwayName(builder, rwy)
        MarkerAddLlzIdent(builder, llz)
        MarkerAddMarkerIdent(builder, mident)
        MarkerAddMarkerType(builder, mt)
        MarkerAddLat(builder, row["Latitude"] or 0.0)
        MarkerAddLon(builder, row["Longitude"] or 0.0)
        markers.append(MarkerEnd(builder))
        if progress and i % 100 == 0:
            progress(i, total)
    if progress:
        progress(total, total)
    return markers


# ---------------------------------------------------------------------------
# GLS
# ---------------------------------------------------------------------------


def _build_gls(cursor, builder, progress=None) -> list[int]:
    cursor.execute("""
        SELECT area_code, airport_identifier, icao_code, gls_ref_path_identifier,
               gls_category, gls_channel, runway_identifier, gls_approach_bearing,
               station_latitude, station_longitude, gls_station_ident,
               gls_approach_slope, magnetic_variation, station_elevation, station_type
        FROM Gls
    """)
    rows = cursor.fetchall()
    total = len(rows)
    gls_list = []
    for i, row in enumerate(rows):
        area = builder.CreateString(row["area_code"] or "")
        ap = builder.CreateString(row["airport_identifier"] or "")
        icao = builder.CreateString(row["icao_code"] or "")
        ref = builder.CreateString(row["gls_ref_path_identifier"] or "")
        cat = builder.CreateString(row["gls_category"] or "")
        rwy = builder.CreateString(row["runway_identifier"] or "")
        st_ident = builder.CreateString(row["gls_station_ident"] or "")
        st_type = builder.CreateString(row["station_type"] or "")
        GLSStart(builder)
        GLSAddAreaCode(builder, area)
        GLSAddAirportIcao(builder, ap)
        GLSAddIcaoCode(builder, icao)
        GLSAddRefPathIdent(builder, ref)
        GLSAddCategory(builder, cat)
        GLSAddChannel(builder, int(row["gls_channel"] or 0))
        GLSAddRunway(builder, rwy)
        GLSAddApproachBearing(builder, row["gls_approach_bearing"] or 0.0)
        GLSAddStationLat(builder, row["station_latitude"] or 0.0)
        GLSAddStationLon(builder, row["station_longitude"] or 0.0)
        GLSAddStationIdent(builder, st_ident)
        GLSAddApproachSlope(builder, row["gls_approach_slope"] or 0.0)
        GLSAddMagneticVariation(builder, row["magnetic_variation"] or 0.0)
        GLSAddStationElevation(builder, int(row["station_elevation"] or 0))
        GLSAddStationType(builder, st_type)
        gls_list.append(GLSEnd(builder))
        if progress and i % 100 == 0:
            progress(i, total)
    if progress:
        progress(total, total)
    return gls_list


# ---------------------------------------------------------------------------
# Grid MORA
# ---------------------------------------------------------------------------


def _build_grid_mora(cursor, builder, progress=None) -> list[int]:
    cursor.execute("PRAGMA table_info(GridMora)")
    mora_cols = sorted(
        [col["name"] for col in cursor.fetchall() if col["name"].startswith("mora")],
        key=lambda x: int(x[4:]),
    )
    cursor.execute("SELECT * FROM GridMora")
    rows = cursor.fetchall()
    total = len(rows)
    mora_list = []
    for i, row in enumerate(rows):
        row_dict = dict(row)
        values = [
            str(row_dict.get(col)) if row_dict.get(col) is not None else ""
            for col in mora_cols
        ]
        # Build string vector
        str_offsets = [builder.CreateString(v) for v in values]
        GridMoraStartMoraValuesVector(builder, len(str_offsets))
        for s in reversed(str_offsets):
            builder.PrependUOffsetTRelative(s)
        values_vec = builder.EndVector()

        GridMoraStart(builder)
        GridMoraAddStartLat(builder, int(row["starting_latitude"] or 0))
        GridMoraAddStartLon(builder, int(row["starting_longitude"] or 0))
        GridMoraAddMoraValues(builder, values_vec)
        mora_list.append(GridMoraEnd(builder))
        if progress and i % 100 == 0:
            progress(i, total)
    if progress:
        progress(total, total)
    return mora_list


# ---------------------------------------------------------------------------
# Airport Communications
# ---------------------------------------------------------------------------


def _build_airport_comms(cursor, builder, progress=None) -> list[int]:
    cursor.execute("""
        SELECT area_code, icao_code, airport_identifier, communication_type,
               communication_frequency, frequency_units, service_indicator,
               callsign, latitude, longitude
        FROM AirportCommunication
    """)
    rows = cursor.fetchall()
    total = len(rows)
    comms = []
    for i, row in enumerate(rows):
        area = builder.CreateString(row["area_code"] or "")
        icao = builder.CreateString(row["icao_code"] or "")
        ap = builder.CreateString(row["airport_identifier"] or "")
        ctype = builder.CreateString(row["communication_type"] or "")
        units = builder.CreateString(row["frequency_units"] or "")
        svc = builder.CreateString(row["service_indicator"] or "")
        cs = builder.CreateString(row["callsign"] or "")
        AirportCommStart(builder)
        AirportCommAddAreaCode(builder, area)
        AirportCommAddIcaoCode(builder, icao)
        AirportCommAddAirportIcao(builder, ap)
        AirportCommAddCommType(builder, ctype)
        AirportCommAddFrequency(builder, row["communication_frequency"] or 0.0)
        AirportCommAddFrequencyUnits(builder, units)
        AirportCommAddServiceIndicator(builder, svc)
        AirportCommAddCallsign(builder, cs)
        AirportCommAddLat(builder, row["latitude"] or 0.0)
        AirportCommAddLon(builder, row["longitude"] or 0.0)
        comms.append(AirportCommEnd(builder))
        if progress and i % 500 == 0:
            progress(i, total)
    if progress:
        progress(total, total)
    return comms
