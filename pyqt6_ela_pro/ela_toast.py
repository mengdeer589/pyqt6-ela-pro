"""
通知提示组件，风格参考 ElaWidgetTools 的 ElaToast。

非模态提示，支持成功/信息/警告/错误四种类型，
自动淡入→停留→淡出→自动关闭。

用法::

    from pyqt6_ela_pro import ElaToast

    ElaToast.success("操作成功")
    ElaToast.error("发生错误")
    ElaToast.info("提示信息")
    ElaToast.warning("警告")
"""

from __future__ import annotations

from enum import IntEnum
from typing import Optional

from PyQt6.QtCore import (
    Qt,
    QRect,
    QRectF,
    QPoint,
    QPropertyAnimation,
    QTimer,
    QAbstractAnimation,
)
from ._internal import is_deleted
from PyQt6.QtGui import QPainter, QPainterPath, QFont, QFontMetrics, QColor, QPaintEvent
from PyQt6.QtWidgets import QWidget, QApplication

from PyQt6ElaWidgetTools import eTheme, ElaThemeType, ElaIconType

from ._motion import Duration, Easing, start_transition
from ._styles import SHADOW_MARGIN, iconGlyph, paintOverlayShadow
from .widget_base import ElaThemeWidget

#: 同一锚点（父控件，None 表示屏幕）下当前存活的 toast，按创建顺序排列。
#: 新的 toast 需要排在已有 toast 下方，否则连发多个会完全重叠成一个。
_LIVE_TOASTS: dict = {}

#: 同锚点 toast 之间的垂直间距（像素）
_TOAST_GAP = 10


def _prune_toasts(anchor) -> None:
    """清掉已销毁的 toast 记录。

    只用 ``is_deleted`` 判断，不看 ``isVisible()``：记录是在 ``__init__``
    里登记的，那时还没 ``show()``，按可见性过滤会把自己当场裁掉。
    正常关闭走 :meth:`ElaToast.closeEvent` 注销；这里只兜住「已析构但
    注销没跑到」的窗口（那时 ``destroyed`` 已经发过，PyQt 包装器失效，
    碰它就是 0xC0000005，所以不能靠 ``destroyed`` 信号）。
    """
    live = _LIVE_TOASTS.get(anchor)
    if not live:
        return
    kept = [t for t in live if not is_deleted(t)]
    if kept:
        _LIVE_TOASTS[anchor] = kept
    else:
        _LIVE_TOASTS.pop(anchor, None)


def _reflow_toasts(anchor) -> None:
    """把该锚点下存活的 toast 紧凑重排。

    关闭中间一条后如果只从登记里删掉、不重排，剩下的会留在原位留出空洞，
    下一条 toast 又按「存活高度之和」顺延 —— 结果和还活着的那条落在同一
    y 上，又叠回去了。必须重排。
    """
    live = _LIVE_TOASTS.get(anchor)
    if not live:
        return
    base = None
    y = 0
    for toast in live:
        if is_deleted(toast):
            continue
        if base is None:
            base = getattr(toast, "_toast_base_y", None)
            if base is None:
                return
        toast.move(toast.x(), base + y)
        y += toast.height() + _TOAST_GAP


class ElaToastType(IntEnum):
    Success = 0
    Info = 1
    Warning = 2
    Error = 3


