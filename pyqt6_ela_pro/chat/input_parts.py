"""输入区内部控件：编辑器 / 输入卡片 / 上下文占用圆环。"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QFontMetrics,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
)
from PyQt6.QtWidgets import QSizePolicy, QWidget
from PyQt6ElaWidgetTools import ElaPlainTextEdit, ElaThemeType

from .._theme import ElaStatusRoleType, statusColor
from ..tooltips import ElaToolTipPositionType, set_tooltip
from ..widget_base import ElaThemeWidget
from ._mime import localFiles, mimeImage
from ._pricing import formatCost
from ._theme import (
    accent_color,
    base_color,
    blend,
    card_border_color,
    card_color,
    muted_color,
    text_color,
)
from .message import _as_int

_LARGE_PASTE_CHARS = 8000
_LARGE_PASTE_LINES = 120
_USAGE_RING_SIZE = 22
_USAGE_WARN_PERCENT = 60
_USAGE_DANGER_PERCENT = 85
_INPUT_CARD_RADIUS = 10
_INPUT_CARD_PADDING = (12, 10, 12, 6)
_INPUT_CARD_SPACING = 4


class _ChatPlainTextEdit(ElaPlainTextEdit):
    """输入编辑器：内容自增高 + 粘贴 / 拖入转附件。
    自增高走 ``sizeHint()``；``textChanged`` 槽只 ``updateGeometry()``，绝不在槽内改
    几何（重入布局 = 0xC0000409）。文件 / 图片与大段文本的落盘交给 :class:`ElaChatInput`。
    """

    #: 剪贴板图片被粘贴 / 图片被拖入（参数：``QImage``）
    imagePasted = pyqtSignal(QImage)
    #: 本地文件被粘贴 / 拖入（参数：本地文件路径列表）
    filesAdded = pyqtSignal(list)
    #: 大段文本被粘贴 / 拖入（参数：文本）；编辑器不写盘，由 :class:`ElaChatInput` 落临时文件
    largeTextPasted = pyqtSignal(str)
    #: 输入法组合文本变化（参数：preedit 串）
    preeditChanged = pyqtSignal(str)
    #: 焦点变化（参数：是否聚焦）
    focusChanged = pyqtSignal(bool)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._min_lines = 1
        self._max_lines = 8
        self._key_handler = None
        # 高度跟着 sizeHint 走（Fixed）；宽度仍由卡片布局拉伸
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def setKeyHandler(self, handler) -> None:  # noqa: N802
        """注入按键处理器（``handler(event) -> bool``，``True`` = 已消费）。
        不用事件过滤器：给随行销毁的子控件 ``installEventFilter(parent)``，在父窗口
        树整体析构时会踩 0xC0000409。
        """
        self._key_handler = handler

    def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        if self._key_handler is not None and self._key_handler(event):
            event.accept()
            return
        super().keyPressEvent(event)

    def inputMethodEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        self.preeditChanged.emit(event.preeditString())
        super().inputMethodEvent(event)

    def focusInEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        super().focusInEvent(event)
        self.focusChanged.emit(True)

    def focusOutEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        super().focusOutEvent(event)
        self.focusChanged.emit(False)

    def setLineBudget(self, minLines: int, maxLines: int) -> None:  # noqa: N802
        """设置可见行数预算（超过 ``maxLines`` 后内部滚动）。"""
        self._min_lines = max(1, _as_int(minLines, 1))
        self._max_lines = max(self._min_lines, _as_int(maxLines, self._min_lines))
        self.updateGeometry()

    def _content_height(self) -> int:
        """按当前宽度与内容算像素高度（夹在行数预算内）。"""
        document = self.document()
        width = self.viewport().width()
        if width > 0:
            document.setTextWidth(width)
        line = QFontMetrics(self.font()).lineSpacing()
        min_height = line * self._min_lines
        max_height = line * self._max_lines
        height = 0.0
        block = document.begin()
        while block.isValid():
            height += self.blockBoundingRect(block).height()
            if height >= max_height:
                # 已超上限：sizeHint 会被布局反复询问，不必再数后面的块
                break
            block = block.next()
        return int(min(max(height, min_height), max_height))

    def sizeHint(self) -> QSize:  # noqa: N802
        hint = super().sizeHint()
        return QSize(hint.width(), self._content_height())

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        hint = super().minimumSizeHint()
        return QSize(hint.width(), self._content_height())

    def canInsertFromMimeData(self, source) -> bool:  # noqa: N802 (Qt 命名)
        return True

    def insertFromMimeData(self, source) -> None:  # noqa: N802 (Qt 命名)
        files = localFiles(source)
        if files:
            self.filesAdded.emit(files)
            return
        image = mimeImage(source)
        if image is not None:
            self.imagePasted.emit(image)
            return
        text = source.text() if source.hasText() else ""
        if text and (
            len(text) >= _LARGE_PASTE_CHARS or text.count("\n") >= _LARGE_PASTE_LINES
        ):
            # 大段粘贴**不塞进编辑框**：转附件（宿主按文件路径读内容）。
            # 编辑器自己不写盘（分层），落盘在 ElaChatInput 里做。
            self.largeTextPasted.emit(text)
            return
        super().insertFromMimeData(source)


class _InputSurface(ElaThemeWidget):
    """输入卡片：包裹附件条 / 编辑框 / 工具栏，自绘圆角边框与聚焦态。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._focused = False
        self._bg = QColor()
        self._border = QColor()
        self._apply_theme()

    def setFocused(self, on: bool) -> None:
        """设置聚焦态（聚焦时边框换强调色）。"""
        on = bool(on)
        if on == self._focused:
            return
        self._focused = on
        self._apply_theme()

    def focused(self) -> bool:
        """是否处于聚焦态。"""
        return self._focused

    def _onThemeChanged(self, mode: ElaThemeType.ThemeMode) -> None:
        super()._onThemeChanged(mode)
        self._apply_theme()

    def _apply_theme(self) -> None:
        mode = self._theme_mode
        self._bg = card_color(mode)
        self._border = accent_color(mode) if self._focused else card_border_color(mode)
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt 命名)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, _INPUT_CARD_RADIUS, _INPUT_CARD_RADIUS)
        painter.fillPath(path, self._bg)
        pen = QPen(self._border)
        pen.setWidthF(1.0)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        painter.end()


