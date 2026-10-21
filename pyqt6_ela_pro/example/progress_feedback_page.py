"""进度与反馈

「告诉用户现在怎么样 / 结果长什么样」：进度、状态标记、卡片。

此前散在三页：进度条在「容器展示」、角标/步骤/评分/分页在「扩展组件」、
各类卡片也在「容器展示」。共同点是**只读地呈现状态**，而
「容器与布局」管的是能装东西的 —— 这条线用户能记住。
"""

import os

from PyQt6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from PyQt6ElaWidgetTools import (
    ElaAcrylicUrlCard,
    ElaIconType,
    ElaImageCard,
    ElaInteractiveCard,
    ElaLCDNumber,
    ElaMessageBarType,
    ElaMessageButton,
    ElaPopularCard,
    ElaProgressBar,
    ElaProgressRing,
    ElaProgressRingType,
    ElaPromotionCard,
    ElaPushButton,
    ElaReminderCard,
)
from .base_page import ExamplePage, _res
from PyQt6.QtGui import QColor, QLinearGradient, QPainter, QPixmap, QRadialGradient
from pyqt6_ela_pro import (
    ElaChip,
    ElaInfoBadge,
    ElaPagination,
    ElaRatingControl,
    ElaSteps,
    ElaTimeline,
)


def _placeholder_card_pixmap(width: int = 640, height: int = 420) -> QPixmap:
    """示例图片缺失时的占位封面：深色渐变，白字在深浅主题下都可读。"""
    pixmap = QPixmap(width, height)
    pixmap.fill(QColor("#12151b"))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    base = QLinearGradient(0.0, 0.0, float(width), float(height))
    base.setColorAt(0.0, QColor("#3a4152"))
    base.setColorAt(1.0, QColor("#151920"))
    painter.fillRect(pixmap.rect(), base)
    glow = QRadialGradient(width * 0.72, height * 0.28, width * 0.6)
    glow.setColorAt(0.0, QColor(110, 150, 255, 110))
    glow.setColorAt(1.0, QColor(110, 150, 255, 0))
    painter.fillRect(pixmap.rect(), glow)
    glow = QRadialGradient(width * 0.2, height * 0.85, width * 0.55)
    glow.setColorAt(0.0, QColor(80, 200, 170, 70))
    glow.setColorAt(1.0, QColor(80, 200, 170, 0))
    painter.fillRect(pixmap.rect(), glow)
    painter.end()
    return pixmap


def _card_pixmap(filename: str) -> QPixmap:
    """加载示例封面；资源缺失或损坏时回退为占位图。"""
    path = _res(filename)
    if os.path.exists(path):
        pixmap = QPixmap(path)
        if not pixmap.isNull():
            return pixmap
    return _placeholder_card_pixmap()


