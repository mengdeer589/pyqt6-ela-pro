"""
进度显示按钮组件。

继承 :class:`~pyqt6_ela_pro.ela_button.ElaButton`，在按钮面上叠加**外部驱动**
的进度填充（``setProgress``）。尺寸 / 变体 / 颜色与 ``ElaButton`` 一致。
"""

from __future__ import annotations

import warnings
from typing import Optional

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPainterPath
from PyQt6.QtWidgets import QWidget

from PyQt6ElaWidgetTools import ElaIconType

from ._colors import parse_color
from .ela_button import (
    ElaButton,
    ElaButtonColor,
    ElaButtonSize,
    ElaButtonVariant,
    paintProgressFill,
)


class ElaProgressButton(ElaButton):
    """进度按钮。

    进度由外部通过 :meth:`setProgress` 控制（0-100），填充画在按钮面上、
    半透明以保证文字始终可读。

    :param text: 按钮文本
    :param icon: ElaAwesome 图标（``ElaIconType.IconName`` 或其整数值）
    :param iconSize: 图标大小，默认 16
    :param variant: 变体，取值见 :data:`ElaButtonVariant`
    :param color: 色彩，取值见 :data:`ElaButtonColor`
    :param danger: 危险色（等价 ``color="danger"``）
    :param size: 尺寸档位 ``small`` / ``middle`` / ``large``（22 / 30 / 38）
    :param getProgressColor: 进度填充色；``None`` 用主题强调色（实心 / 浅底
        变体自动改成文字色扫光，否则强调色叠强调色看不见）
    :param parent: 父控件

    Example::

        button = ElaProgressButton("下载", parent=parent)
        button.setProgress(50)  # 显示 50% 进度
        button.setProgress(100)  # 完成
    """

    progressChanged = pyqtSignal(int)

    # 类级默认值：主题信号可能在本类 ``__init__`` 走到属性赋值之前回调
    _custom_progress_color: bool = False
    _progress_color: QColor = QColor()

    def __init__(
        self,
        text: str = "",
        icon: Optional[ElaIconType.IconName] = None,
        iconSize: int = 16,
        variant: ElaButtonVariant = "outlined",
        color: ElaButtonColor = "default",
        danger: bool = False,
        size: ElaButtonSize = "middle",
        getProgressColor: Optional[QColor] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(
            text=text,
            icon=icon,
            iconSize=iconSize,
            variant=variant,
            color=color,
            danger=danger,
            size=size,
            parent=parent,
        )
        self._progress = 0.0
        self._custom_progress_color = getProgressColor is not None
        self._progress_color = (
            parse_color(getProgressColor) if getProgressColor is not None else QColor()
        )

    # ── Public API ────────────────────────────────────────

    def setProgressColor(self, color) -> None:
        """自定义进度填充色（支持 ``QColor`` 与 ``#rrggbb`` / ``rgba(...)``）。"""
        self._custom_progress_color = True
        self._progress_color = parse_color(color)
        self.update()

    def progressColor(self) -> QColor:
        """当前**生效**的填充色（未自定义时是主题主色）。"""
        if self._custom_progress_color:
            return QColor(self._progress_color)
        return self._progress_fill_color()

    def setProgress(self, percent: int) -> None:
        """设置进度百分比（0-100，越界会打警告并夹取）。"""
        if percent < 0 or percent > 100:
            warnings.warn(
                f"ElaProgressButton.setProgress({percent}) out of range [0, 100]，已夹取",
                RuntimeWarning,
                stacklevel=2,
            )
        percent = max(0, min(100, percent))
        self._progress = percent / 100.0
        self.progressChanged.emit(percent)
        self.update()

    def progress(self) -> int:
        return int(round(self._progress * 100))

    def resetProgress(self) -> None:
        """重置进度为 0。"""
        self.setProgress(0)

    # ── 绘制 ──────────────────────────────────────────────

    def _paint_face_overlay(self, painter: QPainter, path: QPainterPath) -> None:
        color = (
            self._progress_color
            if self._custom_progress_color
            else self._progress_fill_color()
        )
        paintProgressFill(painter, path, self._progress, color)
