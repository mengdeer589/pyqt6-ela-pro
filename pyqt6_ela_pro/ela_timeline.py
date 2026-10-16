"""
时间线组件，风格参考 ElaWidgetTools 的 ElaTimeline。

垂直 / 水平两种排布，包含时间戳、标题、正文和可选图标。

用法::

    timeline = ElaTimeline(parent=self)
    timeline.addItem(ElaTimeline.TimelineItem(
        title="事件", content="描述", timestamp="2024-01-01",
    ))
    timeline.setOrientation("horizontal")
"""

from __future__ import annotations

from typing import Literal, Optional

from PyQt6.QtCore import Qt, QRect, QSize, QRectF, QPointF
from PyQt6.QtGui import QPainter, QPen, QFont, QFontMetrics, QPaintEvent
from PyQt6.QtWidgets import QWidget

from PyQt6ElaWidgetTools import eTheme, ElaThemeType, ElaIconType

from ._styles import iconGlyph
from .widget_base import ElaThemeWidget

ElaTimelineOrientation = Literal["vertical", "horizontal"]

#: ``sizeHint`` 的固定宽度（paintEvent 按真实宽度测，二者公式一致）
_DEFAULT_WIDTH = 400
#: 项间距（垂直排布）
_ITEM_GAP = 8
#: 无图标 / 有图标的节点直径
_CD = 12
_ICD = 24

#: 垂直排布：时间戳在左，节点成列，标题 / 正文在右
_V_LEFT_MARGIN = 80
_V_CONTENT_X = 100
_V_RIGHT_PAD = 20
_V_MIN_ITEM_H = 60

#: 水平排布：节点沿水平线等分，时间戳在上，标题 / 正文在下
_H_EDGE = 20
_H_TS_H = 18
_H_LINE_GAP = 8
_H_PAD_BOTTOM = 12


