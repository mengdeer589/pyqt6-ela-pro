"""独立运行轨迹面板：turn / step / tool / reasoning 的时间线列表。"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QFont, QPainter
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from PyQt6ElaWidgetTools import (
    ElaIconButton,
    ElaIconType,
    ElaScrollArea,
    ElaScrollBar,
    ElaThemeType,
)

from .._internal import is_deleted, safe_connect
from ._pricing import formatCost
from .._styles import ColorText, paintRoundedCard
from .._theme import ElaStatusRoleType, statusColor
from ..tooltips import ElaToolTipPositionType, remove_tooltip, set_tooltip
from ..ela_button import ElaButton
from ..widget_base import ElaThemeWidget
from ._theme import accent_color, base_color, blend, muted_color, text_color
from ._trace import ElaChatTraceResult, ElaChatTraceRow, buildTraceRows
from .blocks._helpers import formatDuration, toolIconFor

#: 最多展示的行数（调试面板，避免一次建几千个控件）
MAX_TRACE_ROWS = 300

_KIND_ICONS = {
    "turn": ElaIconType.IconName.ListTimeline,
    "step": ElaIconType.IconName.ListOl,
    "tool": ElaIconType.IconName.Cube,
    "reasoning": ElaIconType.IconName.Brain,
    "plan": ElaIconType.IconName.ListCheck,
    "permission": ElaIconType.IconName.Comment,
    "compaction": ElaIconType.IconName.BoxArchive,
}


class _DurationBar(QWidget):
    """行内持续时间条（宽度按最大耗时归一）。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._ratio = 0.0
        self._error = False
        self._theme_mode = None
        self.setFixedWidth(72)
        self.setFixedHeight(10)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def setDuration(self, durationMs: float, maxDurationMs: float) -> None:
        try:
            duration = max(0.0, float(durationMs or 0.0))
            maximum = max(1.0, float(maxDurationMs or 0.0))
        except (TypeError, ValueError, OverflowError):
            duration, maximum = 0.0, 1.0
        self._ratio = min(1.0, duration / maximum) if maximum > 0 else 0.0
        self.update()

    def setError(self, on: bool) -> None:
        self._error = bool(on)
        self.update()

    def applyTheme(self, mode) -> None:
        self._theme_mode = mode
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt 命名)
        mode = self._theme_mode
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            rect = QRectF(0, 2, self.width(), max(1, self.height() - 4))
            painter.setBrush(blend(base_color(mode), text_color(mode), 0.10))
            painter.drawRoundedRect(rect, 3, 3)
            if self._ratio > 0:
                width = max(2.0, rect.width() * self._ratio)
                color = (
                    statusColor(mode, ElaStatusRoleType.Error)
                    if self._error
                    else accent_color(mode)
                )
                painter.setBrush(color)
                painter.drawRoundedRect(
                    QRectF(rect.x(), rect.y(), width, rect.height()), 3, 3
                )
        finally:
            painter.end()