def _shortTokens(value) -> str:
    """词元数缩写（``187431`` -> ``187.4k``）。"""
    try:
        number = float(value or 0)
    except (TypeError, ValueError, OverflowError):
        return "0"
    if number < 0:
        number = 0.0
    if number < 1000:
        return str(int(number))
    if number < 1_000_000:
        return f"{number / 1000:.1f}k"
    return f"{number / 1_000_000:.1f}M"


class _ContextUsageRing(ElaThemeWidget):
    """上下文窗口占用指示器（工具栏小圆环 + hover 详情）。
    自绘而非 ``ElaProgressRing``：后者环色硬编码在 C++ 侧，而变色正是本控件的价值。
    三档：< 60% 弱化、60~85% 警示、> 85% 危险；默认常驻（无数据画空底环）。
    """

    #: 点击圆环（宿主据此弹上下文详情面板等；组件自身不做行为）
    clicked = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._used = 0
        self._window = 0
        self._cost_usd = 0.0
        self._hover = False
        self._pressed = False
        self.setFixedSize(_USAGE_RING_SIZE, _USAGE_RING_SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAccessibleName("上下文占用")
        # 刻意不在这里 hide()：它是工具栏默认组件，无数据时画空底环

    def setUsage(self, used: int, window: int, costUsd: float = 0.0) -> None:
        """设置占用（``window <= 0`` 按 0% 显示；控件默认常驻、不再因此隐藏）。"""
        try:
            self._used = max(0, int(used or 0))
            self._window = max(0, int(window or 0))
            self._cost_usd = float(costUsd or 0.0)
        except (TypeError, ValueError, OverflowError):
            self._used = self._window = 0
            self._cost_usd = 0.0
        self._sync()

    def usage(self) -> tuple:
        """获取 ``(已用, 窗口, 花费美元)``。"""
        return (self._used, self._window, self._cost_usd)

    def percent(self) -> int:
        """占用百分比（窗口未知返回 0）。"""
        if self._window <= 0:
            return 0
        return max(0, min(100, round(self._used * 100 / self._window)))

    def level(self) -> int:
        """档位：``0`` 正常 / ``1`` 警示 / ``2`` 危险。"""
        percent = self.percent()
        if percent >= _USAGE_DANGER_PERCENT:
            return 2
        if percent >= _USAGE_WARN_PERCENT:
            return 1
        return 0

    def tooltipText(self) -> str:
        """hover 详情文案（花费 / 百分比 / 词元总数 / 危险提示）。"""
        lines = []
        if self._cost_usd > 0:
            lines.append(f"花费 {formatCost(self._cost_usd)}")
        if self._window > 0:
            lines.append(
                f"上下文 {self.percent()}%"
                f"（{_shortTokens(self._used)} / {_shortTokens(self._window)}）"
            )
        elif self._used > 0:
            lines.append(f"上下文 {_shortTokens(self._used)} 词元")
        else:
            lines.append("上下文占用：暂无数据")
        if self.level() == 2:
            lines.append("上下文接近上限，建议压缩历史")
        return "\n".join(lines)

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            self.update()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        if event.button() == Qt.MouseButton.LeftButton and self._pressed:
            self._pressed = False
            self.update()
            # 只在圆环内松开才算点击（拖出取消，与普通按钮一致）
            if self.rect().contains(event.position().toPoint()):
                self.clicked.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def enterEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        self._hover = False
        self._pressed = False
        self.update()
        super().leaveEvent(event)

    def _sync(self) -> None:
        # 显隐只由 setContextUsageVisible 控制；输入区贴窗口底部 → tooltip 朝上弹
        set_tooltip(self, self.tooltipText(), ElaToolTipPositionType.Top)
        self.update()

    def _arc_color(self):
        mode = self._theme_mode
        base = accent_color(mode)
        level = self.level()
        if level == 2:
            return statusColor(mode, ElaStatusRoleType.Error)
        if level == 1:
            return blend(base, statusColor(mode, ElaStatusRoleType.Warning), 0.75)
        # 低占用刻意弱化：它是「状态」不是「主角」，不该抢注意力
        return blend(muted_color(mode, 0.5), base, 0.35)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        inset = 2.5
        track = QRectF(self.rect()).adjusted(inset, inset, -inset, -inset)
        width = 2.0
        mode = self._theme_mode
        # 按钮式状态层：hover 8% / press 12%（与 ElaButton 同一套比例）
        if self._hover or self._pressed:
            ratio = 0.12 if self._pressed else 0.08
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(blend(base_color(mode), text_color(mode), ratio))
            painter.drawEllipse(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5))
        # 底环：与值环同粗细的浅色圆环，让「还剩多少」可读
        painter.setPen(QPen(blend(base_color(mode), text_color(mode), 0.16), width))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(track)
        # 值环：从 12 点顺时针（drawArc 起点 90°、负角度为正方向）
        percent = self.percent()
        if percent > 0:
            painter.setPen(QPen(self._arc_color(), width))
            painter.drawArc(
                track,
                90 * 16,
                -int(round(percent * 360 / 100)) * 16,
            )
        painter.end()

    def _onThemeChanged(self, mode: ElaThemeType.ThemeMode) -> None:
        super()._onThemeChanged(mode)
        self.update()
