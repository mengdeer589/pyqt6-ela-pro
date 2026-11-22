"""顶层 ``geo`` 坐标系：绘制注册地图，并为 series 提供经纬度映射。"""

from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF

from ._tokens import T
from ._utils import (
    merged_text_style,
    parse_color,
    parse_roam as _parse_roam,
    resolve_color_option,
    text_italic,
    text_weight,
    to_float as _to_float,
    warn_once,
)
from .axes import chartFont
from .geo import mapRegions, mapRegistered, projectPoint, unprojectPoint


class GeoCoord:
    """``geo`` 坐标系；``mapPoint(lon, lat)`` 与地图系列共享投影。"""

    kind = "geo"

    def __init__(self, chart, option=None, index: int = 0):
        self.chart = chart
        self.option = option if isinstance(option, dict) else {}
        raw = self.option.get("geo")
        if isinstance(raw, (list, tuple)):
            geo = raw[index] if 0 <= index < len(raw) else None
        else:
            geo = raw if index == 0 else None
        self.opt = dict(geo) if isinstance(geo, dict) else {}
        self.geo_index = int(index)
        self.map = str(self.opt.get("map") or "")
        self.projection = str(self.opt.get("projection") or "equirectangular").lower()
        self.rect = QRectF()
        self.plot = QRectF()
        self._paths: dict[str, QPainterPath] = {}
        self._polys: dict[str, QPolygonF] = {}
        self._regions: dict[str, list] = {}
        self._x0 = 0.0
        self._y0 = 0.0
        self._ox = 0.0
        self._oy = 0.0
        self._scale = 1.0
        self._zoom = 1.0
        self._pan = QPointF()
        self._pan_start = None
        self._pan_origin = QPointF()
        self._hover_region = None
        self._selected: set[str] = set()
        #: 系列叠加的区域内色（供标签自动对比色；每帧由系列重填）
        self._label_fills: dict[str, QColor] = {}
        self._roam_scale, self._roam_move = _parse_roam(self.opt.get("roam"))

    def setSeries(self, series_opts=None) -> None:
        # geo 的范围由地图 / geo.regions 决定，与系列数据无关。
        return

    def _custom_regions(self) -> dict:
        raw = self.opt.get("regions")
        if not isinstance(raw, dict):
            return {}
        out = {}
        for name, value in raw.items():
            rings = self._normalize_region(value)
            if rings:
                out[str(name)] = rings
        return out

    @staticmethod
    def _normalize_region(value) -> list:
        if not isinstance(value, (list, tuple)) or not value:
            return []
        if (
            isinstance(value[0], (list, tuple))
            and value[0]
            and isinstance(value[0][0], (int, float))
        ):
            value = [value]
        rings = []
        for raw in value:
            if not isinstance(raw, (list, tuple)):
                continue
            points = []
            for point in raw:
                if not isinstance(point, (list, tuple)) or len(point) < 2:
                    continue
                x = _to_float(point[0], None)
                y = _to_float(point[1], None)
                if x is not None and y is not None:
                    points.append((x, y))
            if len(points) >= 3:
                rings.append(points)
        return rings

    def _resolve_regions(self) -> dict:
        if self.map and mapRegistered(self.map):
            regions = mapRegions(self.map, self.projection)
            if regions:
                return regions
        regions = self._custom_regions()
        if regions:
            return regions
        if self.map:
            warn_once(
                "geo-coord-map-missing",
                f"geo.map={self.map!r} 未注册 GeoJSON，也没有 geo.regions",
            )
        return {}

    def regionRings(self) -> dict:
        """当前 geo 的投影 ring 数据（供 map 系列复用）。"""
        return {
            name: [list(ring) for ring in rings]
            for name, rings in self._regions.items()
        }

    def regionAt(self, pos: QPointF):
        """光标下的区域名；无命中返回 None。"""
        for name, path in reversed(list(self._paths.items())):
            if path.contains(pos):
                return name
        return None

    def selectedRegions(self) -> set:
        return set(self._selected)

    def _select_mode(self) -> str:
        return str(self.opt.get("selectedMode") or "multiple").lower()

    @staticmethod
    def _pixels(value, total: float, fallback: float = 0.0) -> float:
        if value is None:
            return fallback
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        text = str(value).strip()
        if text.endswith("%"):
            try:
                return total * float(text[:-1]) / 100.0
            except ValueError:
                return fallback
        try:
            return float(text)
        except (TypeError, ValueError, OverflowError):
            return fallback

    def _sub_rect(self, rect: QRectF) -> QRectF:
        opt = self.opt
        left = self._pixels(opt.get("left"), rect.width(), 0.0)
        right = self._pixels(opt.get("right"), rect.width(), 0.0)
        top = self._pixels(opt.get("top"), rect.height(), 0.0)
        bottom = self._pixels(opt.get("bottom"), rect.height(), 0.0)
        width = opt.get("width")
        height = opt.get("height")
        x0 = rect.left() + left
        x1 = rect.right() - right
        if width is not None:
            w = self._pixels(width, rect.width(), rect.width())
            if opt.get("left") is None and opt.get("right") is not None:
                x0 = x1 - w
            else:
                x1 = x0 + w
        y0 = rect.top() + top
        y1 = rect.bottom() - bottom
        if height is not None:
            h = self._pixels(height, rect.height(), rect.height())
            if opt.get("top") is None and opt.get("bottom") is not None:
                y0 = y1 - h
            else:
                y1 = y0 + h
        return QRectF(x0, y0, max(10.0, x1 - x0), max(10.0, y1 - y0))

    def layout(self, rect: QRectF) -> None:
        rect = self._sub_rect(rect)
        self.rect = QRectF(rect)
        self.plot = QRectF(rect)
        self._label_fills.clear()
        self._paths = {}
        self._polys = {}
        self._regions = self._resolve_regions()
        if not self._regions:
            return
        xs = [
            pt[0] for rings in self._regions.values() for ring in rings for pt in ring
        ]
        ys = [
            pt[1] for rings in self._regions.values() for ring in rings for pt in ring
        ]
        if not xs or not ys:
            return
        x0, x1 = min(xs), max(xs)
        y0, y1 = min(ys), max(ys)
        span_x = max(1e-9, x1 - x0)
        span_y = max(1e-9, y1 - y0)
        margin = 12.0
        avail_w = max(10.0, rect.width() - margin * 2)
        avail_h = max(10.0, rect.height() - margin * 2)
        self._x0, self._y0 = x0, y0
        self._scale = min(avail_w / span_x, avail_h / span_y) * self._zoom
        self._ox = (
            rect.left() + (rect.width() - span_x * self._scale) / 2 + self._pan.x()
        )
        self._oy = (
            rect.top() + (rect.height() - span_y * self._scale) / 2 + self._pan.y()
        )
        for name, rings in self._regions.items():
            path = QPainterPath()
            path.setFillRule(Qt.FillRule.OddEvenFill)
            outer = None
            for ring in rings:
                poly = QPolygonF(
                    [
                        QPointF(
                            self._ox + (px - x0) * self._scale,
                            self._oy + (py - y0) * self._scale,
                        )
                        for px, py in ring
                    ]
                )
                if outer is None:
                    outer = poly
                path.addPolygon(poly)
            if outer is not None:
                self._paths[name] = path
                self._polys[name] = outer

    def _screen(self, x: float, y: float) -> QPointF:
        return QPointF(
            self._ox + (x - self._x0) * self._scale,
            self._oy + (y - self._y0) * self._scale,
        )

    def mapPoint(self, lon, lat=None) -> QPointF:
        if lat is None:
            raise TypeError("GeoCoord.mapPoint 需要 (lon, lat)")
        x, y = projectPoint(lon, lat, self.projection)
        return self._screen(x, y)

    def mapArrays(self, xs, ys):
        import numpy as np

        lon = np.asarray(xs, dtype=np.float64)
        lat = np.asarray(ys, dtype=np.float64)
        if self.projection == "mercator":
            lat = np.clip(lat, -85.05112878, 85.05112878)
            px = np.radians(lon)
            py = -np.log(np.tan(np.pi / 4.0 + np.radians(lat) / 2.0))
        else:
            px = lon
            py = -lat
        sx = self._ox + (px - self._x0) * self._scale
        sy = self._oy + (py - self._y0) * self._scale
        return sx, sy

    def invertPoint(self, pos: QPointF):
        if self._scale <= 0:
            return None
        x = (pos.x() - self._ox) / self._scale + self._x0
        y = (pos.y() - self._oy) / self._scale + self._y0
        return unprojectPoint(x, y, self.projection)

    def containPoint(self, pos: QPointF) -> bool:
        return self.rect.contains(pos)

    def paintTooltipMarker(self, *args, **kwargs) -> None:
        return

    def paintAxes(self, p: QPainter) -> None:
        if not self._paths:
            return
        geo_style = self.opt.get("itemStyle")
        geo_style = dict(geo_style) if isinstance(geo_style, dict) else {}
        fill = resolve_color_option(
            geo_style.get("areaColor") or geo_style.get("color"),
            self.chart,
            T("color.bg.muted", self.chart),
        )
        border = resolve_color_option(
            geo_style.get("borderColor"),
            self.chart,
            T("color.border", self.chart),
        )
        try:
            border_w = max(0.0, float(geo_style.get("borderWidth", 1.0)))
        except (TypeError, ValueError, OverflowError):
            border_w = 1.0
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        for name, path in self._paths.items():
            region_style = {}
            regions = self.opt.get("regions")
            if isinstance(regions, dict):
                raw = regions.get(name)
                if isinstance(raw, dict):
                    region_style = raw.get("itemStyle") or {}
            use_style = region_style
            if name == self._hover_region:
                emph = self.opt.get("emphasis")
                if isinstance(emph, dict) and isinstance(emph.get("itemStyle"), dict):
                    use_style = {**region_style, **emph["itemStyle"]}
                else:
                    use_style = dict(region_style)
                    use_style.setdefault("borderColor", T("color.primary", self.chart))
                    use_style.setdefault("borderWidth", max(1.5, border_w))
            if name in self._selected:
                sel = self.opt.get("select")
                if isinstance(sel, dict) and isinstance(sel.get("itemStyle"), dict):
                    use_style = {**use_style, **sel["itemStyle"]}
                else:
                    use_style = dict(use_style)
                    use_style.setdefault("areaColor", T("color.primary", self.chart))
            region_fill = resolve_color_option(
                use_style.get("areaColor") or use_style.get("color"),
                self.chart,
                fill,
            )
            if name == self._hover_region and region_fill == fill:
                region_fill = region_fill.lighter(112)
            p.setBrush(region_fill)
            try:
                region_border_w = max(
                    0.0, float(use_style.get("borderWidth", border_w))
                )
            except (TypeError, ValueError, OverflowError):
                region_border_w = border_w
            region_border = resolve_color_option(
                use_style.get("borderColor"),
                self.chart,
                border,
            )
            p.setPen(
                QPen(region_border, region_border_w)
                if region_border_w > 0
                else Qt.PenStyle.NoPen
            )
            p.drawPath(path)
        p.restore()

    def paintLabels(self, p: QPainter) -> None:
        """区域名标签：在系列填充之后绘制，避免被 map 系列着色盖住。"""
        if not self._paths:
            return
        label_opt = self.opt.get("label")
        label_opt = dict(label_opt) if isinstance(label_opt, dict) else {}
        if not bool(label_opt.get("show", False)):
            return
        label_style = merged_text_style(self.chart, label_opt)
        font = chartFont(
            label_style.get("fontSize", T("font.xs")),
            text_weight(label_style.get("fontWeight")),
            label_style.get("fontFamily"),
            text_italic(label_style.get("fontStyle")),
        )
        explicit = label_style.get("color")
        p.save()
        p.setFont(font)
        for name, path in self._paths.items():
            if not name:
                continue
            if explicit:
                color = resolve_color_option(
                    explicit, self.chart, T("color.text.secondary", self.chart)
                )
            else:
                # 未指定颜色时按实际底色选字色：深色区域用白字，浅色区域用正文色。
                fill = self._label_fills.get(name)
                if (
                    isinstance(fill, QColor)
                    and fill.isValid()
                    and fill.lightness() < 140
                ):
                    color = parse_color("#ffffff")
                else:
                    color = QColor(T("color.text.primary", self.chart))
            p.setPen(color)
            center = path.boundingRect().center()
            p.drawText(
                QRectF(center.x() - 60, center.y() - 9, 120, 18),
                Qt.AlignmentFlag.AlignCenter,
                name,
            )
        p.restore()

    def onWheel(self, event) -> bool:
        if not self._roam_scale:
            return False
        try:
            pos = QPointF(event.position())
            if not self.rect.contains(pos):
                return False
            factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        except Exception:
            return False
        self._zoom = max(0.3, min(8.0, self._zoom * factor))
        self.chart.invalidateLayout()
        self.chart.update()
        return True

    def onMousePress(self, pos: QPointF) -> bool:
        if not self.rect.contains(pos):
            return False
        if self._roam_move:
            self._pan_start = QPointF(pos)
            self._pan_origin = QPointF(self._pan)
            return True
        if self._select_mode() in ("", "none", "false"):
            return False
        name = self.regionAt(pos)
        if not name:
            return False
        if self._select_mode() == "single":
            self._selected = {name} if name not in self._selected else set()
        elif name in self._selected:
            self._selected.discard(name)
        else:
            self._selected.add(name)
        self.chart._emit_event(
            "click",
            {
                "type": "click",
                "componentType": "geo",
                "name": name,
                "region": name,
                "selected": self.selectedRegions(),
            },
        )
        self.chart._emit_event(
            "geoselectchanged",
            {
                "type": "geoselectchanged",
                "name": name,
                "selected": self.selectedRegions(),
            },
        )
        self.chart.update()
        return True

    def onMouseMove(self, pos: QPointF) -> bool:
        if getattr(self, "_pan_start", None) is not None:
            dx = pos.x() - self._pan_start.x()
            dy = pos.y() - self._pan_start.y()
            if abs(dx) + abs(dy) < 3.0:
                return False
            self._pan = self._pan_origin + QPointF(dx, dy)
            self.chart.invalidateLayout()
            self.chart.update()
            return True
        name = self.regionAt(pos)
        if name != self._hover_region:
            self._hover_region = name
            self.chart.update()
        return False

    def onMouseRelease(self, pos: QPointF) -> bool:
        panned = self._pan_start is not None
        self._pan_start = None
        return panned
