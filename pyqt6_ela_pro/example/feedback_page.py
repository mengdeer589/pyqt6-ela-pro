"""反馈与状态示例页。"""

from PyQt6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from PyQt6ElaWidgetTools import (
    ElaIconType,
    ElaMessageBarType,
    ElaMessageButton,
    ElaProgressBar,
    ElaProgressRing,
    ElaProgressRingType,
    ElaPushButton,
)
from pyqt6_ela_pro import ElaChip, ElaInfoBadge

from .base_page import ExamplePage


class FeedbackStatusPage(ExamplePage):
    """反馈与状态示例页。"""

    PAGE_TITLE = "反馈与状态"

    def _addDemoContent(self, main_layout):
        main_layout.addWidget(self._createSectionHeader("=== 反馈 ==="))
        self._demoMessageButton(main_layout)
        self._demoProgressBar(main_layout)
        self._demoProgressRing(main_layout)

        main_layout.addWidget(self._createSectionHeader("=== 状态标记 ==="))
        self._demoInfoBadge(main_layout)
        self._demoChip(main_layout)

    def _demoMessageButton(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "01. PyQt6ElaWidgetTools - ElaMessageButton 消息按钮",
                self._demoMessageButton,
            )
        )
        self._addInfoText("消息按钮组件，点击显示消息条", parent_layout)
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(15)
        success_btn = ElaMessageButton("Success", self)
        success_btn.setBarTitle("Success")
        success_btn.setBarText("操作成功完成！")
        btn_layout.addWidget(success_btn)
        info_btn = ElaMessageButton("Info", self)
        info_btn.setBarTitle("Information")
        info_btn.setBarText("这是一条信息提示")
        info_btn.setMessageMode(ElaMessageBarType.MessageMode.Information)
        info_btn.setPositionPolicy(ElaMessageBarType.PositionPolicy.TopLeft)
        btn_layout.addWidget(info_btn)
        warning_btn = ElaMessageButton("Warning", self)
        warning_btn.setBarTitle("Warning")
        warning_btn.setBarText("警告，请注意！")
        warning_btn.setMessageMode(ElaMessageBarType.MessageMode.Warning)
        warning_btn.setPositionPolicy(ElaMessageBarType.PositionPolicy.BottomLeft)
        btn_layout.addWidget(warning_btn)
        error_btn = ElaMessageButton("Error", self)
        error_btn.setBarTitle("Error")
        error_btn.setBarText("发生错误！")
        error_btn.setMessageMode(ElaMessageBarType.MessageMode.Error)
        error_btn.setPositionPolicy(ElaMessageBarType.PositionPolicy.BottomRight)
        btn_layout.addWidget(error_btn)
        btn_layout.addStretch()
        parent_layout.addLayout(btn_layout)
        parent_layout.addSpacing(20)

    def _demoProgressBar(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "02. PyQt6ElaWidgetTools - ElaProgressBar 进度条", self._demoProgressBar
            )
        )
        self._addInfoText("水平进度条，显示当前操作进度", parent_layout)
        parent_layout.addSpacing(10)
        progress_bar = ElaProgressBar(self)
        progress_bar.setRange(0, 100)
        progress_bar.setValue(65)
        progress_bar.setFixedWidth(400)
        parent_layout.addWidget(progress_bar)
        parent_layout.addSpacing(30)

    def _demoProgressRing(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "03. PyQt6ElaWidgetTools - ElaProgressRing 环形进度",
                self._demoProgressRing,
            )
        )
        self._addInfoText("环形进度指示器，适用于等待状态", parent_layout)
        parent_layout.addSpacing(10)
        ring_container = QWidget(self)
        ring_layout = QHBoxLayout(ring_container)
        ring1 = ElaProgressRing(self)
        ring1.setValue(75)
        ring1.setIsDisplayValue(True)
        ring1.setValueDisplayMode(ElaProgressRingType.ValueDisplayMode.Percent)
        ring1.setFixedSize(100, 100)
        ring_layout.addWidget(ring1)
        ring2 = ElaProgressRing(self)
        ring2.setValue(50)
        ring2.setIsDisplayValue(True)
        ring2.setValueDisplayMode(ElaProgressRingType.ValueDisplayMode.Actual)
        ring2.setFixedSize(80, 80)
        ring_layout.addWidget(ring2)
        ring3 = ElaProgressRing(self)
        ring3.setIsBusying(True)
        ring3.setFixedSize(60, 60)
        ring_layout.addWidget(ring3)
        parent_layout.addWidget(ring_container)
        parent_layout.addSpacing(30)

    def _demoInfoBadge(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "01. pyqt6_ela_pro - ElaInfoBadge 角标", self._demoInfoBadge
            )
        )
        self._addInfoText(
            "5 种严重级别 (Attention / Informational / Success / Caution / Critical) × 3 种模式",
            parent_layout,
        )
        parent_layout.addSpacing(10)

        severity_names = [
            ("Attention", ElaInfoBadge.ElaSeverityType.Attention),
            ("Informational", ElaInfoBadge.ElaSeverityType.Informational),
            ("Success", ElaInfoBadge.ElaSeverityType.Success),
            ("Caution", ElaInfoBadge.ElaSeverityType.Caution),
            ("Critical", ElaInfoBadge.ElaSeverityType.Critical),
        ]

        row = QHBoxLayout()
        row.setSpacing(30)
        for name, sev in severity_names:
            container = QWidget()
            cl = QVBoxLayout(container)
            cl.setContentsMargins(0, 0, 0, 0)
            cl.setSpacing(4)
            btn = ElaPushButton(name, container)
            btn.setFixedWidth(110)
            badge = ElaInfoBadge(parent=container)
            badge.setSeverity(sev)
            badge.attachTo(btn)
            cl.addWidget(btn)
            row.addWidget(container)
        row.addStretch()
        parent_layout.addLayout(row)
        parent_layout.addSpacing(12)

        row = QHBoxLayout()
        row.setSpacing(30)
        for i, (name, sev) in enumerate(severity_names):
            container = QWidget()
            cl = QVBoxLayout(container)
            cl.setContentsMargins(0, 0, 0, 0)
            cl.setSpacing(4)
            btn = ElaPushButton(name, container)
            btn.setFixedWidth(110)
            badge = ElaInfoBadge(value=(i + 1) * 20, parent=container)
            badge.setSeverity(sev)
            badge.attachTo(btn)
            cl.addWidget(btn)
            row.addWidget(container)
        row.addStretch()
        parent_layout.addLayout(row)
        parent_layout.addSpacing(12)

        row = QHBoxLayout()
        row.setSpacing(30)
        container = QWidget()
        cl = QVBoxLayout(container)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(4)
        btn = ElaPushButton("溢出", container)
        btn.setFixedWidth(110)
        badge = ElaInfoBadge(value=150, parent=container)
        badge.setSeverity(ElaInfoBadge.ElaSeverityType.Caution)
        badge.attachTo(btn)
        cl.addWidget(btn)
        row.addWidget(container)
        container = QWidget()
        cl = QVBoxLayout(container)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(4)
        btn = ElaPushButton("图标", container)
        btn.setFixedWidth(110)
        badge = ElaInfoBadge(icon=ElaIconType.IconName.BadgeCheck, parent=container)
        badge.setSeverity(ElaInfoBadge.ElaSeverityType.Success)
        badge.attachTo(btn)
        cl.addWidget(btn)
        row.addWidget(container)
        container = QWidget()
        cl = QVBoxLayout(container)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(4)
        btn = ElaPushButton("齿轮", container)
        btn.setFixedWidth(110)
        badge = ElaInfoBadge(icon=ElaIconType.IconName.Gear, parent=container)
        badge.setSeverity(ElaInfoBadge.ElaSeverityType.Informational)
        badge.attachTo(btn)
        cl.addWidget(btn)
        row.addWidget(container)
        row.addStretch()
        parent_layout.addLayout(row)
        parent_layout.addSpacing(8)

        row = QHBoxLayout()
        row.setSpacing(15)
        container = QWidget()
        cl = QVBoxLayout(container)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(4)
        target_btn = ElaPushButton("目标按钮", container)
        target_btn.setFixedWidth(110)
        demo_badge = ElaInfoBadge(value=7, parent=container)
        demo_badge.setSeverity(ElaInfoBadge.ElaSeverityType.Attention)
        demo_badge.attachTo(target_btn)
        cl.addWidget(target_btn)
        row.addWidget(container)
        add_btn = ElaPushButton("添加", container)
        add_btn.setFixedWidth(70)
        add_btn.clicked.connect(lambda: demo_badge.attachTo(target_btn))
        row.addWidget(add_btn)
        remove_btn = ElaPushButton("移除", container)
        remove_btn.setFixedWidth(70)
        remove_btn.clicked.connect(demo_badge.detach)
        row.addWidget(remove_btn)
        row.addStretch()
        parent_layout.addLayout(row)
        parent_layout.addSpacing(20)

    def _demoChip(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "02. pyqt6_ela_pro - ElaChip 标签纸片", self._demoChip
            )
        )
        self._addInfoText(
            "16 种颜色（同 ElaButton 色系）+ 可关闭 / 可选择 / 胶囊 / 前置图标；"
            "彩字按 WCAG 对比度 ≥4.5 派生，深浅主题下都清晰",
            parent_layout,
        )
        parent_layout.addSpacing(10)

        colors = [
            ("Default", ElaChip.ElaChipColorType.Default),
            ("Primary", ElaChip.ElaChipColorType.Primary),
            ("Blue", ElaChip.ElaChipColorType.Blue),
            ("Purple", ElaChip.ElaChipColorType.Purple),
            ("Cyan", ElaChip.ElaChipColorType.Cyan),
            ("Green", ElaChip.ElaChipColorType.Green),
            ("Magenta", ElaChip.ElaChipColorType.Magenta),
            ("Pink", ElaChip.ElaChipColorType.Pink),
            ("Red", ElaChip.ElaChipColorType.Red),
            ("Danger", ElaChip.ElaChipColorType.Danger),
            ("Orange", ElaChip.ElaChipColorType.Orange),
            ("Yellow", ElaChip.ElaChipColorType.Yellow),
            ("Volcano", ElaChip.ElaChipColorType.Volcano),
            ("Geekblue", ElaChip.ElaChipColorType.Geekblue),
            ("Lime", ElaChip.ElaChipColorType.Lime),
            ("Gold", ElaChip.ElaChipColorType.Gold),
        ]

        row = QHBoxLayout()
        row.setSpacing(8)
        for name, c in colors:
            chip = ElaChip(name, parent=self)
            chip.setColor(c)
            row.addWidget(chip)
        row.addStretch()
        parent_layout.addLayout(row)
        parent_layout.addSpacing(8)

        row = QHBoxLayout()
        row.setSpacing(8)
        for name, c in colors:
            chip = ElaChip(name, parent=self)
            chip.setColor(c)
            chip.setClosable(True)
            row.addWidget(chip)
        row.addStretch()
        parent_layout.addLayout(row)
        parent_layout.addSpacing(8)

        row = QHBoxLayout()
        row.setSpacing(8)
        for name, c in colors:
            chip = ElaChip(name, parent=self)
            chip.setColor(c)
            chip.setCheckable(True)
            chip.setChecked(True)
            row.addWidget(chip)
        row.addStretch()
        parent_layout.addLayout(row)
        parent_layout.addSpacing(8)

        row = QHBoxLayout()
        row.setSpacing(8)
        pill = ElaChip("胶囊", parent=self)
        pill.setColor(ElaChip.ElaChipColorType.Primary)
        pill.setPill(True)
        row.addWidget(pill)
        closable_pill = ElaChip("可关闭胶囊", parent=self)
        closable_pill.setColor(ElaChip.ElaChipColorType.Blue)
        closable_pill.setPill(True)
        closable_pill.setClosable(True)
        row.addWidget(closable_pill)
        tag_chip = ElaChip("带前置图标", parent=self)
        tag_chip.setColor(ElaChip.ElaChipColorType.Green)
        tag_chip.setLeadingIcon(ElaIconType.IconName.Tag)
        row.addWidget(tag_chip)
        attach_chip = ElaChip("附件", parent=self)
        attach_chip.setColor(ElaChip.ElaChipColorType.Gold)
        attach_chip.setLeadingIcon(ElaIconType.IconName.Paperclip)
        row.addWidget(attach_chip)
        row.addStretch()
        parent_layout.addLayout(row)
        parent_layout.addSpacing(20)
