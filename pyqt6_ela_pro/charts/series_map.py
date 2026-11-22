"""地图系列（type="map"）。"""

from __future__ import annotations


from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF

from ._tokens import T, theme_ramp
from ._utils import parse_roam as _parse_roam
from ._utils import merged_text_style, text_italic, text_weight
from ._utils import (
    flatten_on_canvas,
    ramp_color,
    resolve_color_option,
    to_float as _to_float,
    warn_once,
)
from ._utils import parse_color
from .axes import chartFont
from .core import (
    SeriesRenderer,
    registerSeries,
)
from .geo import mapRegions, mapRegistered
from .geo_coord import GeoCoord


DEMO_MAP = {
    "华北": [(30, 18), (48, 14), (55, 24), (50, 34), (36, 32)],
    "东北": [(56, 4), (74, 6), (78, 20), (62, 26), (55, 18)],
    "华东": [(52, 36), (66, 34), (70, 48), (56, 52), (50, 44)],
    "华南": [(46, 56), (62, 54), (66, 68), (50, 72), (42, 64)],
    "华中": [(36, 36), (50, 36), (48, 52), (34, 50)],
    "西南": [(16, 40), (34, 38), (32, 58), (14, 60), (10, 48)],
    "西北": [(4, 10), (28, 12), (34, 34), (16, 38), (6, 28)],
}


