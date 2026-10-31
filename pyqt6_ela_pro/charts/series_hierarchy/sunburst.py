"""旭日图系列。（``pyqt6_ela_pro.charts`` 内部模块）。"""

from __future__ import annotations


import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QColor,
    QFontMetricsF,
    QPainter,
    QPainterPath,
    QPen,
)

from .._tokens import T
from .._utils import ON_FILL_WHITE, clamp as _clamp
from .._utils import to_float as _to_float
from .._utils import parse_color
from ..core import SeriesRenderer
from ._shared import _assign_branch_colors, _build_hierarchy, _label_font, _parse_pct


class SunburstSeriesRenderer(SeriesRenderer):
    """旭日图（层级环形扇区，中心向外）。

    option 键：
    - ``data``: [{"name","value","children":[...]}]（层级；value 缺省累计子级）；
    - ``radius``: ["15%","90%"]（内孔 / 外半径，相对短边一半）；
    - ``label``: {"show": True, "minAngle": 8（小于该度数省略标签）,
      "fontSize": px}（标签沿角度旋转）；
    - 动画：anim_t 控制角扫掠展开。
    """

    def __init__(self, chart, opt):
        super().__init__(chart, opt)
        self._nodes = []
        self._roots = []
        #: 下钻路径（子级下标序列；空 = 顶层）
        self._focus_path = []
        self._center = QPointF()
        self._r0 = 0.0
        self._r1 = 1.0
        self._max_depth = 1

    def layout(self, rect: QRectF) -> None:
        self._nodes = []
        roots = _build_hierarchy(self.data())
        if not roots:
            self._roots = []
            return
        _assign_branch_colors(self.chart, roots)
        # 下钻：按路径解析当前显示层级（路径失效时回到顶层）
        display = roots
        focus = None
        prefix: tuple = ()
        for idx in list(self._focus_path):
            if 0 <= idx < len(display):
                focus = display[idx]
                prefix = prefix + (idx,)
                display = focus.children
            else:
                self._focus_path = []
                focus = None
                prefix = ()
                display = roots
                break
        self._roots = display
        self._max_depth = max((self._depth_of(r) - r.depth for r in display), default=1)
        self._center = rect.center()
        half = min(rect.width(), rect.height()) / 2 - 8
        radius_opt = self.opt.get("radius") or ["15%", "90%"]
        self._r0 = _clamp(
            _parse_pct(
                radius_opt[0] if len(radius_opt) > 0 else "15%", half, half * 0.15
            ),
            0.0,
            half,
        )
        self._r1 = _clamp(
            _parse_pct(
                radius_opt[1] if len(radius_opt) > 1 else "90%", half, half * 0.9
            ),
            self._r0 + 6.0,
            half,
        )
        total = sum(r.value for r in self._roots) or 1.0
        acc = 0.0
        for root in self._roots:
            span = root.value / total * 360.0
            self._assign_angles(root, acc, acc + span, 0)
            acc += span

        def collect(node, path=()):
            node.style_index = len(self._nodes)
            node.path = path
            self._nodes.append(node)
            for child_index, child in enumerate(node.children):
                collect(child, path + (child_index,))

        for root_index, root in enumerate(self._roots):
            collect(root, prefix + (root_index,))

    def _depth_of(self, node):
        if not node.children:
            return node.depth
        return max(self._depth_of(c) for c in node.children)

    def _assign_angles(self, node, a0, a1, level):
        node.a0, node.a1, node.level = a0, a1, level
        total = sum(c.value for c in node.children)
        if total <= 0:
            return
        acc = a0
        for c in node.children:
            span = (a1 - a0) * c.value / total
            self._assign_angles(c, acc, acc + span, level + 1)
            acc += span

    def _ring(self, level):
        """层号 → (内半径, 外半径)。"""
        band = (self._r1 - self._r0) / max(1, self._max_depth + 1)
        return self._r0 + band * level, self._r0 + band * (level + 1)

    def _pt(self, a_deg, r):
        rad = math.radians(a_deg)
        return QPointF(
            self._center.x() + r * math.sin(rad), self._center.y() - r * math.cos(rad)
        )

    def paint(self, p: QPainter, anim_t: float) -> None:
        if not self._nodes:
            return
        p.save()
        border = QColor(T("color.bg.base"))
        hover = self.chart.hoverInfo()
        hovered = (
            hover[1].get("dataIndex")
            if hover is not None and hover[0] is self
            else None
        )
        for node in self._nodes:
            span = (node.a1 - node.a0) * anim_t
            if span <= 0.05:
                continue
            r0, r1 = self._ring(node.level)
            rect_out = QRectF(
                self._center.x() - r1, self._center.y() - r1, 2 * r1, 2 * r1
            )
            rect_in = QRectF(
                self._center.x() - r0, self._center.y() - r0, 2 * r0, 2 * r0
            )
            qt_start = 90.0 - node.a0
            qt_span = -span
            path = QPainterPath()
            path.arcMoveTo(rect_out, qt_start)
            path.arcTo(rect_out, qt_start, qt_span)
            if r0 > 0.5:
                path.arcTo(rect_in, qt_start + qt_span, -qt_span)
            else:
                path.lineTo(self._center)
            path.closeSubpath()
            color = parse_color(self.itemColor(node.style_index, default=node.color))
            alpha = self.itemOpacity(node.style_index)
            border_color, border_w = self.itemBorder(node.style_index)
            if hovered is not None:
                if node.style_index == hovered:
                    emphasis = self.emphasisColor(node.style_index)
                    color = emphasis if emphasis is not None else color.lighter(112)
                elif self.blursOtherItems():
                    blur = self.blurOpacity()
                    alpha *= blur if blur is not None else 0.35
            if alpha < 1.0:
                color.setAlphaF(color.alphaF() * alpha)
            p.setPen(QPen(border_color or border, border_w if border_w > 0 else 1.0))
            p.setBrush(color)
            p.drawPath(path)
        self._paint_labels(p, anim_t)
        p.restore()

    def onMousePress(self, pos: QPointF) -> bool:
        """下钻交互：点击有子级扇区进入；点击中心孔返回上级。"""
        center_dist = math.hypot(pos.x() - self._center.x(), pos.y() - self._center.y())
        if center_dist <= max(2.0, self._r0) and self._focus_path:
            self._focus_path.pop()
            self.chart.invalidateLayout()
            self.chart.update()
            return True
        hit = self.hitTest(pos)
        if hit is None:
            return False
        index = hit.get("dataIndex")
        if not isinstance(index, int) or not (0 <= index < len(self._nodes)):
            return False
        node = self._nodes[index]
        if not node.children:
            return False
        self._focus_path = list(node.path)
        self.chart.invalidateLayout()
        self.chart.update()
        return True

    def resetDrill(self) -> None:
        """返回顶层（ECharts sunburst 的返回根节点）。"""
        if self._focus_path:
            self._focus_path = []
            self.chart.invalidateLayout()
            self.chart.update()

    def _paint_labels(self, p, anim_t):
        label_opt = dict(self.opt.get("label") or {})
        if not bool(label_opt.get("show", True)):
            return
        min_angle = _to_float(label_opt.get("minAngle"), 8.0)
        c_label = self.labelColor(QColor(ON_FILL_WHITE))
        font = _label_font(self, label_opt)
        p.setFont(font)
        fm = QFontMetricsF(font)
        for node in self._nodes:
            if not node.name:
                continue
            span = (node.a1 - node.a0) * anim_t
            if span < min_angle:
                continue  # 角区过小省略标签
            r0, r1 = self._ring(node.level)
            mid = node.a0 + span / 2
            rm = (r0 + r1) / 2
            pt = self._pt(mid, rm)
            # 沿角度旋转标签；左半圈翻转防倒置
            deg = mid % 360.0
            flip = 90.0 < deg < 270.0
            p.save()
            p.translate(pt)
            p.rotate(deg + (180.0 if flip else 0.0))
            p.setPen(c_label)
            band_w = math.radians(span) * rm
            text = node.name
            tw = fm.horizontalAdvance(text)
            if tw <= max(band_w - 4, 12) or span >= 30:
                p.drawText(
                    QRectF(-tw / 2, -fm.height() / 2, tw + 2, fm.height()),
                    Qt.AlignmentFlag.AlignCenter,
                    text,
                )
            p.restore()

    def hitTest(self, pos: QPointF):
        if self._anim_t < 1.0:
            # 扫掠角按 anim_t 展开：终态扇区位置此刻还没画出来。
            return None
        if not self._nodes:
            return None
        dx = pos.x() - self._center.x()
        dy = pos.y() - self._center.y()
        r = math.hypot(dx, dy)
        a = math.degrees(math.atan2(dx, -dy)) % 360.0
        best = None
        for node in self._nodes:
            # 整圆特判见 ``PieSeriesRenderer.hitTest``（根因完全相同）
            a0 = float(node.a0) % 360.0
            a1 = float(node.a1) % 360.0
            if float(node.a1) - float(node.a0) >= 360.0:
                in_angle = True
            elif a0 <= a1:
                in_angle = a0 <= a < a1
            else:
                in_angle = a >= a0 or a < a1
            if not in_angle:
                continue
            r0, r1 = self._ring(node.level)
            if r0 - 1 <= r <= r1 + 1:
                if best is None or node.level > best.level:
                    best = node
        if best is None:
            return None
        return {
            "name": best.name,
            "value": best.value,
            "series": self.name,
            "depth": best.level,
            "dataIndex": getattr(best, "style_index", None),
        }
