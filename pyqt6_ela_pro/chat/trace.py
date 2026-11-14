"""独立运行轨迹面板：每轮瀑布时间轴 + 当前轮流程图 + 会话趋势轨道。"""

from __future__ import annotations

import logging
import time
from bisect import bisect_right
from dataclasses import dataclass, replace
from typing import Optional

from PyQt6.QtCore import (
    QPointF,
    QRect,
    QRectF,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from PyQt6ElaWidgetTools import (
    ElaIconType,
    ElaMenu,
    ElaPivot,
    ElaScrollArea,
    ElaScrollBar,
    ElaText,
    ElaThemeType,
)

from .._internal import (
    is_deleted,
    safe_connect,
    single_shot_on,
    system_cjk_font_family,
)
from .._styles import ColorText, iconGlyph, paintRoundedCard
from .._theme import ElaStatusRoleType, statusColor
from ..blueprint import (
    ElaBlueprintCanvas,
    ElaBlueprintGraph,
    register_node_type,
    pin,
)
from ..ela_button import ElaButton
from ..ela_dropdown_button import ElaDropDownButton
from ..tooltips import ElaToolTip
from ..widget_base import ElaThemeWidget
from ._pricing import formatCost
from ._theme import (
    accent_color,
    base_color,
    blend,
    border_color,
    mono_font,
    muted_color,
    surface_color,
    text_color,
)
from ._trace import ElaChatTraceResult, ElaChatTraceRow, buildTraceRows
from .blocks._helpers import formatDuration, toolIconFor

logger = logging.getLogger(__name__)

#: 时间轴行高 / 轮头 / 响应头高度
_ROW_H = 24
_STEP_H = 24
_RESP_H = 40
_TURN_H = 38
#: 左栏宽度上限
_MAX_LABEL_W = 292
_MIN_LABEL_W = 196
#: 单轮流程图节点上限
_MAX_GRAPH_NODES = 120
#: 流程图节点类型命名空间
_GRAPH_OWNER = "chat.trace"

_KIND_ICONS = {
    "turn": ElaIconType.IconName.ListTimeline,
    "response": ElaIconType.IconName.MessageBot,
    "step": ElaIconType.IconName.ListOl,
    "tool": ElaIconType.IconName.Cube,
    "reasoning": ElaIconType.IconName.Brain,
    "plan": ElaIconType.IconName.ListCheck,
    "permission": ElaIconType.IconName.Comment,
    "compaction": ElaIconType.IconName.BoxArchive,
}
_GRAPH_TYPES = {
    "turn": "trace.turn",
    "response": "trace.response",
    "step": "trace.step",
    "tool": "trace.tool",
    "reasoning": "trace.reasoning",
    "plan": "trace.plan",
    "permission": "trace.permission",
    "compaction": "trace.compaction",
}


@dataclass(frozen=True)
class ElaChatTraceOptions:
    """轨迹面板的显示选项（全部可热切换）。"""

    #: ``timeline`` / ``graph``
    view: str = "timeline"
    #: 发光 / 渐变 / 呼吸 / 流动
    effects: bool = True
    #: 回放控件与 playhead
    replay: bool = True
    #: 会话趋势轨道
    tracks: bool = True


@dataclass
class _VisualRow:
    """时间轴上的一行（数据 + 纵向位置）。"""

    row: ElaChatTraceRow
    turn_index: int
    y: int
    height: int
    depth: int
    #: 最近响应作用域（响应自身 / 其下步骤与工具共用）
    scope_key: str = ""
    scope_start: float = 0.0
    scope_span: float = 0.0


def _text_font(size: int, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    font = QFont()
    family = system_cjk_font_family()
    if family:
        font.setFamilies([family])
    else:
        font.setFamily(QApplication.font().family())
    font.setPixelSize(int(size))
    font.setWeight(weight)
    return font


def _icon_font(size: int = 11) -> QFont:
    font = QFont("ElaAwesome")
    font.setPixelSize(int(size))
    return font


def _duration_text(ms: float) -> str:
    return formatDuration(ms) or "0s"


def _summary_duration(ms: float) -> str:
    try:
        seconds = max(0.0, float(ms)) / 1000.0
    except (TypeError, ValueError, OverflowError):
        return ""
    if seconds >= 3600:
        return f"{int(seconds // 3600)}h {int(seconds % 3600 // 60)}m"
    return formatDuration(ms)


def _kind_color(kind: str, colors: dict) -> QColor:
    return colors.get(kind) or colors["muted"]


def _shift_hue(color: QColor, delta: float, sat_boost: float = 0.05) -> QColor:
    """保持明度 / alpha，按色相偏移派生一个可区分的分类色。"""
    hue, sat, light, alpha = color.getHslF()
    out = QColor()
    out.setHslF(
        (hue + delta) % 1.0,
        min(1.0, max(0.0, sat + sat_boost)),
        light,
        alpha,
    )
    return out


def _row_key(row: ElaChatTraceRow):
    return (row.kind, row.message_id, row.part_id)


def _has_children(row: ElaChatTraceRow) -> bool:
    return bool(row.children)


def _graph_body(node, container: QWidget) -> None:
    layout = container.layout()
    if layout is None:
        return
    detail = " ".join(str(node.properties.get("detail") or "").split())
    if len(detail) > 64:
        detail = detail[:64] + "…"
    meta = str(node.properties.get("meta") or "")
    if detail:
        label = ElaText(container)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setTextPixelSize(11)
        label.setText(detail)
        layout.addWidget(label)
    if meta:
        value = ElaText(container)
        value.setTextFormat(Qt.TextFormat.PlainText)
        value.setTextPixelSize(10)
        value.setText(meta)
        layout.addWidget(value)


def _register_graph_types() -> None:
    specs = (
        ("trace.turn", "回合", "primary"),
        ("trace.response", "响应", "primary"),
        ("trace.step", "步骤", "primary"),
        ("trace.tool", "工具", "primary"),
        ("trace.reasoning", "思考", "warning"),
        ("trace.plan", "计划", "success"),
        ("trace.permission", "审批", "warning"),
        ("trace.compaction", "压缩", None),
    )
    for type_name, title, accent in specs:
        register_node_type(
            type_name,
            title,
            "运行轨迹",
            inputs=pin("in", "in", "any"),
            outputs=pin("out", "out", "any"),
            accent=accent,
            body_builder=_graph_body,
            owner=_GRAPH_OWNER,
        )


_register_graph_types()


class _TraceCanvas(QWidget):
    """时间轴画布：只画可视行，标签与瀑布条共享行高。"""

    activated = pyqtSignal(int, str)
    turnActivated = pyqtSignal(int)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._result = ElaChatTraceResult()
        self._filter = "all"
        self._collapsed: set = set()
        self._visual: list = []
        self._row_ys: list = []
        self._turn_bounds: list = []  # (turn_index, y0, y1, span_ms)
        self._turn_ys: list = []
        self._content_h = 0
        self._hover_index = -1
        self._hover_pos = QPointF()
        self._hover_x = -1.0
        self._playhead_ms: Optional[float] = None
        self._playhead_key = ""
        self._playhead_rect = QRect()
        self._response_bounds: dict = {}
        self._response_order: list = []
        self._effects = True
        self._theme_mode = None
        self._label_w = _MAX_LABEL_W
        self._font_label = _text_font(12)
        self._font_step = _text_font(12, QFont.Weight.DemiBold)
        self._font_detail = _text_font(11)
        self._font_metric = mono_font(10)
        self._font_ruler = mono_font(10)
        self._font_icon = _icon_font(11)
        self._font_chevron = _icon_font(10)
        self._label_metrics = QFontMetrics(self._font_label)
        self._detail_metrics = QFontMetrics(self._font_detail)
        self._metric_metrics = QFontMetrics(self._font_metric)
        self._ruler_metrics = QFontMetrics(self._font_ruler)
        self._elide_cache: dict = {}
        self._colors: dict = {}
        self._hover_tooltip: Optional[ElaToolTip] = None
        self._tooltip_key = ""
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    # 公共 API
    def setResult(
        self,
        result: ElaChatTraceResult,
        filter: str = "all",
        effects: bool = True,
    ) -> None:
        self._result = result or ElaChatTraceResult()
        self._filter = "errors" if filter == "errors" else "all"
        self._effects = bool(effects)
        keys = {_row_key(item) for turn in self._result.rows for item in turn.walk()}
        self._collapsed &= keys
        self._rebuild()

    def setFilter(self, value: str) -> None:
        self._filter = "errors" if value == "errors" else "all"
        self._rebuild()

    def setEffects(self, on: bool) -> None:
        self._effects = bool(on)
        self.update()

    def visualRows(self) -> list:
        return list(self._visual)

    def rowAtPoint(self, pos: QPointF) -> Optional[_VisualRow]:
        index = self._indexAt(pos.y())
        return self._visual[index] if index >= 0 else None

    def currentRow(self) -> Optional[ElaChatTraceRow]:
        if self._hover_index < 0:
            return None
        return self._visual[self._hover_index].row

    def hoveredVisualRow(self) -> Optional[_VisualRow]:
        if 0 <= self._hover_index < len(self._visual):
            return self._visual[self._hover_index]
        return None

    def clearHover(self, *_args) -> None:
        """滚动时收起 hover 浮层，避免卡片停在旧行上。"""
        if self._hover_index < 0:
            self._hideTooltip()
            return
        old_row = self._hover_index
        self._hover_index = -1
        self._hover_x = -1.0
        self._hideTooltip()
        if 0 <= old_row < len(self._visual):
            item = self._visual[old_row]
            self.update(QRect(0, item.y, self.width(), item.height))

    def turnY(self, index: int) -> int:
        for turn_index, y0, _y1, _span in self._turn_bounds:
            if turn_index == index:
                return y0
        return 0

    def turnAtY(self, y: float) -> int:
        index = bisect_right(self._turn_ys, y) - 1
        if 0 <= index < len(self._turn_bounds):
            turn_index, y0, y1, _span = self._turn_bounds[index]
            if y0 <= y <= y1:
                return turn_index
        return -1

    def setPlayhead(self, ms: Optional[float], responseKey: str = "") -> None:
        old = QRect(self._playhead_rect)
        old_key = self._playhead_key
        old_scope = self._responseLaneRect(old_key)
        self._playhead_ms = None if ms is None else max(0.0, float(ms))
        self._playhead_key = str(responseKey or "")
        new = self._computePlayheadRect()
        self._playhead_rect = new
        rects = [old, new]
        if self._effects:
            rects.extend([old_scope, self._responseLaneRect(self._playhead_key)])
        for rect in rects:
            if not rect.isNull():
                self.update(rect.adjusted(-6, -2, 6, 2))

    def _responseLaneRect(self, key: str) -> QRect:
        bounds = self._response_bounds.get(str(key or ""))
        if bounds is None:
            return QRect()
        _turn_index, y0, y1, _start, _span = bounds
        lane = self._laneRect()
        return QRect(int(lane.left()), int(y0), int(lane.width()), max(1, int(y1 - y0)))

    def responseKeyAtY(self, y: float) -> str:
        for key in self._response_order:
            bounds = self._response_bounds.get(key)
            if bounds is None:
                continue
            _turn_index, y0, y1, _start, _span = bounds
            if y0 <= y <= y1:
                return key
        best = ""
        best_y = float("inf")
        for key in self._response_order:
            bounds = self._response_bounds.get(key)
            if bounds is None:
                continue
            _turn_index, y0, _y1, _start, _span = bounds
            if y0 >= y and y0 < best_y:
                best = key
                best_y = float(y0)
        if best:
            return best
        return self._response_order[-1] if self._response_order else ""

    def responseY(self, key: str) -> int:
        bounds = self._response_bounds.get(str(key or ""))
        return int(bounds[1]) if bounds is not None else 0

    def responseSpan(self, key: str) -> float:
        bounds = self._response_bounds.get(str(key or ""))
        return max(1.0, float(bounds[4])) if bounds is not None else 1.0

    def responseTurn(self, key: str) -> int:
        bounds = self._response_bounds.get(str(key or ""))
        return int(bounds[0]) if bounds is not None else -1

    def playhead(self) -> Optional[float]:
        return self._playhead_ms

    def toggleRow(self, index: int) -> None:
        if not (0 <= index < len(self._visual)):
            return
        visual = self._visual[index]
        if not _has_children(visual.row):
            return
        key = _row_key(visual.row)
        if key in self._collapsed:
            self._collapsed.discard(key)
        else:
            self._collapsed.add(key)
        self._rebuild(preserve_scroll=True)

    def applyTheme(self, mode) -> None:
        self._theme_mode = mode
        accent = accent_color(mode)
        text = text_color(mode)
        base = base_color(mode)
        self._colors = {
            "base": base,
            "text": text,
            "muted": muted_color(mode, 0.55),
            "faint": muted_color(mode, 0.3),
            "accent": accent,
            "error": blend(statusColor(mode, ElaStatusRoleType.Error), text, 0.25),
            "success": statusColor(mode, ElaStatusRoleType.Success),
            "warning": statusColor(mode, ElaStatusRoleType.Warning),
            "band": surface_color(mode, 0.045),
            "resp_band": surface_color(mode, 0.022),
            "border": border_color(mode, 0.14),
            "hover": surface_color(mode, 0.07),
            "tool": accent,
            "response": blend(accent, text, 0.20),
            "reasoning": blend(_shift_hue(accent, 0.16), text, 0.22),
            "plan": statusColor(mode, ElaStatusRoleType.Success),
            "permission": statusColor(mode, ElaStatusRoleType.Warning),
            "compaction": muted_color(mode, 0.45),
        }
        self._elide_cache.clear()
        self.update()

    # 内部布局
    def _rebuild(self, preserve_scroll: bool = False) -> None:
        scroll = 0
        if preserve_scroll:
            parent = self.parentWidget()
            area = parent.parentWidget() if parent is not None else None
            if isinstance(area, ElaScrollArea):
                scroll = area.verticalScrollBar().value()
        self._visual = []
        self._turn_bounds = []
        self._response_bounds = {}
        self._response_order = []
        y = 6
        for turn_index, turn in enumerate(self._result.rows):
            if self._filter == "errors" and not turn.error_below:
                continue
            turn_y = y
            self._visual.append(_VisualRow(turn, turn_index, y, _TURN_H, 0))
            y += _TURN_H
            if _row_key(turn) not in self._collapsed:
                for response in turn.children:
                    if self._filter == "errors" and not response.error_below:
                        continue
                    scope_start = max(0.0, response.start_ms)
                    scope_span = max(1.0, response.span_ms)
                    response_y = y
                    self._visual.append(
                        _VisualRow(
                            response,
                            turn_index,
                            y,
                            _RESP_H,
                            1,
                            response.part_id,
                            scope_start,
                            scope_span,
                        )
                    )
                    y += _RESP_H
                    if _row_key(response) not in self._collapsed:
                        for step in response.children:
                            if self._filter == "errors" and not step.error_below:
                                continue
                            self._visual.append(
                                _VisualRow(
                                    step,
                                    turn_index,
                                    y,
                                    _STEP_H,
                                    2,
                                    response.part_id,
                                    scope_start,
                                    scope_span,
                                )
                            )
                            y += _STEP_H
                            if _row_key(step) not in self._collapsed:
                                for child in step.children:
                                    y = self._addItem(
                                        child,
                                        turn_index,
                                        y,
                                        3,
                                        response.part_id,
                                        scope_start,
                                        scope_span,
                                    )
                    self._response_bounds[response.part_id] = (
                        turn_index,
                        response_y,
                        y,
                        scope_start,
                        scope_span,
                    )
                    self._response_order.append(response.part_id)
            self._turn_bounds.append((turn_index, turn_y, y, turn.span_ms))
            y += 4
        self._content_h = max(1, y + 2)
        self._row_ys = [item.y for item in self._visual]
        self._turn_ys = [bound[1] for bound in self._turn_bounds]
        self.setFixedHeight(self._content_h)
        if preserve_scroll:
            parent = self.parentWidget()
            area = parent.parentWidget() if parent is not None else None
            if isinstance(area, ElaScrollArea):
                area.verticalScrollBar().setValue(scroll)
        self._hover_index = -1
        self._hover_x = -1.0
        self._hideTooltip()
        self.update()

    def _addItem(
        self,
        row: ElaChatTraceRow,
        turnIndex: int,
        y: int,
        depth: int,
        scopeKey: str,
        scopeStart: float,
        scopeSpan: float,
    ) -> int:
        if self._filter == "errors" and not row.error_below:
            return y
        self._visual.append(
            _VisualRow(
                row,
                turnIndex,
                y,
                _ROW_H,
                depth,
                scopeKey,
                scopeStart,
                scopeSpan,
            )
        )
        y += _ROW_H
        if row.children and _row_key(row) not in self._collapsed:
            for child in row.children:
                y = self._addItem(
                    child,
                    turnIndex,
                    y,
                    depth + 1,
                    scopeKey,
                    scopeStart,
                    scopeSpan,
                )
        return y

    def _indexAt(self, y: float) -> int:
        index = bisect_right(self._row_ys, y) - 1
        if 0 <= index < len(self._visual):
            item = self._visual[index]
            if item.y <= y < item.y + item.height:
                return index
        return -1

    def _labelWidth(self) -> int:
        width = int(self.width() * 0.36)
        return max(_MIN_LABEL_W, min(_MAX_LABEL_W, width))

    def _laneRect(self) -> QRectF:
        left = self._labelWidth()
        return QRectF(left, 0, max(40, self.width() - left - 10), self.height())

    def _spanRect(self, row: ElaChatTraceRow, visual: _VisualRow) -> QRectF:
        lane = self._laneRect()
        span = max(1.0, float(visual.scope_span or 1.0))
        start = max(0.0, row.start_ms - visual.scope_start)
        x0 = lane.left() + (start / span) * lane.width()
        width = max(2.0, (max(0.0, row.span_ms) / span) * lane.width())
        return QRectF(x0, 0, min(width, lane.right() - x0), 0)

    def _computePlayheadRect(self) -> QRect:
        if self._playhead_ms is None or not self._playhead_key:
            return QRect()
        bounds = self._response_bounds.get(self._playhead_key)
        if bounds is None:
            return QRect()
        _turn_index, y0, y1, _start, span = bounds
        lane = self._laneRect()
        ratio = min(1.0, max(0.0, self._playhead_ms / max(1.0, span)))
        x = lane.left() + ratio * lane.width()
        return QRect(int(x) - 1, int(y0), 3, max(1, int(y1 - y0)))

    # 绘制
    def paintEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        if not self._colors:
            self.applyTheme(None)
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.fillRect(event.rect(), self._colors["base"])
            self._paintGrid(painter, event.rect())
            for index, item in enumerate(self._visual):
                if item.y + item.height < event.rect().top():
                    continue
                if item.y > event.rect().bottom():
                    break
                self._paintRow(painter, index, item, event.rect())
            self._paintPlayhead(painter)
            self._paintHover(painter)
        except Exception:
            logger.debug("trace canvas paint failed", exc_info=True)
        finally:
            painter.end()

    def _paintGrid(self, painter: QPainter, _rect: QRect) -> None:
        lane = self._laneRect()
        pen = QPen(self._colors["border"])
        pen.setWidthF(1.0)
        pen.setStyle(Qt.PenStyle.DotLine)
        painter.setPen(pen)
        for key in self._response_order:
            bounds = self._response_bounds.get(key)
            if bounds is None:
                continue
            _turn_index, y0, y1, _start, _span = bounds
            if y1 < _rect.top() or y0 > _rect.bottom():
                continue
            for ratio in (0.0, 0.25, 0.5, 0.75, 1.0):
                x = lane.left() + ratio * lane.width()
                painter.drawLine(QPointF(x, y0), QPointF(x, y1))

    def _paintRow(
        self,
        painter: QPainter,
        index: int,
        item: _VisualRow,
        clip: QRect,
    ) -> None:
        row = item.row
        top = item.y
        height = item.height
        label_w = self._labelWidth()
        if index == self._hover_index and row.kind != "turn":
            paintRoundedCard(
                painter,
                QRectF(4, top + 1, self.width() - 8, height - 2),
                background=self._colors["hover"],
                radius=5.0,
            )
        if row.kind == "turn":
            self._paintTurn(painter, item, clip)
            return
        text_h = height - 14 if row.kind == "response" else height
        if row.kind == "response" and index != self._hover_index:
            paintRoundedCard(
                painter,
                QRectF(4, top + 1, self.width() - 8, height - 2),
                background=self._colors["resp_band"],
                radius=4.0,
            )

        indent = 8 + max(0, item.depth) * 13
        chevron_x = indent
        icon_x = indent + 14
        text_x = icon_x + 16
        duration_w = 46
        detail_x = text_x + 108
        detail_right = label_w - duration_w - 12
        if detail_right > detail_x + 20:
            detail = self._elide(row.detail or "", detail_right - detail_x)
            painter.setFont(self._font_detail)
            painter.setPen(self._colors["muted"])
            painter.drawText(
                QRectF(detail_x, top, detail_right - detail_x, text_h),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                detail,
            )
        painter.setFont(self._font_icon)
        painter.setPen(self._colors["faint"])
        painter.drawText(
            QRectF(icon_x, top, 14, text_h),
            Qt.AlignmentFlag.AlignCenter,
            self._iconFor(row),
        )
        if row.children:
            painter.setFont(self._font_chevron)
            painter.setPen(self._colors["muted"])
            painter.drawText(
                QRectF(chevron_x, top, 12, text_h),
                Qt.AlignmentFlag.AlignCenter,
                iconGlyph(ElaIconType.IconName.AngleRight)
                if _row_key(row) in self._collapsed
                else iconGlyph(ElaIconType.IconName.AngleDown),
            )
        painter.setFont(
            self._font_step if row.kind in ("step", "response") else self._font_label
        )
        painter.setPen(self._rowTextColor(row))
        painter.drawText(
            QRectF(text_x, top, max(20, detail_x - text_x - 6), text_h),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            self._elide(
                row.label or row.kind,
                max(20, detail_x - text_x - 6),
                self._label_metrics,
            ),
        )
        duration = formatDuration(row.duration_ms) or "—"
        painter.setFont(self._font_metric)
        painter.setPen(self._colors["muted"])
        painter.drawText(
            QRectF(label_w - duration_w - 6, top, duration_w, text_h),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
            duration,
        )
        lane = self._laneRect()
        rect = self._spanRect(row, item)
        if row.kind == "step":
            painter.setPen(QPen(self._colors["border"], 2.0))
            y = top + height * 0.5
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            return
        if row.kind == "response":
            ruler_y = top + height - 13
            painter.setPen(QPen(self._colors["border"], 1.0))
            painter.drawLine(
                QPointF(lane.left(), ruler_y), QPointF(lane.right(), ruler_y)
            )
            painter.setFont(self._font_ruler)
            painter.setPen(self._colors["muted"])
            span = max(1.0, row.span_ms)
            for ratio, align in (
                (0.0, Qt.AlignmentFlag.AlignLeft),
                (0.5, Qt.AlignmentFlag.AlignHCenter),
                (1.0, Qt.AlignmentFlag.AlignRight),
            ):
                x = lane.left() + ratio * lane.width()
                painter.drawLine(QPointF(x, ruler_y - 2), QPointF(x, ruler_y + 1))
                text = _duration_text(span * ratio)
                width = 70
                left = (
                    x if ratio == 0 else (x - width / 2 if ratio == 0.5 else x - width)
                )
                painter.drawText(
                    QRectF(left, ruler_y + 1, width, 11),
                    align | Qt.AlignmentFlag.AlignTop,
                    text,
                )
            return
        bar = QRectF(
            rect.x(),
            top + (height - 8) * 0.5,
            rect.width(),
            8.0,
        )
        self._paintSpan(painter, bar, row, item.turn_index, lane)

    def _paintTurn(self, painter: QPainter, item: _VisualRow, _clip: QRect) -> None:
        row = item.row
        top = item.y
        height = item.height
        label_w = self._labelWidth()
        paintRoundedCard(
            painter,
            QRectF(4, top + 1, self.width() - 8, height - 2),
            background=self._colors["band"],
            radius=5.0,
        )
        if row.error_below:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self._colors["error"])
            painter.drawEllipse(QRectF(5, top + (height - 10) * 0.5, 4, 4))
        if _row_key(row) in self._collapsed:
            chevron = iconGlyph(ElaIconType.IconName.AngleRight)
        else:
            chevron = iconGlyph(ElaIconType.IconName.AngleDown)
        painter.setFont(self._font_chevron)
        painter.setPen(self._colors["muted"])
        painter.drawText(
            QRectF(10, top, 12, height - 10),
            Qt.AlignmentFlag.AlignCenter,
            chevron,
        )
        painter.setFont(self._font_icon)
        painter.setPen(self._colors["accent"])
        painter.drawText(
            QRectF(24, top, 14, height - 10),
            Qt.AlignmentFlag.AlignCenter,
            iconGlyph(ElaIconType.IconName.ListTimeline),
        )
        painter.setFont(self._font_step)
        painter.setPen(self._rowTextColor(row))
        title_x = 42.0
        metrics = []
        if row.duration_ms:
            metrics.append(formatDuration(row.duration_ms))
        if len(row.children) > 1:
            metrics.append(f"{len(row.children)} 响应")
        if row.tokens:
            metrics.append(f"{row.tokens} tok")
        if row.cost_usd:
            metrics.append(formatCost(row.cost_usd))
        metrics_text = " · ".join(metrics)
        metrics_width = (
            self._metric_metrics.horizontalAdvance(metrics_text) + 12
            if metrics_text
            else 0
        )
        title_w = max(40.0, label_w - title_x - metrics_width - 8)
        painter.drawText(
            QRectF(title_x, top, title_w, height - 10),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            self._elide(row.label or "回合", title_w, self._label_metrics),
        )
        if metrics_text:
            painter.setFont(self._font_metric)
            painter.setPen(self._colors["muted"])
            painter.drawText(
                QRectF(label_w - metrics_width - 4, top, metrics_width, height - 10),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                metrics_text,
            )
        # 轮内响应密度条（子时间轴按响应局部标尺绘制）
        lane = self._laneRect()
        strip_y = top + height - 8
        pen = QPen(self._colors["border"])
        pen.setWidthF(1.0)
        painter.setPen(pen)
        painter.drawLine(QPointF(lane.left(), strip_y), QPointF(lane.right(), strip_y))
        span = max(1.0, row.span_ms)
        fill = QColor(self._colors["response"])
        fill.setAlphaF(0.6)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fill)
        for response in row.children:
            x = lane.left() + (max(0.0, response.start_ms) / span) * lane.width()
            width = max(1.5, (max(0.0, response.span_ms) / span) * lane.width())
            painter.drawRect(QRectF(x, strip_y - 5, min(width, lane.right() - x), 4))
        painter.setBrush(Qt.BrushStyle.NoBrush)

    def _paintSpan(
        self,
        painter: QPainter,
        bar: QRectF,
        row: ElaChatTraceRow,
        turnIndex: int,
        lane: QRectF,
    ) -> None:
        if bar.right() < lane.left() or bar.left() > lane.right():
            return
        if row.span_ms <= 0:
            painter.setPen(QPen(self._colors["muted"], 1.0))
            painter.drawLine(
                QPointF(bar.left(), bar.top()), QPointF(bar.left(), bar.bottom())
            )
            return
        color = (
            self._colors["error"]
            if row.isError
            else _kind_color(row.kind, self._colors)
        )
        fill = QColor(color)
        fill.setAlphaF(0.82)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fill)
        painter.drawRoundedRect(bar, 3.0, 3.0)
        if self._effects:
            glow = QColor(color)
            glow.setAlphaF(0.16)
            painter.setPen(QPen(glow, 1.0))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(bar.adjusted(-1.0, -1.0, 1.0, 1.0), 4.0, 4.0)
        if row.clipped:
            x = bar.right() - 5
            y = bar.center().y()
            painter.setPen(QPen(self._colors["text"], 1.0))
            painter.drawLine(QPointF(x - 3, y - 3), QPointF(x, y))
            painter.drawLine(QPointF(x, y), QPointF(x - 3, y + 3))

    def _paintPlayhead(self, painter: QPainter) -> None:
        if self._playhead_ms is None or not self._playhead_key:
            return
        bounds = self._response_bounds.get(self._playhead_key)
        if bounds is None:
            return
        _turn_index, y0, y1, _start, span = bounds
        rect = self._computePlayheadRect()
        if rect.isNull():
            return
        x = rect.center().x()
        if self._effects:
            trail = QColor(self._colors["accent"])
            trail.setAlphaF(0.05)
            lane = self._laneRect()
            ratio = min(1.0, max(0.0, self._playhead_ms / max(1.0, span)))
            painter.fillRect(
                QRectF(
                    lane.left(),
                    y0,
                    max(0.0, ratio * lane.width()),
                    max(1.0, y1 - y0),
                ),
                trail,
            )
        glow = QColor(self._colors["accent"])
        glow.setAlphaF(0.16)
        painter.setPen(QPen(glow, 7.0))
        painter.drawLine(QPointF(x, y0), QPointF(x, y1))
        painter.setPen(QPen(self._colors["accent"], 1.0))
        painter.drawLine(QPointF(x, y0), QPointF(x, y1))

    def _paintHover(self, painter: QPainter) -> None:
        if self._hover_index < 0 or not self._visual:
            return
        index = self._hover_index
        if not (0 <= index < len(self._visual)):
            return
        item = self._visual[index]
        if item.row.kind == "turn":
            return
        lane = self._laneRect()
        x = self._hover_pos.x()
        if lane.left() <= x <= lane.right():
            pen = QPen(self._colors["faint"])
            pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawLine(QPointF(x, item.y), QPointF(x, item.y + item.height))

    # 交互
    def mouseMoveEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        try:
            pos = event.position()
            old_index = self._hover_index
            index = self._indexAt(pos.y())
            if index != old_index:
                if 0 <= old_index < len(self._visual):
                    item = self._visual[old_index]
                    self.update(QRect(0, item.y, self.width(), item.height))
                self._hover_index = index
                if 0 <= index < len(self._visual):
                    item = self._visual[index]
                    self.update(QRect(0, item.y, self.width(), item.height))
            self._hover_pos = pos
            if 0 <= index < len(self._visual):
                item = self._visual[index]
                if index == old_index and self._hover_x >= 0:
                    self.update(
                        QRect(int(self._hover_x) - 2, item.y, 5, item.height + 1)
                    )
                self.update(QRect(int(pos.x()) - 2, item.y, 5, item.height + 1))
                if item.row.kind == "turn":
                    self._hideTooltip()
                else:
                    self._showTooltip(item.row, event.globalPosition().toPoint())
            else:
                self._hideTooltip()
            self._hover_x = pos.x()
        except Exception:
            logger.debug("trace hover failed", exc_info=True)
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        old_index = self._hover_index
        self._hover_index = -1
        self._hover_x = -1.0
        self._hideTooltip()
        if 0 <= old_index < len(self._visual):
            item = self._visual[old_index]
            self.update(QRect(0, item.y, self.width(), item.height))
        super().leaveEvent(event)

    def hideEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        self._hideTooltip()
        super().hideEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        try:
            index = self._indexAt(event.position().y())
            if index < 0:
                return
            self._hover_index = index
            item = self._visual[index]
            if item.row.kind == "turn":
                if event.position().x() <= 26:
                    self.toggleRow(index)
                self.turnActivated.emit(item.turn_index)
                self.activated.emit(item.row.message_id, "")
                return
            indent = 8 + max(0, item.depth) * 13
            if item.row.children and event.position().x() <= indent + 14:
                self.toggleRow(index)
                return
            self.activated.emit(item.row.message_id, item.row.part_id)
            event.accept()
        except Exception:
            logger.debug("trace click failed", exc_info=True)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        if event.button() != Qt.MouseButton.LeftButton:
            super().mouseDoubleClickEvent(event)
            return
        index = self._indexAt(event.position().y())
        if index >= 0:
            self.toggleRow(index)
        event.accept()

    def _ensureTooltip(self) -> ElaToolTip:
        if self._hover_tooltip is not None and is_deleted(self._hover_tooltip):
            self._hover_tooltip = None
        if self._hover_tooltip is None:
            tooltip = ElaToolTip("", self.window())
            tooltip.setMaxWidth(360)
            tooltip.setWordWrap(True)
            tooltip.hide()
            self._hover_tooltip = tooltip
        return self._hover_tooltip

    def _tooltipText(self, row: ElaChatTraceRow) -> str:
        lines = [row.label or row.kind]
        if row.isError:
            lines.append("失败")
        elif row.estimated:
            lines.append("估算")
        if row.detail:
            lines.append(row.detail)
        metrics = [f"耗时 {formatDuration(row.duration_ms) or '未统计'}"]
        if row.tokens:
            metrics.append(f"{row.tokens} 词元")
        if row.cost_usd:
            metrics.append(formatCost(row.cost_usd))
        lines.append(" · ".join(metrics))
        if row.clipped:
            lines.append("显示跨度已裁剪，真实耗时见上")
        return "\n".join(lines)

    def _showTooltip(self, row: ElaChatTraceRow, globalPos) -> None:
        try:
            tooltip = self._ensureTooltip()
            key = _row_key(row)
            if key != self._tooltip_key:
                tooltip.setText(self._tooltipText(row))
                self._tooltip_key = key
            tooltip.showAtPoint(globalPos)
        except Exception:
            logger.debug("trace tooltip failed", exc_info=True)

    def _hideTooltip(self) -> None:
        self._tooltip_key = ""
        tooltip = self._hover_tooltip
        if tooltip is None:
            return
        try:
            if not is_deleted(tooltip):
                tooltip.hide()
        except (RuntimeError, TypeError):
            pass

    def _elide(self, text: str, width: float, metrics: QFontMetrics = None) -> str:
        if width <= 0:
            return ""
        metrics = metrics or self._detail_metrics
        key = (id(metrics), text, int(width) // 8)
        cached = self._elide_cache.get(key)
        if cached is not None:
            return cached
        value = metrics.elidedText(text, Qt.TextElideMode.ElideRight, int(width))
        if len(self._elide_cache) > 4096:
            self._elide_cache.clear()
        self._elide_cache[key] = value
        return value

    def _rowTextColor(self, row: ElaChatTraceRow) -> QColor:
        if row.kind != "turn" and row.isError:
            return self._colors["error"]
        return self._colors["text"]

    def _iconFor(self, row: ElaChatTraceRow) -> str:
        if row.isError:
            return iconGlyph(ElaIconType.IconName.Ban)
        if row.kind == "tool":
            return iconGlyph(toolIconFor(row.label))
        return iconGlyph(_KIND_ICONS.get(row.kind, ElaIconType.IconName.Cube))


class _TraceTrends(QWidget):
    """会话级趋势轨道：工具密度 / token 分层 / 上下文压力。"""

    turnActivated = pyqtSignal(int)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._rows: list = []
        self._current = 0
        self._context_window = 0
        self._theme_mode = None
        self._colors: dict = {}
        self._font = _text_font(10)
        self._metrics = QFontMetrics(self._font)
        self.setFixedHeight(86)
        self.setMouseTracking(True)

    def setResult(self, result: ElaChatTraceResult, contextWindow: int = 0) -> None:
        self._context_window = max(0, int(contextWindow or 0))
        rows = []
        for turn in result.rows:
            tools = 0
            prompt = cache = completion = 0
            context = 0
            for item in turn.walk():
                if item.kind == "tool":
                    tools += 1
                if item.stats is not None:
                    prompt += int(item.stats.prompt_tokens or 0)
                    cache += int(item.stats.cache_read_tokens or 0) + int(
                        item.stats.cache_write_tokens or 0
                    )
                    completion += int(item.stats.completion_tokens or 0)
                if item.context_tokens:
                    context = max(context, item.context_tokens)
            rows.append((tools, prompt, cache, completion, context))
        self._rows = rows
        self.update()

    def setCurrentTurn(self, index: int) -> None:
        self._current = max(0, int(index))
        self.update()

    def setContextWindow(self, value: int) -> None:
        self._context_window = max(0, int(value or 0))
        self.update()

    def applyTheme(self, mode) -> None:
        self._theme_mode = mode
        self._colors = {
            "base": base_color(mode),
            "text": text_color(mode),
            "muted": muted_color(mode, 0.5),
            "accent": accent_color(mode),
            "cache": surface_color(mode, 0.2),
            "warning": statusColor(mode, ElaStatusRoleType.Warning),
            "border": border_color(mode, 0.12),
        }
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt 命名)
        if not self._colors:
            self.applyTheme(None)
        painter = QPainter(self)
        try:
            painter.fillRect(self.rect(), self._colors["base"])
            painter.setPen(QPen(self._colors["border"], 1.0))
            painter.drawLine(0, 0, self.width(), 0)
            if not self._rows:
                return
            lane = QRectF(66, 6, max(40, self.width() - 76), self.height() - 12)
            count = len(self._rows)
            step = lane.width() / max(1, count)
            painter.setFont(self._font)
            painter.setPen(self._colors["muted"])
            painter.drawText(
                QRectF(8, 2, 54, 20),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                "工具",
            )
            painter.drawText(
                QRectF(8, 28, 54, 20),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                "Token",
            )
            painter.drawText(
                QRectF(8, 54, 54, 20),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                "上下文",
            )
            max_tools = max((row[0] for row in self._rows), default=0)
            max_tokens = max(
                (row[1] + row[2] + row[3] for row in self._rows), default=0
            )
            max_context = max((row[4] for row in self._rows), default=0)
            if self._context_window:
                max_context = max(max_context, self._context_window)
            for index, (tools, prompt, cache, completion, context) in enumerate(
                self._rows
            ):
                x = lane.left() + index * step
                width = max(1.0, step - 0.4)
                if max_tools:
                    height = 14.0 * tools / max_tools
                    if height > 0:
                        painter.fillRect(
                            QRectF(x, 24 - height, width, max(1.0, height)),
                            self._colors["accent"],
                        )
                if max_tokens:
                    base_y = 50.0
                    total = prompt + cache + completion
                    full = 14.0 * total / max_tokens
                    cache_h = 14.0 * cache / max_tokens
                    prompt_h = 14.0 * prompt / max_tokens
                    painter.fillRect(
                        QRectF(x, base_y - full, width, full),
                        self._colors["accent"],
                    )
                    painter.fillRect(
                        QRectF(x, base_y - full, width, cache_h + prompt_h),
                        self._colors["cache"],
                    )
            if max_context:
                points = []
                for index, row in enumerate(self._rows):
                    x = lane.left() + (index + 0.5) * step
                    y = 82.0 - 14.0 * min(1.0, row[4] / max_context)
                    points.append(QPointF(x, y))
                painter.setPen(QPen(self._colors["accent"], 1.0))
                painter.drawPolyline(QPolygonF(points))
                if self._context_window:
                    for ratio in (0.7, 0.9):
                        y = 82.0 - 14.0 * ratio
                        pen = QPen(self._colors["warning"], 1.0)
                        pen.setStyle(Qt.PenStyle.DashLine)
                        painter.setPen(pen)
                        painter.drawLine(
                            QPointF(lane.left(), y), QPointF(lane.right(), y)
                        )
            if 0 <= self._current < count:
                x = lane.left() + (self._current + 0.5) * step
                painter.setPen(QPen(self._colors["accent"], 1.0))
                painter.drawLine(QPointF(x, 2), QPointF(x, self.height() - 2))
        except Exception:
            logger.debug("trace trends paint failed", exc_info=True)
        finally:
            painter.end()

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        if not self._rows:
            return
        lane = QRectF(66, 0, max(40, self.width() - 76), self.height())
        if lane.contains(event.position()):
            ratio = (event.position().x() - lane.left()) / max(1.0, lane.width())
            index = min(len(self._rows) - 1, max(0, int(ratio * len(self._rows))))
            self.turnActivated.emit(index)


