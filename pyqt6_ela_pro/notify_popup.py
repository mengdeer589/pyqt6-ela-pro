"""
右下角通知弹窗组件。

从屏幕右下角滑入，支持消息等级、自动超时关闭和鼠标悬停保持。
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import (
    Qt,
    QAbstractAnimation,
    QEasingCurve,
    QEvent,
    QPoint,
    QPropertyAnimation,
    QRect,
    QRectF,
    QTimer,
    pyqtProperty,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QCursor,
    QEnterEvent,
    QFont,
    QPainter,
    QPaintEvent,
    QResizeEvent,
)
from PyQt6.QtWidgets import QApplication, QHBoxLayout, QVBoxLayout, QWidget

from PyQt6ElaWidgetTools import ElaIconButton, ElaIconType, ElaThemeType, eTheme

from ._internal import connect_theme_signal, disconnect_theme, is_deleted
from ._motion import Duration, start_transition
from ._notify_common import (
    BADGE_SIZE,
    GAP,
    RADIUS,
    STACK_GAP,
    coerceSeverity,
    liveItems,
    paintNotificationCard,
    severityIcon,
    stackOffset,
    stackStep,
)
from ._styles import (
    SHADOW_MARGIN,
    ColorText,
    paintOverlayShadow,
    paintSeverityBadge,
)
from ._theme import ElaSeverity, severityColor, text, textMuted

#: 卡片内容宽（不含两侧阴影边距）
_CONTENT_WIDTH = 300
#: 卡片内边距
_PAD_X = 16
_PAD_Y = 14
#: 卡片圆角
_RADIUS = RADIUS
#: 等级圆直径
_BADGE_SIZE = BADGE_SIZE
#: 等级圆与标题 / 标题与关闭键的间距
_GAP = GAP
#: 关闭键热区
_CLOSE_SIZE = 24
#: 卡片最小高度（不含阴影边距）
_MIN_CARD_HEIGHT = 76
#: 同屏通知的视觉间距（不含两侧阴影边距）
_STACK_GAP = STACK_GAP


class _SeverityBadge(QWidget):
    """实心等级色圆 + ElaAwesome 字形（与上游 ElaMessageBar 同款）。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedSize(_BADGE_SIZE, _BADGE_SIZE)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._severity = ElaSeverity.Info

    def setSeverity(self, severity: ElaSeverity) -> None:
        if severity == self._severity:
            return
        self._severity = severity
        self.update()

    def severity(self) -> ElaSeverity:
        return self._severity

    def paintEvent(self, _event: QPaintEvent) -> None:
        mode = eTheme.getThemeMode()
        painter = QPainter(self)
        paintSeverityBadge(
            painter,
            self.rect(),
            severityColor(mode, self._severity),
            severityIcon(self._severity),
        )


