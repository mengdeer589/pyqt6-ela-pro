"""[pyqt6_ela_pro] Fluent 风格与补充组件示例页。

这一页专门补齐此前 example 从未实例化的组件：``ElaAvatar`` / ``ElaField`` /
``ElaSelectorBar`` / ``ElaShimmer``（pyqt6_ela_pro），以及上游的
``ElaPromotionView`` / ``ElaRibbonBar``。
"""

from PyQt6.QtWidgets import QHBoxLayout
from PyQt6ElaWidgetTools import (
    ElaIconType,
    ElaLineEdit,
    ElaPromotionCard,
    ElaPromotionView,
    ElaRibbonBar,
)

from pyqt6_ela_pro import (
    ElaAvatar,
    ElaAvatarPresenceType,
    ElaAvatarShapeType,
    ElaAvatarSizeType,
    ElaField,
    ElaFieldStatusType,
    ElaSelectorBar,
    ElaShimmer,
    ElaShimmerTemplateType,
)

from .base_page import ExamplePage


class FluentPage(ExamplePage):
    """Fluent 组件与上游补充组件的演示页。"""

    PAGE_TITLE = "Fluent 与补充组件"

    def _addDemoContent(self, main_layout):
        self._demoAvatar(main_layout)
        self._demoField(main_layout)
        self._demoSelectorBar(main_layout)
        self._demoShimmer(main_layout)
        self._demoPromotionView(main_layout)
        self._demoRibbonBar(main_layout)

    def _demoAvatar(self, main_layout):
        main_layout.addLayout(
            self._createHeaderRow(
                "01. pyqt6_ela_pro - ElaAvatar 头像", self._demoAvatar
            )
        )
        self._addInfoText(
            "三档尺寸 / 圆形与圆角方 / 在线状态圆点；名字会自动生成首字母。",
            main_layout,
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
        row.addStretch()
        main_layout.addLayout(row)
        main_layout.addSpacing(20)

    def _demoField(self, main_layout):
        main_layout.addLayout(
            self._createHeaderRow(
                "02. pyqt6_ela_pro - ElaField 表单字段", self._demoField
            )
        )
        self._addInfoText(
            "标签 + 必填星号 + 编辑器槽 + 辅助文字 + 三态校验行；编辑器生命周期按 "
            "ElaWidgetOwnershipType 三态管理。",
            main_layout,
        )
        row = QHBoxLayout()
        row.setSpacing(16)
        normal = ElaField(self)
        normal.setLabel("用户名")
        normal.setRequired(True)
        normal.setHelperText("2-16 个字符")
        normal.setEditor(ElaLineEdit(self))
        row.addWidget(normal, 1)

        error = ElaField(self)
        error.setLabel("邮箱")
        error.setEditor(ElaLineEdit(self))
        error.setStatus(ElaFieldStatusType.Error)
        error.setStatusText("邮箱格式不正确")
        row.addWidget(error, 1)

        success = ElaField(self)
        success.setLabel("显示名")
        success.setEditor(ElaLineEdit(self))
        success.setStatus(ElaFieldStatusType.Success)
        success.setStatusText("可用")
        row.addWidget(success, 1)
        main_layout.addLayout(row)
        main_layout.addSpacing(20)

    def _demoSelectorBar(self, main_layout):
        main_layout.addLayout(
            self._createHeaderRow(
                "03. pyqt6_ela_pro - ElaSelectorBar 分段控件", self._demoSelectorBar
            )
        )
        self._addInfoText(
            "互斥分段 + 三关键帧指示器（移动后绽开）；支持键盘与溢出。",
            main_layout,
        )
        bar = ElaSelectorBar(self)
        bar.addItems(["概览", "组件", "示例"])
        bar.setSelectedIndex(1)
        bar.setFixedWidth(520)
        main_layout.addWidget(bar)
        main_layout.addSpacing(20)

    def _demoShimmer(self, main_layout):
        main_layout.addLayout(
            self._createHeaderRow(
                "04. pyqt6_ela_pro - ElaShimmer 骨架屏", self._demoShimmer
            )
        )
        self._addInfoText(
            "内置文本 / 头像文本 / 图片卡模板；setActive(False) 只停扫光、"
            "基态照画，不会留下空白框。",
            main_layout,
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
        main_layout.addLayout(row)
        main_layout.addSpacing(20)

    def _demoPromotionView(self, main_layout):
        main_layout.addLayout(
            self._createHeaderRow(
                "05. PyQt6ElaWidgetTools - ElaPromotionView 推广视图",
                self._demoPromotionView,
            )
        )
        self._addInfoText(
            "推广卡片的容器：appendPromotionCard + 自动滚动；每张卡片仍复用 "
            "ElaPromotionCard。",
            main_layout,
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
        main_layout.addWidget(view)
        main_layout.addSpacing(20)

    def _demoRibbonBar(self, main_layout):
        main_layout.addLayout(
            self._createHeaderRow(
                "06. PyQt6ElaWidgetTools - ElaRibbonBar 功能区",
                self._demoRibbonBar,
            )
        )
        self._addInfoText(
            "按页 / 组组织 QAction，switchRibbonPage 切页；可绑定 QTabBar 或 ElaPivot。",
            main_layout,
        )
        ribbon = ElaRibbonBar(self)
        ribbon.addRibbonAction(
            "通用操作", "文件管理", "新建", ElaIconType.IconName.FilePlus
        )
        ribbon.addRibbonAction(
            "通用操作", "文件管理", "打开", ElaIconType.IconName.FolderOpen
        )
        ribbon.addRibbonAction(
            "记录与回放", "回放控制", "播放", ElaIconType.IconName.CirclePlay
        )
        ribbon.addRibbonAction(
            "系统与设置", "系统设置", "设置", ElaIconType.IconName.GearComplex
        )
        ribbon.switchRibbonPage("通用操作")
        main_layout.addWidget(ribbon)
        main_layout.addSpacing(20)
