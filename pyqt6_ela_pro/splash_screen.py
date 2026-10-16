"""
启动画面组件，风格参考 ElaWidgetTools 的 ElaSplashScreen。

全 QPainter 自定义绘制，支持主题自适应、Logo、淡入淡出动画、可拖动。

用法::

    splash = ElaSplashScreen(parent=self)
    splash.setTitle("My App")
    splash.setSubTitle("Version 1.0")
    splash.show()
    # ... loading ...
    splash.setValue(100)
    splash.finish(main_window)
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, QRect, QRectF, QPoint, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QFont,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPaintEvent,
    QMouseEvent,
    QShowEvent,
)
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QApplication

from PyQt6ElaWidgetTools import (
    eTheme,
    ElaThemeType,
    ElaText,
    ElaTextType,
    ElaProgressBar,
    ElaProgressRing,
)

from ._internal import single_shot_on
from ._motion import start_transition_timer
from .widget_base import ElaThemeWidget

_TEXT_STACK_WARMED = False


def _warmTextStack() -> None:
    """付掉 Qt6 的一次性字体解析成本（**幂等**）。

    PyQt6/Qt6 下首次 ``QFont().defaultFamily()`` 要 ~190ms（解析系统默认字体、初始化
    字体引擎；Qt5 几乎为 0）。splash 的职责正是「遮住启动期工作」，所以在这里付掉它 ——
    否则这笔成本会随机落在宿主第一个页面构造里，让那一页莫名多 190ms（实测落在某个无
    关演示节里，那一节从 4ms 变成 194ms）。之后调用是 0.0x ms 级。

    不用我们 splash 的宿主可以自己在启动阶段调一次 ``QFont().defaultFamily()``。
    """
    global _TEXT_STACK_WARMED
    if _TEXT_STACK_WARMED:
        return
    _TEXT_STACK_WARMED = True
    try:
        QFont().defaultFamily()
    except Exception:  # noqa: BLE001 —— 预热失败不该影响启动
        pass


class ElaSplashScreen(ElaThemeWidget):
    """启动画面组件。

    全 QPainter 自定义绘制，支持 Logo、标题、副标题、状态文字、进度条/环，
    主题自适应、淡入淡出动画、鼠标拖动。

    :param parent: 父控件
    """

    closed = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self._border_radius = 12
        self._minimum = 0
        self._maximum = 100
        self._value = 0
        self._is_show_progress_bar = True
        self._is_show_progress_ring = True
        self._is_closable = False
        self._logo = QPixmap()
        self._is_dragging = False
        self._drag_start = QPoint()
        self._fade_target = None
        self._fade_opacity = 1.0
        self._fade_settled = False
        self._fade_timer = QTimer(self)

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(580, 400)

        self._title_text = ElaText(self)
        self._title_text.setTextStyle(ElaTextType.TextStyle.TitleLarge)
        self._title_text.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._subtitle_text = ElaText(self)
        self._subtitle_text.setTextStyle(ElaTextType.TextStyle.Subtitle)
        self._subtitle_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._subtitle_text.setWordWrap(True)
        self._subtitle_text.setMinimumWidth(400)

        self._status_text = ElaText(self)
        self._status_text.setTextStyle(ElaTextType.TextStyle.Body)
        self._status_text.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._progress_bar = ElaProgressBar(self)
        self._progress_bar.setMinimum(0)
        self._progress_bar.setMaximum(100)
        self._progress_bar.setFixedHeight(24)

        self._progress_ring = ElaProgressRing(self)
        self._progress_ring.setFixedSize(48, 48)
        self._progress_ring.setIsBusying(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 50, 36, 36)
        layout.setSpacing(6)
        layout.addStretch(2)
        layout.addWidget(self._title_text, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addSpacing(4)
        layout.addWidget(self._subtitle_text, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addStretch(1)
        layout.addWidget(self._progress_ring, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addSpacing(8)
        layout.addWidget(self._status_text, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addSpacing(12)
        layout.addWidget(self._progress_bar)
        layout.addStretch(1)

    # ── Public API ────────────────────────────────────────

    def setBorderRadius(self, r: int) -> None:
        self._border_radius = r
        self.update()

    def borderRadius(self) -> int:
        return self._border_radius

    def setTitle(self, title: str) -> None:
        self._title_text.setText(title)

    def title(self) -> str:
        return self._title_text.text()

    def setSubTitle(self, text: str) -> None:
        self._subtitle_text.setText(text)

    def subTitle(self) -> str:
        return self._subtitle_text.text()

    def setStatusText(self, text: str) -> None:
        self._status_text.setText(text)

    def statusText(self) -> str:
        return self._status_text.text()

    def setLogo(self, logo: QPixmap) -> None:
        self._logo = logo
        self.update()

    def logo(self) -> QPixmap:
        return self._logo

    def setMinimum(self, n: int) -> None:
        self._minimum = n
        self._progress_bar.setMinimum(n)

    def minimum(self) -> int:
        return self._minimum

    def setMaximum(self, n: int) -> None:
        self._maximum = n
        self._progress_bar.setMaximum(n)

    def maximum(self) -> int:
        return self._maximum

    def setValue(self, n: int) -> None:
        self._value = n
        self._progress_bar.setValue(n)
        self._progress_ring.setValue(n)

    def value(self) -> int:
        return self._value

    def setShowProgressBar(self, show: bool) -> None:
        self._is_show_progress_bar = show
        self._progress_bar.setVisible(show)

    def isShowProgressBar(self) -> bool:
        return self._is_show_progress_bar

    def setShowProgressRing(self, show: bool) -> None:
        self._is_show_progress_ring = show
        self._progress_ring.setVisible(show)

    def isShowProgressRing(self) -> bool:
        return self._is_show_progress_ring

    def setClosable(self, closable: bool) -> None:
        self._is_closable = closable

    def isClosable(self) -> bool:
        return self._is_closable

    def show(self) -> None:
        """显示启动画面（居中于当前屏幕）。"""
        screen = QApplication.primaryScreen()
        if screen:
            sg = screen.availableGeometry()
            self.move(
                (sg.width() - self.width()) // 2, (sg.height() - self.height()) // 2
            )
        self._progress_bar.setVisible(self._is_show_progress_bar)
        self._progress_ring.setVisible(self._is_show_progress_ring)
        self.setWindowOpacity(1.0)
        super().show()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        # 等 splash 画出来再付 Qt6 的一次性字体解析（见 ``_warmTextStack``）：
        # 在 showEvent 里同步调会把 splash 自己的出现也推迟 ~190ms。
        single_shot_on(self, 0, _warmTextStack)

    def close(self) -> None:
        """关闭启动画面并发射 ``closed`` 信号。"""
        self._fade_timer.stop()
        super().close()
        self.closed.emit()
    def finish(self, main_window: QWidget) -> None:
        """淡出关闭并显示主窗口。"""
        if self._fade_timer.isActive() or self._fade_settled:
            return
        self._fade_target = main_window
        self._fade_opacity = 1.0
        self._fade_timer.setInterval(20)
        self._fade_timer.timeout.connect(self._onFadeTick)
        if not start_transition_timer(self._fade_timer):
            # Reduced/Disabled：同步落终值。收尾（关自己 + 激活主窗口）不能丢，
            # 所以走同一条 _settleFadeOut。
            self._settleFadeOut()

    # ── Internal ──────────────────────────────────────────

    def _settleFadeOut(self) -> None:
        """淡出收尾：关自己 + 把主窗口顶到前台。

        正常路径与动效 snap 都走这一个入口，否则两条路会各做一半。
        """
        self._fade_timer.stop()
        self._fade_settled = True
        target = self._fade_target
        self.setWindowOpacity(1.0)
        self.closed.emit()
        super().close()
        if target:
            target.show()
            target.raise_()
            target.activateWindow()

    def _onFadeTick(self) -> None:
        if not self.isVisible():
            self._fade_timer.stop()
            return
        self._fade_opacity -= 0.05
        if self._fade_opacity <= 0:
            self._settleFadeOut()
            return
        self.setWindowOpacity(self._fade_opacity)

    def _onThemeChanged(self, mode: ElaThemeType.ThemeMode) -> None:
        self._theme_mode = mode
        self.update()

    # ── Events ────────────────────────────────────────────

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_dragging = True
            self._drag_start = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._is_dragging:
            self.move(event.globalPosition().toPoint() - self._drag_start)
            event.accept()

    def mouseReleaseEvent(self, _event: QMouseEvent) -> None:
        self._is_dragging = False

    # ── Paint ─────────────────────────────────────────────

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        mode = self._theme_mode
        br = self._border_radius
        sb = 6
        fg = QRect(sb, sb, self.width() - 2 * sb, self.height() - 2 * sb)

        eTheme.drawEffectShadow(painter, self.rect(), sb, br)

        path = QPainterPath()
        path.addRoundedRect(QRectF(fg), br, br)
        painter.setClipPath(path)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.DialogBase))
        painter.drawRoundedRect(QRectF(fg), br, br)

        if not self._logo.isNull():
            ls = min(80, min(fg.width(), fg.height()) // 3)
            lr = QRect(fg.x() + (fg.width() - ls) // 2, fg.y() + 30, ls, ls)
            painter.drawPixmap(
                lr,
                self._logo.scaled(
                    ls,
                    ls,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                ),
            )

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(
            QPen(eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.PopupBorder), 1)
        )
        painter.drawRoundedRect(QRectF(fg), br, br)