class ElaNotifyPopup(QWidget):
    """右下角通知弹窗：滑入显示，支持自动超时关闭与鼠标悬停保持。"""

    closed = pyqtSignal()

    def __init__(
        self,
        title: str = "",
        content: str = "",
        timeout: int = 10000,
        severity: ElaSeverity = ElaSeverity.Info,
        y_offset: int = 0,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)

        self._title = title
        self._content = content
        self._timeout = timeout
        self._severity = coerceSeverity(severity)
        self._y_offset = y_offset
        self._is_closing = False
        self._animation = None
        self._progress_anim = None
        self._timer = None
        self._theme_mode = eTheme.getThemeMode()
        self._progress = -1.0
        #: 阴影边距。须在 _setup_ui 前定下：布局内容边距要把它算进去。
        self._shadow_margin = SHADOW_MARGIN

        self._setup_ui()
        self._init()

    def _setup_ui(self):
        sm = self._shadow_margin
        layout = QVBoxLayout(self)
        layout.setContentsMargins(_PAD_X + sm, _PAD_Y + sm, _PAD_X + sm, _PAD_Y + sm)
        layout.setSpacing(_GAP)

        header = QHBoxLayout()
        header.setSpacing(_GAP)

        self._badge = _SeverityBadge(self)
        self._badge.setSeverity(self._severity)
        header.addWidget(self._badge, 0, Qt.AlignmentFlag.AlignVCenter)

        self._title_text = ColorText(self)
        self._title_text.setTextPixelSize(14)
        self._title_text.setTextWeight(QFont.Weight.DemiBold)
        self._title_text.setTextFormat(Qt.TextFormat.PlainText)
        self._title_text.setWordWrap(False)
        self._title_text.setText(self._title)
        header.addWidget(self._title_text, 1, Qt.AlignmentFlag.AlignVCenter)

        self._close_btn = ElaIconButton(
            ElaIconType.IconName.Xmark, 12, _CLOSE_SIZE, _CLOSE_SIZE, self
        )
        self._close_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close_btn.setAccessibleName("关闭")
        self._close_btn.setBorderRadius(5)
        self._close_btn.setLightIconColor(textMuted(ElaThemeType.ThemeMode.Light))
        self._close_btn.setDarkIconColor(textMuted(ElaThemeType.ThemeMode.Dark))
        self._close_btn.setLightHoverIconColor(text(ElaThemeType.ThemeMode.Light))
        self._close_btn.setDarkHoverIconColor(text(ElaThemeType.ThemeMode.Dark))
        self._closeSlot = (
            self._on_close
        )  # 断连要同一对象（lambda / partial 必须存引用）
        self._close_btn.clicked.connect(self._closeSlot)
        header.addWidget(self._close_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        layout.addLayout(header)

        self._content_text = ColorText(self)
        self._content_text.setTextPixelSize(12)
        self._content_text.setTextFormat(Qt.TextFormat.PlainText)
        self._content_text.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        self._content_text.setWordWrap(True)
        self._content_text.setText(self._content)
        self._content_text.setVisible(bool(self._content))

        body = QHBoxLayout()
        body.setContentsMargins(_BADGE_SIZE + _GAP, 0, 0, 0)
        body.addWidget(self._content_text, 1)
        layout.addLayout(body, 1)

        self._apply_text_colors()

    def _init(self):
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.X11BypassWindowManagerHint
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedWidth(_CONTENT_WIDTH + self._shadow_margin * 2)
        self._sync_height()

        self._animation = QPropertyAnimation(self, b"pos")

        # 功能进度：不接 start_transition —— Reduced 会把时长压到 50ms，
        # 时间条就和 timeout 脱节了（同长按按钮的进度环）。
        self._progress_anim = QPropertyAnimation(self, b"progress")
        self._progress_anim.setEasingCurve(QEasingCurve.Type.Linear)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_timeout)

        connect_theme_signal(self)

    def _onThemeChanged(self, mode):
        self._theme_mode = mode
        self._apply_text_colors()
        self._badge.update()
        self.update()

    def _apply_text_colors(self) -> None:
        self._title_text.setTextColor(text(self._theme_mode))
        self._content_text.setTextColor(textMuted(self._theme_mode))

    def _update_title_elide(self) -> None:
        if not hasattr(self, "_title_text"):
            return
        avail = (
            self.width()
            - 2 * self._shadow_margin
            - 2 * _PAD_X
            - _BADGE_SIZE
            - _GAP
            - _CLOSE_SIZE
            - _GAP
        )
        elided = self._title_text.fontMetrics().elidedText(
            self._title, Qt.TextElideMode.ElideRight, max(0, avail)
        )
        if elided != self._title_text.text():
            self._title_text.setText(elided)

    def _sync_height(self) -> None:
        """按内容折行高度定高；长文本不裁、短文本不留白。"""
        sm = self._shadow_margin
        card_w = self.width() - 2 * sm
        card_h = _PAD_Y * 2 + max(_BADGE_SIZE, _CLOSE_SIZE)
        if self._content:
            body_w = card_w - 2 * _PAD_X - _BADGE_SIZE - _GAP
            card_h += _GAP + max(0, self._content_text.heightForWidth(body_w))
        self.setFixedHeight(max(_MIN_CARD_HEIGHT, card_h) + 2 * sm)
        self._update_title_elide()

    def _update_positions(self):
        screen = self._get_screen_geometry()
        # availableGeometry() 是带原点的矩形：必须叠加 x()/y()，否则主屏不在虚拟
        # 原点时（如左侧副屏 x=-1920）弹窗会被摆到错误的屏幕甚至屏幕外。
        self._start_pos = QPoint(
            screen.x() + screen.width() - self.width() - 5,
            screen.y() + screen.height(),
        )
        self._end_pos = QPoint(
            screen.x() + screen.width() - self.width() - 5,
            max(
                screen.y(),
                screen.y() + screen.height() - self.height() - 5 - self._y_offset,
            ),
        )

    def _moveToEnd(self) -> None:
        """回到当前堆叠终态；滑入动画进行中则只改终点，不打断动画。"""
        self._update_positions()
        if (
            self._animation is not None
            and self._animation.state() == QAbstractAnimation.State.Running
        ):
            self._animation.setEndValue(self._end_pos)
        else:
            self.move(self._end_pos)

    @staticmethod
    def _get_screen_geometry():
        app = QApplication.instance()
        # 跟随光标所在屏（多屏时别把通知丢到主屏）；取不到回退主屏
        screen = None
        if app is not None:
            screen = QApplication.screenAt(QCursor.pos()) or app.primaryScreen()
        if screen is None:
            return QRect(0, 0, 1920, 1080)
        return screen.availableGeometry()

    def _get_progress(self) -> float:
        return self._progress

    def _set_progress(self, value: float) -> None:
        self._progress = value
        self.update()

    progress = pyqtProperty(float, _get_progress, _set_progress)

    def _start_progress(self) -> None:
        self._progress_anim.stop()
        self._progress = 1.0
        self._progress_anim.setStartValue(1.0)
        self._progress_anim.setEndValue(0.0)
        self._progress_anim.setDuration(self._timeout)
        self._progress_anim.start()
        self.update()

    def _stop_progress(self) -> None:
        self._progress_anim.stop()
        self._progress = -1.0
        self.update()

    def showNotification(
        self,
        title: str = "",
        content: str = "",
        timeout: int = -1,
        severity: Optional[ElaSeverity] = None,
    ) -> None:
        """显示通知弹窗（带滑入动画）。

        ``timeout=-1`` 沿用当前设置；``severity=None`` 沿用当前等级。
        """
        if title:
            self.setTitle(title)
        if content:
            self.setContent(content)
        if severity is not None:
            self.setSeverity(severity)
        if timeout >= 0:
            self.setTimeout(timeout)

        self._sync_height()
        self._update_positions()
        self._timer.stop()
        self._is_closing = False
        self._animation.stop()
        self.move(self._start_pos)
        super().show()

        self._animation.setStartValue(self.pos())
        self._animation.setEndValue(self._end_pos)
        # 滑入**不传 on_complete** —— 传了会在滑入结束时把弹窗关掉。
        start_transition(self._animation, Duration.Normal)

        if self._timeout > 0:
            self._timer.start(self._timeout)
            self._start_progress()
        else:
            self._stop_progress()

    def _on_close(self):
        self._close_animation()

    def _close_animation(self):
        if self._is_closing:
            return
        self._is_closing = True
        self._timer.stop()
        self._progress_anim.stop()
        self._animation.stop()
        self._animation.setStartValue(self.pos())
        self._animation.setEndValue(self._start_pos)
        # 收尾只有这一个注册点。start_transition 内部保证「先断旧再连新」，
        # 所以关闭动画进行中收到 showNotification 会正确地取消收尾、弹回打开态，
        # 而不会叠连接让 _on_animation_end 跑两次（两次 closed.emit()）。
        start_transition(
            self._animation, Duration.Normal, on_complete=self._on_animation_end
        )

    def _on_animation_end(self):
        self._is_closing = False
        self.hide()
        self.closed.emit()

    def _on_timeout(self):
        self._close_animation()

    def enterEvent(self, event: QEnterEvent) -> None:
        self._timer.stop()
        self._progress_anim.stop()
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        if self._timeout > 0 and self.isVisible() and not self._is_closing:
            self._timer.start(self._timeout)
            self._start_progress()
        super().leaveEvent(event)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._update_title_elide()

    def setTitle(self, title: str) -> None:
        self._title = title
        self._update_title_elide()
        if self.isVisible() and not self._is_closing:
            self._sync_height()
            self._moveToEnd()

    def setContent(self, content: str) -> None:
        self._content = content
        self._content_text.setText(content)
        self._content_text.setVisible(bool(content))
        if self.isVisible() and not self._is_closing:
            self._sync_height()
            self._moveToEnd()

    def setSeverity(self, severity) -> None:
        """设置消息等级（``ElaSeverity`` 或 info/success/warning/error）。"""
        self._severity = coerceSeverity(severity)
        self._badge.setSeverity(self._severity)
        self.update()

    def severity(self) -> ElaSeverity:
        """当前消息等级。"""
        return self._severity

    def setTimeout(self, timeout: int) -> None:
        """超时自动关闭时长（毫秒），0 = 不自动关闭。"""
        self._timeout = timeout

    def setYOffset(self, offset: int) -> None:
        """更新堆叠偏移；可见时立即落到新的终态位置。"""
        self._y_offset = offset
        if self.isVisible() and not self._is_closing:
            self._moveToEnd()

    def deleteLater(self) -> None:
        """断开信号并清理资源。
        弹窗是无父顶层控件里创建/销毁最频繁的，而 ``processEvents()`` 不派发
        ``DeferredDelete``，只靠 ``destroyed`` 钩子会积压，故在这里断主题信号。
        """
        self._timer.stop()
        self._animation.stop()
        self._progress_anim.stop()
        disconnect_theme(self)
        slot = getattr(self, "_closeSlot", None)
        if slot is not None:
            try:
                self._close_btn.clicked.disconnect(slot)
            except (TypeError, RuntimeError):
                pass
            # 置空保证幂等：deleteLater 可能被调用两次（管理器 + 关闭路径）
            self._closeSlot = None
        super().deleteLater()

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        sm = self._shadow_margin
        card_w = self.width() - 2 * sm
        card_h = self.height() - 2 * sm

        paintOverlayShadow(painter, self.rect(), margin=sm, radius=_RADIUS)
        painter.translate(sm, sm)
        paintNotificationCard(
            painter,
            QRectF(0, 0, card_w, card_h),
            self._severity,
            progress=self._progress,
            radius=_RADIUS,
        )


