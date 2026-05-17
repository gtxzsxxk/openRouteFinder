"""Recursive-descent METAR parser."""

import re
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class CloudLayer:
    cover: str
    base: Optional[int] = None


@dataclass
class ParsedMetar:
    raw: str
    station: Optional[str] = None
    issue_time: Optional[str] = None
    wind_direction: Optional[int] = None
    wind_speed: Optional[int] = None
    wind_speed_unit: str = "MPS"
    wind_gust: Optional[int] = None
    visibility: Optional[str] = None
    weather: List[str] = field(default_factory=list)
    clouds: List[CloudLayer] = field(default_factory=list)
    temperature: Optional[int] = None
    dewpoint: Optional[int] = None
    qnh: Optional[int] = None
    trend: Optional[str] = None


def _parse_wind(token: str) -> Optional[dict]:
    """Parse wind token: dddssMPS, dddssKT, dddssKMH, dddssGssMPS, VRBssMPS, etc."""
    m = re.match(r'^(\d{3}|VRB)(\d{2,3})(?:G(\d{2,3}))?(MPS|KT|KMH)$', token)
    if not m:
        return None
    return {
        'direction': None if m.group(1) == 'VRB' else int(m.group(1)),
        'speed': int(m.group(2)),
        'gust': int(m.group(3)) if m.group(3) else None,
        'unit': m.group(4),
    }


def _parse_visibility(token: str) -> Optional[str]:
    if token == 'CAVOK':
        return 'CAVOK'
    if re.match(r'^\d{4}$', token) or re.match(r'^\d{1,2}SM$', token):
        return token
    return None


def _parse_cloud(token: str) -> Optional[CloudLayer]:
    m = re.match(r'^(FEW|SCT|BKN|OVC|NSC|NCD|SKC)(\d{3})?$', token)
    if not m:
        return None
    return CloudLayer(cover=m.group(1), base=int(m.group(2)) * 100 if m.group(2) else None)


def _parse_temp_pressure(token: str) -> Optional[dict]:
    """Parse temperature/dewpoint or pressure."""
    # Temperature: M03/M02 or 28/12
    m = re.match(r'^(M?\d{2})/(M?\d{2})$', token)
    if m:
        def parse_t(s):
            return -int(s[1:]) if s.startswith('M') else int(s)
        return {'type': 'temp', 'temperature': parse_t(m.group(1)), 'dewpoint': parse_t(m.group(2))}
    # Pressure: Q1012 or A2992
    m = re.match(r'^Q(\d{4})$', token)
    if m:
        return {'type': 'qnh', 'qnh': int(m.group(1))}
    return None


def parse_metar(raw: str) -> ParsedMetar:
    """Parse a METAR string."""
    result = ParsedMetar(raw=raw.strip())
    tokens = result.raw.split()

    if not tokens:
        return result

    # Detect non-standard "METAR NOT AVAILABLE" format
    if 'NOT' in tokens and 'AVAILABLE' in tokens:
        return result

    # Skip METAR/COR/SPECI prefix
    idx = 0
    if tokens[idx] in ('METAR', 'COR', 'SPECI'):
        idx += 1

    # Station identifier
    if idx < len(tokens) and re.match(r'^[A-Z]{4}$', tokens[idx]):
        result.station = tokens[idx]
        idx += 1

    # Issue time: DDHHMMZ
    if idx < len(tokens) and re.match(r'^\d{6}Z$', tokens[idx]):
        result.issue_time = tokens[idx]
        idx += 1

    # Wind
    if idx < len(tokens):
        wind = _parse_wind(tokens[idx])
        if wind:
            result.wind_direction = wind['direction']
            result.wind_speed = wind['speed']
            result.wind_gust = wind['gust']
            result.wind_speed_unit = wind['unit']
            idx += 1

    # Visibility (may have two tokens for runway visibility, skip for now)
    if idx < len(tokens):
        vis = _parse_visibility(tokens[idx])
        if vis:
            result.visibility = vis
            idx += 1

    # Weather phenomena and clouds (iterate until temp or pressure)
    while idx < len(tokens):
        token = tokens[idx]

        # Temperature/pressure signals end of cloud/weather section
        tp = _parse_temp_pressure(token)
        if tp:
            break

        # Cloud
        cloud = _parse_cloud(token)
        if cloud:
            result.clouds.append(cloud)
            idx += 1
            continue

        # Weather phenomenon
        if re.match(r'^[-+]?(RA|SN|FG|BR|HZ|FU|DU|SA|SS|DS|TS|SQ|FC|SH|BL|DR|MI|BC|PR|VC|PO|FC)+$', token):
            result.weather.append(token)
            idx += 1
            continue

        idx += 1

    # Temperature and pressure
    while idx < len(tokens):
        tp = _parse_temp_pressure(tokens[idx])
        if tp and tp['type'] == 'temp' and result.temperature is None:
            result.temperature = tp['temperature']
            result.dewpoint = tp['dewpoint']
            idx += 1
            continue
        if tp and tp['type'] == 'qnh' and result.qnh is None:
            result.qnh = tp['qnh']
            idx += 1
            continue
        break

    # Trend (remaining tokens)
    if idx < len(tokens):
        result.trend = ' '.join(tokens[idx:])

    return result


_TREND_MAP = {
    'NOSIG': '无显著变化',
    'TEMPO': '临时',
    'BECMG': '逐渐变为',
    'FM': '从',
    'TL': '至',
    'AT': '在',
}

_WEATHER_MAP = {
    'RA': '雨',
    'SN': '雪',
    'FG': '雾',
    'BR': '轻雾',
    'HZ': '霾',
    'FU': '烟',
    'DU': '浮尘',
    'SA': '沙',
    'SS': '沙暴',
    'DS': '尘暴',
    'TS': '雷暴',
    'SQ': '飑',
    'FC': '漏斗云',
    'SH': '阵性',
    'BL': '高吹',
    'DR': '低吹',
    'MI': '浅',
    'BC': '碎片',
    'PR': '部分',
    'VC': '附近',
    'PO': '尘卷风',
}


def translate_trend(trend: str) -> str:
    """Translate METAR trend string to Chinese."""
    if not trend:
        return trend
    tokens = trend.split()
    parts = []
    for token in tokens:
        if token in _TREND_MAP:
            parts.append(_TREND_MAP[token])
            continue
        m = re.match(r'^(FM|TL|AT)(\d{4})$', token)
        if m:
            prefix = _TREND_MAP.get(m.group(1), m.group(1))
            parts.append(f"{prefix} {m.group(2)}Z")
            continue
        if token in _WEATHER_MAP:
            parts.append(_WEATHER_MAP[token])
            continue
        if token.startswith('-') and token[1:] in _WEATHER_MAP:
            parts.append(f"小{_WEATHER_MAP[token[1:]]}")
            continue
        if token.startswith('+') and token[1:] in _WEATHER_MAP:
            parts.append(f"大{_WEATHER_MAP[token[1:]]}")
            continue
        parts.append(token)
    return ' '.join(parts)