class _TraceGraphPage(QWidget):
    """当前轮的只读流程图（蓝图画布，懒创建）。"""

    rowActivated = pyqtSignal(int, str)
    turnActivated = pyqtSignal(int)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._result: Optional[ElaChatTraceResult] = None
        self._turn_index = 0
        self._canvas: Optional[ElaBlueprintCanvas] = None
        self._node_rows: dict = {}
        self._dirty = True
        self._replay_ms: Optional[float] = None
        self._label = ColorText(self)
        self._label.setTextFormat(Qt.TextFormat.PlainText)
        self._label.setTextPixelSize(11)
        self._prev = ElaButton("上一轮", variant="text", size="small", parent=self)
        self._next = ElaButton("下一轮", variant="text", size="small", parent=self)
        safe_connect(
            self._prev,
            "clicked",
            lambda _=False: self._step(-1),
            "trace.graph_prev",
            receiver=self._prev,
        )
        safe_connect(
            self._next,
            "clicked",
            lambda _=False: self._step(1),
            "trace.graph_next",
            receiver=self._next,
        )
        bar = QHBoxLayout()
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setSpacing(6)
        bar.addWidget(self._label, 1)
        bar.addWidget(self._prev)
        bar.addWidget(self._next)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(6)
        self._layout.addLayout(bar)

    def setResult(self, result: ElaChatTraceResult) -> None:
        self._result = result
        self._turn_index = min(self._turn_index, max(0, len(result.rows) - 1))
        self._dirty = True
        if self.isVisible():
            self._rebuild()

    def setTurn(self, index: int) -> None:
        if self._result is None:
            return
        index = max(0, min(index, max(0, len(self._result.rows) - 1)))
        if index != self._turn_index:
            self._turn_index = index
            self._dirty = True
        if self.isVisible():
            self._rebuild()

    def currentTurn(self) -> int:
        return self._turn_index

    def setReplayProgress(self, ms: Optional[float]) -> None:
        self._replay_ms = ms
        if self.isVisible():
            self._applyReplay()

    def resetReplay(self) -> None:
        self._replay_ms = None
        if self.isVisible():
            self._applyReplay()

    def applyTheme(self, mode) -> None:
        self._label.setTextColor(muted_color(mode, 0.6))
        self._label.setTextPixelSize(11)

    def showEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        super().showEvent(event)
        if self._dirty:
            self._rebuild()

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        super().resizeEvent(event)
        if self._canvas is not None and self._canvas.isVisible():
            self._canvas.fit_view()

    def _ensureCanvas(self) -> ElaBlueprintCanvas:
        if self._canvas is None:
            self._canvas = ElaBlueprintCanvas(
                ElaBlueprintGraph(),
                self,
                owner=_GRAPH_OWNER,
                use_gl=False,
            )
            self._canvas.setReadOnly(True)
            safe_connect(
                self._canvas,
                "node_activated",
                self._onNodeActivated,
                "trace.graph_node",
                receiver=self._canvas,
            )
            self._layout.addWidget(self._canvas, 1)
            self._scheduleFit()
        return self._canvas

    def _scheduleFit(self) -> None:
        canvas = self._canvas
        if canvas is None:
            return

        def fit() -> None:
            try:
                if not is_deleted(canvas) and canvas.isVisible():
                    canvas.fit_view()
            except Exception:
                logger.debug("trace graph fit failed", exc_info=True)

        single_shot_on(self, 0, fit)

    def _step(self, delta: int) -> None:
        if self._result is None:
            return
        target = max(0, min(len(self._result.rows) - 1, self._turn_index + delta))
        if target != self._turn_index:
            self._turn_index = target
            self._dirty = True
            if self.isVisible():
                self._rebuild()
            self.turnActivated.emit(target)

    def _rebuild(self) -> None:
        try:
            self._rebuild_impl()
        except Exception:
            logger.exception("trace graph rebuild failed")

    def _rebuild_impl(self) -> None:
        self._dirty = False
        _register_graph_types()
        if self._result is None or not self._result.rows:
            self._label.setText("")
            if self._canvas is not None:
                self._canvas.graph.clear()
            return
        total = len(self._result.rows)
        turn = self._result.rows[self._turn_index]
        title = turn.label if len(turn.label) <= 36 else turn.label[:36] + "…"
        self._label.setText(f"第 {self._turn_index + 1}/{total} 轮 · {title}")
        canvas = self._ensureCanvas()
        canvas.setReadOnly(False)
        self._node_rows = {}
        try:
            canvas.graph.clear()
            count = 0

            def add(row: ElaChatTraceRow, parent, depth: int):
                nonlocal count
                if count >= _MAX_GRAPH_NODES:
                    return None
                type_name = _GRAPH_TYPES.get(row.kind, "trace.tool")
                meta = []
                if row.duration_ms:
                    meta.append(formatDuration(row.duration_ms))
                if row.tokens:
                    meta.append(f"{row.tokens} tok")
                node = canvas.create_node(
                    type_name,
                    QPointF(0.0, 0.0),
                    {
                        "detail": row.detail,
                        "meta": " · ".join(meta),
                    },
                    title=row.label or row.kind,
                )
                if node is None:
                    return None
                count += 1
                if row.error_below:
                    node.set_status("error")
                self._node_rows[node.id] = row
                if parent is not None:
                    try:
                        parent.connect(node, "out", "in")
                    except ValueError:
                        pass
                for child in row.children:
                    add(child, node, depth + 1)
                return node

            root = add(turn, None, 0)
            if root is not None:
                self._place(canvas, root)
            if count >= _MAX_GRAPH_NODES:
                self._label.setText(self._label.text() + f" · 仅显示前 {count} 个节点")
            canvas.fit_view()
        finally:
            canvas.setReadOnly(True)
        self._applyReplay()
        self._scheduleFit()

    def _place(self, canvas: ElaBlueprintCanvas, root) -> None:
        children: dict = {}
        for edge in canvas.graph.edges():
            children.setdefault(edge.from_node, []).append(edge.to_node)
        cursor = [0.0]
        seen: set = set()
        node_height = max(
            (float(node.size.height()) for node in canvas.graph.nodes()),
            default=60.0,
        )
        pitch = max(150.0, node_height + 40.0)

        def place(node_id: str, depth: int) -> float:
            node = canvas.graph.node(node_id)
            if node is None or node_id in seen:
                return 0.0
            seen.add(node_id)
            kids = children.get(node_id, [])
            if not kids:
                y = cursor[0]
                cursor[0] += pitch
            else:
                ys = [place(child, depth + 1) for child in kids]
                y = (min(ys) + max(ys)) / 2.0
            node.pos = QPointF(depth * 300.0, y)
            return y

        place(root.id, 0)
        canvas.fit_view()

    def _applyReplay(self) -> None:
        if self._canvas is None:
            return
        ms = self._replay_ms
        for node_id, row in self._node_rows.items():
            node = self._canvas.graph.node(node_id)
            if node is None:
                continue
            if ms is None:
                node.set_status("error" if row.error_below else "idle")
                continue
            if row.start_ms + max(row.span_ms, 1.0) <= ms:
                node.set_status("error" if row.error_below else "done")
            elif row.start_ms <= ms:
                node.set_status("running")
            else:
                node.set_status("idle")

    def _onNodeActivated(self, nodeId: str) -> None:
        row = self._node_rows.get(str(nodeId))
        if row is not None:
            self.rowActivated.emit(row.message_id, row.part_id)


