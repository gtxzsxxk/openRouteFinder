import pickle
import json
import os
import sys

# Add parent to path so we can import RouteFinderLib
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from RouteFinderLib import RTFCALC
import config

_perload_node_list = None
_airport_maps = None
_data_version = None


def load_data():
    global _perload_node_list, _airport_maps, _data_version

    if _perload_node_list is not None:
        return

    nav_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), config.SET_NAVDAT_PATH)
    ap_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), config.SET_APDAT_PATH)

    with open(nav_path, "rb") as f:
        _perload_node_list = pickle.load(f)

    with open(ap_path, "rb") as f:
        _airport_maps = pickle.load(f)

    cycle_path = os.path.join(config.LOCAL_ASDATA_PATH, "Cycle.txt")
    if os.path.exists(cycle_path):
        with open(cycle_path, "r") as f:
            _data_version = f.read().strip()
    else:
        _data_version = config.NAVDAT_CYCLE


def get_node_list():
    load_data()
    return _perload_node_list


def get_airport_maps():
    load_data()
    return _airport_maps


def get_data_version():
    load_data()
    return _data_version


def _opposite_runway(name: str) -> str:
    """Get the opposite runway designator (e.g., 18L -> 36R)."""
    digits = []
    suffix = []
    for c in name:
        if c.isdigit():
            digits.append(c)
        else:
            suffix.append(c)
    num = int(''.join(digits)) if digits else 0
    opp_num = num + 18 if num <= 18 else num - 18
    suffix_map = {'L': 'R', 'R': 'L', 'C': 'C'}
    opp_suffix = suffix_map.get(''.join(suffix), '')
    return f"{opp_num:02d}{opp_suffix}"


def _parse_runways(airport_str: str) -> list:
    """Parse runway data from raw airport string."""
    runways = {}
    lines = airport_str.strip().split('\n')
    for line in lines:
        parts = line.strip().split(',')
        if len(parts) < 10 or parts[0] != 'R':
            continue
        name = parts[1].strip()
        try:
            heading = float(parts[2].strip())
            length = float(parts[3].strip())
            width = float(parts[4].strip())
            lat = float(parts[8].strip())
            lon = float(parts[9].strip())
        except (ValueError, IndexError):
            continue
        runways[name] = {
            'name': name,
            'heading': heading,
            'length': length,
            'width': width,
            'lat': lat,
            'lon': lon,
        }

    result = []
    paired = set()
    for name, rwy in runways.items():
        if name in paired:
            continue
        opp_name = _opposite_runway(name)
        if opp_name in runways and opp_name not in paired:
            paired.add(name)
            paired.add(opp_name)
            result.append({
                'name': f"{name}/{opp_name}",
                'thresholds': [
                    {'name': name, 'lat': rwy['lat'], 'lon': rwy['lon'], 'heading': rwy['heading']},
                    {'name': opp_name, 'lat': runways[opp_name]['lat'], 'lon': runways[opp_name]['lon'], 'heading': runways[opp_name]['heading']},
                ],
                'length': rwy['length'],
                'width': rwy['width'],
            })
        else:
            result.append({
                'name': name,
                'thresholds': [{'name': name, 'lat': rwy['lat'], 'lon': rwy['lon'], 'heading': rwy['heading']}],
                'length': rwy['length'],
                'width': rwy['width'],
            })
    return result


def search_route(orig: str, dest: str):
    load_data()
    orig = orig.upper()
    dest = dest.upper()

    if orig not in _airport_maps or dest not in _airport_maps:
        return None

    objsearch = RTFCALC(_airport_maps, _perload_node_list, _data_version)
    result = objsearch.Dijkstra(orig, dest)

    if objsearch.startNode is None or objsearch.endNode is None:
        return None

    # Parse the JSON string into dict
    result_dict = json.loads(result) if isinstance(result, str) else result

    # Enrich with runway data
    if isinstance(result_dict, dict):
        result_dict['origRunways'] = _parse_runways(_airport_maps[orig])
        result_dict['destRunways'] = _parse_runways(_airport_maps[dest])

    return result_dict