class ElaNotifyManager:
    """通知弹窗管理器（单例）"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._popups = []
        return cls._instance

    def showNotification(
        self,
        title: str = "",
        content: str = "",
        timeout: int = 5000,
        severity: ElaSeverity = ElaSeverity.Info,
    ) -> None:
        """创建并显示通知弹窗；多条通知从屏幕右下角向上堆叠避让。"""
        self._popups = liveItems(self._popups, lambda popup: popup.isVisible())
        # 窗口高度含上下各一格阴影边距，堆叠偏移要把它扣掉才是视觉间距。
        y_offset = stackOffset(
            self._popups,
            gap=_STACK_GAP,
            margin=SHADOW_MARGIN,
            predicate=lambda popup: not popup._is_closing,
        )
        popup = ElaNotifyPopup(
            title=title,
            content=content,
            timeout=timeout,
            severity=severity,
            y_offset=y_offset,
        )
        popup.closed.connect(lambda p=popup: self._onPopupClosed(p))
        self._popups.append(popup)
        popup.showNotification(title, content, timeout)

    def _onPopupClosed(self, popup: ElaNotifyPopup) -> None:
        if popup in self._popups:
            self._popups.remove(popup)
        if not is_deleted(popup):
            popup.deleteLater()
        self._reflow()

    def _reflow(self) -> None:
        """把剩余通知紧凑回落，避免关掉中间一条后留下空洞。"""
        offset = 0
        for popup in liveItems(
            self._popups,
            lambda item: item.isVisible() and not item._is_closing,
        ):
            popup.setYOffset(offset)
            offset += stackStep(popup, gap=_STACK_GAP)


def show_notify(
    title: str = "",
    content: str = "",
    timeout: int = 5000,
    severity: ElaSeverity = ElaSeverity.Info,
) -> None:
    """快捷显示通知弹窗。"""
    return ElaNotifyManager().showNotification(
        title, content, timeout, severity=severity
    )
