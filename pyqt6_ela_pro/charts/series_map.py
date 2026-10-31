"""地图系列（从 ``components`` 归位：它是系列，不是组件）。"""

from __future__ import annotations


from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPen, QPolygonF

from ._tokens import T
from ._utils import ON_FILL_WHITE, parse_roam as _parse_roam
from ._utils import merged_text_style, text_italic, text_weight
from ._utils import to_float as _to_float, warn_once, with_alpha
from ._utils import parse_color
from .axes import chartFont
from .core import (
    SeriesRenderer,
    registerSeries,
)

from .components import lerp_color


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

    option::

        {"type": "map", "map": "demo"|自定义名, "nameProperty": "name",
         "data": [{"name": "华北", "value": 120, "itemStyle": {...}}, ...]}

    - ``map`` 为 ``"demo"``（或缺省）时使用内置示意地图 ``DEMO_MAP``；
    - 自定义地图经 ``option["geo"]["regions"] = {"名称": [[x, y], ...]}``
      传入多边形顶点列表（任意平面坐标，自动等比缩放到绘图区）；
    - 区域着色：优先经 ``chart.components`` 中 visualMap 组件的
      ``mapColor(v)``，其次 ``itemStyle.color``，否则按 primary.subtle →
      primary 色带插值；
    - ``nameProperty``：区域标签取自 data 项的该键（缺省 "name"）；
    - ``roam``：True / ``1`` / ``"true"`` / ``"scale"`` / ``"move"`` 控制滚轮
      缩放 + 拖拽平移（ECharts 语义；默认 False）；``zoom`` 初始缩放；
      ``resetRoam()`` 复位。**数字与布尔字符串都按 true 认** —— 从 JSON 读进
      来的 option 里 ``roam`` 常是数字，原先落进「方向名」分支被静默关掉。
    """

    def __init__(self, chart, opt):
        super().__init__(chart, opt)
        self._polys = []  # [(region_name, QPolygonF, data_index)]
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

    def _index_map(self) -> dict:
        """区域名 → data 下标（itemStyle / 命中回传用）。"""
        out = {}
        for i, item in enumerate(self.data()):
            if isinstance(item, dict):
                name = str(item.get(self.opt.get("nameProperty") or "name") or "")
            else:
                name = str(item)
            out.setdefault(name, i)
        return out

    # -- 数据 ------------------------------------------------------------
    def _regions(self) -> dict:
        """当前生效的 {名称: [[x, y], ...]} 多边形字典。"""
        name = str(self.opt.get("map") or "demo")
        geo = (getattr(self.chart, "_option", {}) or {}).get("geo") or {}
        custom = geo.get("regions") if isinstance(geo, dict) else None
        if name not in ("demo", "china-simple") and isinstance(custom, dict) and custom:
            out = {}
            for k, poly in custom.items():
                pts = []
                for pt in poly or []:
                    if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                        px = _to_float(pt[0], None)
                        py = _to_float(pt[1], None)
                        if px is not None and py is not None:
                            pts.append((px, py))
                if len(pts) >= 3:
                    out[str(k)] = pts
            if out:
                return out
        if name not in ("demo", "china-simple"):
            # **不要静默回落演示地图**。用户写了 ``map: "my-map"`` 却没给
            # ``geo.regions``，拿到的是内置的「华北 / 东北 / …」，而他的数据
            # 用的是真实地图的省名 —— 一个都匹配不上，整张图全是底色，且
            # 没有任何报错。回落保留（空图更难排查），但必须喊一声。
            warn_once(
                "map-regions-missing",
                f"map={name!r} 需要 option['geo']['regions'] 提供多边形顶点，"
                f"缺省已回落到内置演示地图（{len(DEMO_MAP)} 个区块）；"
                f"数据里的区域名多半匹配不上",
            )
        return {k: [tuple(pt) for pt in v] for k, v in DEMO_MAP.items()}

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
                out[str(nm)] = v
        return out

    # -- 协议 ------------------------------------------------------------
    def layout(self, rect: QRectF) -> None:
        self._rect = QRectF(rect)
        self._polys = []
        regions = self._regions()
        if not regions:
            return
        xs = [pt[0] for pts in regions.values() for pt in pts]
        ys = [pt[1] for pts in regions.values() for pt in pts]
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
        for name, pts in regions.items():
            poly = QPolygonF(
                [
                    QPointF(ox + (px - x0) * scale, oy + (py - y0) * scale)
                    for px, py in pts
                ]
            )
            self._polys.append((name, poly, index_map.get(name)))

    # -- 交互：缩放 / 平移（roam） ----------------------------------------
    def onWheel(self, event) -> bool:
        if not self._roam[0]:
            return False
        try:
            pos = (
                event.position()
                if hasattr(event, "position")
                else QPointF(event.position().toPoint())
            )
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
        if not self._roam[1] or not self._rect.contains(pos):
            return False
        self._pan_start = QPointF(pos)
        self._pan_origin = QPointF(self._pan)
        self._panning = False
        return False  # 不消费点击：区域点击仍可触发 itemClicked

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
        """本系列该用哪个 visualMap 组件（``None`` = 用内置色带）。

        组件查找统一在 ``SeriesRenderer.visualMapComponent``（显式绑定优先 →
        通用件），这里只保留旧名字给绘制代码用。
        """
        return self.visualMapComponent()

    def _fill_color(
        self, name: str, values: dict, vmin: float, vmax: float, vm
    ) -> QColor:
        v = values.get(name)
        if v is None:
            return QColor(T("color.bg.muted"))
        if vm is not None:
            try:
                return parse_color(vm.mapColor(v))
            except Exception:
                pass
        span = vmax - vmin
        frac = 0.5 if span == 0 else (v - vmin) / span
        return lerp_color(T("color.primary.subtle"), T("color.primary"), frac)

    def labelStyle(self) -> dict:
        """区域名样式（``label``；未设置的键回退顶层 ``textStyle``）。"""
        label = self.opt.get("label")
        return merged_text_style(
            self.chart, label if isinstance(label, dict) else {}
        )

    def labelShown(self) -> bool:
        """区域名是否显示（``label.show``，地图默认 **True**）。"""
        label = self.opt.get("label")
        return bool(label.get("show", True)) if isinstance(label, dict) else True

    def paint(self, p: QPainter, anim_t: float = 1.0) -> None:
        if not self._polys:
            return
        values = self._value_map()
        vals = [v for v in values.values() if v is not None]
        vmin = min(vals) if vals else 0.0
        vmax = max(vals) if vals else 1.0
        vm = self._visual_map()
        p.save()
        # ``label``：区域名（ECharts 键）。``show: false`` 可关；字号 / 颜色 /
        # 字重走与其它系列同一套解析链（含顶层 textStyle 兜底）。
        label_show = self.labelShown()
        label_style = self.labelStyle()
        font = chartFont(
            label_style.get("fontSize", T("font.xs")),
            text_weight(label_style.get("fontWeight")),
            label_style.get("fontFamily"),
            text_italic(label_style.get("fontStyle")),
        )
        p.setFont(font)
        border = QPen(QColor(T("color.border.strong")), 1)
        hover = self.chart.hoverInfo()
        hovered = (
            hover[1].get("dataIndex")
            if hover is not None and hover[0] is self
            else None
        )
        for name, poly, data_index in self._polys:
            fill = self._fill_color(name, values, vmin, vmax, vm)
            if data_index is not None:
                override = self.itemColor(data_index, default=fill)
                if override != fill:
                    fill = override
            if hovered is not None and data_index is not None:
                if data_index == hovered:
                    fill = parse_color(fill).lighter(112)
                elif self.blursOtherItems():
                    fill = with_alpha(parse_color(fill), 150)
            p.setPen(border)
            p.setBrush(fill)
            p.drawPolygon(poly)
            if not label_show or not name:
                continue
            # 区域名称标签（多边形包围盒中心）；未显式给 label.color 时按底色亮度自动选
            c = poly.boundingRect().center()
            label_color = label_style.get("color")
            if isinstance(label_color, str) and label_color:
                p.setPen(parse_color(label_color))
            elif fill.lightness() < 130:
                p.setPen(QColor(ON_FILL_WHITE))
            else:
                p.setPen(QColor(T("color.text.primary")))
            label = name
            p.drawText(
                QRectF(c.x() - 40, c.y() - 8, 80, 16),
                Qt.AlignmentFlag.AlignCenter,
                label,
            )
        p.restore()

    def hitTest(self, pos: QPointF):
        values = self._value_map()
        for name, poly, data_index in reversed(self._polys):
            if poly.containsPoint(pos, Qt.FillRule.OddEvenFill):
                return {
                    "name": name,
                    "value": values.get(name),
                    "series": self.name,
                    "dataIndex": data_index,
                }
        return None

    def valueAtIndex(self, index: int):
        return None


registerSeries("map", MapSeriesRenderer)
