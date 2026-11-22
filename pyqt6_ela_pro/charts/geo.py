"""GeoJSON 地图注册与投影。"""

from __future__ import annotations

import math

from ._utils import warn_once, to_float as _to_float

_MAPS: dict[str, dict] = {}
_PROJECTED: dict[tuple[str, str], dict] = {}


def _first(props: dict, *keys):
    for key in keys:
        value = props.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _ring(raw) -> list[tuple[float, float]]:
    points = []
    for point in raw or []:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            continue
        lon = _to_float(point[0], None)
        lat = _to_float(point[1], None)
        if lon is None or lat is None:
            continue
        points.append((lon, lat))
    return points


def _polygon_coords(coords) -> list[list[tuple[float, float]]]:
    rings = []
    for raw in coords or []:
        points = _ring(raw)
        if len(points) >= 3:
            rings.append(points)
    return rings


def _feature_polygons(geometry) -> list[list[list[tuple[float, float]]]]:
    if not isinstance(geometry, dict):
        return []
    kind = str(geometry.get("type") or "")
    coords = geometry.get("coordinates")
    if kind == "Polygon":
        rings = _polygon_coords(coords)
        return [rings] if rings else []
    if kind == "MultiPolygon":
        out = []
        for polygon in coords or []:
            rings = _polygon_coords(polygon)
            if rings:
                out.append(rings)
        return out
    if kind == "GeometryCollection":
        out = []
        for item in geometry.get("geometries") or []:
            out.extend(_feature_polygons(item))
        return out
    return []


def _parse_geojson(data) -> dict[str, list[list[tuple[float, float]]]]:
    if isinstance(data, dict) and str(data.get("type") or "") in (
        "Polygon",
        "MultiPolygon",
        "GeometryCollection",
    ):
        features = [{"geometry": data, "properties": {}}]
    else:
        features = data.get("features") if isinstance(data, dict) else None
        if features is None:
            features = [data] if isinstance(data, dict) else []
    regions: dict[str, list[list[tuple[float, float]]]] = {}
    for feature in features:
        if not isinstance(feature, dict):
            continue
        props = feature.get("properties")
        props = props if isinstance(props, dict) else {}
        name = _first(
            props,
            "name",
            "NAME",
            "Name",
            "title",
            "TITLE",
            "adcode",
            "id",
        )
        polygons = _feature_polygons(feature.get("geometry"))
        if not polygons:
            continue
        if not name:
            name = f"region{len(regions)}"
        rings = []
        for polygon in polygons:
            rings.extend(polygon)
        if name in regions:
            regions[name].extend(rings)
        else:
            regions[name] = rings
    return regions


def registerMap(name: str, geojson) -> bool:
    """注册 GeoJSON（FeatureCollection / Feature / Polygon / MultiPolygon）。

    :returns: 是否解析出至少一个区域
    """
    key = str(name or "").strip()
    if not key:
        return False
    regions = _parse_geojson(geojson)
    if not regions:
        warn_once(
            f"geo-register:{key}",
            f"registerMap({key!r}) 没有解析到 Polygon / MultiPolygon 区域",
        )
        return False
    _MAPS[key] = {
        "regions": regions,
        "projection": "equirectangular",
    }
    _PROJECTED.clear()
    return True


def unregisterMap(name: str) -> bool:
    key = str(name or "").strip()
    _PROJECTED.pop(key, None)
    for cache_key in [k for k in _PROJECTED if k[0] == key]:
        _PROJECTED.pop(cache_key, None)
    return _MAPS.pop(key, None) is not None


def mapNames() -> list[str]:
    return sorted(_MAPS)


def mapRegistered(name: str) -> bool:
    return str(name or "").strip() in _MAPS


def _project(lon: float, lat: float, projection: str):
    if projection == "mercator":
        lat = max(-85.05112878, min(85.05112878, lat))
        y = math.log(math.tan(math.pi / 4.0 + math.radians(lat) / 2.0))
        return math.radians(lon), -y
    return lon, -lat


def projectPoint(lon: float, lat: float, projection: str = "equirectangular"):
    """经纬度 → 投影坐标（y 轴向下）。"""
    lon = _to_float(lon, 0.0)
    lat = _to_float(lat, 0.0)
    return _project(lon, lat, str(projection or "").lower())


def unprojectPoint(x: float, y: float, projection: str = "equirectangular"):
    """投影坐标 → 经纬度。"""
    x = _to_float(x, 0.0)
    y = _to_float(y, 0.0)
    if str(projection or "").lower() == "mercator":
        return math.degrees(x), math.degrees(
            2.0 * math.atan(math.exp(-y)) - math.pi / 2.0
        )
    return x, -y


def _unwrap_ring(points, span: float):
    """跨 180° 经线时把 x 连续化，避免整幅地图被拉成全球宽。"""
    if len(points) < 2:
        return points
    out = [points[0]]
    prev = points[0][0]
    for x, y in points[1:]:
        while x - prev > span / 2.0:
            x -= span
        while x - prev < -span / 2.0:
            x += span
        out.append((x, y))
        prev = x
    return out


def mapRegions(name: str, projection: str = None) -> dict:
    """注册地图 → ``{区域名: [ring, ...]}``（已投影，y 轴向下）。"""
    entry = _MAPS.get(str(name or "").strip())
    if entry is None:
        return {}
    mode = str(projection or entry.get("projection") or "equirectangular").lower()
    if mode not in ("mercator", "equirectangular"):
        warn_once(
            f"geo-projection:{mode}",
            f"不支持的投影 {mode!r}，已回落到 equirectangular",
        )
        mode = "equirectangular"
    name_key = str(name or "").strip()
    cache_key = (name_key, mode)
    cached = _PROJECTED.get(cache_key)
    if cached is not None:
        return cached
    out = {}
    span = 2.0 * math.pi if mode == "mercator" else 360.0
    for region, rings in entry["regions"].items():
        projected = []
        ref_x = None
        for ring in rings:
            points = [_project(lon, lat, mode) for lon, lat in ring]
            if ref_x is not None and points:
                # 同一区域跨 180° 的岛屿要落在同一个 360° 周期里。
                shift = round((ref_x - points[0][0]) / span) * span
                if shift:
                    points = [(x + shift, y) for x, y in points]
            points = _unwrap_ring(points, span)
            if points and ref_x is None:
                ref_x = points[0][0]
            if len(points) >= 3:
                projected.append(points)
        if projected:
            out[region] = projected
    _PROJECTED[cache_key] = out
    return out


__all__ = [
    "mapNames",
    "mapRegistered",
    "mapRegions",
    "projectPoint",
    "registerMap",
    "unprojectPoint",
    "unregisterMap",
]