class ElaChatTracePanel(ElaThemeWidget):
    """独立运行轨迹面板（由宿主放进对话框 / ``QSplitter``）。"""

    #: 点击某行（参数：消息 id）
    rowActivated = pyqtSignal(int)
    #: 点击某行（参数：消息 id、分段 id）
    partActivated = pyqtSignal(int, str)
    #: 当前轮变化（参数：轮下标）
    turnChanged = pyqtSignal(int)

    def __init__(
        self,
        view=None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setAutoFillBackground(True)
        self._view = view
        self._result = ElaChatTraceResult()
        self._filter = "all"
        self._options = ElaChatTraceOptions()
        self._context_window = 0
        self._current_turn = 0
        self._syncing = False
        self._replay_timer = QTimer(self)
        self._replay_timer.setInterval(33)
        safe_connect(
            self._replay_timer,
            "timeout",
            self._onReplayTick,
            "trace.replay_tick",
            receiver=self,
        )
        self._replay_active = False
        self._replay_origin_ms = 0.0
        self._replay_origin_time = 0.0
        self._replay_turn = 0
        self._replay_response_index = -1
        self._replay_speed = 1.0
        self._last_replay_ui = 0.0
        self._response_offsets: list = []
        self._response_keys: list = []
        self._response_turns: list = []
        self._response_starts: list = []
        self._response_spans: list = []
        self._response_total = 0.0
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
        header.addWidget(self._title)
        header.addWidget(self._summary, 1)
        header.addWidget(self._refresh_button)
        layout.addLayout(header)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)
        self._view_pivot = ElaPivot(self)
        self._view_pivot.setTextPixelSize(12)
        self._view_pivot.appendPivot("时间轴")
        self._view_pivot.appendPivot("流程图")
        self._view_pivot.setCurrentIndex(0)
        self._filter_pivot = ElaPivot(self)
        self._filter_pivot.setTextPixelSize(12)
        self._filter_pivot.appendPivot("全部")
        self._filter_pivot.appendPivot("仅失败")
        self._filter_pivot.setCurrentIndex(0)
        self._replay_button = ElaButton(
            "回放", variant="text", size="small", parent=self
        )
        self._speed_button = ElaDropDownButton("1×", parent=self)
        self._speed_menu = ElaMenu(self._speed_button)
        for speed in (0.5, 1.0, 2.0, 5.0, 10.0, 20.0):
            action = self._speed_menu.addAction(f"{speed:g}×")
            action.setData(speed)
        self._speed_button.setMenu(self._speed_menu)
        self._clip_label = ColorText(self)
        self._clip_label.setTextFormat(Qt.TextFormat.PlainText)
        self._clip_label.setWordWrap(False)
        safe_connect(
            self._view_pivot,
            "pivotClicked",
            self._onViewPivot,
            "trace.view_pivot",
            receiver=self._view_pivot,
        )
        safe_connect(
            self._filter_pivot,
            "pivotClicked",
            self._onFilterPivot,
            "trace.filter_pivot",
            receiver=self._filter_pivot,
        )
        safe_connect(
            self._replay_button,
            "clicked",
            lambda _=False: self.toggleReplay(),
            "trace.replay",
            receiver=self._replay_button,
        )
        safe_connect(
            self._speed_menu,
            "triggered",
            self._onSpeedAction,
            "trace.speed_menu",
            receiver=self._speed_menu,
        )
        toolbar.addWidget(self._view_pivot)
        toolbar.addSpacing(8)
        toolbar.addWidget(self._filter_pivot)
        toolbar.addSpacing(8)
        toolbar.addWidget(self._replay_button)
        toolbar.addWidget(self._speed_button)
        toolbar.addWidget(self._clip_label, 1)
        layout.addLayout(toolbar)

        self._stack = QStackedWidget(self)
        layout.addWidget(self._stack, 1)

        self._timeline_page = QWidget(self._stack)
        timeline_layout = QVBoxLayout(self._timeline_page)
        timeline_layout.setContentsMargins(0, 0, 0, 0)
        timeline_layout.setSpacing(6)
        self._scroll = ElaScrollArea(self._timeline_page)
        self._scroll.setWidgetResizable(True)
        self._scroll.setVerticalScrollBar(ElaScrollBar(self._scroll))
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._canvas = _TraceCanvas(self._scroll)
        self._scroll.setWidget(self._canvas)
        self._scroll.setAutoFillBackground(False)
        self._scroll.viewport().setAutoFillBackground(False)
        self._canvas.setAutoFillBackground(False)
        timeline_layout.addWidget(self._scroll, 1)
        self._trends = _TraceTrends(self._timeline_page)
        timeline_layout.addWidget(self._trends)
        safe_connect(
            self._scroll.verticalScrollBar(),
            "valueChanged",
            self._canvas.clearHover,
            "trace.scroll_hover",
            receiver=self._canvas,
        )

        self._graph_page = _TraceGraphPage(self._stack)
        self._stack.addWidget(self._timeline_page)
        self._stack.addWidget(self._graph_page)

        self._empty = ColorText("暂无运行记录", self)
        self._empty.setTextFormat(Qt.TextFormat.PlainText)
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._empty, 1)

        safe_connect(
            self._canvas,
            "activated",
            self._onRowActivated,
            "trace.row",
            receiver=self._canvas,
        )
        safe_connect(
            self._canvas,
            "turnActivated",
            self._onTurnActivated,
            "trace.turn",
            receiver=self._canvas,
        )
        safe_connect(
            self._trends,
            "turnActivated",
            self._onTurnActivated,
            "trace.trend_turn",
            receiver=self._trends,
        )
        safe_connect(
            self._graph_page,
            "rowActivated",
            self._onRowActivated,
            "trace.graph_row",
            receiver=self._graph_page,
        )
        safe_connect(
            self._graph_page,
            "turnActivated",
            self._onTurnActivated,
            "trace.graph_turn",
            receiver=self._graph_page,
        )
        self._sync_filter_pivot()
        self._sync_options()
        self._apply_theme()

    # 公共 API
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

    def options(self) -> ElaChatTraceOptions:
        """当前显示选项。"""
        return self._options

    def setOptions(self, options: ElaChatTraceOptions) -> None:
        """整体替换显示选项（热切换）。"""
        if not isinstance(options, ElaChatTraceOptions):
            raise TypeError("options 必须是 ElaChatTraceOptions")
        view = options.view if options.view in ("timeline", "graph") else "timeline"
        self._options = replace(options, view=view)
        self._sync_options()

    def setOption(self, name: str, value) -> None:
        """切换单个选项（``view`` / ``effects`` / ``replay`` / ``tracks``）。"""
        if not hasattr(self._options, name):
            raise AttributeError(f"未知轨迹选项：{name!r}")
        self.setOptions(replace(self._options, **{name: value}))

    def setViewMode(self, mode: str) -> None:
        """切换主视图：``timeline`` / ``graph``。"""
        self.setOptions(replace(self._options, view=mode))

    def setFilter(self, value: str) -> None:
        """筛选：``all`` / ``errors``。"""
        self._filter = "errors" if value == "errors" else "all"
        self._canvas.setFilter(self._filter)
        self._sync_filter_pivot()

    def filter(self) -> str:
        """当前筛选。"""
        return self._filter

    def refresh(self) -> None:
        """重新读取 ``view.messages()`` 并重建视图。"""
        self.stopReplay()
        messages = self._view.messages() if self._view is not None else []
        self._result = buildTraceRows(messages)
        self._build_replay_timeline()
        self._update_summary()
        self._canvas.setResult(self._result, self._filter, self._options.effects)
        self._trends.setResult(self._result, self._context_window)
        self._graph_page.setResult(self._result)
        self._current_turn = min(self._current_turn, max(0, len(self._result.rows) - 1))
        self._trends.setCurrentTurn(self._current_turn)
        self._sync_tracks_visible()
        self._graph_page.setTurn(self._current_turn)
        self._empty.setVisible(self._result.isEmpty())
        self._stack.setVisible(not self._result.isEmpty())
        self._sync_filter_pivot()

    def _build_replay_timeline(self) -> None:
        offsets = []
        keys = []
        turns = []
        starts = []
        spans = []
        total = 0.0
        for turn_index, turn in enumerate(self._result.rows):
            for response in turn.children:
                span = max(1.0, float(response.span_ms or 1.0))
                offsets.append(total)
                keys.append(response.part_id)
                turns.append(turn_index)
                starts.append(max(0.0, float(response.start_ms or 0.0)))
                spans.append(span)
                total += span
        self._response_offsets = offsets
        self._response_keys = keys
        self._response_turns = turns
        self._response_starts = starts
        self._response_spans = spans
        self._response_total = total

    def rows(self) -> list:
        """当前时间轴展示的数据行（测试 / 高级用法）。"""
        return [item.row for item in self._canvas.visualRows()]

    def setContextWindow(self, tokens: int) -> None:
        """设置上下文窗口上限（用于压力轨道的 70% / 90% 阈值线）。"""
        self._context_window = max(0, int(tokens or 0))
        self._trends.setContextWindow(self._context_window)

    def contextWindow(self) -> int:
        """当前上下文窗口上限。"""
        return self._context_window

    def currentTurn(self) -> int:
        """当前轮下标。"""
        return self._current_turn

    def setCurrentTurn(self, index: int) -> None:
        """切换当前轮（流程图 / 趋势轨道 / 回放共用）。"""
        if not self._result.rows:
            return
        index = max(0, min(int(index), len(self._result.rows) - 1))
        if index == self._current_turn:
            return
        self._current_turn = index
        self._trends.setCurrentTurn(index)
        self._graph_page.setTurn(index)
        self.turnChanged.emit(index)

    def startReplay(self) -> None:
        """从当前可见响应开始连续回放到末尾（跨轮 / 跨响应自动推进）。"""
        if not self._result.rows or not self._options.replay:
            return
        if self._replay_active or not self._response_keys:
            return
        if (
            self._response_total > 0
            and self._replay_origin_ms >= self._response_total - 1.0
        ):
            index = 0
        else:
            value = self._scroll.verticalScrollBar().value()
            key = self._canvas.responseKeyAtY(value + 6)
            try:
                index = self._response_keys.index(key)
            except ValueError:
                index = 0
        self._replay_response_index = index
        turn_index = self._response_turns[index]
        self.setCurrentTurn(turn_index)
        self._replay_turn = turn_index
        self._replay_origin_ms = self._response_offsets[index]
        self._replay_origin_time = time.perf_counter()
        self._last_replay_ui = 0.0
        self._replay_active = True
        self._replay_timer.start()
        key = self._response_keys[index]
        self._canvas.setPlayhead(0.0, key)
        self._graph_page.setReplayProgress(self._response_starts[index])
        self._replay_button.setText("停止")
        y = self._canvas.responseY(key)
        if y >= 0:
            self._scroll.verticalScrollBar().setValue(max(0, y - 4))

    def stopReplay(self) -> None:
        """停止回放并清除 playhead。"""
        self._replay_active = False
        self._replay_timer.stop()
        self._canvas.setPlayhead(None)
        self._graph_page.resetReplay()
        self._replay_button.setText("回放")
        self._replay_origin_ms = 0.0
        self._replay_response_index = -1

    def toggleReplay(self) -> None:
        """开始 / 停止回放。"""
        if self._replay_active:
            self.stopReplay()
        else:
            self.startReplay()

    def isReplaying(self) -> bool:
        """是否正在回放。"""
        return self._replay_active

    def replaySpeed(self) -> float:
        """回放倍速。"""
        return self._replay_speed

    def cycleReplaySpeed(self) -> float:
        """切换回放倍速（0.5 / 1 / 2 / 5 / 10 / 20）。"""
        speeds = (0.5, 1.0, 2.0, 5.0, 10.0, 20.0)
        index = speeds.index(self._replay_speed) if self._replay_speed in speeds else 1
        return self.setReplaySpeed(speeds[(index + 1) % len(speeds)])

    def setReplaySpeed(self, speed: float) -> float:
        """设置回放倍速；非法值夹到最近的合法档位。"""
        speeds = (0.5, 1.0, 2.0, 5.0, 10.0, 20.0)
        try:
            value = float(speed)
        except (TypeError, ValueError):
            value = 1.0
        value = min(speeds, key=lambda item: abs(item - value))
        current = self._currentReplayMs() if self._replay_active else 0.0
        self._replay_speed = value
        if self._replay_active:
            self._replay_origin_ms = min(max(0.0, current), self._response_total)
            self._replay_origin_time = time.perf_counter()
        self._speed_button.setText(f"{value:g}×")
        return value

    def _currentReplayMs(self) -> float:
        return (
            self._replay_origin_ms
            + (time.perf_counter() - self._replay_origin_time)
            * 1000.0
            * self._replay_speed
        )

    def _onReplayTick(self) -> None:
        if not self._replay_active or not self._response_keys:
            return
        total = self._response_total
        if total <= 0:
            self.stopReplay()
            return
        global_ms = min(self._currentReplayMs(), total)
        if global_ms >= total:
            self._finishReplay(total)
            return
        index = bisect_right(self._response_offsets, global_ms) - 1
        index = max(0, min(index, len(self._response_keys) - 1))
        local = max(0.0, global_ms - self._response_offsets[index])
        key = self._response_keys[index]
        turn_index = self._response_turns[index]
        turn_local = self._response_starts[index] + local
        if index != self._replay_response_index:
            self._replay_response_index = index
            self._replay_turn = turn_index
            now = time.perf_counter()
            if (
                now - self._last_replay_ui >= 0.08
                or index == len(self._response_keys) - 1
            ):
                self._last_replay_ui = now
                self.setCurrentTurn(turn_index)
                y = self._canvas.responseY(key)
                if y >= 0:
                    self._scroll.verticalScrollBar().setValue(max(0, y - 4))
                self._graph_page.setReplayProgress(turn_local)
        self._canvas.setPlayhead(local, key)
        self._graph_page.setReplayProgress(turn_local)

    def _finishReplay(self, total: float) -> None:
        """自然播完：停表但把 playhead 留在末尾。"""
        self._replay_active = False
        self._replay_timer.stop()
        self._replay_button.setText("回放")
        self._replay_origin_ms = total
        if not self._response_keys:
            return
        last = len(self._response_keys) - 1
        self._replay_response_index = last
        turn_index = self._response_turns[last]
        key = self._response_keys[last]
        self._replay_turn = turn_index
        self.setCurrentTurn(turn_index)
        y = self._canvas.responseY(key)
        if y >= 0:
            self._scroll.verticalScrollBar().setValue(max(0, y - 4))
        local = self._response_spans[last]
        self._canvas.setPlayhead(local, key)
        self._graph_page.setReplayProgress(self._response_starts[last] + local)

    # 内部
    def _onRowActivated(self, messageId: int, partId: str) -> None:
        try:
            visual = self._canvas.hoveredVisualRow()
            if visual is not None:
                self.setCurrentTurn(visual.turn_index)
            self.rowActivated.emit(int(messageId or 0))
            self.partActivated.emit(int(messageId or 0), str(partId or ""))
        except Exception:
            logger.debug("trace row activation failed", exc_info=True)

    def _onTurnActivated(self, index: int) -> None:
        self.setCurrentTurn(index)
        y = self._canvas.turnY(index)
        if y >= 0:
            self._scroll.verticalScrollBar().setValue(max(0, y - 4))

    def _update_summary(self) -> None:
        result = self._result
        if result.isEmpty():
            self._summary.setText("")
            self._clip_label.setText("")
            return
        parts = [
            f"{len(result.rows)} 轮",
            f"{sum(len(turn.children) for turn in result.rows)} 次响应",
            f"{result.tool_count} 次工具",
        ]
        if result.error_count:
            parts.append(f"{result.error_count} 失败")
        duration = _summary_duration(result.total_duration_ms)
        if duration:
            parts.append(duration)
        if result.tokens:
            parts.append(f"{result.tokens} tok")
        if result.cost_usd:
            parts.append(formatCost(result.cost_usd))
        self._summary.setText(" · ".join(parts))
        if result.clipped_count:
            self._clip_label.setText(f"{result.clipped_count} 项耗时已裁剪")
        else:
            self._clip_label.setText("")

    def _sync_filter_pivot(self) -> None:
        self._syncing = True
        try:
            self._filter_pivot.setCurrentIndex(1 if self._filter == "errors" else 0)
        finally:
            self._syncing = False

    def _onViewPivot(self, index: int) -> None:
        if self._syncing:
            return
        self.setViewMode("graph" if int(index) == 1 else "timeline")

    def _onFilterPivot(self, index: int) -> None:
        if self._syncing:
            return
        self.setFilter("errors" if int(index) == 1 else "all")

    def _onSpeedAction(self, action) -> None:
        try:
            value = action.data()
        except (AttributeError, RuntimeError):
            value = 1.0
        try:
            self.setReplaySpeed(float(value))
        except (TypeError, ValueError):
            self.setReplaySpeed(1.0)

    def _sync_options(self) -> None:
        graph = self._options.view == "graph"
        self._stack.setCurrentWidget(self._graph_page if graph else self._timeline_page)
        self._syncing = True
        try:
            self._view_pivot.setCurrentIndex(1 if graph else 0)
        finally:
            self._syncing = False
        self._canvas.setEffects(self._options.effects)
        self._sync_tracks_visible()
        self._replay_button.setVisible(self._options.replay)
        self._speed_button.setVisible(self._options.replay)
        if graph:
            index = self._canvas.turnAtY(
                self._scroll.verticalScrollBar().value()
                + self._scroll.viewport().height() // 2
            )
            if index >= 0:
                self.setCurrentTurn(index)
            self._graph_page.setTurn(self._current_turn)
        if not self._options.replay:
            self.stopReplay()

    def _sync_tracks_visible(self) -> None:
        self._trends.setVisible(
            self._options.tracks
            and self._options.view != "graph"
            and len(self._result.rows) > 1
        )

    def _apply_theme(self) -> None:
        mode = self._theme_mode
        self.update()
        self._scroll.viewport().setAutoFillBackground(False)
        self._canvas.setAutoFillBackground(False)
        self._title.setTextColor(text_color(mode))
        self._title.setTextPixelSize(14)
        self._summary.setTextColor(muted_color(mode, 0.6))
        self._summary.setTextPixelSize(12)
        self._clip_label.setTextColor(statusColor(mode, ElaStatusRoleType.Warning))
        self._clip_label.setTextPixelSize(10)
        self._empty.setTextColor(muted_color(mode, 0.5))
        self._empty.setTextPixelSize(12)
        self._canvas.applyTheme(mode)
        self._trends.applyTheme(mode)
        self._graph_page.applyTheme(mode)

    def _onThemeChanged(self, mode: ElaThemeType.ThemeMode) -> None:
        super()._onThemeChanged(mode)
        self._apply_theme()

    def hideEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        self.stopReplay()
        self._canvas.clearHover()
        super().hideEvent(event)


__all__ = [
    "ElaChatTraceOptions",
    "ElaChatTracePanel",
]