class _TraceRowWidget(QWidget):
    """轨迹单行（缩进 + 图标 + 名称 + 详情 + 耗时 + 时间条）。"""

    activated = pyqtSignal(int, str)

    def __init__(
        self,
        row: ElaChatTraceRow,
        maxDurationMs: float,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._row = row
        self._hovered = False
        self._theme_mode = None
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(26)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8 + max(0, row.depth) * 14, 0, 8, 0)
        layout.setSpacing(6)
        self._icon = ElaIconButton(self._iconFor(row), 10, 14, 14, self)
        self._icon.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._icon.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._label = ColorText(self)
        self._label.setTextFormat(Qt.TextFormat.PlainText)
        self._label.setWordWrap(False)
        self._label.setText(row.label or row.kind)
        self._detail = ColorText(self)
        self._detail.setTextFormat(Qt.TextFormat.PlainText)
        self._detail.setWordWrap(False)
        self._detail.setText(row.detail or "")
        self._detail.setMaximumWidth(220)
        if row.detail:
            set_tooltip(
                self._detail,
                row.detail,
                ElaToolTipPositionType.Top,
                maxWidth=520,
                wordWrap=True,
            )
        else:
            remove_tooltip(self._detail)
        self._duration = ColorText(self)
        self._duration.setTextFormat(Qt.TextFormat.PlainText)
        self._duration.setWordWrap(False)
        self._duration.setText(formatDuration(row.duration_ms))
        self._bar = _DurationBar(self)
        self._bar.setDuration(row.duration_ms, maxDurationMs)
        self._bar.setError(row.isError)
        layout.addWidget(self._icon, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self._label, 0)
        layout.addWidget(self._detail, 1)
        layout.addWidget(self._duration, 0, Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self._bar, 0, Qt.AlignmentFlag.AlignVCenter)

    @staticmethod
    def _iconFor(row: ElaChatTraceRow):
        if row.isError:
            return ElaIconType.IconName.Ban
        if row.kind == "tool":
            return toolIconFor(row.label)
        return _KIND_ICONS.get(row.kind, ElaIconType.IconName.Cube)

    def row(self) -> ElaChatTraceRow:
        """获取行数据。"""
        return self._row

    def enterEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        if event.button() == Qt.MouseButton.LeftButton:
            try:
                self.activated.emit(self._row.message_id, self._row.part_id)
            except Exception:
                pass
            event.accept()
            return
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        painter = QPainter(self)
        try:
            if self._hovered:
                paintRoundedCard(
                    painter,
                    QRectF(self.rect()).adjusted(2, 2, -2, -2),
                    background=blend(
                        base_color(self._theme_mode),
                        text_color(self._theme_mode),
                        0.06,
                    ),
                    radius=6.0,
                )
        finally:
            painter.end()
        super().paintEvent(event)

    def applyTheme(self, mode) -> None:
        """按主题刷新颜色（由面板统一调用，避免每行各连一次单例信号）。"""
        self._theme_mode = mode
        danger = statusColor(mode, ElaStatusRoleType.Error)
        color = danger if self._row.isError else text_color(mode)
        self._label.setTextColor(color)
        self._label.setTextPixelSize(12)
        self._detail.setTextColor(muted_color(mode, 0.55))
        self._detail.setTextPixelSize(11)
        self._duration.setTextColor(muted_color(mode, 0.5))
        self._duration.setTextPixelSize(11)
        self._icon.setLightIconColor(color)
        self._icon.setDarkIconColor(color)
        self._bar.applyTheme(mode)
        self.update()