class ElaToast(ElaThemeWidget):
    """通知提示。私有构造，使用静态方法创建。"""

    def __init__(
        self,
        toast_type: ElaToastType,
        text: str,
        display_msec: int,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(None)

        self._border_radius = 8
        self._display_msec = display_msec
        self._toast_type = toast_type
        self._text = text
        self._shadow_border = SHADOW_MARGIN

        self.setObjectName("ElaToast")
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

        # 停留计时器必须是本控件的**子对象**：`QTimer.singleShot` 是无主定时器，
        # 回调不随任何控件销毁，toast 被提前关掉后照样在 T+ms 触发去摸已释放的
        # 包装器 → RuntimeError 穿过 C++ 边界 = 0xC0000409 静默终止。
        # （PyQt6 没有带 context 的 singleShot 重载，签名只有 ms + slot 两种。）
        self._dwell_timer = QTimer(self)
        self._dwell_timer.setSingleShot(True)
        self._dwell_timer.timeout.connect(self._startFadeOut)

        self._icon_font = QFont("ElaAwesome")
        self._text_font = QFont()

        self._text_font.setPixelSize(14)
        fm = QFontMetrics(self._text_font)
        tw = fm.horizontalAdvance(text)
        total_w = max(200, min(400, tw + 80))
        self.setFixedHeight(48)
        self.setFixedWidth(total_w + self._shadow_border * 2)

        # 顶部居中；同一锚点下已有 toast 时向下顺延，避免连发多条完全重叠。
        anchor = parent if parent is not None else None
        self._toast_anchor = anchor
        _prune_toasts(anchor)
        offset = 0
        for other in _LIVE_TOASTS.get(anchor, ()):
            offset += other.height() + _TOAST_GAP

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
            screen = QApplication.primaryScreen()
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

    # ── Static public API ─────────────────────────────────

    @staticmethod
    def success(
        text: str, display_msec: int = 2000, parent: Optional[QWidget] = None
    ) -> None:
        """成功提示。``parent`` 决定定位锚点（缺省为屏幕）。"""
        toast = ElaToast(ElaToastType.Success, text, display_msec, parent)
        toast._present()

    @staticmethod
    def info(
        text: str, display_msec: int = 2000, parent: Optional[QWidget] = None
    ) -> None:
        """信息提示。``parent`` 决定定位锚点（缺省为屏幕）。"""
        toast = ElaToast(ElaToastType.Info, text, display_msec, parent)
        toast._present()

    @staticmethod
    def warning(
        text: str, display_msec: int = 2000, parent: Optional[QWidget] = None
    ) -> None:
        """警告提示。``parent`` 决定定位锚点（缺省为屏幕）。"""
        toast = ElaToast(ElaToastType.Warning, text, display_msec, parent)
        toast._present()

    @staticmethod
    def error(
        text: str, display_msec: int = 2000, parent: Optional[QWidget] = None
    ) -> None:
        """错误提示。``parent`` 决定定位锚点（缺省为屏幕）。"""
        toast = ElaToast(ElaToastType.Error, text, display_msec, parent)
        toast._present()

    # ── Internal ──────────────────────────────────────────

    def _run_animation(self) -> None:
        self._opacity = 0.0
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
        self._dwell_timer.start(self._display_msec)

    def _startFadeOut(self) -> None:
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

    def _onThemeChanged(self, mode: ElaThemeType.ThemeMode) -> None:
        self._theme_mode = mode
        self.update()

    # ── Paint ─────────────────────────────────────────────

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        mode = self._theme_mode
        sb = self._shadow_border
        br = self._border_radius
        fg = QRect(sb, sb, self.width() - 2 * sb, self.height() - 2 * sb)

        # 阴影：边距一直留着（窗口尺寸按 _shadow_border 撑开），但阴影本身一直没画，
        # 于是 toast 看起来比别的弹层「扁」一层。这里补上。
        paintOverlayShadow(painter, self.rect(), margin=sb, radius=br)

        painter.setPen(eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.PopupBorder))
        painter.setBrush(eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.PopupBase))
        painter.drawRoundedRect(fg, br, br)

        if self._toast_type == ElaToastType.Success:
            ind_color = QColor(0x0F, 0x7B, 0x0F)
            icon_enum = ElaIconType.IconName.Check
        elif self._toast_type == ElaToastType.Info:
            ind_color = eTheme.getThemeColor(
                mode, ElaThemeType.ThemeColor.PrimaryNormal
            )
            icon_enum = ElaIconType.IconName.CircleInfo
        elif self._toast_type == ElaToastType.Warning:
            ind_color = QColor(0xF7, 0x93, 0x0E)
            icon_enum = ElaIconType.IconName.CircleExclamation
        else:
            ind_color = eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.StatusDanger)
            icon_enum = ElaIconType.IconName.CircleXmark

        # 左侧 4px 语义色条，裁到圆角盒内
        clip_path = QPainterPath()
        clip_path.addRoundedRect(QRectF(fg), br, br)
        painter.save()
        painter.setClipPath(clip_path)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(ind_color)
        painter.drawRect(QRect(fg.x(), fg.y(), 4, fg.height()))
        painter.restore()

        self._icon_font.setPixelSize(16)
        painter.setFont(self._icon_font)
        painter.setPen(ind_color)
        painter.drawText(
            QRect(fg.x() + 14, fg.y(), 20, fg.height()),
            Qt.AlignmentFlag.AlignCenter,
            iconGlyph(icon_enum),
        )

        self._text_font.setPixelSize(14)
        painter.setFont(self._text_font)
        painter.setPen(eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.BasicText))
        painter.drawText(
            QRect(fg.x() + 42, fg.y(), fg.width() - 52, fg.height()),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            self._text,
        )
