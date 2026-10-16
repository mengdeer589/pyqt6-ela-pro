"""
对话框基类模块。

提供 ``ElaDialogBase``，基于 ``ElaContentDialog`` 封装，自带取消/确定按钮栏。
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QPushButton, QWidget, QVBoxLayout
from PyQt6ElaWidgetTools import ElaContentDialog, ElaText, eTheme, ElaThemeType

#: 内容自适应时的窗口宽度上限（超出部分换行、高度随内容增长）
_AUTO_FIT_MAX_WIDTH = 620


class ElaDialogBase(ElaContentDialog):
    """基于 ElaContentDialog 的对话框基类。

    默认提供底部按钮栏（取消/确定），可设置标题和主体内容组件。
    显示时默认按内容自适应尺寸（长文案不被裁切；``setAutoFit(False)`` 关闭）。

    :param title: 对话框标题
    :type title: str
    :param middleText: 中间按钮文本，为 ``None`` 时隐藏中间按钮。
    :type middleText: str, optional
    :param parent: 父级 widget（**必填**）。底层 ``ElaContentDialog`` 需要它来创建遮罩控件，
        传 ``None`` 会让进程崩溃，因此这里会抛 :class:`ValueError`。
    :type parent: QWidget
    :raises ValueError: ``parent`` 为 ``None`` 时抛出（否则进程会静默 abort）

    Example::

        dlg = ElaDialogBase(title="退出", middleText="稍后提醒", parent=parent)
        dlg.setTitle("退出")
        dlg.setParamWidget(my_content_widget)
        dlg.exec()
    """

    def __init__(
        self,
        title: str = "标题",
        middleText: str | None = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        # ElaContentDialog 的 C++ 构造函数无条件解引用 parent（ElaContentDialog.cpp:
        # `d->_maskWidget->setFixedSize(parent->size())`），传 None 会空指针解引用，
        # 在 Qt 之外触发 0xC0000409 静默 abort（无 traceback）。这里提前拦下并给出可读报错。
        if parent is None:
            raise ValueError(
                "ElaDialogBase 需要 parent：底层 ElaContentDialog 用 parent 尺寸创建遮罩控件，"
                "parent=None 会导致进程崩溃。请传入宿主窗口，例如 "
                "ElaDialogBase(parent=self.window())。"
            )
        # 浅色主题下 DialogBase 槽位偏灰，这里把它调到本组件要的浅灰白。
        # **必须在构造期写、不能放模块级**：模块级等于「import 本库就改掉宿主
        # 的全局主题」，而且没有 NOTIFY 信号、宿主也还原不回去（resetAccentColor
        # 只管强调色那一组）。放这里的作用域就是「用了本组件的对话框」。
        eTheme.setThemeColor(
            ElaThemeType.ThemeMode.Light,
            ElaThemeType.ThemeColor.DialogBase,
            QColor("#fafafa"),
        )
        super().__init__(parent)
        self._titleWidget: Optional[ElaText] = None
        self._paramWidget: Optional[QWidget] = None
        self._paramLay: Optional[QVBoxLayout] = None
        #: 显示时按内容自适应尺寸（原生 ElaContentDialog 不重算，见 showEvent）
        self._auto_fit = True

        self.setLeftButtonText("取消")
        self.setRightButtonText("确定")

        if middleText is None:
            try:
                btn = self.findChild(QPushButton, "middleButton")
            except Exception:
                btn = None
            if btn is not None:
                btn.setVisible(False)
            else:
                for btn in self.findChildren(QPushButton):
                    if btn.text() == "minimum":
                        btn.setVisible(False)
                        break
        else:
            self.setMiddleButtonText(middleText)
            # 存成实例属性：disconnect 要拿到**同一个可调用对象**（lambda / partial
            # 断不掉；bound method 统一也按这条写 —— 见 AGENTS）。
            self._middleBtnSlot = self._middleBtnClicked
            self.middleButtonClicked.connect(self._middleBtnSlot)

        self._initParamArea(title)

    def _initParamArea(self, title: str = "标题") -> None:
        """初始化主体内容区域。"""
        self._paramWidget = QWidget(self)
        self._paramLay = QVBoxLayout(self._paramWidget)
        self._paramLay.setContentsMargins(25, 20, 25, 10)
        self._paramLay.setSpacing(2)
        self._titleWidget = ElaText(title, self._paramWidget)
        self._titleWidget.setTextPixelSize(15)
        self._paramLay.addWidget(self._titleWidget)
        self._paramLay.addSpacing(5)
        super().setCentralWidget(self._paramWidget)

    def setTitle(self, title: str) -> None:
        self._titleWidget.setText(title)

    def setParamWidget(self, widget: QWidget) -> None:
        """设置主体内容组件（替换旧的，旧控件 ``deleteLater``）。"""
        while self._paramLay.count() > 2:
            item = self._paramLay.takeAt(2)
            old_widget = item.widget() if item else None
            if old_widget is not None and old_widget is not widget:
                old_widget.deleteLater()
        self._paramLay.addWidget(widget)

    def setAutoFit(self, on: bool = True) -> None:
        """设置「显示时按内容自适应尺寸」（默认开启）。

        原生 ``ElaContentDialog`` 构造时把窗口定在 400px 宽、``setCentralWidget``
        换内容后也不重算，多行正文会被裁切；开启后在 ``showEvent`` 里按布局
        ``heightForWidth`` 重新适配（宽度上限 620px，超出部分换行、高度随内容增长）。
        宿主需要固定尺寸时传 ``False``。
        """
        self._auto_fit = bool(on)

    def autoFit(self) -> bool:
        """显示时是否按内容自适应尺寸。"""
        return self._auto_fit

    def showEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        if self._auto_fit:
            self._fit_to_content()
        super().showEvent(event)

    def _fit_to_content(self) -> None:
        """按内容重算窗口尺寸（先定宽，再按布局 ``heightForWidth`` 求高）。

        ``adjustSize()`` 单用不够：顶层窗口会被 Qt 钳到 2/3 屏宽，且高度不走
        子控件的 ``heightForWidth``（长文案仍裁切）。
        """
        layout = self.layout()
        if layout is None:
            return
        layout.activate()
        width = max(
            self.minimumWidth(),
            min(self.sizeHint().width(), _AUTO_FIT_MAX_WIDTH),
        )
        self.resize(width, self.height())
        layout.activate()
        height = layout.heightForWidth(width)
        if height <= 0:
            # 布局里没有 heightForWidth 能力时（如纯固定尺寸内容）回退 sizeHint
            height = self.sizeHint().height()
        height = max(self.minimumSizeHint().height(), height)
        if height > 0:
            self.resize(width, height)
            layout.activate()

    def deleteLater(self) -> None:
        slot = getattr(self, "_middleBtnSlot", None)
        if slot is not None:
            try:
                self.middleButtonClicked.disconnect(slot)
            except (TypeError, RuntimeError):
                pass
            self._middleBtnSlot = None
        super().deleteLater()

    def _middleBtnClicked(self) -> None:
        self.done(2)
