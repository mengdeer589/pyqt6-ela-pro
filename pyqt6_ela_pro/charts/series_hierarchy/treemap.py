"""矩形树图系列。（``pyqt6_ela_pro.charts`` 内部模块）。"""

from __future__ import annotations


from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QColor,
    QFontMetricsF,
    QPainter,
    QPen,
)

from .._tokens import T
from .._utils import ON_FILL_WHITE, clamp as _clamp
from .._utils import to_float as _to_float
from .._utils import with_alpha
from .._utils import parse_color
from ..core import SeriesRenderer
from ._shared import (
    _assign_branch_colors,
    _build_hierarchy,
    _label_font,
    _squarify,
    _text_color,
)


class TreemapSeriesRenderer(SeriesRenderer):
    """矩形树图（squarified 布局，父子分层渲染）。

    支持 ``data`` / ``breadcrumb`` / ``label`` / ``gapWidth``；点击父块下钻，
    点击空白 / 面包屑返回上级（``resetDrill()`` 回顶层）。
    """

    def __init__(self, chart, opt):
        super().__init__(chart, opt)
        self._nodes = []  # 所有可见节点（父先子后，绘制时子覆盖父）
        self._crumb = ""
        self._crumb_y = 2.0
        #: 下钻路径（子级下标序列；空 = 顶层）
        self._focus_path = []

    def layout(self, rect: QRectF) -> None:
        self._nodes = []
        roots = _build_hierarchy(self.data())
        if not roots:
            self._crumb = ""
            return
        _assign_branch_colors(self.chart, roots)
        # 下钻：按路径解析当前显示层级（路径失效时回到顶层）
        display = roots
        focus_names = []
        prefix: tuple = ()
        for idx in list(self._focus_path):
            if 0 <= idx < len(display):
                focus_names.append(display[idx].name)
                prefix = prefix + (idx,)
                display = display[idx].children
            else:
                self._focus_path = []
                focus_names = []
                prefix = ()
                display = roots
                break
        crumb_opt = dict(self.opt.get("breadcrumb") or {})
        # ECharts 默认显示面包屑；顶部预留条带避免与内容重叠
        self._crumb_show = bool(crumb_opt.get("show", True))
        top_pad = 22.0 if self._crumb_show else 0.0
        area = QRectF(
            rect.left() + 2,
            rect.top() + top_pad + 2,
            max(4.0, rect.width() - 4),
            max(4.0, rect.height() - top_pad - 4),
        )
        self._crumb = " / ".join(r.name for r in roots if r.name)
        self._crumb_y = rect.top() + 3
        gap = _clamp(_to_float(self.opt.get("gapWidth"), 1.0), 0.0, 8.0)
        order = [0]

        def lay(node, r, path=()):
            node.rect = r
            node.style_index = order[0]
            node.path = path
            order[0] += 1
            self._nodes.append(node)
            if not node.children or r.width() < 10 or r.height() < 10:
                return
            inner = QRectF(r).adjusted(1, 1, -1, -1)
            # 父容器：顶部预留 header 条带（ECharts 父子分层观感）
            header_h = 16.0 if r.height() > 34 else 0.0
            inner.setTop(inner.top() + header_h)
            if inner.width() < 6 or inner.height() < 6:
                return
            items = [(id(c), c.value) for c in node.children]
            rects = _squarify(items, inner)
            for child_index, c in enumerate(node.children):
                cr = rects.get(id(c))
                if cr is None:
                    continue
                lay(
                    c,
                    cr.adjusted(gap / 2, gap / 2, -gap / 2, -gap / 2),
                    path + (child_index,),
                )

        items = [(id(r_), r_.value) for r_ in display]
        rects = _squarify(items, area)
        for root_index, root in enumerate(display):
            rr = rects.get(id(root))
            if rr is None:
                continue
            lay(
                root,
                rr.adjusted(gap / 2, gap / 2, -gap / 2, -gap / 2),
                prefix + (root_index,),
            )
        self._crumb = " / ".join(focus_names) if focus_names else ""

    def onMousePress(self, pos: QPointF) -> bool:
        """下钻交互：点击父块进入；点击空白 / 面包屑返回上级。"""
        hit = self.hitTest(pos)
        if hit is None:
            if self._focus_path:
                self._focus_path.pop()
                self.chart.invalidateLayout()
                self.chart.update()
                return True
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
        """返回顶层。"""
        if self._focus_path:
            self._focus_path = []
            self.chart.invalidateLayout()
            self.chart.update()

    def paint(self, p: QPainter, anim_t: float) -> None:
        if not self._nodes:
            return
        p.save()
        label_opt = dict(self.opt.get("label") or {})
        label_show = bool(label_opt.get("show", True))
        c_label = self.labelTextStyle().get("color")
        c_label = parse_color(c_label) if isinstance(c_label, str) and c_label else None
        font = _label_font(self, label_opt)
        p.setFont(font)
        fm = QFontMetricsF(font)
        border = QColor(T("color.bg.base"))
        hover = self.chart.hoverInfo()
        hovered = (
            hover[1].get("dataIndex")
            if hover is not None and hover[0] is self
            else None
        )
        for node in self._nodes:
            r = node.rect
            if r.width() <= 0.5 or r.height() <= 0.5:
                continue
            color = parse_color(self.itemColor(node.style_index, default=node.color))
            alpha = self.itemOpacity(node.style_index)
            if hovered is not None:
                if node.style_index == hovered:
                    color = color.lighter(112)
                elif self.blursOtherItems():
                    # 只在 emphasis.focus == "self" 时淡化其余项
                    alpha *= 0.35
            color = with_alpha(color, int((60 + 195 * anim_t) * alpha))
            border_color, border_w = self.itemBorder(node.style_index)
            p.setPen(QPen(border_color or border, border_w or 1.0))
            p.setBrush(color)
            p.drawRect(r)
            if not label_show or not node.name:
                continue
            is_parent = bool(node.children)
            if is_parent:
                # 父级标签画在 header 区（顶部）
                if r.height() < 20:
                    continue
                p.setPen(c_label or QColor(ON_FILL_WHITE))
                p.drawText(
                    QRectF(r.left() + 4, r.top() + 1, r.width() - 8, 15),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    node.name,
                )
                continue
            if (
                r.width() < fm.horizontalAdvance(node.name) * 0.9
                or r.height() < fm.height() + 2
            ):
                continue  # 矩形过小省略标签
            p.setPen(c_label or with_alpha(QColor(ON_FILL_WHITE), 230))
            p.drawText(
                QRectF(r.left() + 3, r.top() + 1, r.width() - 6, fm.height()),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                node.name,
            )
        # 顶部面包屑（默认显示，drill 后为当前焦点路径）
        if getattr(self, "_crumb_show", False) and self._crumb:
            p.setFont(font)
            p.setPen(_text_color("color.text.secondary"))
            p.drawText(
                QRectF(
                    6,
                    self._crumb_y,
                    max(20.0, self.chart.width() - 12),
                    fm.height() + 2,
                ),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                self._crumb,
            )
        p.restore()

    def hitTest(self, pos: QPointF):
        best = None
        for node in self._nodes:
            if node.rect.contains(pos):
                if best is None or node.depth > best.depth:
                    best = node
        if best is None:
            return None
        return {
            "name": best.name,
            "value": best.value,
            "series": self.name,
            "depth": best.depth,
            "dataIndex": getattr(best, "style_index", None),
        }
