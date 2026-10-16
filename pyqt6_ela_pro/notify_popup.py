"""
右下角通知弹窗组件。

从屏幕右下角滑入的通知弹窗，支持自动超时关闭和鼠标悬停保持。
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import (
    Qt,
    QEvent,
    QPoint,
    QPropertyAnimation,
    QRect,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout
from PyQt6.QtGui import QPainter, QPaintEvent, QEnterEvent

from PyQt6ElaWidgetTools import (
    eTheme,
    ElaThemeType,
    ElaText,
    ElaIconType,
    ElaToolButton,
)

from ._internal import connect_theme_signal, disconnect_theme
from ._motion import Duration, start_transition
from ._styles import SHADOW_MARGIN, paintOverlayShadow


class ElaNotifyPopup(QWidget):
    """右下角通知弹窗：滑入显示，支持自动超时关闭与鼠标悬停保持。"""

    closed = pyqtSignal()

    def __init__(
        self,
        title: str = "",
        content: str = "",
        timeout: int = 10000,
        y_offset: int = 0,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)

        self._title = title
        self._content = content
        self._timeout = timeout
        self._y_offset = y_offset
        self._is_closing = False
        self._animation = None
        self._timer = None
        #: 阴影边距。必须在 _setup_ui 之前定下来 —— 布局的内容边距要把它算进去。
        self._shadow_margin = SHADOW_MARGIN

        self._setup_ui()
        self._init()

    def _setup_ui(self):
        sm = self._shadow_margin
        layout = QVBoxLayout(self)
        # 15/12 是卡片内容内缩；再加一圈阴影边距，否则子控件会压在阴影上。
        layout.setContentsMargins(15 + sm, 12 + sm, 15 + sm, 12 + sm)
        layout.setSpacing(8)

        header_layout = QHBoxLayout()
        header_layout.setSpacing(8)

        self._title_text = ElaText(self)
        self._title_text.setTextPixelSize(14)
        self._title_text.setText(self._title)
        header_layout.addWidget(self._title_text, 1)
        header_layout.addStretch()

        self._close_btn = ElaToolButton(self)
        self._close_btn.setElaIcon(ElaIconType.IconName.Xmark)
        self._close_btn.setFixedSize(24, 24)
        self._closeSlot = self._on_close  # 断连要同一对象（lambda / partial 必须存引用）
        self._close_btn.clicked.connect(self._closeSlot)
        header_layout.addWidget(self._close_btn)

        layout.addLayout(header_layout)

        self._content_text = ElaText(self)
        self._content_text.setTextPixelSize(12)
        self._content_text.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self._content_text.setWordWrap(True)
        self._content_text.setText(self._content)
        layout.addWidget(self._content_text, 1)

    def _init(self):
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.X11BypassWindowManagerHint
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        sm = self._shadow_margin
        self.setFixedWidth(300 + sm * 2)
        self.resize(300 + sm * 2, 100 + sm * 2)

        self._animation = QPropertyAnimation(self, b"pos")

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_timeout)

        connect_theme_signal(self)

    def _onThemeChanged(self, _mode):
        self.update()

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

    @staticmethod
    def _get_screen_geometry():
        app = QApplication.instance()
        screen = app.primaryScreen() if app is not None else None
        if screen is None:
            return QRect(0, 0, 1920, 1080)
        return screen.availableGeometry()

    def showNotification(
        self, title: str = "", content: str = "", timeout: int = -1
    ) -> None:
        """显示通知弹窗（带滑入动画）；``timeout=-1`` 沿用当前设置。"""
        if title:
            self.setTitle(title)
        if content:
            self.setContent(content)
        if timeout >= 0:
            self.setTimeout(timeout)

        self._update_positions()
        self._timer.stop()
        self._is_closing = False
        self._animation.stop()
        self.move(self._start_pos)
        super().show()

        self._animation.setStartValue(self.pos())
        self._animation.setEndValue(self._end_pos)
        # 滑入**不传 on_complete** —— 传了就会在滑入结束时把弹窗关掉。
        # 以前靠「先 disconnect 再 start」表达同一件事，现在语义直写在参数上。
        start_transition(self._animation, Duration.Normal)

        if self._timeout > 0:
            self._timer.start(self._timeout)

    def _on_close(self):
        self._close_animation()

    def _close_animation(self):
        if self._is_closing:
            return
        self._is_closing = True
        self._timer.stop()
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
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        if self._timeout > 0:
            self._timer.start(self._timeout)
        super().leaveEvent(event)

    def setTitle(self, title: str) -> None:
        self._title = title
        self._title_text.setText(title)

    def setContent(self, content: str) -> None:
        self._content = content
        self._content_text.setText(content)

    def setTimeout(self, timeout: int) -> None:
        """超时自动关闭时长（毫秒），0 = 不自动关闭。"""
        self._timeout = timeout

    def deleteLater(self) -> None:
        """断开信号并清理资源。

        弹窗是本库创建/销毁最频繁的无父顶层控件，而 ``processEvents()`` 不派发
        ``DeferredDelete`` —— 只靠 ``destroyed`` 上的钩子会连着好几个，所以主题单例
        信号在这里就断。
        """
        self._timer.stop()
        self._animation.stop()
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

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        mode = eTheme.getThemeMode()
        bg_color = eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.BasicBase)
        border_color = eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.BasicBaseLine)
        sm = self._shadow_margin

        paintOverlayShadow(painter, self.rect(), margin=sm, radius=8)
        painter.translate(sm, sm)

        painter.setPen(border_color)
        painter.setBrush(bg_color)
        painter.drawRoundedRect(
            QRect(0, 0, self.width() - 2 * sm, self.height() - 2 * sm), 8, 8
        )

        super().paintEvent(event)


class ElaNotifyManager:
    """通知弹窗管理器（单例）"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._popups = []
        return cls._instance

    def showNotification(
        self, title: str = "", content: str = "", timeout: int = 5000
    ) -> None:
        """创建并显示通知弹窗；多条通知从屏幕右下角向上堆叠避让。"""
        y_offset = sum(p.height() + 10 for p in self._popups)
        popup = ElaNotifyPopup(
            title=title, content=content, timeout=timeout, y_offset=y_offset
        )
        popup.closed.connect(lambda p=popup: self._onPopupClosed(p))
        self._popups.append(popup)
        popup.showNotification(title, content, timeout)

    def _onPopupClosed(self, popup: ElaNotifyPopup) -> None:
        if popup in self._popups:
            self._popups.remove(popup)
        popup.deleteLater()


def show_notify(title: str = "", content: str = "", timeout: int = 5000) -> None:
    """快捷显示通知弹窗。"""
    return ElaNotifyManager().showNotification(title, content, timeout)