class ProgressFeedbackPage(ExamplePage):
    """进度与反馈示例页。"""

    PAGE_TITLE = "进度与反馈"

    def __init__(self, parent=None):
        super().__init__(parent)

    def _addDemoContent(self, main_layout):
        self._demoLCDNumber(main_layout)
        self._demoMessageButton(main_layout)
        self._demoProgressBar(main_layout)
        self._demoProgressRing(main_layout)
        self._demoImageCard(main_layout)
        self._demoInteractiveCard(main_layout)
        self._demoPopularCard(main_layout)
        self._demoPromotionCard(main_layout)
        self._demoReminderCard(main_layout)
        self._demoAcrylicUrlCard(main_layout)
        self._demoInfoBadge(main_layout)
        self._demoChip(main_layout)
        self._demoSteps(main_layout)
        self._demoRatingControl(main_layout)
        self._demoPagination(main_layout)
        self._demoTimeline(main_layout)

    def _demoLCDNumber(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "01. PyQt6ElaWidgetTools - ElaLCDNumber LCD数字显示",
                self._demoLCDNumber,
            )
        )
        self._addInfoText(
            "LCD数字显示组件，setIsUseAutoClock(True) 自动显示当前时间", parent_layout
        )
        lcd_layout = QHBoxLayout()
        lcd_layout.setSpacing(15)
        lcd = ElaLCDNumber(self)
        lcd.setFixedHeight(100)
        lcd.setIsUseAutoClock(True)
        lcd.setIsTransparent(False)
        lcd_layout.addWidget(lcd)
        lcd_layout.addStretch()
        parent_layout.addLayout(lcd_layout)
        parent_layout.addSpacing(20)

    def _demoMessageButton(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "02. PyQt6ElaWidgetTools - ElaMessageButton 消息按钮",
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
                "01. PyQt6ElaWidgetTools - ElaProgressBar 进度条", self._demoProgressBar
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
                "02. PyQt6ElaWidgetTools - ElaProgressRing 环形进度",
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

    def _setCardImage(self, card, filename):
        card.setCardImage(_card_pixmap(filename).toImage())

    def _demoImageCard(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "03. PyQt6ElaWidgetTools - ElaImageCard 图片卡片", self._demoImageCard
            )
        )
        self._addInfoText("带图片的卡片组件", parent_layout)
        if not os.path.exists(_res("miku.png")):
            self._addInfoText(
                "本地未放置示例图片 resource/images/miku.png，以下卡片封面使用程序生成的占位图",
                parent_layout,
            )
        parent_layout.addSpacing(10)
        card = ElaImageCard(self)
        card.setFixedSize(240, 180)
        card.setBorderRadius(8)
        self._setCardImage(card, "miku.png")
        parent_layout.addWidget(card)
        parent_layout.addSpacing(30)

    def _setCardPixmap(self, card, filename):
        card.setCardPixmap(_card_pixmap(filename))

    def _demoInteractiveCard(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "04. PyQt6ElaWidgetTools - ElaInteractiveCard 交互卡片",
                self._demoInteractiveCard,
            )
        )
        self._addInfoText("可交互的卡片组件，支持点击", parent_layout)
        parent_layout.addSpacing(10)
        card = ElaInteractiveCard(self)
        card.setTitle("热门文章")
        card.setSubTitle("点击查看详情")
        card.setBorderRadius(8)
        self._setCardPixmap(card, "miku.png")
        card.setCardPixmapSize(240, 120)
        card.setFixedSize(260, 200)
        parent_layout.addWidget(card)
        parent_layout.addSpacing(30)

    def _demoPopularCard(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "05. PyQt6ElaWidgetTools - ElaPopularCard 热门卡片",
                self._demoPopularCard,
            )
        )
        self._addInfoText("展示热门内容的卡片组件", parent_layout)
        parent_layout.addSpacing(10)
        card = ElaPopularCard(self)
        card.setTitle("STYX HELIX")
        card.setSubTitle("阅读量: 10,000+")
        card.setInteractiveTips("查看详情")
        card.setCardButtonText("立即阅读")
        card.setBorderRadius(8)
        self._setCardPixmap(card, "miku.png")
        card.setFixedSize(260, 220)
        parent_layout.addWidget(card)
        parent_layout.addSpacing(30)

    def _demoPromotionCard(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "06. PyQt6ElaWidgetTools - ElaPromotionCard 推广卡片",
                self._demoPromotionCard,
            )
        )
        self._addInfoText("推广促销类卡片组件", parent_layout)
        parent_layout.addSpacing(10)
        card = ElaPromotionCard(self)
        card.setTitle("STYX HELIX")
        card.setSubTitle("Never close your eyes")
        card.setCardTitle("MiKu")
        card.setPromotionTitle("SONG~")
        card.setBorderRadius(10)
        self._setCardPixmap(card, "miku.png")
        card.setHorizontalCardPixmapRatio(0.5)
        card.setFixedSize(340, 180)
        parent_layout.addWidget(card)
        parent_layout.addSpacing(30)

    def _demoReminderCard(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "07. PyQt6ElaWidgetTools - ElaReminderCard 提醒卡片",
                self._demoReminderCard,
            )
        )
        self._addInfoText("提醒通知类卡片组件", parent_layout)
        parent_layout.addSpacing(10)
        card = ElaReminderCard(self)
        card.setTitle("会议提醒")
        card.setSubTitle("下午3点有一场会议")
        card.setBorderRadius(8)
        self._setCardPixmap(card, "miku.png")
        card.setFixedSize(320, 100)
        parent_layout.addWidget(card)
        parent_layout.addSpacing(30)

    def _demoAcrylicUrlCard(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "08. PyQt6ElaWidgetTools - ElaAcrylicUrlCard 亚克力URL卡片",
                self._demoAcrylicUrlCard,
            )
        )
        self._addInfoText("带亚克力效果的URL链接卡片", parent_layout)
        parent_layout.addSpacing(10)
        card = ElaAcrylicUrlCard(self)
        card.setTitle("访问网站")
        card.setSubTitle("点击打开链接")
        card.setUrl("https://example.com")
        card.setBorderRadius(8)
        self._setCardPixmap(card, "miku.png")
        card.setFixedSize(320, 120)
        parent_layout.addWidget(card)
        parent_layout.addSpacing(30)

    def _demoInfoBadge(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "05. pyqt6_ela_pro - ElaInfoBadge 角标", self._demoInfoBadge
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
                "06. pyqt6_ela_pro - ElaChip 标签纸片", self._demoChip
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

    def _demoSteps(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "07. pyqt6_ela_pro - ElaSteps 步骤条（水平 / 竖直）", self._demoSteps
            )
        )
        steps = ElaSteps(parent=self)
        steps.step_titles = [
            "第一步",
            "第二步",
            "第三步",
            "第四步",
            "第五步",
            "第六步",
            "第七步",
        ]
        steps.currentStepChanged.connect(lambda v: print(f"步骤: {v + 1}"))
        parent_layout.addWidget(steps)
        nav = QHBoxLayout()
        prev_btn = ElaPushButton("上一步", self)
        prev_btn.clicked.connect(steps.previous)
        nav.addWidget(prev_btn)
        next_btn = ElaPushButton("下一步", self)
        next_btn.clicked.connect(steps.next)
        nav.addWidget(next_btn)
        nav.addStretch()
        parent_layout.addLayout(nav)

        vertical_row = QHBoxLayout()
        vertical_steps = ElaSteps(parent=self)
        vertical_steps.setOrientation("vertical")
        vertical_steps.step_titles = ["需求评审", "方案设计", "开发实现", "测试发布"]
        vertical_steps.setCurrentStep(1)
        vertical_steps.setFixedWidth(220)
        vertical_row.addWidget(vertical_steps)
        vertical_row.addStretch()
        parent_layout.addLayout(vertical_row)
        parent_layout.addSpacing(20)

    def _demoRatingControl(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "08. pyqt6_ela_pro - ElaRatingControl 评分", self._demoRatingControl
            )
        )
        rating = ElaRatingControl(parent=self)
        rating.ratingChanged.connect(lambda v: print(f"评分: {v}"))
        parent_layout.addWidget(rating)
        parent_layout.addSpacing(20)

    def _demoPagination(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "09. pyqt6_ela_pro - ElaPagination 分页", self._demoPagination
            )
        )
        pag = ElaPagination(parent=self)
        pag.setTotalPages(100)
        pag.setJumperVisible(True)
        pag.currentPageChanged.connect(lambda p: print(f"跳转到第 {p} 页"))
        parent_layout.addWidget(pag)
        parent_layout.addSpacing(20)

    def _demoTimeline(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "10. pyqt6_ela_pro - ElaTimeline 时间线（垂直 / 水平）",
                self._demoTimeline,
            )
        )
        timeline = ElaTimeline(parent=self)
        timeline.addItem(
            ElaTimeline.TimelineItem(
                title="创建项目",
                content="项目框架初始化完成",
                timestamp="2024-01-01",
                icon=ElaIconType.IconName.FloppyDisk,
            )
        )
        timeline.addItem(
            ElaTimeline.TimelineItem(
                title="开发阶段",
                content="核心功能开发中",
                timestamp="2024-02-15",
            )
        )
        timeline.addItem(
            ElaTimeline.TimelineItem(
                title="测试阶段",
                content="进行集成测试",
                timestamp="2024-03-20",
            )
        )
        timeline.setMinimumHeight(200)
        parent_layout.addWidget(timeline)
        nav = QHBoxLayout()
        for i, label in enumerate(["创建项目", "开发阶段", "测试阶段"]):
            btn = ElaPushButton(label, self)
            btn.setFixedWidth(90)
            btn.clicked.connect(lambda checked, idx=i: timeline.setCurrentStep(idx))
            nav.addWidget(btn)
        nav.addStretch()
        parent_layout.addLayout(nav)

        horizontal = ElaTimeline(parent=self)
        horizontal.setOrientation("horizontal")
        horizontal.addItem(
            ElaTimeline.TimelineItem(
                title="立项", content="确定目标与范围", timestamp="01-01"
            )
        )
        horizontal.addItem(
            ElaTimeline.TimelineItem(
                title="开发",
                content="按计划推进",
                timestamp="02-15",
                icon=ElaIconType.IconName.Code,
            )
        )
        horizontal.addItem(
            ElaTimeline.TimelineItem(
                title="发布", content="上线并观察", timestamp="03-20"
            )
        )
        horizontal.setCurrentStep(1)
        horizontal.setMinimumHeight(140)
        parent_layout.addWidget(horizontal)
        parent_layout.addSpacing(20)