class ElaTimeline(ElaThemeWidget):
    """时间线组件。"""

    class TimelineItem:
        def __init__(
            self,
            title: str = "",
            content: str = "",
            timestamp: str = "",
            icon: ElaIconType.IconName = ElaIconType.IconName.None_,
        ):
            self.title = title
            self.content = content
            self.timestamp = timestamp
            self.icon = icon

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self._items: list[ElaTimeline.TimelineItem] = []
        self._current_step = 0
        self._orientation: ElaTimelineOrientation = "vertical"
        self.setObjectName("ElaTimeline")
        self._icon_font = QFont("ElaAwesome")

    # ── Public API ───────────────────────────────────────

    def addItem(self, item: TimelineItem) -> None:
        self._items.append(item)
        self.updateGeometry()
        self.update()

    def clearItems(self) -> None:
        self._items.clear()
        self.updateGeometry()
        self.update()

    def itemCount(self) -> int:
        return len(self._items)

    def setOrientation(self, orientation: ElaTimelineOrientation) -> None:
        """切换排布方向（``"vertical"`` / ``"horizontal"``，非法值抛 ``ValueError``）。"""
        if orientation not in ("vertical", "horizontal"):
            raise ValueError(f"Invalid orientation: {orientation!r}")
        self._orientation = orientation
        self.updateGeometry()
        self.update()

    def orientation(self) -> str:
        return self._orientation

    def setCurrentStep(self, index: int) -> None:
        self._current_step = max(0, min(index, len(self._items) - 1))
        self.update()

    def currentStep(self) -> int:
        return self._current_step

    # ── Internal ─────────────────────────────────────────

    def _onThemeChanged(self, mode: ElaThemeType.ThemeMode) -> None:
        self._theme_mode = mode
        self.update()

    def _title_font(self) -> QFont:
        font = self.font()
        font.setPixelSize(14)
        font.setBold(True)
        return font

    def _content_font(self) -> QFont:
        font = self.font()
        font.setPixelSize(13)
        return font

    def _layout_vertical(self, width: int) -> tuple[list[tuple[int, int, int]], int]:
        """垂直排布测量：``[(行顶 y, 标题高, 正文高), ...]`` 与总高。

        ``paintEvent`` 与 ``sizeHint`` 共用（宽度不同、公式一致）。
        """
        title_fm = QFontMetrics(self._title_font())
        content_fm = QFontMetrics(self._content_font())
        content_w = max(0, width - _V_CONTENT_X - _V_RIGHT_PAD)
        rows: list[tuple[int, int, int]] = []
        y = 0
        for item in self._items:
            th = title_fm.height()
            cth = 0
            if item.content:
                cth = content_fm.boundingRect(
                    QRect(0, 0, content_w, 10000),
                    Qt.TextFlag.TextWordWrap,
                    item.content,
                ).height()
            ih = max(_V_MIN_ITEM_H, th + (4 + cth if cth else 0) + 10)
            rows.append((y, th, cth))
            y += ih + _ITEM_GAP
        return rows, y

    def _layout_horizontal(
        self, width: int
    ) -> tuple[list[tuple[float, float, int, int, bool]], float, float, float]:
        """水平排布测量：``([(列左 x, 列宽, 标题高, 正文高, 有图标), ...], 中线 y, 最大节点半径, 总高)``。"""
        count = len(self._items)
        title_fm = QFontMetrics(self._title_font())
        content_fm = QFontMetrics(self._content_font())
        usable = max(0, width - 2 * _H_EDGE)
        col_w = usable / count if count else 0.0
        rows: list[tuple[float, float, int, int, bool]] = []
        max_r = 0.0
        body_h = 0
        for i, item in enumerate(self._items):
            inner_w = max(0.0, col_w - 12)
            th = title_fm.height()
            cth = 0
            if item.content:
                cth = content_fm.boundingRect(
                    QRect(0, 0, int(inner_w), 10000),
                    Qt.TextFlag.TextWordWrap,
                    item.content,
                ).height()
            has_icon = item.icon != ElaIconType.IconName.None_
            rows.append((_H_EDGE + i * col_w, col_w, th, cth, has_icon))
            max_r = max(max_r, _ICD / 2 if has_icon else _CD / 2)
            body_h = max(body_h, th + (4 + cth if cth else 0))
        line_y = _H_TS_H + max_r
        total = line_y + max_r + _H_LINE_GAP + body_h + _H_PAD_BOTTOM
        return rows, line_y, max_r, total

    # ── Paint ────────────────────────────────────────────

    def paintEvent(self, _event: QPaintEvent) -> None:
        if not self._items:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        mode = self._theme_mode
        primary = eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.PrimaryNormal)
        border = eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.BasicBorder)
        text = eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.BasicText)
        details = eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.BasicDetailsText)

        if self._orientation == "horizontal":
            self._paint_horizontal(painter, primary, border, text, details)
        else:
            self._paint_vertical(painter, primary, border, text, details)

    def _draw_node(
        self,
        painter: QPainter,
        item: TimelineItem,
        i: int,
        cx: float,
        cy: float,
        primary,
        border,
    ) -> None:
        """绘制单个节点（当前步用强调色，其余描边色；有图标时画图标）。"""
        has_icon = item.icon != ElaIconType.IconName.None_
        r = _ICD / 2 if has_icon else _CD / 2
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(primary if i == self._current_step else border)
        rect = QRectF(cx - r, cy - r, r * 2, r * 2)
        painter.drawEllipse(rect)
        if has_icon:
            self._icon_font.setPixelSize(12)
            painter.setFont(self._icon_font)
            painter.setPen(Qt.GlobalColor.white)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, iconGlyph(item.icon))

    def _paint_vertical(
        self, painter: QPainter, primary, border, text, details
    ) -> None:
        rows, _ = self._layout_vertical(self.width())
        cr = _CD // 2
        icr = _ICD // 2
        line_x = _V_LEFT_MARGIN + cr
        content_w = max(0, self.width() - _V_CONTENT_X - _V_RIGHT_PAD)
        title_font = self._title_font()
        content_font = self._content_font()

        for i, item in enumerate(self._items):
            cy, th, cth = rows[i]
            has_icon = item.icon != ElaIconType.IconName.None_
            cur_cr = icr if has_icon else cr
            cc_y = cy + cur_cr

            # 时间戳
            ts_font = self.font()
            ts_font.setPixelSize(12)
            painter.setFont(ts_font)
            painter.setPen(details)
            painter.drawText(
                QRect(
                    0,
                    cc_y - ts_font.pixelSize() // 2,
                    _V_LEFT_MARGIN - 10,
                    ts_font.pixelSize(),
                ),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                item.timestamp,
            )

            # 节点
            self._draw_node(painter, item, i, line_x, cc_y, primary, border)

            # 连接线
            if i < len(self._items) - 1:
                painter.setPen(QPen(border, 1))
                painter.drawLine(
                    QPointF(line_x, cc_y + cur_cr),
                    QPointF(line_x, rows[i + 1][0]),
                )

            painter.setFont(title_font)
            painter.setPen(text)
            painter.drawText(
                QRect(_V_CONTENT_X, cy, int(content_w), th),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                item.title,
            )

            # 正文
            if item.content:
                painter.setFont(content_font)
                painter.setPen(details)
                painter.drawText(
                    QRect(_V_CONTENT_X, cy + th + 4, int(content_w), cth),
                    Qt.TextFlag.TextWordWrap
                    | Qt.AlignmentFlag.AlignLeft
                    | Qt.AlignmentFlag.AlignTop,
                    item.content,
                )

    def _paint_horizontal(
        self, painter: QPainter, primary, border, text, details
    ) -> None:
        rows, line_y, max_r, _ = self._layout_horizontal(self.width())
        if not rows:
            return
        title_font = self._title_font()
        content_font = self._content_font()
        title_fm = QFontMetrics(title_font)
        ts_font = self.font()
        ts_font.setPixelSize(12)

        # 连接线（从首节点中心到末节点中心，画在节点层之下）
        if len(rows) > 1:
            first_cx = rows[0][0] + rows[0][1] / 2
            last_cx = rows[-1][0] + rows[-1][1] / 2
            painter.setPen(QPen(border, 1))
            painter.drawLine(QPointF(first_cx, line_y), QPointF(last_cx, line_y))

        body_y = line_y + max_r + _H_LINE_GAP
        for i, item in enumerate(self._items):
            col_x, col_w, th, cth, _ = rows[i]
            cx = col_x + col_w / 2
            inner_w = max(0.0, col_w - 8)

            # 时间戳（节点上方）
            painter.setFont(ts_font)
            painter.setPen(details)
            painter.drawText(
                QRectF(col_x, 0, col_w, _H_TS_H),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                item.timestamp,
            )

            # 节点
            self._draw_node(painter, item, i, cx, line_y, primary, border)

            # 标题 / 正文（节点下方）
            painter.setFont(title_font)
            painter.setPen(text)
            painter.drawText(
                QRectF(col_x + 4, body_y, inner_w, th),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                title_fm.elidedText(
                    item.title, Qt.TextElideMode.ElideRight, int(inner_w)
                ),
            )
            if item.content:
                painter.setFont(content_font)
                painter.setPen(details)
                painter.drawText(
                    QRectF(col_x + 4, body_y + th + 4, inner_w, cth),
                    Qt.TextFlag.TextWordWrap
                    | Qt.AlignmentFlag.AlignHCenter
                    | Qt.AlignmentFlag.AlignTop,
                    item.content,
                )

    def sizeHint(self) -> QSize:
        if not self._items:
            return QSize(_DEFAULT_WIDTH, 0)
        if self._orientation == "horizontal":
            _, _, _, total = self._layout_horizontal(_DEFAULT_WIDTH)
        else:
            _, total = self._layout_vertical(_DEFAULT_WIDTH)
        return QSize(_DEFAULT_WIDTH, int(total))
