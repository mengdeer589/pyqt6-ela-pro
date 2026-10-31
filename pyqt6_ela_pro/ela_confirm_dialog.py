"""
确认弹框组件：贴锚点弹出的轻量确认条。

表面（阴影 + 圆角底 + 1px 描边）由 ``QPainter`` 自绘，内容用 Ela 原生拼装
（``ColorText`` 标题 / 正文 + ``ElaButton`` 取消 / 确定），与库内其它组件共享
同一套字阶、按钮与主题令牌。支持深浅色主题自适应。

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
    QPoint,
    QRect,
    QRectF,
    QSize,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QFont,
    QFontMetrics,
    QPainter,
    QPaintEvent,
)
from PyQt6.QtWidgets import QApplication, QDialog, QHBoxLayout, QVBoxLayout, QWidget

from PyQt6ElaWidgetTools import eTheme, ElaThemeType

from ._internal import _ThemeAwareMixin, is_deleted, single_shot_on
from ._styles import SHADOW_MARGIN, ColorText, paintOverlayShadow, paintRoundedCard
from ._theme import border, surfacePopup
from .ela_button import ElaButton


#: 弹框与锚点组件之间的间距（像素）
_CONFIRM_DIALOG_GAP = 5
#: 内容区宽度（不含两侧阴影边距）
_BOX_WIDTH = 300
#: 内容区左右内边距
_PAD_X = 16
#: 内容区上内边距
_PAD_TOP = 14
#: 内容区下内边距
_PAD_BOTTOM = 14
#: 标题与正文之间的间距
_TITLE_GAP = 6
#: 正文与按钮行之间的间距
_BODY_GAP = 16
#: 正文区最大高度（超出裁切 —— 无边框弹框没有滚动条；400px 够常规确认文案）
_CONTENT_MAX_H = 400
#: 标题 / 正文字号（对齐 ``ElaDialogBase`` 的 15px 标题与 ``ElaText`` Body 的 13px）
_TITLE_PIXEL_SIZE = 15
_CONTENT_PIXEL_SIZE = 13


class ElaConfirmDialog(_ThemeAwareMixin, QDialog):
    """贴锚点弹出的确认弹框。

    表面自绘（``PopupBase`` + ``PopupBorder``，阴影边距见 ``SHADOW_MARGIN``），
    文字与按钮是 Ela 原生控件：标题 15px DemiBold、正文 13px 自动换行，
    ``取消`` / ``确定`` 为 :class:`ElaButton`（outlined / solid + primary）。
    支持深浅色主题自适应。

    :param parent: 父组件，同时作为弹出位置的锚点
    :param position: ``"bottom"`` 放锚点下方、``"top"`` 放上方（放不下自动翻边）
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
        self._position = position  # "bottom" or "top"
        #: 阴影边距。``FramelessWindowHint`` 去掉了系统阴影，不自己画就完全没有
        #: 阴影（弹框比 toast / 气泡「扁」一层）。窗口尺寸要把这圈算进去。
        self._shadow_margin = SHADOW_MARGIN

        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        #: 弹框宽度固定（轻量 popover 没有手动调宽的场景），高度随正文撑开。
        self.setFixedWidth(_BOX_WIDTH + 2 * self._shadow_margin)

        sm = self._shadow_margin
        self._title_label = ColorText(self)
        self._title_label.setTextPixelSize(_TITLE_PIXEL_SIZE)
        self._title_label.setTextWeight(QFont.Weight.DemiBold)
        # 标题 / 正文都可能来自宿主或模型输出，必须按纯文本渲染。
        self._title_label.setTextFormat(Qt.TextFormat.PlainText)
        self._title_label.setWordWrap(False)
        self._title_label.setVisible(bool(self._title))

        self._content_label = ColorText(self)
        self._content_label.setTextPixelSize(_CONTENT_PIXEL_SIZE)
        self._content_label.setTextFormat(Qt.TextFormat.PlainText)
        self._content_label.setWordWrap(True)
        # 定高后默认是垂直居中；正文必须从顶部起排（否则标题与正文之间会凭空
        # 多出半行，而底部又少半行）。
        self._content_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )

        # 按钮走库内统一按钮族：文字 + 主次层级（取消中性 / 确定实心主色）。
        self._cancel_btn = ElaButton(
            "取消",
            variant="outlined",
            color="default",
            size="middle",
            parent=self,
        )
        self._confirm_btn = ElaButton(
            "确定",
            variant="solid",
            color="primary",
            size="middle",
            parent=self,
        )
        # Enter / Space 落在「当前聚焦的按钮」上（Windows 消息框惯例）：初始焦点
        # 给「确定」，Tab 到「取消」后回车就是取消；两个按钮都没焦点时回落到
        # 默认按钮「确定」。
        self._cancel_btn.setAutoDefault(True)
        self._confirm_btn.setAutoDefault(True)
        self._confirm_btn.setDefault(True)
        self._confirm_btn.clicked.connect(self._onConfirm)
        self._cancel_btn.clicked.connect(self._onCancel)

        layout = QVBoxLayout(self)
        # 边距 = 阴影边距 + 内容内缩；窗口尺寸把 shadow margin 算进来，子控件
        # 不会压到阴影上。
        layout.setContentsMargins(
            sm + _PAD_X, sm + _PAD_TOP, sm + _PAD_X, sm + _PAD_BOTTOM
        )
        layout.setSpacing(0)
        layout.addWidget(self._title_label)
        layout.addSpacing(_TITLE_GAP)
        layout.addWidget(self._content_label)
        layout.addSpacing(_BODY_GAP)

        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.setSpacing(8)
        button_layout.addStretch(1)
        button_layout.addWidget(self._cancel_btn)
        button_layout.addWidget(self._confirm_btn)
        layout.addLayout(button_layout)

        self.setTabOrder(self._cancel_btn, self._confirm_btn)
        self._onThemeChanged(eTheme.getThemeMode())
        self._refresh_size()

    # ── Public API ────────────────────────────────────────

    def setTitle(self, title: str) -> None:
        self._title = title
        self._sync_title_text()
        # 空标题不占一行（``show(parent, title="", ...)`` 是合法调用）。
        self._title_label.setVisible(bool(title))
        self._refresh_size()

    def title(self) -> str:
        return self._title

    def setContent(self, content: str) -> None:
        """正文；按换行后的高度重算窗口大小。"""
        self._content = content
        self._content_label.setText(content)
        self._refresh_size()

    def content(self) -> str:
        return self._content

    def sizeHint(self) -> QSize:
        """窗口大小 = 固定宽度 + 布局按内容算出的高度。

        没有它，类调用 ``show()`` 会停在最小尺寸、正文被裁掉一大半（用户看不到
        自己在确认什么）。正文超过 ``_CONTENT_MAX_H`` 的部分仍裁切（无边框弹框
        没有滚动条）。
        """
        layout = self.layout()
        width = _BOX_WIDTH + 2 * self._shadow_margin
        if layout is None:
            return super().sizeHint()
        layout.activate()
        height = layout.heightForWidth(width)
        if height <= 0:
            height = layout.sizeHint().height()
        return QSize(width, max(height, self.minimumSizeHint().height()))

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

    def _content_width(self) -> int:
        return _BOX_WIDTH - 2 * _PAD_X

    def _sync_title_text(self) -> None:
        """标题单行显示，超宽按省略号截断（无边框窗口不能靠拉伸看全）。"""
        font_metrics = QFontMetrics(self._title_label.font())
        self._title_label.setText(
            font_metrics.elidedText(
                self._title,
                Qt.TextElideMode.ElideRight,
                self._content_width(),
            )
        )

    def _sync_content_height(self) -> None:
        """正文按当前宽度折行后的高度定高（上限 ``_CONTENT_MAX_H``）。"""
        need = self._content_label.heightForWidth(self._content_width())
        if need <= 0:
            need = self._content_label.fontMetrics().lineSpacing()
        self._content_label.setFixedHeight(min(need + 2, _CONTENT_MAX_H))

    def _refresh_size(self) -> None:
        self._sync_title_text()
        self._sync_content_height()
        self.adjustSize()

    def showEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        super().showEvent(event)
        # 初始焦点给「确定」（Enter / Space 都落到主操作），OtherFocusReason
        # 不会触发 ElaButton 的键盘焦点环 —— 弹框一打开就套一圈主色环会被误读
        # 成「已选中」。
        self._confirm_btn.setFocus(Qt.FocusReason.OtherFocusReason)
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
        if anchor is None or is_deleted(anchor) or is_deleted(self):
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
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        mode = self._theme_mode
        sm = self._shadow_margin
        br = self._border_radius
        w = self.width() - 2 * sm
        h = self.height() - 2 * sm

        paintOverlayShadow(painter, self.rect(), margin=sm, radius=br)

        # 之后所有坐标都按**盒子原点**算，所以整体平移一次，不逐个加偏移。
        painter.translate(sm, sm)
        paintRoundedCard(
            painter,
            QRectF(0, 0, w, h),
            background=surfacePopup(mode),
            border=border(mode),
            radius=br,
        )
