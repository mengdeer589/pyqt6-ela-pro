"""树图系列。（``pyqt6_ela_pro.charts`` 内部模块）。"""

from __future__ import annotations


from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QColor,
    QFontMetricsF,
    QPainter,
    QPainterPath,
    QPen,
)

from .._tokens import T
from .._symbol import drawSymbol
from .._utils import to_float as _to_float
from .._utils import with_alpha
from .._utils import parse_roam as _parse_roam
from ..core import SeriesRenderer
from ._shared import (
    _assign_branch_colors,
    _build_hierarchy,
    _dist,
    _label_font,
    _node_border,
    _node_color,
    _node_opacity,
    _hierarchy_item_count,
    _hierarchy_name_at,
    _hierarchy_selected_seeds,
    _hierarchy_value,
    _text_color,
)


class TreeSeriesRenderer(SeriesRenderer):
    """树图（按层级布局）。
    支持 ``data`` / ``orient``（"LR" / "TB"）/ ``edgeShape``（"polyline" /
    "curve"）/ ``label`` / ``symbolSize``。
    """

    labelVisibleByDefault = True

    def __init__(self, chart, opt):
        super().__init__(chart, opt)
        self._nodes = []  # [(node, QPointF)]
        self._edges = []  # [(QPointF parent, QPointF child)]
        self._plot = QRectF()
        self._zoom = 1.0
        self._pan = QPointF()
        self._pan_start = None
        self._pan_origin = QPointF()
        self._roam = _parse_roam(self.opt.get("roam", False))
        self._expanded: set = set()
        self._expandable = self.opt.get("expandAndCollapse", True) is not False
        depth = self.opt.get("initialTreeDepth", 2)
        try:
            self._initial_depth = int(depth)
        except (TypeError, ValueError, OverflowError):
            self._initial_depth = 2

    def itemCount(self) -> int:
        return _hierarchy_item_count(self)

    def valueAtIndex(self, index: int):
        return _hierarchy_value(self, index)

    def nameAtIndex(self, index: int) -> str:
        return _hierarchy_name_at(self, index)

    def selectedSeedIndices(self) -> set:
        return _hierarchy_selected_seeds(self)

    def layout(self, rect: QRectF) -> None:
        self._nodes = []
        self._edges = []
        self._plot = QRectF(rect)
        roots = _build_hierarchy(self.data())
        if not roots:
            return
        _assign_branch_colors(self.chart, roots)
        # 逻辑布局：x = 深度，y = 叶子序号（内部节点取子级均值）
        leaf_counter = [0]

        def place(node, depth):
            node.x = float(depth)
            if not node.children:
                node.y = float(leaf_counter[0])
                leaf_counter[0] += 1
            else:
                for c in node.children:
                    place(c, depth + 1)
                node.y = sum(c.y for c in node.children) / len(node.children)

        for root in roots:
            place(root, 0)
        max_depth = 0
        leaf_total = max(1, leaf_counter[0])

        def walk(node):
            nonlocal max_depth
            max_depth = max(max_depth, int(node.x))
            for c in node.children:
                walk(c)

        for root in roots:
            walk(root)
        orient = str(self.opt.get("orient") or "LR").upper()
        pad = 36.0
        span_x = max(1, max_depth)
        span_y = max(1, leaf_total - 1)
        usable_w = max(10.0, rect.width() - pad * 2)
        usable_h = max(10.0, rect.height() - pad * 2)

        def to_px(node):
            fx = node.x / span_x if span_x else 0.5
            fy = 0.5 if leaf_total <= 1 else node.y / span_y
            if orient == "TB":
                return QPointF(
                    rect.left() + pad + fy * usable_w,
                    rect.top() + pad * 0.5 + fx * (usable_h - pad * 0.5),
                )
            return QPointF(
                rect.left() + pad + fx * (usable_w - pad * 0.5),
                rect.top() + pad + fy * (usable_h - pad),
            )

        pos = {}

        def collect(node, path=()):
            pt = to_px(node)
            pos[id(node)] = pt
            node.style_index = len(self._nodes)
            node.path = path
            self._nodes.append((node, pt))
            show_children = (
                not self._expandable
                or self._initial_depth < 0
                or node.depth < self._initial_depth
                or path in self._expanded
            )
            if not show_children:
                return
            for child_index, c in enumerate(node.children):
                collect(c, path + (child_index,))
                self._edges.append((pt, pos[id(c)]))

        for root in roots:
            collect(root)

    def _transform(self, pt: QPointF) -> QPointF:
        if self._zoom == 1.0 and self._pan.isNull():
            return QPointF(pt)
        c = self._plot.center()
        return QPointF(
            c.x() + (pt.x() - c.x()) * self._zoom + self._pan.x(),
            c.y() + (pt.y() - c.y()) * self._zoom + self._pan.y(),
        )

    def paint(self, p: QPainter, anim_t: float) -> None:
        if not self._nodes:
            return
        p.save()
        self._label_rects = []
        orient = str(self.opt.get("orient") or "LR").upper()
        edge = str(self.opt.get("edgeShape") or "polyline")
        c_line = _text_color("color.border.strong", self.chart)
        pen = QPen(c_line, 1.2)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        # 边按 anim_t 逐层显现：以父→子中点裁剪
        for p0, p1 in self._edges:
            p0 = self._transform(p0)
            p1 = self._transform(p1)
            q1 = QPointF(
                p0.x() + (p1.x() - p0.x()) * anim_t, p0.y() + (p1.y() - p0.y()) * anim_t
            )
            if edge == "curve":
                path = QPainterPath(p0)
                if orient == "TB":
                    my = (p0.y() + q1.y()) / 2
                    path.cubicTo(QPointF(p0.x(), my), QPointF(q1.x(), my), q1)
                else:
                    mx = (p0.x() + q1.x()) / 2
                    path.cubicTo(QPointF(mx, p0.y()), QPointF(mx, q1.y()), q1)
                p.drawPath(path)
            else:  # polyline 正交折线
                if orient == "TB":
                    mid = QPointF(q1.x(), p0.y())
                else:
                    mid = QPointF(p0.x(), q1.y())
                p.drawLine(p0, mid)
                p.drawLine(mid, q1)
        # 节点 + 标签
        label_opt = dict(self.opt.get("label") or {})
        label_show = bool(label_opt.get("show", True))
        c_label = self.labelColor()
        font = _label_font(self, label_opt)
        p.setFont(font)
        fm = QFontMetricsF(font)
        size = _to_float(self.opt.get("symbolSize"), 8.0)
        hover = self.chart.hoverInfo()
        hovered = (
            hover[1].get("dataIndex")
            if hover is not None and hover[0] is self
            else None
        )
        for node, raw_pt in self._nodes:
            pt = self._transform(raw_pt)
            color = _node_color(self, node)
            alpha = _node_opacity(self, node)
            border_color, border_w = _node_border(self, node)
            if border_color is None or border_w <= 0:
                border_color = QColor(T("color.bg.elevated", self.chart))
                border_w = 1.5
            color, alpha, border_color, border_w = self.stateStyle(
                node.style_index, hovered, color, alpha, border_color, border_w
            )
            p.setPen(QPen(border_color, border_w))
            p.setBrush(with_alpha(color, int(255 * alpha)))
            kind = "circle"
            if isinstance(getattr(node, "item", None), dict):
                kind = str(node.item.get("symbol") or "circle")
            kind = str(self.opt.get("symbol") or kind)
            drawSymbol(p, kind, pt, size)
            if not label_show or not node.name:
                continue
            text = self.hierarchyLabelText(
                node.style_index,
                node.name,
                getattr(node, "value", None),
                getattr(node, "item", None),
            )
            p.setPen(c_label)
            tw = fm.horizontalAdvance(text)
            if orient == "TB":
                rect = QRectF(
                    pt.x() - tw / 2, pt.y() + size / 2 + 2, tw + 4, fm.height()
                )
                hit = self.paintLabelIn(
                    p,
                    rect,
                    text,
                    index=node.style_index,
                    align=Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                    color=c_label,
                )
            else:
                is_leaf = not node.children
                if is_leaf:
                    rect = QRectF(
                        pt.x() + size / 2 + 3,
                        pt.y() - fm.height() / 2,
                        tw + 4,
                        fm.height(),
                    )
                    hit = self.paintLabelIn(
                        p,
                        rect,
                        text,
                        index=node.style_index,
                        align=Qt.AlignmentFlag.AlignLeft
                        | Qt.AlignmentFlag.AlignVCenter,
                        color=c_label,
                    )
                else:
                    rect = QRectF(
                        pt.x() - tw - size / 2 - 3,
                        pt.y() - fm.height() / 2,
                        tw + 4,
                        fm.height(),
                    )
                    hit = self.paintLabelIn(
                        p,
                        rect,
                        text,
                        index=node.style_index,
                        align=Qt.AlignmentFlag.AlignRight
                        | Qt.AlignmentFlag.AlignVCenter,
                        color=c_label,
                    )
            if not hit.isNull():
                self._label_rects.append((node.style_index, hit, text))
        p.restore()

    def onMousePress(self, pos: QPointF) -> bool:
        if self._expandable:
            for node, raw_pt in self._nodes:
                if _dist(pos, self._transform(raw_pt)) <= 12.0 and node.children:
                    path = tuple(getattr(node, "path", ()))
                    if path in self._expanded:
                        self._expanded.discard(path)
                    else:
                        self._expanded.add(path)
                    self.chart.invalidateLayout()
                    self.chart.update()
                    return True
        if self._roam[1] and not self._plot.isNull() and self._plot.contains(pos):
            self._pan_start = QPointF(pos)
            self._pan_origin = QPointF(self._pan)
            return True
        return False

    def onMouseMove(self, pos: QPointF) -> bool:
        if self._pan_start is not None:
            self._pan = self._pan_origin + (QPointF(pos) - self._pan_start)
            self.chart.invalidateLayout()
            self.chart.update()
            return True
        return False

    def onMouseRelease(self, pos: QPointF) -> bool:
        if self._pan_start is not None:
            self._pan_start = None
            return True
        return False

    def onWheel(self, event) -> bool:
        if not self._roam[0] or self._plot.isNull():
            return False
        try:
            pos = event.position()
        except Exception:
            pos = QPointF()
        if not self._plot.contains(pos):
            return False
        delta = event.angleDelta().y()
        if delta == 0:
            return False
        factor = 1.15 if delta > 0 else 1 / 1.15
        self._zoom = max(0.2, min(5.0, self._zoom * factor))
        self.chart.invalidateLayout()
        self.chart.update()
        return True

    def resetRoam(self) -> None:
        """复位 roam 缩放 / 平移。"""
        self._pan = QPointF()
        self._pan_start = None
        self._pan_origin = QPointF()
        self._zoom = 1.0
        self.chart.invalidateLayout()
        self.chart.update()

    def hitTest(self, pos: QPointF):
        best = None
        best_d = 12.0
        for node, raw_pt in self._nodes:
            d = _dist(pos, self._transform(raw_pt))
            if d <= best_d:
                best_d = d
                best = node
        if best is None:
            return None
        return {
            "name": best.name,
            "value": best.value,
            "color": _node_color(self, best),
            "series": self.name,
            "depth": int(best.x),
            "dataIndex": best.style_index,
        }
