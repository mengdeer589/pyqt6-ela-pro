"""
[pyqt6_ela_pro] 弹窗与提示页面

工具提示 / 状态提示 / 通知气泡 / 各类对话框。

抽屉类（``ElaDrawerArea`` / ``ElaDrawer`` / 侧边抽屉）已挪到「容器与
布局」—— 它们是**容器**（装内容、可折叠），不是提示。
"""

import traceback
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from PyQt6ElaWidgetTools import (
    ElaColorDialog,
    ElaContentDialog,
    ElaDialog,
    ElaPushButton,
    ElaText,
)
from pyqt6_ela_pro import (
    ElaConfirmDialog,
    ElaMessageDialog,
    ElaStateToolTip,
    ElaToast,
    ElaToolTip,
    ElaToolTipPositionType,
    remove_tooltip,
    set_tooltip,
    show_notify,
)
from .base_page import ExamplePage


class DrawerTooltipPage(ExamplePage):
    """抽屉与提示组件页面"""

    PAGE_TITLE = "弹窗与提示"

    def __init__(self, parent=None):
        self._drawers = {}
        self._stateTooltip = None
        self._tooltip_demo_btn = None
        self._color_swatch = None
        # 属性必须在 super().__init__() 之前就位：基类构造里会调 _addDemoContent
        self._current_color = QColor("#3B82F6")
        self._recent_colors = []
        super().__init__(parent)

    def _addDemoContent(self, main_layout):
        self._demoTooltip(main_layout)
        self._demoTooltipDirect(main_layout)
        self._demoStateTooltip(main_layout)
        self._demoToast(main_layout)
        self._demoNotifyPopup(main_layout)
        self._demoMessageDialog(main_layout)
        self._demoConfirmDialog(main_layout)
        self._demoElaDialog(main_layout)
        self._demoContentDialog(main_layout)
        self._demoColorDialog(main_layout)

    def _demoTooltip(self, parent_layout):
        parent_layout.addWidget(self._createSectionHeader("=== ela_ext - 提示组件 ==="))
        self._demoToolTip(parent_layout)

    def _demoToolTip(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "02. ela_ext - ElaToolTip 工具提示", self._demoToolTip
            )
        )
        self._addInfoText("鼠标悬停在按钮上查看提示", parent_layout)
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(15)
        btn1 = ElaPushButton("保存", self)
        btn1.setFixedWidth(100)
        set_tooltip(btn1, "保存当前内容", position=ElaToolTipPositionType.Bottom)
        btn_layout.addWidget(btn1)
        btn2 = ElaPushButton("删除", self)
        btn2.setFixedWidth(100)
        set_tooltip(
            btn2, "删除选中项目\n（此操作不可撤销）", position=ElaToolTipPositionType.Right
        )
        btn_layout.addWidget(btn2)
        btn3 = ElaPushButton("关于", self)
        btn3.setFixedWidth(100)
        set_tooltip(btn3, "关于本软件 v1.0.0", position=ElaToolTipPositionType.Top)
        btn_layout.addWidget(btn3)
        btn_layout.addStretch()
        parent_layout.addLayout(btn_layout)
        parent_layout.addSpacing(20)

    def _demoTooltipDirect(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "03. ela_ext - remove_tooltip 与 ElaToolTip 直接使用",
                self._demoTooltipDirect,
            )
        )
        self._addInfoText(
            "左侧按钮有 tooltip，点击右侧按钮移除/恢复；「自定义内容 ToolTip」"
            "演示 setContentWidget（提示内容换成任意控件；卡片标题用 ElaText.setIsBold）",
            parent_layout,
        )
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(15)
        self._tooltip_demo_btn = ElaPushButton("有提示的按钮", self)
        self._tooltip_demo_btn.setFixedWidth(120)
        set_tooltip(self._tooltip_demo_btn, "这是一个悬浮提示")
        btn_layout.addWidget(self._tooltip_demo_btn)
        self._tooltip_remove_btn = ElaPushButton("移除提示", self)
        self._tooltip_remove_btn.setFixedWidth(100)

        def _toggle_tooltip():
            if self._tooltip_demo_btn is None:
                return
            if self._tooltip_remove_btn.text() == "移除提示":
                remove_tooltip(self._tooltip_demo_btn)
                self._tooltip_remove_btn.setText("恢复提示")
            else:
                set_tooltip(self._tooltip_demo_btn, "这是一个悬浮提示")
                self._tooltip_remove_btn.setText("移除提示")

        self._tooltip_remove_btn.clicked.connect(_toggle_tooltip)
        btn_layout.addWidget(self._tooltip_remove_btn)
        btn_layout.addSpacing(20)
        show_tip_btn = ElaPushButton("显示 ElaToolTip", self)
        show_tip_btn.setFixedWidth(120)
        show_custom_tip_btn = ElaPushButton("自定义内容 ToolTip", self)
        show_custom_tip_btn.setFixedWidth(160)
        close_tip_btn = ElaPushButton("关闭 ToolTip", self)
        close_tip_btn.setFixedWidth(100)
        self._direct_tip = None
        self._custom_tip = None

        def _dispose_tip(tip):
            if tip is None:
                return
            try:
                tip.hide()
                tip.deleteLater()
            except RuntimeError:
                pass

        def _show_tooltip_direct():
            _dispose_tip(self._direct_tip)
            self._direct_tip = ElaToolTip("手动定位的提示框", self.window())
            self._direct_tip.showAt(show_tip_btn, position=ElaToolTipPositionType.TopRight)

        def _show_custom_tooltip_direct():
            """提示内容换成任意控件（对齐上游 ElaToolTip.setCustomWidget）。"""
            _dispose_tip(self._custom_tip)
            content = QWidget()
            content.setFixedSize(200, 56)
            content_layout = QVBoxLayout(content)
            content_layout.setContentsMargins(4, 4, 4, 4)
            content_layout.setSpacing(2)
            title = ElaText("自定义内容", content)
            title.setTextPixelSize(13)
            title.setIsBold(True)
            desc = ElaText("ToolTip 里可以放任意控件", content)
            desc.setTextPixelSize(12)
            content_layout.addWidget(title)
            content_layout.addWidget(desc)
            tip = ElaToolTip("", self.window())
            tip.setContentWidget(content)
            tip.showAt(show_custom_tip_btn, position=ElaToolTipPositionType.Bottom)
            self._custom_tip = tip

        def _close_tooltip_direct():
            _dispose_tip(self._direct_tip)
            self._direct_tip = None
            _dispose_tip(self._custom_tip)
            self._custom_tip = None

        show_tip_btn.clicked.connect(_show_tooltip_direct)
        show_custom_tip_btn.clicked.connect(_show_custom_tooltip_direct)
        close_tip_btn.clicked.connect(_close_tooltip_direct)
        btn_layout.addWidget(show_tip_btn)
        btn_layout.addWidget(show_custom_tip_btn)
        btn_layout.addWidget(close_tip_btn)
        btn_layout.addStretch()
        parent_layout.addLayout(btn_layout)
        parent_layout.addSpacing(20)

    def _demoStateTooltip(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "04. ela_ext - ElaStateToolTip 状态提示", self._demoStateTooltip
            )
        )
        self._addInfoText("显示加载状态、成功/失败状态的提示", parent_layout)
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(15)
        loading_btn = ElaPushButton("显示加载中", self)
        loading_btn.setFixedWidth(120)
        loading_btn.clicked.connect(self._showLoadingStateTooltip)
        btn_layout.addWidget(loading_btn)
        success_btn = ElaPushButton("显示成功", self)
        success_btn.setFixedWidth(120)
        success_btn.clicked.connect(self._showSuccessStateTooltip)
        btn_layout.addWidget(success_btn)
        close_btn = ElaPushButton("关闭提示", self)
        close_btn.setFixedWidth(120)
        close_btn.clicked.connect(self._closeStateTooltip)
        btn_layout.addWidget(close_btn)
        btn_layout.addStretch()
        parent_layout.addLayout(btn_layout)
        parent_layout.addSpacing(20)

    def _checkValid(self, widget) -> bool:
        try:
            return widget is not None and widget.isWidgetType()
        except RuntimeError:
            return False

    def _showStateTooltip(self, title, content, is_done=False):
        try:
            if self._checkValid(self._stateTooltip):
                self._stateTooltip.setTitle(title)
                self._stateTooltip.setContent(content)
                if is_done:
                    self._stateTooltip.setState(True)
                return
            self._stateTooltip = ElaStateToolTip(title, content, self)
            self._stateTooltip.closed.connect(self._onStateTooltipClosed)
            pos = self._stateTooltip.getSuitablePos()
            self._stateTooltip.move(pos)
            self._stateTooltip.show()
            if is_done:
                self._stateTooltip.setState(True)
        except Exception:
            print(traceback.format_exc())

    def _showLoadingStateTooltip(self):
        self._showStateTooltip("正在加载", "请稍候...")

    def _showSuccessStateTooltip(self):
        self._showStateTooltip("加载完成", "数据已成功加载", is_done=True)

    def _onStateTooltipClosed(self):
        self._stateTooltip = None

    def _closeStateTooltip(self):
        if self._checkValid(self._stateTooltip):
            self._stateTooltip.hide()
            self._stateTooltip.deleteLater()
        self._stateTooltip = None

    def _demoToast(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow("05. ela_ext - ElaToast 通知提示", self._demoToast)
        )
        self._addInfoText(
            "非模态通知，支持成功/信息/警告/错误四种类型，自动淡入→停留→淡出",
            parent_layout,
        )
        row = QHBoxLayout()
        row.setSpacing(15)
        for text, slot in [
            ("成功", lambda: ElaToast.success("操作成功完成！", parent=self)),
            ("信息", lambda: ElaToast.info("这是一条信息提示", parent=self)),
            ("警告", lambda: ElaToast.warning("请注意，磁盘空间不足", parent=self)),
            ("错误", lambda: ElaToast.error("发生错误，请重试", parent=self)),
        ]:
            btn = ElaPushButton(text, self)
            btn.setFixedWidth(80)
            btn.clicked.connect(slot)
            row.addWidget(btn)
        row.addStretch()
        parent_layout.addLayout(row)
        parent_layout.addSpacing(20)

    def _demoNotifyPopup(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "06. ela_ext - ElaNotifyPopup 通知弹窗", self._demoNotifyPopup
            )
        )
        self._addInfoText(
            "右下角通知弹窗，从屏幕边缘滑入，支持自动关闭和鼠标悬停保持",
            parent_layout,
        )
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(15)
        show_btn = ElaPushButton("显示通知", self)
        show_btn.setFixedWidth(100)
        show_btn.clicked.connect(self._onShowNotify)
        btn_layout.addWidget(show_btn)
        btn_layout.addStretch()
        parent_layout.addLayout(btn_layout)
        parent_layout.addSpacing(20)

    def _onShowNotify(self):
        show_notify(
            title="提示",
            content="这是一条通知信息，用于提醒用户某些重要事项。",
            timeout=10000,
        )

    def _demoMessageDialog(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "07. ela_ext - ElaMessageDialog 消息对话框", self._demoMessageDialog
            )
        )
        self._addInfoText(
            "简化的消息对话框接口，使用 ElaText 组件渲染内容", parent_layout
        )
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(15)
        info_btn = ElaPushButton("显示消息", self)
        info_btn.setFixedWidth(100)
        info_btn.clicked.connect(self._onShowMessageDialog)
        btn_layout.addWidget(info_btn)
        btn_layout.addStretch()
        parent_layout.addLayout(btn_layout)
        parent_layout.addSpacing(20)

    def _onShowMessageDialog(self):
        result = ElaMessageDialog.show(
            self,
            title="提示",
            message="确定要退出应用程序吗？此操作不可撤销。",
            middleText="稍后提醒",
        )
        if result == 0:
            print("您点击了取消按钮")
        elif result == 1:
            print("您点击了确定按钮")
        elif result == 2:
            print("您点击了稍后提醒按钮")

    def _demoConfirmDialog(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "08. ela_ext - ElaConfirmDialog 确认对话框", self._demoConfirmDialog
            )
        )
        self._addInfoText(
            "全 QPainter 自绘的确认对话框，支持 bottom（下方）和 top（上方）弹出位置",
            parent_layout,
        )
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(15)
        btn_bottom = ElaPushButton("下方弹出", self)
        btn_bottom.setFixedWidth(100)
        btn_bottom.clicked.connect(
            lambda: self._onShowConfirmDialog(btn_bottom, "bottom")
        )
        btn_layout.addWidget(btn_bottom)
        btn_top = ElaPushButton("上方弹出", self)
        btn_top.setFixedWidth(100)
        btn_top.clicked.connect(lambda: self._onShowConfirmDialog(btn_top, "top"))
        btn_layout.addWidget(btn_top)
        btn_layout.addStretch()
        parent_layout.addLayout(btn_layout)
        parent_layout.addSpacing(20)

    def _onShowConfirmDialog(self, btn, position="bottom"):
        result = ElaConfirmDialog.show(
            btn, "提示", f"确定要执行此操作吗？（{position}）", position=position
        )
        if result:
            print("用户点击了确认")
        else:
            print("用户点击了取消")

    def _demoElaDialog(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "09. PyQt6ElaWidgetTools - ElaDialog 对话框", self._demoElaDialog
            )
        )
        self._addInfoText(
            "Ela 主题对话框，支持窗口按钮控制、默认关闭设置、固定大小模式",
            parent_layout,
        )
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(15)
        dlg_btn = ElaPushButton("打开 ElaDialog", self)
        dlg_btn.setFixedWidth(120)

        def _on_open_dialog():
            dlg = ElaDialog(self)
            dlg.setWindowTitle("示例对话框")
            dlg.setIsDefaultClosed(False)
            dlg.setIsFixedSize(True)
            dlg.closeButtonClicked.connect(dlg.reject)
            dlg.accepted.connect(lambda: print("ElaDialog accepted"))
            dlg.rejected.connect(lambda: print("ElaDialog rejected"))
            dlg.exec()

        dlg_btn.clicked.connect(_on_open_dialog)
        btn_layout.addWidget(dlg_btn)
        btn_layout.addStretch()
        parent_layout.addLayout(btn_layout)
        parent_layout.addSpacing(20)

    def _demoContentDialog(self, main_layout):
        main_layout.addLayout(
            self._createHeaderRow(
                "10. PyQt6ElaWidgetTools - ElaContentDialog 内容对话框",
                self._demoContentDialog,
            )
        )
        self._addInfoText(
            "ElaMessageDialog 的基类：内容区 + 左/中/右三个槽位按钮 + 信号。"
            "注意 ElaConfirmDialog 并不继承它（直接继承 QDialog），"
            "所以想自己拼一个带标题栏的对话框要用它",
            main_layout,
        )
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(15)

        basic_btn = ElaPushButton("打开基础内容对话框", self)
        basic_btn.setFixedWidth(160)

        def _on_open_basic():
            # 左 / 右按钮信号是 0ms 延迟发出的：宿主必须保留引用，否则 exec()
            # 返回后 PyQt 立刻析构对话框、延迟信号被取消（见 AGENTS.md「对话框基座」）。
            self._content_dialog = dlg = ElaContentDialog(self)
            dlg.setWindowTitle("内容对话框")
            dlg.setCentralWidget(
                ElaText("这里是 setCentralWidget 放进去的内容", 12, self)
            )
            dlg.leftButtonClicked.connect(lambda: (print("左键"), dlg.accept()))
            dlg.rightButtonClicked.connect(lambda: (print("右键"), dlg.accept()))
            dlg.exec()

        basic_btn.clicked.connect(_on_open_basic)
        btn_layout.addWidget(basic_btn)

        three_btn = ElaPushButton("打开三按钮版", self)
        three_btn.setFixedWidth(160)

        def _on_open_three():
            # 同上：保留引用才能收到三个延迟信号；只取 exec() 返回值则不需要。
            self._content_dialog = dlg = ElaContentDialog(self)
            dlg.setWindowTitle("三个按钮槽位")
            dlg.setCentralWidget(ElaText("左键 / 中键 / 右键三个槽位", 12, self))
            dlg.setLeftButtonText("左")
            dlg.setMiddleButtonText("中")
            dlg.setRightButtonText("右")
            dlg.leftButtonClicked.connect(lambda: (print("左"), dlg.accept()))
            dlg.middleButtonClicked.connect(lambda: (print("中"), dlg.accept()))
            dlg.rightButtonClicked.connect(lambda: (print("右"), dlg.accept()))
            dlg.exec()

        three_btn.clicked.connect(_on_open_three)
        btn_layout.addWidget(three_btn)
        btn_layout.addStretch()
        main_layout.addLayout(btn_layout)
        main_layout.addSpacing(20)

    def _demoColorDialog(self, main_layout):
        main_layout.addLayout(
            self._createHeaderRow(
                "11. PyQt6ElaWidgetTools - ElaColorDialog 颜色对话框",
                self._demoColorDialog,
            )
        )
        self._addInfoText(
            "颜色选择面板：取色板 + 自定义色 + getCustomColorList() 取最近使用；"
            "选中即发 colorSelected",
            main_layout,
        )
        self._color_swatch = ElaText("当前色：#3B82F6", self)
        self._color_swatch.setTextPixelSize(14)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(15)
        pick_btn = ElaPushButton("打开取色器", self)
        pick_btn.setFixedWidth(140)
        pick_btn.clicked.connect(self._onOpenColorDialog)
        btn_layout.addWidget(pick_btn)

        preset = ElaPushButton("不打开，直接设当前色", self)
        preset.setFixedWidth(180)
        preset.clicked.connect(self._onPresetColor)
        btn_layout.addWidget(preset)

        recent = ElaPushButton("打印最近使用色", self)
        recent.setFixedWidth(160)
        recent.clicked.connect(self._onPrintRecentColors)
        btn_layout.addWidget(recent)

        btn_layout.addStretch()
        main_layout.addLayout(btn_layout)
        main_layout.addWidget(self._color_swatch)
        main_layout.addSpacing(20)

    # -- ElaColorDialog 回调 ------------------------------------------------

    def _onOpenColorDialog(self):
        dlg = ElaColorDialog(self)
        dlg.setWindowTitle("选择颜色")
        dlg.setCurrentColor(self._current_color)
        dlg.colorSelected.connect(self._onColorSelected)
        dlg.exec()
        self._recent_colors = dlg.getCustomColorList()

    def _onColorSelected(self, color):
        # colorSelected 给的是 ElaColorDialog 内部维护的 QColor
        self._current_color = color
        self._color_swatch.setText(f"当前色：{color.name()}")

    def _onPresetColor(self):
        """不开面板，直接改「当前色」—— 适合宿主自己有主题色面板的场景。"""
        self._onColorSelected(QColor("#10B981"))

    def _onPrintRecentColors(self):
        dlg = ElaColorDialog(self)
        names = [c.name() for c in dlg.getCustomColorList()]
        print("最近使用色：", names or "（空——得先自己选过色才有）")