class ElaChatTracePanel(ElaThemeWidget):
    """独立运行轨迹面板（由宿主放进对话框 / ``QSplitter``）。"""

    #: 点击某行（参数：消息 id）
    rowActivated = pyqtSignal(int)
    #: 点击某行（参数：消息 id、分段 id）
    partActivated = pyqtSignal(int, str)

    def __init__(
        self,
        view=None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        # ElaThemeWidget 已经按主题更新 palette Window；打开自动填充即可，
        # 不需要在 paintEvent 里手写 base_color。
        self.setAutoFillBackground(True)
        self._view = view
        self._result = ElaChatTraceResult()
        self._filter = "all"
        self._rows: list = []
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)
        header = QHBoxLayout()
        header.setSpacing(8)
        self._title = ColorText("运行轨迹", self)
        self._title.setTextFormat(Qt.TextFormat.PlainText)
        self._title.setTextPixelSize(14)
        self._title.setTextWeight(QFont.Weight.DemiBold)
        self._summary = ColorText(self)
        self._summary.setTextFormat(Qt.TextFormat.PlainText)
        self._summary.setWordWrap(False)
        self._refresh_button = ElaButton(
            "刷新", variant="text", size="small", parent=self
        )
        safe_connect(
            self._refresh_button,
            "clicked",
            lambda _=False: self.refresh(),
            "trace.refresh",
            receiver=self._refresh_button,
        )
        self._all_button = ElaButton("全部", variant="text", size="small", parent=self)
        self._error_button = ElaButton(
            "仅失败", variant="text", size="small", parent=self
        )
        safe_connect(
            self._all_button,
            "clicked",
            lambda _=False: self.setFilter("all"),
            "trace.filter_all",
            receiver=self._all_button,
        )
        safe_connect(
            self._error_button,
            "clicked",
            lambda _=False: self.setFilter("errors"),
            "trace.filter_errors",
            receiver=self._error_button,
        )
        header.addWidget(self._title)
        header.addWidget(self._summary, 1)
        header.addWidget(self._refresh_button)
        header.addWidget(self._all_button)
        header.addWidget(self._error_button)
        layout.addLayout(header)

        self._scroll = ElaScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setVerticalScrollBar(ElaScrollBar(self._scroll))
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._content = QWidget(self._scroll)
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(0)
        self._scroll.setWidget(self._content)
        # ElaScrollArea 的 viewport 会在 setWidget / 主题 polish 后重新打开
        # autoFillBackground；必须在这之后关掉，让面板自己画的主题底色透上来。
        self._scroll.setAutoFillBackground(False)
        self._scroll.viewport().setAutoFillBackground(False)
        self._content.setAutoFillBackground(False)
        layout.addWidget(self._scroll, 1)
        self._empty = ColorText("暂无运行记录", self)
        self._empty.setTextFormat(Qt.TextFormat.PlainText)
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._empty)
        self._sync_filter_buttons()
        self._apply_theme()

    def setView(self, view) -> None:
        """绑定聊天视图并立即刷新。"""
        self._view = view
        self.refresh()

    def view(self):
        """获取当前绑定的聊天视图。"""
        return self._view

    def result(self) -> ElaChatTraceResult:
        """获取最近一次构建的轨迹结果。"""
        return self._result

    def refresh(self) -> None:
        """重新读取 ``view.messages()`` 并重建列表。"""
        messages = self._view.messages() if self._view is not None else []
        self._result = buildTraceRows(messages)
        self._update_summary()
        self._rebuild_rows()

    def setFilter(self, value: str) -> None:
        """筛选：``all`` / ``errors``。"""
        self._filter = "errors" if value == "errors" else "all"
        self._sync_filter_buttons()
        self._rebuild_rows()

    def filter(self) -> str:
        """当前筛选。"""
        return self._filter

    def _update_summary(self) -> None:
        result = self._result
        if result.isEmpty():
            self._summary.setText("")
            return
        parts = [
            f"{len(result.rows)} 轮",
            f"{result.tool_count} 次工具",
        ]
        if result.error_count:
            parts.append(f"{result.error_count} 失败")
        duration = formatDuration(result.total_duration_ms)
        if duration:
            parts.append(duration)
        if result.cost_usd:
            parts.append(formatCost(result.cost_usd))
        self._summary.setText(" · ".join(parts))

    def _has_error(self, row: ElaChatTraceRow) -> bool:
        if row.isError:
            return True
        return any(self._has_error(child) for child in row.children)

    def _filtered_rows(self) -> list:
        rows = list(self._result.flatten())
        if self._filter == "errors":
            rows = [row for row in rows if self._has_error(row)]
        return rows[:MAX_TRACE_ROWS]

    def _rebuild_rows(self) -> None:
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            widget = item.widget()
            if widget is None:
                continue
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()
        self._rows.clear()
        rows = self._filtered_rows()
        self._empty.setVisible(not rows)
        self._scroll.setVisible(bool(rows))
        if not rows:
            self._sync_filter_buttons()
            return
        maximum = max(
            (row.duration_ms for row in rows if row.duration_ms > 0),
            default=0.0,
        )
        for row in rows:
            widget = _TraceRowWidget(row, maximum, self._content)
            widget.applyTheme(self._theme_mode)
            safe_connect(
                widget,
                "activated",
                self._on_row_activated,
                "trace.row_activated",
                receiver=widget,
            )
            self._content_layout.addWidget(widget)
            self._rows.append(widget)
        self._content_layout.addStretch(1)
        self._sync_filter_buttons()

    def _sync_filter_buttons(self) -> None:
        self._all_button.setVariant("solid" if self._filter == "all" else "text")
        self._error_button.setVariant("solid" if self._filter == "errors" else "text")

    def _on_row_activated(self, messageId: int, partId: str) -> None:
        try:
            self.rowActivated.emit(int(messageId or 0))
            self.partActivated.emit(int(messageId or 0), str(partId or ""))
        except Exception:
            pass

    def rows(self) -> list:
        """当前展示的行控件（测试 / 高级用法）。"""
        return list(self._rows)

    def _apply_theme(self) -> None:
        mode = self._theme_mode
        self.update()
        # 透出面板 paintEvent 的主题底色；不写死任何颜色。
        self._scroll.viewport().setAutoFillBackground(False)
        self._content.setAutoFillBackground(False)
        self._title.setTextColor(text_color(mode))
        self._title.setTextPixelSize(14)
        self._summary.setTextColor(muted_color(mode, 0.6))
        self._summary.setTextPixelSize(12)
        self._empty.setTextColor(muted_color(mode, 0.5))
        self._empty.setTextPixelSize(12)
        for row in self._rows:
            if not is_deleted(row):
                row.applyTheme(mode)

    def _onThemeChanged(self, mode: ElaThemeType.ThemeMode) -> None:
        super()._onThemeChanged(mode)
        self._apply_theme()


__all__ = ["ElaChatTracePanel", "MAX_TRACE_ROWS"]
