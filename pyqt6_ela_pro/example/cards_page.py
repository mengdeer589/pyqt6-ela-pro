"""卡片与展示示例页。"""

import os

from PyQt6.QtGui import QColor, QLinearGradient, QPainter, QPixmap, QRadialGradient
from PyQt6.QtWidgets import QHBoxLayout
from PyQt6ElaWidgetTools import (
    ElaAcrylicUrlCard,
    ElaIconType,
    ElaImageCard,
    ElaInteractiveCard,
    ElaLCDNumber,
    ElaPopularCard,
    ElaPromotionCard,
    ElaPromotionView,
    ElaPushButton,
)
from pyqt6_ela_pro import (
    ElaAvatar,
    ElaAvatarPresenceType,
    ElaAvatarShapeType,
    ElaAvatarSizeType,
    ElaShimmer,
    ElaShimmerTemplateType,
    ElaTimeline,
)

from .base_page import ExamplePage, _res


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


class CardsPage(ExamplePage):
    """卡片与展示示例页。"""

    PAGE_TITLE = "卡片与展示"

    def _addDemoContent(self, main_layout):
        main_layout.addWidget(self._createSectionHeader("=== 卡片 ==="))
        self._demoImageCard(main_layout)
        self._demoInteractiveCard(main_layout)
        self._demoPopularCard(main_layout)
        self._demoPromotionCard(main_layout)
        self._demoAcrylicUrlCard(main_layout)
        self._demoPromotionView(main_layout)

        main_layout.addWidget(self._createSectionHeader("=== 展示与占位 ==="))
        self._demoLCDNumber(main_layout)
        self._demoTimeline(main_layout)
        self._demoAvatar(main_layout)
        self._demoShimmer(main_layout)

    def _setCardImage(self, card, filename):
        card.setCardImage(_card_pixmap(filename).toImage())

    def _setCardPixmap(self, card, filename):
        card.setCardPixmap(_card_pixmap(filename))

    def _demoImageCard(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "01. PyQt6ElaWidgetTools - ElaImageCard 图片卡片", self._demoImageCard
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

    def _demoInteractiveCard(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "02. PyQt6ElaWidgetTools - ElaInteractiveCard 交互卡片",
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
                "03. PyQt6ElaWidgetTools - ElaPopularCard 热门卡片",
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
                "04. PyQt6ElaWidgetTools - ElaPromotionCard 推广卡片",
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

    def _demoAcrylicUrlCard(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "05. PyQt6ElaWidgetTools - ElaAcrylicUrlCard 亚克力URL卡片",
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

    def _demoPromotionView(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "06. PyQt6ElaWidgetTools - ElaPromotionView 推广视图",
                self._demoPromotionView,
            )
        )
        self._addInfoText(
            "推广卡片的容器：appendPromotionCard + 自动滚动；每张卡片仍复用 "
            "ElaPromotionCard。",
            parent_layout,
        )
        view = ElaPromotionView(self)
        for index, title in enumerate(("STYX HELIX", "Beach", "Dream")):
            card = ElaPromotionCard(self)
            card.setTitle(title)
            card.setSubTitle("Never close your eyes")
            card.setCardTitle(f"Track {index + 1}")
            card.setPromotionTitle("SONG~")
            card.setBorderRadius(10)
            card.setFixedSize(340, 180)
            view.appendPromotionCard(card)
        view.setIsAutoScroll(True)
        view.setAutoScrollInterval(4000)
        view.setFixedHeight(220)
        parent_layout.addWidget(view)
        parent_layout.addSpacing(20)

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

    def _demoTimeline(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "02. pyqt6_ela_pro - ElaTimeline 时间线（垂直 / 水平）",
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

    def _demoAvatar(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "03. pyqt6_ela_pro - ElaAvatar 头像", self._demoAvatar
            )
        )
        self._addInfoText(
            "4 档尺寸或任意边长 / 圆形、4px 与 8px 圆角方 / 在线状态圆点；"
            "名字自动生成首字母。",
            parent_layout,
        )
        row = QHBoxLayout()
        row.setSpacing(20)
        for name, size, shape, presence in (
            (
                "Alice",
                ElaAvatarSizeType.Medium,
                ElaAvatarShapeType.Circular,
                ElaAvatarPresenceType.Available,
            ),
            (
                "Bob",
                ElaAvatarSizeType.Large,
                ElaAvatarShapeType.Circular,
                ElaAvatarPresenceType.Away,
            ),
            (
                "十二",
                ElaAvatarSizeType.Large,
                ElaAvatarShapeType.Square,
                ElaAvatarPresenceType.Busy,
            ),
            (
                "John Smith",
                ElaAvatarSizeType.ExtraLarge,
                ElaAvatarShapeType.Circular,
                ElaAvatarPresenceType.Offline,
            ),
        ):
            avatar = ElaAvatar(self)
            avatar.setName(name)
            avatar.setAvatarSize(size)
            avatar.setShape(shape)
            avatar.setPresence(presence)
            row.addWidget(avatar)
        compact = ElaAvatar(self)
        compact.setAvatarExtent(30)
        compact.setShape(ElaAvatarShapeType.Rounded)
        compact.setIconName(ElaIconType.IconName.Robot)
        compact.setPresence(ElaAvatarPresenceType.Available)
        row.addWidget(compact)
        row.addStretch()
        parent_layout.addLayout(row)
        parent_layout.addSpacing(20)

    def _demoShimmer(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "04. pyqt6_ela_pro - ElaShimmer 骨架屏", self._demoShimmer
            )
        )
        self._addInfoText(
            "内置文本 / 头像文本 / 图片卡模板；setActive(False) 只停扫光、"
            "基态照画，不会留下空白框。",
            parent_layout,
        )
        row = QHBoxLayout()
        row.setSpacing(16)
        text = ElaShimmer(self)
        text.setTemplate(ElaShimmerTemplateType.TextBlock)
        text.setFixedSize(240, 80)
        row.addWidget(text)

        avatar_text = ElaShimmer(self)
        avatar_text.setTemplate(ElaShimmerTemplateType.AvatarTextRow)
        avatar_text.setFixedSize(240, 56)
        row.addWidget(avatar_text)

        image = ElaShimmer(self)
        image.setTemplate(ElaShimmerTemplateType.ImageCard)
        image.setFixedSize(240, 140)
        row.addWidget(image)
        row.addStretch()
        parent_layout.addLayout(row)
        parent_layout.addSpacing(20)
