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
from .._utils import to_float as _to_float
from ..core import SeriesRenderer
from ._shared import (
    _assign_branch_colors,
    _build_hierarchy,
    _dist,
    _label_font,
    _text_color,
)


class TreeSeriesRenderer(SeriesRenderer):
    """树图（按层级布局）。

    支持 ``data`` / ``orient``（"LR" / "TB"）/ ``edgeShape``（"polyline" /
    "curve"）/ ``label`` / ``symbolSize``。
    """

    def __init__(self, chart, opt):
        super().__init__(chart, opt)
        self._nodes = []  # [(node, QPointF)]
        self._edges = []  # [(QPointF parent, QPointF child)]

    def layout(self, rect: QRectF) -> None:
        self._nodes = []
        self._edges = []
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
            fy = node.y / span_y if span_y else 0.5
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

        def collect(node):
            pt = to_px(node)
            pos[id(node)] = pt
            self._nodes.append((node, pt))
            for c in node.children:
                collect(c)
                self._edges.append((pt, pos[id(c)]))

        for root in roots:
            collect(root)

    def paint(self, p: QPainter, anim_t: float) -> None:
        if not self._nodes:
            return
        p.save()
        orient = str(self.opt.get("orient") or "LR").upper()
        edge = str(self.opt.get("edgeShape") or "polyline")
        c_line = _text_color("color.border.strong")
        pen = QPen(c_line, 1.2)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        # 边按 anim_t 逐层显现：以父→子中点裁剪
        for p0, p1 in self._edges:
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
        c_label = self.labelColor(_text_color("color.text.primary"))
        font = _label_font(self, label_opt)
        p.setFont(font)
        fm = QFontMetricsF(font)
        size = _to_float(self.opt.get("symbolSize"), 8.0)
        for node, pt in self._nodes:
            p.setPen(QPen(QColor(T("color.bg.elevated")), 1.5))
            p.setBrush(node.color or self.color())
            p.drawEllipse(pt, size / 2, size / 2)
            if not label_show or not node.name:
                continue
            p.setPen(c_label)
            tw = fm.horizontalAdvance(node.name)
            if orient == "TB":
                p.drawText(
                    QRectF(pt.x() - tw / 2, pt.y() + size / 2 + 2, tw + 4, fm.height()),
                    Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                    node.name,
                )
            else:
                is_leaf = not node.children
                if is_leaf:
                    p.drawText(
                        QRectF(
                            pt.x() + size / 2 + 3,
                            pt.y() - fm.height() / 2,
                            tw + 4,
                            fm.height(),
                        ),
                        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                        node.name,
                    )
                else:
                    p.drawText(
                        QRectF(
                            pt.x() - tw - size / 2 - 3,
                            pt.y() - fm.height() / 2,
                            tw + 4,
                            fm.height(),
                        ),
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                        node.name,
                    )
        p.restore()

    def hitTest(self, pos: QPointF):
        best = None
        best_d = 12.0
        for node, pt in self._nodes:
            d = _dist(pos, pt)
            if d <= best_d:
                best_d = d
                best = node
        if best is None:
            return None
        return {
            "name": best.name,
            "value": best.value,
            "series": self.name,
            "depth": int(best.x),
        }
