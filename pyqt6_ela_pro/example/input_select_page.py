"""输入与选择

文本 / 数值 / 日期 / 勾选这一类「往里填东西」的控件。

此前它们散在「基础控件」和「扩展组件」两页，而那两页的分界线
（控件 vs 容器）用户根本记不住 —— 现在按**用途**分：这一页只管
「用户往里输入 / 从里选」。下拉框的 11 个变体另开一页
（ComboBoxPage），因为单个组件就有 11 种形态，塞进来这页会失衡。
"""

from PyQt6.QtWidgets import QHBoxLayout
from PyQt6ElaWidgetTools import (
    ElaCalendar,
    ElaCalendarPicker,
    ElaCheckBox,
    ElaDoubleSpinBox,
    ElaLineEdit,
    ElaPlainTextEdit,
    ElaPushButton,
    ElaRadioButton,
    ElaRoller,
    ElaRollerPicker,
    ElaSlider,
    ElaSpinBox,
    ElaText,
    ElaToggleSwitch,
)
from .base_page import ExamplePage
from pyqt6_ela_pro import (
    ElaPasswordEdit,
    ElaSpotlight,
    ElaTagLineEdit,
    ElaUploadArea,
)


class InputSelectPage(ExamplePage):
    """输入与选择示例页。"""

    PAGE_TITLE = "输入与选择"

    def __init__(self, parent=None):
        super().__init__(parent)

    def _addDemoContent(self, main_layout):
        self._demoLineEdit(main_layout)
        self._demoPlainTextEdit(main_layout)
        self._demoSpinBox(main_layout)
        self._demoDoubleSpinBox(main_layout)
        self._demoSlider(main_layout)
        self._demoCalendar(main_layout)
        self._demoCalendarPicker(main_layout)
        self._demoCheckBox(main_layout)
        self._demoRadioButton(main_layout)
        self._demoToggleSwitch(main_layout)
        self._demoRoller(main_layout)
        self._demoRollerPicker(main_layout)
        self._demoPasswordEdit(main_layout)
        self._demoTagLineEdit(main_layout)
        self._demoUploadArea(main_layout)
        self._demoSpotlight(main_layout)

    def _demoLineEdit(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "01. PyQt6ElaWidgetTools - ElaLineEdit 单行输入框", self._demoLineEdit
            )
        )
        self._addInfoText("标准单行输入框组件", parent_layout)
        edit_layout = QHBoxLayout()
        edit_layout.setSpacing(15)
        line_edit = ElaLineEdit(self)
        line_edit.setPlaceholderText("请输入文本")
        line_edit.setFixedWidth(200)
        edit_layout.addWidget(line_edit)
        line_edit_disabled = ElaLineEdit(self)
        line_edit_disabled.setPlaceholderText("禁用状态")
        line_edit_disabled.setFixedWidth(200)
        line_edit_disabled.setEnabled(False)
        edit_layout.addWidget(line_edit_disabled)
        edit_layout.addStretch()
        parent_layout.addLayout(edit_layout)
        parent_layout.addSpacing(20)

    def _demoPlainTextEdit(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "02. PyQt6ElaWidgetTools - ElaPlainTextEdit 多行文本编辑",
                self._demoPlainTextEdit,
            )
        )
        self._addInfoText("多行文本编辑组件", parent_layout)
        text_edit = ElaPlainTextEdit(self)
        text_edit.setPlaceholderText("请输入多行文本...")
        text_edit.setFixedHeight(100)
        parent_layout.addWidget(text_edit)
        parent_layout.addSpacing(20)

    def _demoSpinBox(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "03. PyQt6ElaWidgetTools - ElaSpinBox 整数微调框", self._demoSpinBox
            )
        )
        self._addInfoText("整数微调框组件", parent_layout)
        spin_layout = QHBoxLayout()
        spin_layout.setSpacing(15)
        spin_box = ElaSpinBox(self)
        spin_box.setFixedWidth(150)
        spin_layout.addWidget(spin_box)
        spin_layout.addStretch()
        parent_layout.addLayout(spin_layout)
        parent_layout.addSpacing(20)

    def _demoDoubleSpinBox(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "04. PyQt6ElaWidgetTools - ElaDoubleSpinBox 浮点数微调框",
                self._demoDoubleSpinBox,
            )
        )
        self._addInfoText("浮点数微调框组件", parent_layout)
        dspin_layout = QHBoxLayout()
        dspin_layout.setSpacing(15)
        dspin_box = ElaDoubleSpinBox(self)
        dspin_box.setFixedWidth(150)
        dspin_box.setDecimals(2)
        dspin_layout.addWidget(dspin_box)
        dspin_layout.addStretch()
        parent_layout.addLayout(dspin_layout)
        parent_layout.addSpacing(20)

    def _onSliderValueChanged(self, value):
        self._sliderValueLabel.setText(str(value))

    def _demoSlider(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "05. PyQt6ElaWidgetTools - ElaSlider 滑块", self._demoSlider
            )
        )
        self._addInfoText("滑块组件，支持 valueChanged 信号实时反馈", parent_layout)
        slider_layout = QHBoxLayout()
        slider_layout.setSpacing(15)
        self._slider = ElaSlider(self)
        self._slider.setFixedWidth(200)
        self._slider.setRange(0, 100)
        self._slider.setValue(50)
        self._slider.valueChanged.connect(self._onSliderValueChanged)
        slider_layout.addWidget(self._slider)
        self._sliderValueLabel = ElaText("50", self)
        self._sliderValueLabel.setTextPixelSize(14)
        self._sliderValueLabel.setFixedWidth(40)
        slider_layout.addWidget(self._sliderValueLabel)
        slider_layout.addStretch()
        parent_layout.addLayout(slider_layout)
        parent_layout.addSpacing(20)

    def _demoCalendar(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "06. PyQt6ElaWidgetTools - ElaCalendar 日历", self._demoCalendar
            )
        )
        self._addInfoText("日历组件", parent_layout)
        calendar = ElaCalendar(self)
        calendar.setFixedWidth(280)
        parent_layout.addWidget(calendar)
        parent_layout.addSpacing(20)

    def _demoCalendarPicker(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "07. PyQt6ElaWidgetTools - ElaCalendarPicker 日期选择器",
                self._demoCalendarPicker,
            )
        )
        self._addInfoText("日期选择器组件", parent_layout)
        picker_layout = QHBoxLayout()
        picker_layout.setSpacing(15)
        calendar_picker = ElaCalendarPicker(self)
        calendar_picker.setFixedWidth(150)
        picker_layout.addWidget(calendar_picker)
        picker_layout.addStretch()
        parent_layout.addLayout(picker_layout)
        parent_layout.addSpacing(20)

    def _demoCheckBox(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "01. PyQt6ElaWidgetTools - ElaCheckBox 复选框", self._demoCheckBox
            )
        )
        self._addInfoText("复选框组件", parent_layout)
        checkbox_layout = QHBoxLayout()
        checkbox_layout.setSpacing(15)
        checkbox = ElaCheckBox("复选框", self)
        checkbox_layout.addWidget(checkbox)
        checkbox_disabled = ElaCheckBox("禁用", self)
        checkbox_disabled.setEnabled(False)
        checkbox_layout.addWidget(checkbox_disabled)
        checkbox_layout.addStretch()
        parent_layout.addLayout(checkbox_layout)
        parent_layout.addSpacing(20)

    def _demoRadioButton(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "02. PyQt6ElaWidgetTools - ElaRadioButton 单选按钮",
                self._demoRadioButton,
            )
        )
        self._addInfoText("单选按钮组件", parent_layout)
        radio_layout = QHBoxLayout()
        radio_layout.setSpacing(15)
        radio1 = ElaRadioButton("选项1", self)
        radio_layout.addWidget(radio1)
        radio2 = ElaRadioButton("选项2", self)
        radio2.setChecked(True)
        radio_layout.addWidget(radio2)
        radio_disabled = ElaRadioButton("禁用", self)
        radio_disabled.setEnabled(False)
        radio_layout.addWidget(radio_disabled)
        radio_layout.addStretch()
        parent_layout.addLayout(radio_layout)
        parent_layout.addSpacing(20)

    def _demoToggleSwitch(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "03. PyQt6ElaWidgetTools - ElaToggleSwitch 开关", self._demoToggleSwitch
            )
        )
        self._addInfoText("开关组件", parent_layout)
        switch_layout = QHBoxLayout()
        switch_layout.setSpacing(15)
        toggle_switch = ElaToggleSwitch(self)
        switch_layout.addWidget(toggle_switch)
        switch_disabled = ElaToggleSwitch(self)
        switch_disabled.setEnabled(False)
        switch_layout.addWidget(switch_disabled)
        switch_layout.addStretch()
        parent_layout.addLayout(switch_layout)
        parent_layout.addSpacing(20)

    def _demoRoller(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "05. PyQt6ElaWidgetTools - ElaRoller 滚轮选择器", self._demoRoller
            )
        )
        self._addInfoText(
            "滚轮样式的选择器，支持自定义列表项、可见项数量和循环滚动", parent_layout
        )
        roller_layout = QHBoxLayout()
        roller_layout.setSpacing(15)
        roller = ElaRoller(self)
        roller.setItemList(["选项 A", "选项 B", "选项 C", "选项 D", "选项 E", "选项 F"])
        roller.setCurrentIndex(2)
        roller.setFixedWidth(140)
        roller.setMaxVisibleItems(5)
        roller_layout.addWidget(roller)
        roller_current = ElaText("当前: 选项 C", self)
        roller_current.setTextPixelSize(13)
        roller.currentDataChanged.connect(
            lambda d: roller_current.setText(f"当前: {d}")
        )
        roller_layout.addWidget(roller_current)
        roller_layout.addStretch()
        parent_layout.addLayout(roller_layout)
        parent_layout.addSpacing(20)

    def _demoRollerPicker(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "06. PyQt6ElaWidgetTools - ElaRollerPicker 滚轮选择按钮",
                self._demoRollerPicker,
            )
        )
        self._addInfoText("点击按钮弹出滚轮选择面板，支持多个滚轮组合", parent_layout)
        picker_layout = QHBoxLayout()
        picker_layout.setSpacing(15)
        picker = ElaRollerPicker(self)
        picker.setText("选择日期")
        picker.setFixedWidth(150)
        picker.addRoller([str(y) for y in range(2020, 2031)])
        picker.addRoller([f"{m:02d}月" for m in range(1, 13)])
        picker.addRoller([f"{d:02d}日" for d in range(1, 29)])
        picker.currentDataChanged.connect(
            lambda d: picker.setText(
                f"{d[0]}-{d[1]}-{d[2]}" if isinstance(d, (list, tuple)) else str(d)
            )
        )
        picker_layout.addWidget(picker)
        picker_layout.addStretch()
        parent_layout.addLayout(picker_layout)
        parent_layout.addSpacing(20)

    def _demoPasswordEdit(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "01. pyqt6_ela_pro - ElaPasswordEdit 密码输入框", self._demoPasswordEdit
            )
        )
        self._addInfoText("带密码可见切换和底部强调线动画的密码输入框", parent_layout)
        edit_layout = QHBoxLayout()
        edit_layout.setSpacing(15)
        pwd = ElaPasswordEdit(self)
        pwd.setPlaceholderText("请输入密码")
        pwd.setFixedWidth(200)
        edit_layout.addWidget(pwd)
        pwd_disabled = ElaPasswordEdit(self)
        pwd_disabled.setPlaceholderText("禁用状态")
        pwd_disabled.setFixedWidth(200)
        pwd_disabled.setEnabled(False)
        edit_layout.addWidget(pwd_disabled)
        edit_layout.addStretch()
        parent_layout.addLayout(edit_layout)
        parent_layout.addSpacing(20)

    def _demoTagLineEdit(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "10. pyqt6_ela_pro - ElaTagLineEdit 标签输入框", self._demoTagLineEdit
            )
        )
        self._addInfoText(
            "带「上置标题」的输入框：标题不是 placeholder，是独立的小标签，"
            "输入后仍然留着；另有可开关的清空按钮与校验错误态",
            parent_layout,
        )
        edit_layout = QHBoxLayout()
        edit_layout.setSpacing(15)

        titled = ElaTagLineEdit(self, "用户名")
        titled.setTitleFontSize(12)
        titled.setPlaceholderText("请输入用户名")
        titled.setIsClearButtonEnable(True)
        titled.setFixedWidth(200)
        edit_layout.addWidget(titled)

        # 无标题 + 无清空按钮：退化成普通输入框的样子
        plain = ElaTagLineEdit(self)
        plain.setPlaceholderText("无标题、无清空按钮")
        plain.setFixedWidth(200)
        edit_layout.addWidget(plain)

        # 校验态：notifyInvalidInput() 上红、clearError() 撤销
        checked = ElaTagLineEdit(self, "错误态演示")
        checked.setText("invalid")
        checked.setFixedWidth(200)
        checked.notifyInvalidInput()
        edit_layout.addWidget(checked)

        edit_layout.addStretch()
        parent_layout.addLayout(edit_layout)

        action_layout = QHBoxLayout()
        action_layout.setSpacing(15)
        mark_bad = ElaPushButton("标为校验失败", self)
        mark_bad.setFixedWidth(130)
        mark_bad.clicked.connect(checked.notifyInvalidInput)
        clear_bad = ElaPushButton("清除错误态", self)
        clear_bad.setFixedWidth(130)
        clear_bad.clicked.connect(checked.clearError)
        action_layout.addWidget(mark_bad)
        action_layout.addWidget(clear_bad)
        action_layout.addStretch()
        parent_layout.addLayout(action_layout)
        parent_layout.addSpacing(20)

    def _demoUploadArea(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "11. pyqt6_ela_pro - ElaUploadArea 上传区域", self._demoUploadArea
            )
        )
        upload = ElaUploadArea(parent=self)
        upload.setFixedSize(300, 180)
        upload.filesSelected.connect(lambda paths: print(f"选择文件: {paths}"))
        upload.fileRejected.connect(
            lambda path, reason: print(f"拒绝: {path} ({reason})")
        )
        parent_layout.addWidget(upload)
        parent_layout.addSpacing(20)

    def _demoSpotlight(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "12. pyqt6_ela_pro - ElaSpotlight 引导遮罩", self._demoSpotlight
            )
        )
        self._addInfoText("单目标聚光 + 多步骤引导", parent_layout)

        row = QHBoxLayout()
        row.setSpacing(15)
        single_btn = ElaPushButton("单目标聚光", self)
        single_btn.setFixedWidth(110)
        single_target = ElaPushButton("高亮目标", self)
        single_target.setFixedWidth(110)
        row.addWidget(single_target)
        row.addWidget(single_btn)
        row.addStretch()
        parent_layout.addLayout(row)

        def _on_single():
            s = ElaSpotlight(self)
            s._title = "提示"
            s._content = "这是一个单目标引导示例"
            s.showSpotlight(single_target, "知道了")

        single_btn.clicked.connect(_on_single)
        parent_layout.addSpacing(12)

        self._addInfoText("多步骤引导，依次高亮下方三个按钮", parent_layout)
        spot_btn1 = ElaPushButton("第一步", self)
        spot_btn1.setFixedWidth(100)
        spot_btn2 = ElaPushButton("第二步", self)
        spot_btn2.setFixedWidth(100)
        spot_btn3 = ElaPushButton("第三步", self)
        spot_btn3.setFixedWidth(100)
        launch_btn = ElaPushButton("开始引导", self)
        launch_btn.setFixedWidth(100)
        spot_layout = QHBoxLayout()
        spot_layout.setSpacing(15)
        spot_layout.addWidget(spot_btn1)
        spot_layout.addWidget(spot_btn2)
        spot_layout.addWidget(spot_btn3)
        spot_layout.addWidget(launch_btn)
        spot_layout.addStretch()
        parent_layout.addLayout(spot_layout)

        def _on_multi():
            s = ElaSpotlight(self)
            s.setSteps(
                [
                    ElaSpotlight.SpotlightStep(
                        spot_btn1, "第一步", "点击此按钮开始操作", False
                    ),
                    ElaSpotlight.SpotlightStep(
                        spot_btn2, "第二步", "配置相关参数", False
                    ),
                    ElaSpotlight.SpotlightStep(
                        spot_btn3, "第三步", "确认并完成", False
                    ),
                ]
            )
            s.finished.connect(lambda: print("多步引导结束"))
            s.start()

        launch_btn.clicked.connect(_on_multi)
        parent_layout.addSpacing(20)
