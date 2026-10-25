"""图例组件（含分页与悬停高亮）。（``pyqt6_ela_pro.charts`` 内部模块）。"""

from __future__ import annotations

from typing import TYPE_CHECKING


from PyQt6.QtCore import (
    QPointF,
    QRectF,
    Qt,
)
from PyQt6.QtGui import (
    QColor,
    QFontMetricsF,
    QPainter,
)

from .._tokens import (
    T,
)
from .._utils import merged_text_style, parse_color, text_italic, text_weight
from ..axes import (
    chartFont,
)
from ._shared import _opt_float

if TYPE_CHECKING:
    from .widget import ElaChartWidget


class Legend:
    """图例组件（ECharts ``legend``）。

    option：``show`` / ``orient`` / ``top|bottom|left|right`` / ``data``
    （条目白名单与排序）/ ``selected``（{name: bool} 初始显隐）/ ``itemWidth`` /
    ``itemHeight`` / ``itemGap`` / ``textStyle`` / ``selectedMode``
    （``"multiple"`` 默认 / ``"single"``）。条目由 ElaChartWidget 按系列名
    注入（``setItems([(name, color), ...])``，color 仅为兜底值）——绘制时
    色块经 chart 实时取系列当前色，主题切换后无需重建即生效。
    横向条目超过 ``maxRows``（默认 3）自动分页；``type: "scroll"`` 强制单行
    分页（‹ › + 页码），多个系列不再溢出绘图区。
    """

    #: 条目点击回调：chart 注入 ``legend.on_toggle = chart._legendSelectToggle``
    on_toggle = None

    def __init__(self, chart: "ElaChartWidget", opt: dict = None):
        self.chart = chart
        self.opt = {"show": True, "orient": "horizontal"}
        self.setOption(opt)
        self._items = []  # [(name, QColor)]（已按 legend.data 过滤排序）
        self._all_items = []  # [(name, QColor)]（未过滤）
        self._item_rects = []  # [QRectF] 与 _page_items 对齐
        self._page_items = []  # 当前页的 [(name, color)]
        self._page = 0
        self._page_count = 1
        self._paginate = False
        self._page_rects = []  # [QRectF]（上一页 / 下一页）
        self.rect = QRectF()
        self.on_toggle = getattr(chart, "_legendSelectToggle", None)

    def setOption(self, opt: dict) -> None:
        if isinstance(opt, dict):
            merged = {"show": True, "orient": "horizontal"}
            merged.update(opt)
            self.opt = merged
        else:
            self.opt = {"show": True, "orient": "horizontal"}

    def setItems(self, items: list) -> None:
        self._all_items = [(str(n), c) for n, c in (items or []) if str(n)]
        data = self.opt.get("data")
        if isinstance(data, list) and data:
            wanted = [str(n) for n in data]
            by_name = dict(self._all_items)
            self._items = [(n, by_name[n]) for n in wanted if n in by_name]
        else:
            self._items = list(self._all_items)

    # -- option 取值 -------------------------------------------------------
    def itemWidth(self) -> float:
        try:
            return max(2.0, float(self.opt.get("itemWidth", 9)))
        except (TypeError, ValueError, OverflowError):
            return 9.0

    def itemHeight(self) -> float:
        try:
            return max(2.0, float(self.opt.get("itemHeight", 9)))
        except (TypeError, ValueError, OverflowError):
            return 9.0

    def itemGap(self) -> float:
        try:
            return max(2.0, float(self.opt.get("itemGap", 10)))
        except (TypeError, ValueError, OverflowError):
            return 10.0

    def textStyle(self) -> dict:
        """图例文字样式（组件级优先，未设置的键回退顶层 ``textStyle``）。"""
        return merged_text_style(self.chart, self.opt.get("textStyle"))

    def _font(self):
        style = self.textStyle()
        size = _opt_float(style.get("fontSize"), T("font.xs"))
        return chartFont(
            size,
            text_weight(style.get("fontWeight")),
            style.get("fontFamily"),
            text_italic(style.get("fontStyle")),
        )

    def selectedMode(self) -> str:
        mode = str(self.opt.get("selectedMode") or "multiple")
        return "single" if mode == "single" else "multiple"

    def _item_color(self, name: str):
        """条目实时色：按系列名从 chart 当前渲染器取色（主题感知），
        找不到渲染器时返回 None（调用方退回 setItems 的兜底色）。"""
        for r in self.chart.seriesRenderers:
            if r.name == name:
                return r.color()
        return None

    @property
    def shown(self) -> bool:
        return bool(self.opt.get("show", True)) and bool(self._items)

    @property
    def orient(self) -> str:
        return "vertical" if str(self.opt.get("orient")) == "vertical" else "horizontal"

    # -- 布局 -------------------------------------------------------------
    def _entry(self, name: str):
        """单条目的 (宽, 高) 与字体。"""
        font = self._font()
        fm = QFontMetricsF(font)
        iw, ih = self.itemWidth(), self.itemHeight()
        h = max(18.0, fm.height() + 6, ih + 6)
        w = iw + 6 + fm.horizontalAdvance(name) + self.itemGap()
        return w, h

    def _entry_height(self) -> float:
        fm = QFontMetricsF(self._font())
        return max(18.0, fm.height() + 6, self.itemHeight() + 6)

    def _max_rows(self) -> int:
        try:
            return max(1, int(self.opt.get("maxRows", 3) or 3))
        except (TypeError, ValueError, OverflowError):
            return 3

    def _scroll_type(self) -> bool:
        return str(self.opt.get("type") or "").strip().lower() == "scroll"

    def _wrap_rows(self, width: float) -> list:
        """条目按可用宽度换行 → ``[[(name, color), ...], ...]``。"""
        avail = max(40.0, float(width) - 8.0)
        rows = []
        row = []
        row_w = 0.0
        for item in self._items:
            w, _ = self._entry(item[0])
            if row and row_w + w > avail:
                rows.append(row)
                row = []
                row_w = 0.0
            row.append(item)
            row_w += w
        if row:
            rows.append(row)
        return rows

    def preferredSize(self, avail_w: float, avail_h: float):
        """按可用空间返回 (w, h)：横向按换行 / 分页后的行数，纵向为列宽。"""
        if not self.shown:
            return 0.0, 0.0
        if self.orient != "horizontal":
            w = max((self._entry(n)[0] for n, _ in self._items), default=0.0)
            return w, avail_h
        entry_h = self._entry_height()
        rows = self._wrap_rows(avail_w)
        max_rows = self._max_rows()
        paginate = self._scroll_type() or len(rows) > max_rows
        rows_per_page = 1 if self._scroll_type() else max_rows
        visible = rows_per_page if paginate else len(rows)
        return avail_w, visible * entry_h + max(0, visible - 1) * 2 + 4

    def layout(self, rect: QRectF) -> None:
        """在已分配条带内排布（横向换行 / 分页，纵向顶对齐）。"""
        self.rect = QRectF(rect)
        self._item_rects = []
        self._page_items = []
        self._page_rects = []
        if not self.shown or rect.isNull():
            return
        gap = self.itemGap()
        entry_h = self._entry_height()
        if self.orient != "horizontal":
            x = rect.left() + 4
            y = rect.top() + 4
            self._page_items = list(self._items)
            for name, _ in self._page_items:
                w, _ = self._entry(name)
                self._item_rects.append(QRectF(x, y, w - gap, entry_h))
                y += entry_h + 2
            self._paginate = False
            self._page_count = 1
            return

        rows = self._wrap_rows(rect.width())
        max_rows = self._max_rows()
        rows_per_page = 1 if self._scroll_type() else max_rows
        pages = [
            rows[i : i + rows_per_page] for i in range(0, len(rows), rows_per_page)
        ] or [[]]
        self._page_count = max(1, len(pages))
        self._paginate = self._scroll_type() or len(rows) > max_rows
        if self._paginate and self._page_count <= 1:
            self._paginate = False
        self._page = max(0, min(self._page, self._page_count - 1))
        page_rows = pages[self._page]
        self._page_items = [item for row in page_rows for item in row]

        usable_w = float(rect.width()) - (42.0 if self._paginate else 8.0)
        y = rect.top() + 2.0
        for row in page_rows:
            total = sum(self._entry(item[0])[0] for item in row) - gap
            x = rect.left() + 4.0 + max(0.0, (usable_w - total) / 2.0)
            for item in row:
                w, _ = self._entry(item[0])
                self._item_rects.append(QRectF(x, y, w - gap, entry_h))
                x += w
            y += entry_h + 2.0
        if self._paginate:
            cy = rect.center().y()
            self._page_rects = [
                QRectF(rect.right() - 38.0, cy - 8.0, 16.0, 16.0),
                QRectF(rect.right() - 18.0, cy - 8.0, 16.0, 16.0),
            ]

    # -- 交互 -------------------------------------------------------------
    def hitTest(self, pos: QPointF):
        """命中当前页的条目名或 None。"""
        for (name, _), r in zip(self._page_items, self._item_rects):
            if r.contains(pos):
                return name
        return None

    def pageHitTest(self, pos: QPointF) -> int:
        """分页按钮命中：``1`` 下一页 / ``-1`` 上一页 / ``0`` 无。"""
        if not self._paginate or len(self._page_rects) < 2:
            return 0
        if self._page_rects[0].adjusted(-2, -2, 2, 2).contains(pos):
            return -1
        if self._page_rects[1].adjusted(-2, -2, 2, 2).contains(pos):
            return 1
        return 0

    def setPage(self, delta: int) -> None:
        """翻页（保留布局条带，只重排图例条目）。"""
        if not self._paginate or not delta:
            return
        page = max(0, min(self._page + int(delta), self._page_count - 1))
        if page == self._page:
            return
        self._page = page
        self.layout(self.rect)
        self.chart.update()

    def toggle(self, name: str) -> None:
        if callable(self.on_toggle):
            self.on_toggle(name)

    # -- 绘制 -------------------------------------------------------------
    def paint(self, p: QPainter) -> None:
        if not self.shown or not self._item_rects:
            return
        p.save()
        font = self._font()
        p.setFont(font)
        style = self.textStyle()
        iw, ih = self.itemWidth(), self.itemHeight()
        for (name, fallback), r in zip(self._page_items, self._item_rects):
            enabled = self.chart._seriesVisible(name)
            live = self._item_color(name) if enabled else None
            swatch = parse_color(live) if live is not None else parse_color(fallback)
            if not enabled:
                swatch = QColor(T("color.text.disabled"))
            text_c = parse_color(
                style.get("color") or T("color.text.primary")
                if enabled
                else T("color.text.disabled")
            )
            # 悬停高亮：该条目文字转强调色（对齐 Plotly 图例 hover）
            if enabled and self.chart._legend_hover == name:
                text_c = QColor(T("color.primary"))
            # 色块（圆角小方块）
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(swatch)
            box = QRectF(r.left(), r.center().y() - ih / 2, iw, ih)
            p.drawRoundedRect(box, 2, 2)
            p.setPen(text_c)
            p.drawText(
                QRectF(box.right() + 6, r.top(), r.width() - iw - 6, r.height()),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                name,
            )
        if self._paginate and len(self._page_rects) == 2:
            p.setPen(QColor(T("color.text.secondary")))
            for rect, glyph in zip(self._page_rects, ("‹", "›")):
                p.drawText(rect, Qt.AlignmentFlag.AlignCenter, glyph)
            p.setFont(
                chartFont(max(9.0, T("font.xs") - 2), None, self.chart.fontFamily())
            )
            p.drawText(
                QRectF(
                    self._page_rects[0].left() - 30,
                    self._page_rects[0].top(),
                    28,
                    self._page_rects[0].height(),
                ),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                f"{self._page + 1}/{self._page_count}",
            )
        p.restore()
