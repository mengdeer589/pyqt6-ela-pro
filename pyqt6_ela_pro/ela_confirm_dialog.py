"""
确认对话框组件，风格参考 ElaWidgetTools 的 ElaMessageDialog。

全 QPainter 自定义绘制，包含标题、正文、确认/取消图标按钮。
支持深浅色主题自适应。

用法::

    from pyqt6_ela_pro import ElaConfirmDialog

    # 模态调用
    if ElaConfirmDialog.show(self, "提示", "确定要删除吗？"):
        # 用户点击了确认

    # 信号方式
    dlg = ElaConfirmDialog(self)
    dlg.setTitle("提示")
    dlg.setContent("确定要退出吗？")
    dlg.confirmed.connect(lambda: print("确认"))
    dlg.cancelled.connect(lambda: print("取消"))
    dlg.show()
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import (
    Qt,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    QSize,
    QSizeF,
    pyqtSignal,
    QEvent,
)
from PyQt6.QtGui import (
    QColor,
    QEnterEvent,
    QFontMetrics,
    QKeyEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPaintEvent,
    QMouseEvent,
    QFont,
)
from PyQt6.QtWidgets import QApplication, QDialog, QWidget, QVBoxLayout, QHBoxLayout

from PyQt6ElaWidgetTools import eTheme, ElaThemeType

from ._internal import _ThemeAwareMixin, single_shot_on
from ._styles import SHADOW_MARGIN, paintOverlayShadow
from .widget_base import ElaThemeWidget


#: 弹框与锚点组件之间的间距（像素）
_CONFIRM_DIALOG_GAP = 5
#: 内容区起始 y（标题下方）
_CONTENT_TOP = 45
#: 内容区底部留白（分隔线上方）
_CONTENT_BOTTOM_PAD = 15
#: 按钮行高度
_BUTTON_ROW_H = 40
#: 内容区最大高度（超出裁切 —— 无边框弹框没有滚动条；400px 够常规确认文案）
_CONTENT_MAX_H = 400


class _ElaConfirmButton(ElaThemeWidget):
    """确认/取消图标按钮，全 QPainter 自绘。"""

    clicked = pyqtSignal()

    TYPE_CONFIRM = 0
    TYPE_CANCEL = 1

    def __init__(self, button_type: int, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._type = button_type
        self._is_hovered = False
        self._is_pressed = False
        self.setFixedHeight(_BUTTON_ROW_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("确认" if button_type == self.TYPE_CONFIRM else "取消")

    def _onThemeChanged(self, mode: ElaThemeType.ThemeMode) -> None:
        self._theme_mode = mode
        self.update()

    def enterEvent(self, event: QEnterEvent) -> None:
        self._is_hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        self._is_hovered = False
        self._is_pressed = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_pressed = True
            self.update()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._is_pressed:
            self._is_pressed = False
            self.update()
            if self.rect().contains(event.position().toPoint()):
                self.clicked.emit()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """空格 / 回车激活（按钮可 Tab 聚焦，键盘用户也能确认 / 取消）。"""
        if event.key() in (
            Qt.Key.Key_Space,
            Qt.Key.Key_Return,
            Qt.Key.Key_Enter,
        ):
            self.clicked.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def _state_layer(self) -> QColor:
        """hover / press 状态层：**暗色叠白、亮色叠黑**（黑叠黑在深色下看不见）。"""
        if self._theme_mode == ElaThemeType.ThemeMode.Dark:
            return QColor(255, 255, 255)
        return QColor(0, 0, 0)

    def _box_path(self) -> Optional[QPainterPath]:
        """父弹框圆角盒在本按钮坐标系里的路径（状态层 / 焦点环都裁到它）。

        按钮行在弹框底部：不裁的话方块状态层会糊住盒子的圆角、还盖到阴影
        边距上（实测 hover 时窗口左下角出现 ``a=10`` 的方块）。
        """
        parent = self.parent()
        margin = getattr(parent, "_shadow_margin", None)
        radius = getattr(parent, "borderRadius", None)
        if margin is None or radius is None:
            return None
        top_left = self.mapFrom(parent, QPoint(int(margin), int(margin)))
        box = QRectF(
            QPointF(top_left),
            QSizeF(parent.width() - 2 * margin, parent.height() - 2 * margin),
        )
        path = QPainterPath()
        r = float(radius())
        path.addRoundedRect(box, r, r)
        return path

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        clip = self._box_path()
        if clip is not None:
            painter.save()
            painter.setClipPath(clip)
        if self._is_pressed or self._is_hovered:
            layer = self._state_layer()
            layer.setAlpha(24 if self._is_pressed else 12)
            painter.fillRect(self.rect(), layer)
        if self.hasFocus():
            accent = eTheme.getThemeColor(
                self._theme_mode, ElaThemeType.ThemeColor.PrimaryNormal
            )
            painter.setPen(QPen(accent, 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 4, 4)
        if clip is not None:
            painter.restore()

        color = eTheme.getThemeColor(
            self._theme_mode, ElaThemeType.ThemeColor.BasicText
        )
        painter.setPen(
            QPen(
                color,
                2,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
        )

        cx = self.width() // 2
        cy = self.height() // 2

        if self._type == self.TYPE_CONFIRM:
            painter.drawLine(cx - 6, cy, cx - 2, cy + 4)
            painter.drawLine(cx - 2, cy + 4, cx + 6, cy - 4)
        else:
            off = 5
            painter.drawLine(cx - off, cy - off, cx + off, cy + off)
            painter.drawLine(cx - off, cy + off, cx + off, cy - off)


class ElaConfirmDialog(_ThemeAwareMixin, QDialog):
    """确认对话框。

    全 QPainter 自绘，带有标题、正文和两个图标按钮（确认 ✓ / 取消 ✕）。
    支持深浅色主题自适应。

    :param parent: 父组件
    """

    confirmed = pyqtSignal()
    cancelled = pyqtSignal()

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        position: str = "bottom",
    ) -> None:
        super().__init__(parent)

        self._title = "标题"
        self._content = ""
        self._border_radius = 8
        self._title_pixel_size = 15
        self._content_pixel_size = 13
        self._position = position  # "bottom" or "top"
        #: 阴影边距。``FramelessWindowHint`` 去掉了系统阴影，不自己画就完全没有
        #: 阴影（弹框比 toast / 气泡「扁」一层）。窗口尺寸要把这圈算进去。
        self._shadow_margin = SHADOW_MARGIN

        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setMinimumSize(
            280 + self._shadow_margin * 2, 150 + self._shadow_margin * 2
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._confirm_btn = _ElaConfirmButton(_ElaConfirmButton.TYPE_CONFIRM, self)
        self._cancel_btn = _ElaConfirmButton(_ElaConfirmButton.TYPE_CANCEL, self)
        self._confirm_btn.clicked.connect(self._onConfirm)
        self._cancel_btn.clicked.connect(self._onCancel)

        layout = QVBoxLayout(self)
        # 按钮行落在圆角盒**内部**：不内缩的话按钮铺满整窗，方块状态层会盖到
        # 阴影边距和圆角上（配合 _ElaConfirmButton._box_path 的裁剪）
        layout.setContentsMargins(
            self._shadow_margin, 0, self._shadow_margin, self._shadow_margin
        )
        layout.setSpacing(0)
        layout.addStretch()

        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.setSpacing(0)
        btn_layout.addWidget(self._confirm_btn, 1)
        btn_layout.addWidget(self._cancel_btn, 1)
        layout.addLayout(btn_layout)

        self._onThemeChanged(eTheme.getThemeMode())
        self.adjustSize()

    # ── Public API ────────────────────────────────────────

    def setTitle(self, title: str) -> None:
        self._title = title
        self.update()

    def title(self) -> str:
        return self._title

    def setContent(self, content: str) -> None:
        """正文；隐藏时按换行后的高度重算窗口大小。"""
        self._content = content
        self._refresh_size()
        self.update()

    def content(self) -> str:
        return self._content

    def sizeHint(self) -> QSize:
        """按**换行后的正文高度**给出窗口大小。

        没有它，类调用 ``show()`` 只有最小尺寸 288×158、正文区固定 50px
        —— 8 行文案实测需要 144px，**一大半被裁掉**（用户看不到自己在确认什么）。
        超过 ``_CONTENT_MAX_H`` 的部分仍裁切（无边框弹框没有滚动条）。
        """
        sm = self._shadow_margin
        font = self.font()
        font.setPixelSize(self._content_pixel_size)
        fm = QFontMetrics(font)
        need = fm.boundingRect(
            QRect(0, 0, 280 - 30, 10000),
            Qt.TextFlag.TextWordWrap,
            self._content,
        )
        content_h = max(50, min(need.height() + 4, _CONTENT_MAX_H))
        box_h = _CONTENT_TOP + content_h + _CONTENT_BOTTOM_PAD + _BUTTON_ROW_H
        return QSize(280 + 2 * sm, box_h + 2 * sm)

    def _refresh_size(self) -> None:
        """正文变化后重算窗口尺寸（可见时不动 —— 用户可能已手动调整过）。"""
        if not self.isVisible():
            self.adjustSize()

    def setBorderRadius(self, radius: int) -> None:
        self._border_radius = radius
        self.update()

    def borderRadius(self) -> int:
        return self._border_radius

    def setPosition(self, position: str) -> None:
        self._position = position
        self.update()

    def position(self) -> str:
        return self._position

    def show(
        self,
        title: str = "",
        message: str = "",
        position: str = "bottom",
    ) -> bool:
        """模态显示确认对话框（类调用）或普通显示（实例调用）。

        类调用 ``ElaConfirmDialog.show(parent, title, message, position)`` 返回
        ``True`` = 点了确认；实例调用 ``dlg.show()`` 返回 ``False``（两种调用统一
        成布尔语义，便于 ``if dlg.show():``）。
        """
        if isinstance(self, ElaConfirmDialog):
            super().show()
            return False
        parent = self
        dialog = ElaConfirmDialog(parent, position=position)
        dialog.setTitle(title)
        dialog.setContent(message)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        result = dialog.exec()
        return result == QDialog.DialogCode.Accepted

    # ── Internal ──────────────────────────────────────────

    def showEvent(self, event):
        super().showEvent(event)
        if self.parent():
            single_shot_on(self, 0, self._positionDialog)

    def _positionDialog(self) -> None:
        """把弹框摆到锚点组件附近，并收敛进锚点所在屏幕的工作区。

        ``"bottom"`` 放在锚点下方、``"top"`` 放在上方；一侧放不下翻到另一侧，
        最后水平 / 垂直夹回工作区（与 :meth:`ElaToolTip.showAt` 同一套规则）。
        锚点贴着窗口 / 屏幕边缘时（例如聊天输入区）才不会弹出到屏幕外。

        回归：原先只算「锚点底边 + 5」不做兜底，锚点撑满窗口（整块聊天组件 /
        最大化窗口）时 ``y`` 直接落到屏幕外，弹框整块不可见。
        """
        anchor = self.parent()
        if anchor is None:
            return
        try:
            anchor_rect = QRect(anchor.mapToGlobal(QPoint(0, 0)), anchor.size())
        except (RuntimeError, AttributeError):
            return

        gap = _CONFIRM_DIALOG_GAP
        above = self._position == "top"
        x = anchor_rect.left() - 10
        if above:
            y = anchor_rect.top() - self.height() - gap
        else:
            y = anchor_rect.bottom() + gap + 1

        screen = QApplication.screenAt(anchor_rect.center())
        if screen is None:
            screen = QApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            if above and y < area.top():
                y = anchor_rect.bottom() + gap + 1
            elif not above and y + self.height() - 1 > area.bottom():
                y = anchor_rect.top() - self.height() - gap
            x = max(area.left(), min(x, area.right() - self.width() + 1))
            y = max(area.top(), min(y, area.bottom() - self.height() + 1))
        self.move(int(x), int(y))

    def _onConfirm(self) -> None:
        self.confirmed.emit()
        self.accept()

    def _onCancel(self) -> None:
        self.reject()

    def reject(self) -> None:
        """取消（按钮 / ``Escape`` / 程序化关闭都走这里）。

        ``cancelled`` 与 ``confirmed`` 对称且无条件发 —— 原先只在 ``_onCancel``
        里发，Escape 关掉弹框时宿主收不到信号。
        """
        self.cancelled.emit()
        super().reject()

    def _onThemeChanged(self, mode: ElaThemeType.ThemeMode) -> None:
        self._theme_mode = mode
        self.update()

    # ── Paint ─────────────────────────────────────────────

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        mode = self._theme_mode
        sm = self._shadow_margin
        br = self._border_radius
        w = self.width() - 2 * sm
        h = self.height() - 2 * sm

        paintOverlayShadow(painter, self.rect(), margin=sm, radius=br)

        # 之后所有坐标字面量（15/45/h-40 …）都按**盒子原点**算，所以整体平移一次，
        # 不逐个加偏移 —— 少一处漏改就少一处错位。
        painter.translate(sm, sm)
        box = QRect(0, 0, w, h)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.BasicBase))
        painter.drawRoundedRect(box, br, br)

        # Title（超宽省略 —— 无边框窗口不能靠拉伸看全）
        title_font = self.font()
        title_font.setPixelSize(self._title_pixel_size)
        title_font.setWeight(QFont.Weight.Bold)
        painter.setFont(title_font)
        painter.setPen(eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.BasicText))
        title_text = QFontMetrics(title_font).elidedText(
            self._title, Qt.TextElideMode.ElideRight, w - 30
        )
        painter.drawText(
            QRect(15, 15, w - 30, 25),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
            title_text,
        )

        content_font = self.font()
        content_font.setPixelSize(self._content_pixel_size)
        content_font.setWeight(QFont.Weight.Normal)
        painter.setFont(content_font)
        content_h = h - 40 - 45 - 15
        if content_h > 0:
            painter.drawText(
                QRect(15, 45, w - 30, content_h),
                Qt.TextFlag.TextWordWrap
                | Qt.AlignmentFlag.AlignLeft
                | Qt.AlignmentFlag.AlignTop,
                self._content,
            )

        painter.setPen(
            QPen(eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.BasicBorder), 1)
        )
        painter.drawLine(0, h - 40, w, h - 40)
