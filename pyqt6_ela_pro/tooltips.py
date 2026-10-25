"""
工具提示组件模块。

提供两种提示组件：

- ``ElaToolTip``：悬浮提示组件，支持 8 种显示位置
- ``ElaStateToolTip``：带状态指示的提示组件，支持加载中/成功/失败等状态

``set_tooltip`` 和 ``remove_tooltip`` 函数用于为任意 ``QWidget`` 绑定或解除
悬浮提示，使用弱引用字典管理，不会阻止 widget 被垃圾回收。
"""

from __future__ import annotations

from enum import Enum
from typing import Optional
import weakref

from PyQt6.QtCore import (
    QObject,
    QPropertyAnimation,
    Qt,
    QTimer,
    pyqtSignal,
    QPoint,
    QRect,
    QEvent,
    QRectF,
)

from ._colors import parse_color
from ._internal import is_deleted, single_shot_on
from ._motion import Duration, start_idle_loop, start_transition
from .widget_base import ElaThemeWidget
from PyQt6.QtGui import (
    QPainter,
    QFont,
    QBrush,
    QColor,
    QPaintEvent,
    QHideEvent,
    QShowEvent,
    QMouseEvent,
    QPen,
    QPainterPath,
)
from PyQt6.QtWidgets import QApplication, QWidget, QLabel, QGraphicsDropShadowEffect

from PyQt6ElaWidgetTools import eTheme, ElaThemeType, ElaIconType, ElaText


TOOLTIP_BORDER_RADIUS: int = 8
TOOLTIP_SHADOW_BORDER_WIDTH: int = 3
TOOLTIP_LIGHT_BG_COLOR: str = "#ffffff"
TOOLTIP_DARK_BG_COLOR: str = "#202020"
#: ``Full`` 模式下的淡出时长。实际时长受全局动效策略约束
#: （``Reduced`` 压到 ≤50ms、``Disabled`` 同步落终值，见 :mod:`._motion`）。
TOOLTIP_FADE_DURATION: int = Duration.Fast
TOOLTIP_AUTO_CLOSE_DELAY: int = 1000
TOOLTIP_ROTATE_TIMER_INTERVAL: int = 50
TOOLTIP_ROTATE_ANGLE_DELTA: int = 20

STATETOOLTIP_BORDER_RADIUS: int = 10
STATETOOLTIP_TITLE_FONT_SIZE: int = 14
STATETOOLTIP_CONTENT_FONT_SIZE: int = 13
STATETOOLTIP_MIN_WIDTH: int = 200
STATETOOLTIP_MAX_WIDTH: int = 360
STATETOOLTIP_HEIGHT: int = 56
STATETOOLTIP_CLOSE_BUTTON_SIZE: int = 20
STATETOOLTIP_ICON_SIZE: int = 16
STATETOOLTIP_ACCENT_WIDTH: int = 4
STATETOOLTIP_SUCCESS_COLOR_LIGHT: str = "#4CAF50"
STATETOOLTIP_SUCCESS_COLOR_DARK: str = "#66BB6A"


class ElaToolTipPositionType(Enum):
    """提示框相对于目标 widget 的显示位置枚举。"""

    Top = 0
    """显示在目标上方"""

    Bottom = 1
    """显示在目标下方"""

    Left = 2
    """显示在目标左侧"""

    Right = 3
    """显示在目标右侧"""

    TopLeft = 4
    """显示在目标左上方"""

    TopRight = 5
    """显示在目标右上方"""

    BottomLeft = 6
    """显示在目标左下方"""

    BottomRight = 7
    """显示在目标右下方"""


