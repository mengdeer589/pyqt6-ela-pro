"""通知提示组件（顶部居中、单行、自动淡出）。"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import (
    Qt,
    QAbstractAnimation,
    QEvent,
    QPoint,
    QPropertyAnimation,
    QRectF,
    QTimer,
)
from PyQt6.QtGui import (
    QCursor,
    QEnterEvent,
    QFont,
    QFontMetrics,
    QPainter,
    QPaintEvent,
)
from PyQt6.QtWidgets import QApplication, QWidget

from PyQt6ElaWidgetTools import ElaThemeType

from ._internal import is_deleted
from ._motion import Duration, Easing, start_transition
from ._notify_common import (
    BADGE_SIZE,
    GAP,
    SEVERITY_ICONS,
    STACK_GAP,
    liveItems,
    paintNotificationCard,
    stackOffset,
    stackStep,
)
from ._styles import SHADOW_MARGIN, paintOverlayShadow, paintSeverityBadge
from ._theme import ElaSeverity, text
from .widget_base import ElaThemeWidget

#: 同一锚点（父控件，None 表示屏幕）下当前存活的 toast，按创建顺序排列。
#: 新的 toast 需要排在已有 toast 下方，否则连发多个会完全重叠成一个。
_LIVE_TOASTS: dict = {}

#: 同锚点 toast 之间的视觉间距（像素）
_TOAST_GAP = STACK_GAP

#: 卡片高度（不含上下阴影边距）
_TOAST_HEIGHT = 40
#: 卡片左右内边距
_PAD_X = 14
#: 等级圆直径
_BADGE_SIZE = BADGE_SIZE
#: 等级圆与文本间距
_GAP = GAP
#: 文本额外留白（避免刚好卡在宽度上限时频繁省略）
_TEXT_SLACK = 12
#: 卡片宽度上下限
_MIN_WIDTH = 200
_MAX_WIDTH = 400


def _prune_toasts(anchor) -> None:
    """清掉已销毁的 toast 记录。
    只看 ``is_deleted``、不看 ``isVisible()``：登记发生在 ``__init__`` 里，
    此时还没 ``show()``。也不能靠 ``destroyed`` 信号 —— 那时 PyQt 包装器
    已换成基类包装器，读不到实例属性。
    """
    live = _LIVE_TOASTS.get(anchor)
    if not live:
        return
    kept = liveItems(live)
    if kept:
        _LIVE_TOASTS[anchor] = kept
    else:
        _LIVE_TOASTS.pop(anchor, None)


def _reflow_toasts(anchor) -> None:
    """把该锚点下存活的 toast 紧凑重排。

    不重排会在关闭中间一条后留出空洞，下一条 toast 顺延时与存活项重叠。
    """
    live = liveItems(_LIVE_TOASTS.get(anchor, ()))
    if not live:
        return
    base = getattr(live[0], "_toast_base_y", None)
    if base is None:
        return
    y = 0
    for toast in live:
        toast.move(toast.x(), base + y)
        y += stackStep(toast, gap=_TOAST_GAP)


class ElaToast(ElaThemeWidget):
    """通知提示。私有构造，使用静态方法创建。"""

    def __init__(
        self,
        severity: ElaSeverity,
        text: str,
        display_msec: int,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(None)

        self._border_radius = 8
        self._display_msec = display_msec
        self._severity = ElaSeverity(severity)
        self._text = text
        self._shadow_border = SHADOW_MARGIN
        self._is_closing = False

        self.setObjectName("ElaToast")
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

        # 计时器必须是本控件的**子对象**：无主 `QTimer.singleShot` 不随控件销毁，
        # toast 提前关闭后仍会在 T+ms 摸已释放的包装器 → RuntimeError 穿过 C++
        # 边界 = 0xC0000409 静默终止。
        self._dwell_timer = QTimer(self)
        self._dwell_timer.setSingleShot(True)
        self._dwell_timer.timeout.connect(self._startFadeOut)

        self._text_font = QFont()
        self._text_font.setPixelSize(14)
        fm = QFontMetrics(self._text_font)
        tw = fm.horizontalAdvance(text)
        chrome = 2 * _PAD_X + _BADGE_SIZE + _GAP
        total_w = max(_MIN_WIDTH, min(_MAX_WIDTH, tw + chrome + _TEXT_SLACK))
        self._elided_text = fm.elidedText(
            text, Qt.TextElideMode.ElideRight, total_w - chrome
        )
        self.setFixedHeight(_TOAST_HEIGHT + 2 * self._shadow_border)
        self.setFixedWidth(total_w + 2 * self._shadow_border)

        # 顶部居中；同一锚点下已有 toast 时向下顺延，避免连发多条完全重叠。
        anchor = parent if parent is not None else None
        self._toast_anchor = anchor
        _prune_toasts(anchor)
        offset = stackOffset(_LIVE_TOASTS.get(anchor, ()), gap=_TOAST_GAP)

        pos = QPoint()
        if parent:
            parent_global = parent.mapToGlobal(QPoint(0, 0))
            pw = parent.width()
            base_y = parent_global.y() + 60
            pos = QPoint(
                parent_global.x() + (pw - self.width()) // 2,
                base_y + offset,
            )
        else:
            screen = (
                QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
            )
            if screen:
                sg = screen.availableGeometry()
                base_y = sg.y() + 60
                pos = QPoint(
                    sg.x() + (sg.width() - self.width()) // 2,
                    base_y + offset,
                )
            else:
                base_y = 60
        #: 堆叠基准 y（不含顺延偏移），重排时用它当起点
        self._toast_base_y = base_y
        self.move(pos)
        _LIVE_TOASTS.setdefault(anchor, []).append(self)

    def _present(self) -> None:
        self.show()
        self._run_animation()

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        """关闭时从堆叠登记里摘除，并把剩下的紧凑重排。"""
        anchor = getattr(self, "_toast_anchor", None)
        live = _LIVE_TOASTS.get(anchor)
        if live:
            try:
                live.remove(self)
            except ValueError:
                pass
            if not live:
                _LIVE_TOASTS.pop(anchor, None)
            else:
                _reflow_toasts(anchor)
        super().closeEvent(event)

    @staticmethod
    def success(
        text: str, display_msec: int = 2000, parent: Optional[QWidget] = None
    ) -> None:
        """成功提示。``parent`` 决定定位锚点（缺省为光标所在屏）。"""
        toast = ElaToast(ElaSeverity.Success, text, display_msec, parent)
        toast._present()

    @staticmethod
    def info(
        text: str, display_msec: int = 2000, parent: Optional[QWidget] = None
    ) -> None:
        """信息提示。``parent`` 决定定位锚点（缺省为光标所在屏）。"""
        toast = ElaToast(ElaSeverity.Info, text, display_msec, parent)
        toast._present()

    @staticmethod
    def warning(
        text: str, display_msec: int = 2000, parent: Optional[QWidget] = None
    ) -> None:
        """警告提示。``parent`` 决定定位锚点（缺省为光标所在屏）。"""
        toast = ElaToast(ElaSeverity.Warning, text, display_msec, parent)
        toast._present()

    @staticmethod
    def error(
        text: str, display_msec: int = 2000, parent: Optional[QWidget] = None
    ) -> None:
        """错误提示。``parent`` 决定定位锚点（缺省为光标所在屏）。"""
        toast = ElaToast(ElaSeverity.Error, text, display_msec, parent)
        toast._present()

    def _run_animation(self) -> None:
        self._fade_in = QPropertyAnimation(self, b"windowOpacity")
        self._fade_in.setStartValue(0.0)
        self._fade_in.setEndValue(1.0)
        self._fade_in.setEasingCurve(Easing.type_name(Easing.Decelerate))
        start_transition(
            self._fade_in,
            Duration.Fast,
            on_complete=self._onFadeInFinished,
            deletion_policy=QAbstractAnimation.DeletionPolicy.DeleteWhenStopped,
        )

    def _onFadeInFinished(self) -> None:
        # fade-in 动画是 DeleteWhenStopped：走到这里时它的 C++ 对象已经销毁，
        # 所以这里绝不能碰 self._fade_in（只能用自己的 _dwell_timer）。
        if is_deleted(self):
            return
        # 悬停期间不开始计时；leaveEvent 会在移开后补上。
        if self.underMouse() or self._dwell_timer.isActive():
            return
        self._dwell_timer.start(self._display_msec)

    def _startFadeOut(self) -> None:
        if self._is_closing:
            return
        self._is_closing = True
        self._dwell_timer.stop()
        self._fade_out = QPropertyAnimation(self, b"windowOpacity")
        self._fade_out.setStartValue(1.0)
        self._fade_out.setEndValue(0.0)
        self._fade_out.setEasingCurve(Easing.type_name(Easing.Accelerate))
        start_transition(
            self._fade_out,
            Duration.Normal,
            on_complete=self.close,
            deletion_policy=QAbstractAnimation.DeletionPolicy.DeleteWhenStopped,
        )

    def enterEvent(self, event: QEnterEvent) -> None:
        self._dwell_timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        if self.isVisible() and not self._is_closing:
            self._dwell_timer.start(self._display_msec)
        super().leaveEvent(event)

    def _onThemeChanged(self, mode: ElaThemeType.ThemeMode) -> None:
        self._theme_mode = mode
        self.update()

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        mode = self._theme_mode
        sb = self._shadow_border
        br = self._border_radius
        card_w = self.width() - 2 * sb
        card_h = self.height() - 2 * sb

        # 阴影：窗口尺寸已按 _shadow_border 撑开，此处必须画出阴影，
        # 否则 toast 看起来比别的弹层「扁」一层。
        paintOverlayShadow(painter, self.rect(), margin=sb, radius=br)
        painter.translate(sb, sb)

        sev_color = paintNotificationCard(
            painter, QRectF(0, 0, card_w, card_h), self._severity, radius=br
        )

        badge_rect = QRectF(
            _PAD_X, (card_h - _BADGE_SIZE) / 2, _BADGE_SIZE, _BADGE_SIZE
        )
        paintSeverityBadge(
            painter, badge_rect, sev_color, SEVERITY_ICONS[self._severity]
        )

        text_left = _PAD_X + _BADGE_SIZE + _GAP
        text_width = card_w - text_left - _PAD_X
        painter.setFont(self._text_font)
        painter.setPen(text(mode))
        painter.drawText(
            QRectF(text_left, 0, text_width, card_h),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            self._elided_text,
        )