class MapSeriesRenderer(SeriesRenderer):
    """简化地图系列（type="map"）。
    ``map="demo"``（或缺省）用内置示意地图；自定义地图经
    ``option["geo"]["regions"] = {"名称": [[x, y], ...]}`` 传入多边形顶点。
    """

    def __init__(self, chart, opt):
        super().__init__(chart, opt)
        self._polys = []  # [(region_name, QPolygonF, data_index)]
        self._paths = {}  # 区域名 → QPainterPath（含孔洞 / 多岛）
        self._region_colors = {}
        self._rect = QRectF()
        self._roam = _parse_roam(self.opt.get("roam", False))
        try:
            self._zoom = max(0.2, min(6.0, float(self.opt.get("zoom") or 1.0)))
        except (TypeError, ValueError, OverflowError):
            self._zoom = 1.0
        self._pan = QPointF()
        self._pan_start = None
        self._pan_origin = QPointF()
        self._panning = False
        self._geo = None  # 复用顶层 geo 底图时指向该 GeoCoord

    def boundGeo(self):
        """与顶层 ``geo`` 共用底图时返回该 coord（``geoIndex`` 显式，或同名 map）。"""
        geo_index = self.opt.get("geoIndex")
        if geo_index is not None:
            try:
                coord = self.chart.geoCoord(int(geo_index))
            except (TypeError, ValueError, OverflowError):
                return None
            return coord if coord is not None and not coord.rect.isNull() else None
        name = str(self.opt.get("map") or "")
        if not name:
            return None
        for coord in self.chart.geoCoords():
            if coord.map == name and not coord.rect.isNull():
                return coord
        return None

    def _index_map(self) -> dict:
        """区域名 → data 下标（itemStyle / 命中回传用）。"""
        out = {}
        key = str(self.opt.get("nameProperty") or "name")
        for i, item in enumerate(self.data()):
            if isinstance(item, dict):
                name = str(item.get(key, item.get("name")) or "")
            else:
                name = str(item)
            out.setdefault(name, i)
        return out

    def _regions(self) -> dict:
        """当前生效的 ``{名称: [ring, ...]}`` 多边形字典（已投影）。"""
        geo_index = self.opt.get("geoIndex")
        if geo_index is not None:
            coord = self.chart.geoCoord(geo_index)
            if coord is not None:
                regions = coord.regionRings()
                if regions:
                    return regions
        name = str(self.opt.get("map") or "demo")
        geo = (getattr(self.chart, "_option", {}) or {}).get("geo") or {}
        projection = self.opt.get("projection")
        if not projection and isinstance(geo, dict):
            projection = geo.get("projection")
        if mapRegistered(name):
            regions = mapRegions(name, projection)
            if regions:
                return regions
        custom = geo.get("regions") if isinstance(geo, dict) else None
        if name not in ("demo", "china-simple") and isinstance(custom, dict) and custom:
            out = {}
            for key, value in custom.items():
                rings = self._normalize_region(value)
                if rings:
                    out[str(key)] = rings
            if out:
                return out
        if name not in ("demo", "china-simple"):
            # 不要静默回落演示地图：自定义地图名缺 regions / GeoJSON 时整图
            # 全是底色且零报错。
            warn_once(
                "map-regions-missing",
                f"map={name!r} 未注册 GeoJSON，且 option['geo']['regions'] "
                f"没有多边形顶点；已回落到内置演示地图（{len(DEMO_MAP)} 个区块），"
                f"数据里的区域名多半匹配不上",
            )
        return {k: [[tuple(pt) for pt in v]] for k, v in DEMO_MAP.items()}

    @staticmethod
    def _normalize_region(value) -> list:
        """``[[x,y], ...]`` / ``[[[x,y], ...], ...]`` → ring 列表。"""
        return GeoCoord._normalize_region(value)

    def _value_map(self) -> dict:
        """data [{name, value}] → {区域名: 数值}（nameProperty 可改键）。"""
        key = str(self.opt.get("nameProperty") or "name")
        out = {}
        for item in self.data():
            if not isinstance(item, dict):
                continue
            nm = item.get(key, item.get("name"))
            v = _to_float(item.get("value"), None)
            if nm is not None:
                out.setdefault(str(nm), v)
        return out

    def layout(self, rect: QRectF) -> None:
        self._rect = QRectF(rect)
        self._polys = []
        self._paths = {}
        self._region_colors = {}
        geo = self.boundGeo()
        self._geo = geo
        if geo is not None:
            # 底图由顶层 geo 画：这里只复用它的路径，系列只叠加数据着色。
            index_map = self._index_map()
            self._paths = geo._paths
            self._polys = [
                (name, poly, index_map.get(name)) for name, poly in geo._polys.items()
            ]
            return
        regions = self._regions()
        if not regions:
            return
        xs = [pt[0] for rings in regions.values() for ring in rings for pt in ring]
        ys = [pt[1] for rings in regions.values() for ring in rings for pt in ring]
        if not xs or not ys:
            return
        x0, x1 = min(xs), max(xs)
        y0, y1 = min(ys), max(ys)
        span_x = max(1e-6, x1 - x0)
        span_y = max(1e-6, y1 - y0)
        margin = 18.0
        avail_w = max(10.0, rect.width() - margin * 2)
        avail_h = max(10.0, rect.height() - margin * 2)
        scale = min(avail_w / span_x, avail_h / span_y) * self._zoom
        ox = rect.left() + (rect.width() - span_x * scale) / 2 + self._pan.x()
        oy = rect.top() + (rect.height() - span_y * scale) / 2 + self._pan.y()
        index_map = self._index_map()
        for name, rings in regions.items():
            path = QPainterPath()
            path.setFillRule(Qt.FillRule.OddEvenFill)
            outer = None
            for ring in rings:
                poly = QPolygonF(
                    [
                        QPointF(ox + (px - x0) * scale, oy + (py - y0) * scale)
                        for px, py in ring
                    ]
                )
                if outer is None:
                    outer = poly
                path.addPolygon(poly)
            if outer is None:
                continue
            self._paths[name] = path
            self._polys.append((name, outer, index_map.get(name)))

    def onWheel(self, event) -> bool:
        if self._geo is not None or not self._roam[0]:
            return False
        try:
            pos = event.position()
            delta = event.angleDelta().y()
        except Exception:
            return False
        if self._rect.isNull() or not self._rect.contains(pos):
            return False
        factor = 1.15 if delta > 0 else 1 / 1.15
        self._zoom = max(0.2, min(6.0, self._zoom * factor))
        self.chart.invalidateLayout()
        self.chart.update()
        return True

    def onMousePress(self, pos: QPointF) -> bool:
        if self._geo is not None or not self._roam[1] or not self._rect.contains(pos):
            return False
        self._pan_start = QPointF(pos)
        self._pan_origin = QPointF(self._pan)
        self._panning = False
        # 吞下按下：松开时由 core 的 click-vs-drag 判定补发点击，
        # 否则拖拽平移会在按下瞬间误发 itemClicked。
        return True

    def onMouseMove(self, pos: QPointF) -> bool:
        if self._pan_start is None:
            return False
        dx = pos.x() - self._pan_start.x()
        dy = pos.y() - self._pan_start.y()
        if not self._panning and abs(dx) + abs(dy) < 3.0:
            return False
        self._panning = True
        self._pan = self._pan_origin + QPointF(dx, dy)
        self.chart.invalidateLayout()
        self.chart.update()
        return True

    def onMouseRelease(self, pos: QPointF) -> bool:
        was_panning = self._panning
        self._pan_start = None
        self._panning = False
        return was_panning

    def resetRoam(self) -> None:
        """复位缩放与平移。"""
        self._zoom = 1.0
        self._pan = QPointF()
        self.chart.invalidateLayout()
        self.chart.update()

    def _visual_map(self):
        """本系列该用哪个 visualMap 组件（``None`` = 用内置色带）。"""
        return self.visualMapComponent()

    def _fill_color(
        self, name: str, values: dict, vmin: float, vmax: float, vm
    ) -> QColor:
        v = values.get(name)
        if v is None:
            # 半透明叠色压到画布再返回：标签对比 / hover 提亮 / 命中色都要实际观感
            return flatten_on_canvas(T("color.bg.muted", self.chart), self.chart)
        if vm is not None:
            try:
                return parse_color(vm.mapColor(v))
            except Exception:
                pass
        span = vmax - vmin
        frac = 0.5 if span == 0 else (v - vmin) / span
        return ramp_color(theme_ramp(self.chart), frac, self.chart)

    def labelStyle(self) -> dict:
        """区域名样式（``label``；未设置的键回退顶层 ``textStyle``）。"""
        label = self.opt.get("label")
        return merged_text_style(self.chart, label if isinstance(label, dict) else {})

    def labelShown(self) -> bool:
        """区域名是否显示（``label.show``）；绑定顶层 geo 时默认交给 geo 画。"""
        label = self.opt.get("label")
        if isinstance(label, dict) and "show" in label:
            return bool(label.get("show"))
        return self._geo is None

    def paint(self, p: QPainter, anim_t: float = 1.0) -> None:
        if not self._polys:
            return
        values = self._value_map()
        vals = [v for v in values.values() if v is not None]
        vmin = min(vals) if vals else 0.0
        vmax = max(vals) if vals else 1.0
        vm = self._visual_map()
        p.save()
        self._label_rects = []
        # ``label``：区域名，字号 / 颜色 / 字重走统一解析链（含顶层兜底）。
        label_show = self.labelShown()
        label_style = self.labelStyle()
        font = chartFont(
            label_style.get("fontSize", T("font.xs")),
            text_weight(label_style.get("fontWeight")),
            label_style.get("fontFamily"),
            text_italic(label_style.get("fontStyle")),
        )
        p.setFont(font)
        bound = self._geo is not None
        item_style = self.opt.get("itemStyle")
        item_style = dict(item_style) if isinstance(item_style, dict) else {}
        base_border = resolve_color_option(
            item_style.get("borderColor"),
            self.chart,
            T("color.border.strong", self.chart),
        )
        base_border_w = _to_float(item_style.get("borderWidth"), 0.0 if bound else 1.0)
        hover = self.chart.hoverInfo()
        hovered = (
            hover[1].get("dataIndex")
            if hover is not None and hover[0] is self
            else None
        )
        for name, poly, data_index in self._polys:
            if bound and data_index is None:
                continue  # 无数据区域交给顶层 geo（保留其 hover / select 样式）
            fill = self._fill_color(name, values, vmin, vmax, vm)
            if data_index is not None:
                override = self.itemColor(data_index, default=fill)
                if override != fill:
                    fill = override
            self._region_colors[name] = fill
            alpha = self.itemOpacity(data_index) if data_index is not None else 1.0
            fill, alpha, border_color, border_w = self.stateStyle(
                data_index, hovered, fill, alpha, base_border, base_border_w
            )
            if alpha < 1.0:
                fill.setAlphaF(fill.alphaF() * alpha)
            if border_w > 0:
                p.setPen(QPen(border_color or base_border, border_w))
            else:
                p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(fill)
            path = self._paths.get(name)
            if path is not None:
                p.drawPath(path)
            else:
                p.drawPolygon(poly)
            if not label_show or not name:
                continue
            # 区域名称标签（多边形包围盒中心）；未显式给 label.color 时按底色亮度自动选
            bounds = path.boundingRect() if path is not None else poly.boundingRect()
            c = bounds.center()
            p.setPen(self.contrastLabelColor(fill, data_index))
            item = None
            data = self.data()
            if isinstance(data_index, int) and 0 <= data_index < len(data):
                item = data[data_index]
            text = self.hierarchyLabelText(
                data_index,
                name,
                values.get(name),
                item,
            )
            rect = QRectF(c.x() - 60, c.y() - 8, 120, 16)
            hit = self.paintLabelIn(
                p,
                rect,
                text,
                index=data_index,
                align=Qt.AlignmentFlag.AlignCenter,
                color=self.contrastLabelColor(fill, data_index),
            )
            if not hit.isNull() and isinstance(data_index, int) and data_index >= 0:
                self._label_rects.append((data_index, hit, text))
        if bound:
            self._geo._label_fills.update(self._region_colors)
        p.restore()

    def hitTest(self, pos: QPointF):
        values = self._value_map()
        vals = [v for v in values.values() if v is not None]
        vmin = min(vals) if vals else 0.0
        vmax = max(vals) if vals else 1.0
        for name, poly, data_index in reversed(self._polys):
            path = self._paths.get(name)
            inside = (
                path.contains(pos)
                if path is not None
                else poly.containsPoint(pos, Qt.FillRule.OddEvenFill)
            )
            if inside:
                color = self._region_colors.get(name)
                if color is None:
                    color = self._fill_color(
                        name, values, vmin, vmax, self._visual_map()
                    )
                    if data_index is not None:
                        color = self.itemColor(data_index, default=color)
                return {
                    "name": name,
                    "value": values.get(name),
                    "color": color,
                    "series": self.name,
                    "dataIndex": data_index,
                }
        return None

    def valueAtIndex(self, index: int):
        data = self.data()
        try:
            idx = int(index)
        except (TypeError, ValueError, OverflowError):
            return None
        if not 0 <= idx < len(data):
            return None
        item = data[idx]
        name = ""
        value = None
        if isinstance(item, dict):
            name = str(item.get(self.opt.get("nameProperty") or "name") or "")
            value = item.get("value")
        else:
            name = str(item)
        return {
            "name": name,
            "value": value,
            "color": self.itemColor(idx),
            "series": self.name,
            "dataIndex": idx,
        }


registerSeries("map", MapSeriesRenderer)