class _ToolTipLabel(QLabel):
    """提示文本标签：绘制前自愈显式色。

    提示框是原生 ``Qt.Tool`` 顶层窗；创建 / 改窗口标志 / 平台样式切换都可能把
    子标签的 palette 刷回应用默认色（深色下就是黑字）。和 ``ColorText`` 同一套
    做法：颜色存实例上，绘制前发现 palette 被改回就重写一次。
    """

    def __init__(self, text: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(text, parent)
        self._text_color: Optional[QColor] = None

    def setTextColor(self, color) -> None:  # noqa: N802 (Qt 命名)
        self._text_color = parse_color(color)
        self._apply_text_color()

    def _apply_text_color(self) -> None:
        if self._text_color is None:
            return
        palette = self.palette()
        role = self.foregroundRole()
        if palette.color(role) != self._text_color:
            palette.setColor(role, self._text_color)
            self.setPalette(palette)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        self._apply_text_color()
        super().paintEvent(event)


class ElaToolTip(QWidget):
    """轻量级悬浮提示组件。

    圆角阴影背景框 + 文本标签，通过 :meth:`showAt` 指定目标 widget 与显示位置。
    """

    def __init__(self, text: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._text = text
        self._borderRadius = TOOLTIP_BORDER_RADIUS
        self._shadowBorderWidth = TOOLTIP_SHADOW_BORDER_WIDTH
        self._currentTheme = eTheme.getThemeMode()
        #: 多行模式（配合 ``_max_width``）：长文本折行而不是拉成超宽单行
        self._word_wrap = False
        self._max_width = 0
        #: 自定义内容控件（非 None 时隐藏文本标签、尺寸跟随它）
        self._content_widget: Optional[QWidget] = None
        #: 窗口标志延迟到首次显示 / 查询时再设：构造期 setWindowFlags 会创建
        #: 原生 top-level 窗口，滚动时批量物化消息会连续闪出小 Qt 窗口。
        self._flags_ready = False

        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # 父窗口尚未 show 时创建的子控件会随父窗口一起显示：本组件此时还没
        # showAt 定位，不显式隐藏就会被画在父窗口左上角（宿主在窗口 show 之前
        # 建聊天页 / 工具栏时必中）。
        self.hide()

        self._label = _ToolTipLabel(text, self)
        self._label.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        font = QFont()
        font.setPixelSize(12)
        self._label.setFont(font)
        self._apply_text_color()

        # 跟随主题切换（绑定方法连接，对象销毁时 Qt 自动断开）
        eTheme.themeModeChanged.connect(self._onThemeChanged)

        self._updateSize()

    def _ensureWindowFlags(self) -> None:
        """首次显示 / 查询时再设 Tool 窗口标志（避免构造期创建原生窗口）。"""
        if self._flags_ready:
            return
        self._flags_ready = True
        self.setWindowFlags(
            Qt.WindowType.Tool  # type: ignore[arg-type]
            | Qt.WindowType.FramelessWindowHint  # type: ignore[arg-type]
            | Qt.WindowType.WindowStaysOnTopHint  # type: ignore[arg-type]
        )

    def windowFlags(self):
        """读取窗口标志时补设（测试 / 宿主查询不改变「延迟到显示」的语义）。"""
        self._ensureWindowFlags()
        return super().windowFlags()

    def show(self) -> None:
        """显示前补设窗口标志。"""
        self._ensureWindowFlags()
        super().show()

    def _apply_text_color(self) -> None:
        """按当前主题设置标签文字颜色（否则深色背景下文字不可见）。"""
        color = eTheme.getThemeColor(
            self._currentTheme, ElaThemeType.ThemeColor.BasicText
        )
        self._label.setTextColor(color)

    def _onThemeChanged(self, mode: ElaThemeType.ThemeMode) -> None:
        """主题切换：更新底色、边框与文字颜色。"""
        self._currentTheme = mode
        self._apply_text_color()
        self.update()

    def setWordWrap(self, on: bool) -> None:  # noqa: N802 (Qt 命名)
        """多行模式：长文本折行。与 :meth:`setMaxWidth` 配合使用。"""
        self._word_wrap = bool(on)
        self._label.setWordWrap(self._word_wrap)
        self._updateSize()

    def setMaxWidth(self, width: int) -> None:  # noqa: N802 (Qt 命名)
        """最大宽度（像素，``0`` = 不限）。只影响折行布局，不截断文本。"""
        self._max_width = max(0, int(width))
        self._updateSize()

    def setContentWidget(self, widget: Optional[QWidget]) -> None:  # noqa: N802
        """用任意控件当提示内容（对齐上游 ``ElaToolTip.setCustomWidget``）。

        - ``None`` / 传自身会被忽略（与上游同）；
        - **替换时旧控件会被 ``deleteLater()``** —— 提示框持有内容控件的所有权，
          提示框销毁（``remove_tooltip`` / ``deleteLater``）时内容一并销毁；
        - 设置后文本标签隐藏，弹体尺寸跟随 ``widget.sizeHint()``（无效时取
          ``widget.size()``）。
        """
        if widget is None or widget is self or widget is self._content_widget:
            return
        old = self._content_widget
        if old is not None:
            old.hide()
            old.setParent(None)
            old.deleteLater()
        self._content_widget = widget
        widget.setParent(self)
        self._label.hide()
        self._updateSize()

    def contentWidget(self) -> Optional[QWidget]:  # noqa: N802 (Qt 命名)
        """当前自定义内容控件（未设置时为 ``None``，此时显示文本标签）。"""
        return self._content_widget

    def _updateSize(self) -> None:
        """根据内容更新 tooltip 的固定尺寸（自定义控件 / 多行折行 / 单行）。"""
        if self._content_widget is not None:
            widget = self._content_widget
            # 显式 setFixedSize 的内容控件以固定尺寸为准 —— layout 的 sizeHint 可能
            # 小于固定尺寸，按 hint 定弹体会让内容溢出被裁（实测两行卡片裁掉尾字）。
            if widget.minimumSize() == widget.maximumSize():
                hint = widget.size()
            else:
                hint = widget.sizeHint()
            if not hint.isValid() or hint.isEmpty():
                hint = widget.size()
            width = max(1, hint.width()) + 24
            height = max(1, hint.height()) + 16
            widget.setGeometry(12, 8, width - 24, height - 16)
            self.setFixedSize(width, height)
            return
        if self._word_wrap and self._max_width > 0:
            inner = max(1, self._max_width - 24)
            metrics = self._label.fontMetrics()
            rect = metrics.boundingRect(
                QRect(0, 0, inner, 0), Qt.TextFlag.TextWordWrap, self._text
            )
            if rect.width() > inner:
                # 无空格的长串（URL / base64 / 一长串英文）按词边界折不开 ——
                # 退回「任意位置换行」，否则文本会被裁掉
                rect = metrics.boundingRect(
                    QRect(0, 0, inner, 0), Qt.TextFlag.TextWrapAnywhere, self._text
                )
            width = min(self._max_width, rect.width() + 24)
            height = rect.height() + 16
            self._label.setFixedSize(max(0, width - 24), max(0, height - 16))
            self.setFixedSize(width, height)
            self._label.move(12, 8)
            return
        # 回到单行布局前必须清掉上一轮的固定尺寸，否则 adjustSize 不再生效
        self._label.setMinimumSize(0, 0)
        self._label.setMaximumSize(16777215, 16777215)
        self._label.adjustSize()
        width = self._label.width() + 24
        height = self._label.height() + 16
        self.setFixedSize(width, height)
        self._label.move(12, 8)

    def setText(self, text: str) -> None:
        self._text = text
        self._label.setText(text)
        self._updateSize()

    def paintEvent(self, _a0: Optional[QPaintEvent]) -> None:
        painter = QPainter(self)
        painter.setRenderHints(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)

        themeMode = self._currentTheme

        eTheme.drawEffectShadow(
            painter, self.rect(), self._shadowBorderWidth, self._borderRadius
        )

        bgColor = eTheme.getThemeColor(themeMode, ElaThemeType.ThemeColor.BasicBase)
        borderColor = eTheme.getThemeColor(
            themeMode, ElaThemeType.ThemeColor.BasicBaseLine
        )
        painter.setPen(borderColor)
        painter.setBrush(QBrush(bgColor))
        painter.drawRoundedRect(
            QRect(3, 3, self.width() - 6, self.height() - 6),
            self._borderRadius,
            self._borderRadius,
        )

    def showAt(
        self,
        widget: QWidget,
        position: ElaToolTipPositionType = ElaToolTipPositionType.Top,
    ) -> None:
        """在指定 widget 附近按 *position* 显示（最后会收敛进屏幕工作区）。"""
        self._ensureWindowFlags()
        if not self.isWindow():
            self.setParent(None)

        try:
            globalPos = widget.mapToGlobal(QPoint(0, 0))
        except (RuntimeError, AttributeError):
            return
        widgetRect = QRect(globalPos, widget.size())

        if position == ElaToolTipPositionType.Top:
            x = widgetRect.center().x() - self.width() // 2
            y = widgetRect.top() - self.height() - 6
        elif position == ElaToolTipPositionType.Bottom:
            x = widgetRect.center().x() - self.width() // 2
            y = widgetRect.bottom() + 6
        elif position == ElaToolTipPositionType.Left:
            x = widgetRect.left() - self.width() - 6
            y = widgetRect.center().y() - self.height() // 2
        elif position == ElaToolTipPositionType.Right:
            x = widgetRect.right() + 6
            y = widgetRect.center().y() - self.height() // 2
        elif position == ElaToolTipPositionType.TopLeft:
            x = widgetRect.left()
            y = widgetRect.top() - self.height() - 6
        elif position == ElaToolTipPositionType.TopRight:
            x = widgetRect.right() - self.width()
            y = widgetRect.top() - self.height() - 6
        elif position == ElaToolTipPositionType.BottomLeft:
            x = widgetRect.left()
            y = widgetRect.bottom() + 6
        elif position == ElaToolTipPositionType.BottomRight:
            x = widgetRect.right() - self.width()
            y = widgetRect.bottom() + 6
        else:
            x = widgetRect.center().x() - self.width() // 2
            y = widgetRect.top() - self.height() - 6

        above = position in (
            ElaToolTipPositionType.Top,
            ElaToolTipPositionType.TopLeft,
            ElaToolTipPositionType.TopRight,
        )
        x, y = self._clamp_to_screen(x, y, widget, above)
        self.move(int(x), int(y))
        self.show()

    def _clamp_to_screen(self, x: int, y: int, widget: QWidget, above: bool) -> tuple:
        """把提示框收敛到目标 widget 所在屏幕的工作区：上方放不下翻到下方、反之亦然。"""
        try:
            screen = QApplication.screenAt(widget.mapToGlobal(widget.rect().center()))
            if screen is None:
                screen = QApplication.primaryScreen()
            if screen is None:
                return x, y
            area = screen.availableGeometry()
            widgetRect = QRect(widget.mapToGlobal(QPoint(0, 0)), widget.size())
        except (RuntimeError, AttributeError):
            return x, y
        if above and y < area.top():
            y = widgetRect.bottom() + 6
        elif not above and y + self.height() > area.bottom() + 1:
            y = widgetRect.top() - self.height() - 6
        x = max(area.left(), min(x, area.right() - self.width() + 1))
        y = max(area.top(), min(y, area.bottom() - self.height() + 1))
        return x, y


_tooltip_dict: weakref.WeakKeyDictionary[QWidget, ElaToolTip] = (
    weakref.WeakKeyDictionary()
)
_filter_dict: weakref.WeakKeyDictionary[QWidget, _TooltipEventFilter] = (
    weakref.WeakKeyDictionary()
)


class _TooltipEventFilter(QObject):
    """事件过滤器，监听目标 widget 的进入 / 离开以显示或隐藏提示框。"""

    def __init__(
        self,
        tooltip: ElaToolTip,
        position: ElaToolTipPositionType,
        target_widget: QWidget,
    ) -> None:
        super().__init__(target_widget)
        self._tooltip: weakref.ref[ElaToolTip] = weakref.ref(tooltip)
        self._position = position

    def setPosition(self, position: ElaToolTipPositionType) -> None:
        """更新显示位置（同一 widget 重新绑定时复用提示框）。"""
        self._position = position

    def eventFilter(self, a0: Optional[QObject], a1: Optional[QEvent]) -> bool:
        """进入显示、离开隐藏；``QEvent.Type.ToolTip`` 一律吞掉（否则原生提示会一起弹出）。"""
        tooltip = self._tooltip()
        if tooltip is None or a0 is None or a1 is None:
            return False
        eventType = a1.type()
        if eventType == QEvent.Type.Enter:
            if isinstance(a0, QWidget):
                tooltip.showAt(a0, self._position)
        elif eventType == QEvent.Type.Leave:
            tooltip.hide()
        elif eventType == QEvent.Type.ToolTip:
            return True
        return False


def remove_tooltip_from_dict(widget: QWidget) -> None:
    """内部用：从全局字典移除并销毁 widget 的 tooltip（:func:`remove_tooltip` 会调）。"""
    if widget in _tooltip_dict:
        tooltip = _tooltip_dict.pop(widget)
        try:
            tooltip.hide()
            tooltip.deleteLater()
        except RuntimeError:
            pass
    if widget in _filter_dict:
        _filter_dict.pop(widget)


def set_tooltip(
    widget: QWidget,
    text: str,
    position: ElaToolTipPositionType = ElaToolTipPositionType.Top,
    *,
    maxWidth: int = 0,
    wordWrap: bool = False,
    contentWidget: Optional[QWidget] = None,
) -> None:
    """为 widget 绑定悬浮提示。

    装上事件过滤器，鼠标进入显示、离开隐藏。同一 widget 重复调用**复用**已有
    提示框（只更新文本 / 折行配置 / 位置）：``ElaToolTip`` 构造要排一次文本，
    批量物化时每次 remove + new 是纯浪费（聊天一次恢复实测 4609 次创建）。
    从自定义内容退回纯文本时没有清空 API，才重建。
    绑定后会吞掉 ``QEvent.Type.ToolTip``（原生 ``QToolTip`` 与自定义提示会同时弹出）。

    ``maxWidth`` / ``wordWrap`` 用于长文本：默认单行（宽度=文本宽度），超长
    文本会拉成一条远宽于屏幕的横条；开启折行后按 ``maxWidth`` 换行。

    ``contentWidget`` 给定时用该控件替代文本（透传
    :meth:`ElaToolTip.setContentWidget`，此时忽略 ``text`` / ``maxWidth`` /
    ``wordWrap`` 的展示，控件所有权归提示框）。
    """
    existing = _tooltip_dict.get(widget)
    if existing is not None and not is_deleted(existing):
        if contentWidget is None and existing.contentWidget() is None:
            # 复用：只改配置与文本。每次 remove + new 会重建 QWidget，并在
            # Win7 上重排一次提示文本（聊天里 4609 次/会话，bug #17）。
            existing.setWordWrap(bool(wordWrap))
            existing.setMaxWidth(maxWidth if maxWidth else 0)
            existing.setText(text)
            filter_instance = _filter_dict.get(widget)
            if filter_instance is not None:
                filter_instance.setPosition(position)
            return
        if contentWidget is not None:
            existing.setContentWidget(contentWidget)
            filter_instance = _filter_dict.get(widget)
            if filter_instance is not None:
                filter_instance.setPosition(position)
            return
        # 从自定义内容退回纯文本：ElaToolTip 没有「清空内容控件」的 API
        remove_tooltip(widget)
    elif existing is not None:
        # 字典里是已销毁的包装器：先清干净再重建。
        remove_tooltip(widget)

    tooltip = ElaToolTip(text, widget.window())
    if wordWrap:
        tooltip.setWordWrap(True)
    if maxWidth:
        tooltip.setMaxWidth(maxWidth)
    if contentWidget is not None:
        tooltip.setContentWidget(contentWidget)
    _tooltip_dict[widget] = tooltip

    filter_instance = _TooltipEventFilter(tooltip, position, widget)
    _filter_dict[widget] = filter_instance
    widget.installEventFilter(filter_instance)

    def _auto_remove() -> None:
        # 注意：这里在 ``destroyed`` 里对（已失效的）wrapper 做 WeakKeyDictionary
        # 哈希 —— 与 ``animation.py`` 注释里「对已失效 wrapper 取哈希必崩 6/6」
        # 的说法相反；2026-10 实测本文件该路径 5 种销毁场景全部安全（含
        # deleteLater / sip.delete / 父窗口级联 / tooltip 显示中 / 对已销毁
        # 控件 remove）。两处结论并存，改这里前先跑 tests/regression 的销毁用例。
        try:
            remove_tooltip_from_dict(widget)
        except RuntimeError:
            pass

    # 只连一次：复用路径不再重复叠 destroyed 连接（长会话里曾叠到数千个）。
    if not getattr(widget, "_ela_tooltip_autoremove", False):
        widget._ela_tooltip_autoremove = True
        widget.destroyed.connect(_auto_remove)


def remove_tooltip(widget: QWidget) -> None:
    """解除 widget 的悬浮提示绑定。"""
    if widget in _filter_dict:
        widget.removeEventFilter(_filter_dict[widget])
        del _filter_dict[widget]
    if widget in _tooltip_dict:
        tooltip = _tooltip_dict.pop(widget)
        tooltip.hide()
        tooltip.deleteLater()


class ElaStateToolTip(ElaThemeWidget):
    """带状态指示的提示组件：加载中（旋转图标）/ 完成（对勾），带淡出动画与 ``closed`` 信号。"""

    closed = pyqtSignal()

    def __init__(
        self, title: str = "", content: str = "", parent: Optional[QWidget] = None
    ) -> None:
        super().__init__(parent)
        self._title = title
        self._content = content
        self._isDone = False
        self._rotateAngle = 0
        self._deltaAngle = TOOLTIP_ROTATE_ANGLE_DELTA
        self._borderRadius = STATETOOLTIP_BORDER_RADIUS
        self._currentTheme = eTheme.getThemeMode()
        self._isClosing = False
        self._destroyed = False
        self._closeBtnHovered = False

        self._animation = QPropertyAnimation(self, b"windowOpacity")
        self._rotateTimer = QTimer(self)

        self._titleLabel = ElaText(title, self)
        self._contentLabel = ElaText(content, self)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setColor(QColor(0, 0, 0, 40))
        shadow.setOffset(0, 4)
        shadow.setBlurRadius(20)
        self.setGraphicsEffect(shadow)

        self.setMouseTracking(True)
        self._setup_ui()
        self._connectSignals()

    def _setup_ui(self) -> None:
        self._rotateTimer.timeout.connect(self._rotateTimerFlow)

        self._contentLabel.setMinimumWidth(STATETOOLTIP_MIN_WIDTH)
        self._contentLabel.setWordWrap(True)
        self._contentLabel.setMaximumWidth(STATETOOLTIP_MAX_WIDTH)

        self._updateContent()
        self._updateSizeAndPositions()

    def _connectSignals(self) -> None:
        # 持续动效：Reduced/Disabled 下不转。角度冻结在当前值 —— 仍是一段可见的
        # 弧（loading 指示器还在，只是不动），所以不需要摆姿态钩子。
        start_idle_loop(self._rotateTimer, TOOLTIP_ROTATE_TIMER_INTERVAL)

    def _onThemeChanged(self, mode: int) -> None:
        self._currentTheme = mode
        self.update()

    def _getAccentColor(self) -> QColor:
        if self._isDone:
            mode = self._currentTheme
            return (
                QColor(STATETOOLTIP_SUCCESS_COLOR_DARK)
                if mode == ElaThemeType.ThemeMode.Dark
                else QColor(STATETOOLTIP_SUCCESS_COLOR_LIGHT)
            )
        return eTheme.getThemeColor(
            self._currentTheme, ElaThemeType.ThemeColor.PrimaryNormal
        )

    def _drawCloseButton(self, painter: QPainter) -> None:
        btn_size = STATETOOLTIP_CLOSE_BUTTON_SIZE
        btn_x = self.width() - btn_size - 12
        btn_y = 8
        btn_rect = QRect(btn_x, btn_y, btn_size, btn_size)

        if self._closeBtnHovered:
            hover_bg = eTheme.getThemeColor(
                self._currentTheme, ElaThemeType.ThemeColor.BasicHover
            )
            painter.save()
            painter.setBrush(hover_bg)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(btn_rect)
            painter.restore()

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        text_color = eTheme.getThemeColor(
            self._currentTheme, ElaThemeType.ThemeColor.BasicText
        )
        line_pen = QPen(text_color, 2, Qt.PenStyle.SolidLine)
        painter.setPen(line_pen)

        margin = 6
        painter.drawLine(
            btn_x + margin,
            btn_y + margin,
            btn_x + btn_size - margin,
            btn_y + btn_size - margin,
        )
        painter.drawLine(
            btn_x + btn_size - margin,
            btn_y + margin,
            btn_x + margin,
            btn_y + btn_size - margin,
        )
        painter.restore()

    def _updateContent(self) -> None:
        self._titleLabel.setText(self._title)
        self._contentLabel.setText(self._content)

        self._titleLabel.setTextPixelSize(STATETOOLTIP_TITLE_FONT_SIZE)
        self._contentLabel.setTextPixelSize(STATETOOLTIP_CONTENT_FONT_SIZE)

        self._titleLabel.adjustSize()
        self._contentLabel.adjustSize()

        height = max(
            self._titleLabel.height() + self._contentLabel.height() + 32,
            STATETOOLTIP_HEIGHT,
        )
        self.setFixedSize(STATETOOLTIP_MAX_WIDTH, height)

        icon_area = 28
        self._titleLabel.move(STATETOOLTIP_ACCENT_WIDTH + icon_area + 8, 10)
        self._contentLabel.move(
            STATETOOLTIP_ACCENT_WIDTH + icon_area + 8,
            10 + self._titleLabel.height() + 4,
        )
        self._contentLabel.setFixedWidth(
            STATETOOLTIP_MAX_WIDTH
            - STATETOOLTIP_ACCENT_WIDTH
            - icon_area
            - 8
            - STATETOOLTIP_CLOSE_BUTTON_SIZE
            - 12
        )

    def _updateSizeAndPositions(self) -> None:
        self._updateContent()

    def _checkValid(self) -> bool:
        if self._destroyed:
            return False
        try:
            self.isWidgetType()
            return True
        except RuntimeError:
            self._destroyed = True
            return False

    def setTitle(self, title: str) -> None:
        if not self._checkValid():
            return
        self._title = title
        self._titleLabel.setText(title)
        self._titleLabel.adjustSize()
        self._updateSizeAndPositions()

    def setContent(self, content: str) -> None:
        if not self._checkValid():
            return
        self._content = content
        self._contentLabel.setText(content)
        self._contentLabel.adjustSize()
        self._updateSizeAndPositions()

    def setState(self, isDone: bool) -> None:
        if not self._checkValid():
            return
        self._isDone = isDone
        self.update()
        if isDone:
            single_shot_on(self, TOOLTIP_AUTO_CLOSE_DELAY, self._fadeOut)

    def _stopTimerAndAnimation(self) -> None:
        if self._rotateTimer.isActive():
            self._rotateTimer.stop()
        if self._animation.state() == QPropertyAnimation.State.Running:
            self._animation.stop()

    def _onCloseButtonClicked(self) -> None:
        self._fadeOut()

    def _fadeOut(self) -> None:
        if self._isClosing or not self._checkValid():
            return
        self._isClosing = True
        self._stopTimerAndAnimation()
        self._animation.setStartValue(1)
        self._animation.setEndValue(0)
        # 收尾只有一个注册点。之前这里是裸 finished.connect（没有先断开），
        # 叠上 close()→重新 show→再 _fadeOut 的路径就会连两遍，
        # _onFadeOutFinished 跑两次 = deleteLater 两次。start_transition
        # 内部保证「先断旧再连新」。
        start_transition(
            self._animation,
            TOOLTIP_FADE_DURATION,
            on_complete=self._onFadeOutFinished,
        )

    def _onFadeOutFinished(self) -> None:
        if not self._checkValid():
            return
        self.closed.emit()
        self.hide()
        self.deleteLater()

    def _rotateTimerFlow(self) -> None:
        if not self._checkValid():
            return
        self._rotateAngle = (self._rotateAngle + self._deltaAngle) % 360
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        btn_size = STATETOOLTIP_CLOSE_BUTTON_SIZE
        btn_x = self.width() - btn_size - 12
        btn_y = 8
        btn_rect = QRect(btn_x, btn_y, btn_size, btn_size)
        hovered = btn_rect.contains(event.position().toPoint())
        if hovered != self._closeBtnHovered:
            self._closeBtnHovered = hovered
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        if self._closeBtnHovered:
            self._closeBtnHovered = False
            self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        btn_size = STATETOOLTIP_CLOSE_BUTTON_SIZE
        btn_x = self.width() - btn_size - 12
        btn_y = 8
        btn_rect = QRect(btn_x, btn_y, btn_size, btn_size)
        if event.button() == Qt.MouseButton.LeftButton and btn_rect.contains(
            event.position().toPoint()
        ):
            self._onCloseButtonClicked()
            return
        super().mousePressEvent(event)

    def showEvent(self, a0: Optional[QShowEvent]) -> None:
        # _rotateTimer 只在 _connectSignals 里启动、hideEvent 里停止。复用同一个
        # tooltip（hide 后再 show，是「连续提示同一个控件」的常规用法）时若不重启，
        # loading spinner 会永久停在最后一个角度。
        super().showEvent(a0)
        # 重新展示 = 上一轮的关闭流程作废。_isClosing 只在 _fadeOut 里置位、
        # 成功路径不复位（那里紧接着就 deleteLater 了），所以中途被 stop 掉的
        # 淡出会把它永久留在 True：不复位的话这个 tooltip 既再也淡不出去，
        # spinner 也永远重启不了。
        if not self._destroyed:
            self._isClosing = False
        if (
            not self._isClosing
            and not self._destroyed
            and not self._rotateTimer.isActive()
        ):
            start_idle_loop(self._rotateTimer, TOOLTIP_ROTATE_TIMER_INTERVAL)

    def hideEvent(self, a0: Optional[QHideEvent]) -> None:
        if not self._isClosing:
            self._stopTimerAndAnimation()
        super().hideEvent(a0)

    def close(self) -> bool:
        self._isClosing = True
        self._stopTimerAndAnimation()
        return super().close()

    def deleteLater(self) -> None:
        self._destroyed = True
        self._stopTimerAndAnimation()
        self._theme_cleanup()
        super().deleteLater()

    def paintEvent(self, _a0: Optional[QPaintEvent]) -> None:
        if not self._checkValid():
            return
        painter = QPainter(self)
        painter.setRenderHints(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)

        themeMode = self._currentTheme
        r = self._borderRadius
        w, h = self.width(), self.height()

        bg_color = eTheme.getThemeColor(themeMode, ElaThemeType.ThemeColor.PopupBase)
        path = QPainterPath()
        path.addRoundedRect(0, 0, w, h, r, r)
        painter.fillPath(path, bg_color)

        accent_color = self._getAccentColor()
        painter.save()
        painter.setClipRect(0, 0, w, h)
        painter.setBrush(accent_color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(0, 0, STATETOOLTIP_ACCENT_WIDTH, h, r, r)
        painter.drawRect(
            STATETOOLTIP_ACCENT_WIDTH - 2,
            0,
            4,
            h,
        )
        painter.restore()

        text_color = eTheme.getThemeColor(themeMode, ElaThemeType.ThemeColor.BasicText)
        icon_area_x = STATETOOLTIP_ACCENT_WIDTH + 6
        icon_area_y = h // 2

        if not self._isDone:
            painter.save()
            painter.translate(icon_area_x + 14, icon_area_y)
            painter.rotate(self._rotateAngle)
            iconFont = QFont("ElaAwesome")
            iconFont.setPixelSize(STATETOOLTIP_ICON_SIZE)
            painter.setFont(iconFont)
            painter.setPen(text_color)
            painter.drawText(
                QRectF(-8, -8, 16, 16),
                Qt.AlignmentFlag.AlignCenter,
                chr(ElaIconType.IconName.ArrowRotateRight.value),
            )
            painter.restore()
        else:
            painter.save()
            painter.translate(icon_area_x + 14, icon_area_y)
            iconFont = QFont("ElaAwesome")
            iconFont.setPixelSize(STATETOOLTIP_ICON_SIZE)
            painter.setFont(iconFont)
            painter.setPen(accent_color)
            painter.drawText(
                QRectF(-8, -8, 16, 16),
                Qt.AlignmentFlag.AlignCenter,
                chr(ElaIconType.IconName.BadgeCheck.value),
            )
            painter.restore()

        self._drawCloseButton(painter)
        painter.end()

    def getSuitablePos(self) -> QPoint:
        if not self._checkValid():
            return QPoint(0, 0)
        parent = self.parent()
        if parent is None or not isinstance(parent, QWidget):
            return QPoint(0, 0)
        for i in range(10):
            dy = i * (self.height() + 16)
            pos = QPoint(parent.width() - self.width() - 24, 50 + dy)
            widget = parent.childAt(pos + QPoint(2, 2))
            if isinstance(widget, ElaStateToolTip):
                pos += QPoint(0, self.height() + 16)
            else:
                break
        return pos
