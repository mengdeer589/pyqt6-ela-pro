"""容器与布局

「装东西」的控件：滚动区、抽屉、分隔、分组、流式布局。

与「视图与列表」的分界是**有没有子项列表**：这一页管单个内容块
怎么摆（滚动 / 折叠 / 切分），下一页管一堆同类项怎么组织。
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QHBoxLayout, QVBoxLayout, QWidget
from PyQt6.QtGui import QFont
from PyQt6ElaWidgetTools import (
    ElaCheckBox,
    ElaFlowLayout,
    ElaPushButton,
    ElaScrollArea,
    ElaScrollPage,
    ElaText,
    ElaToggleSwitch,
)
from pyqt6_ela_pro import (
    ElaButton,
    ElaDivider,
    ElaDrawer,
    ElaDrawerArea,
    ElaDrawerPositionType,
    ElaGroupBox,
    ElaThemeWidget,
    create_ela_splitter,
)
from .base_page import ExamplePage


class ContainerLayoutPage(ExamplePage):
    """容器与布局示例页。"""

    PAGE_TITLE = "容器与布局"

    def __init__(self, parent=None):
        self._drawers = {}
        self._stateTooltip = None
        self._tooltip_demo_btn = None
        super().__init__(parent)

    def _addDemoContent(self, main_layout):
        # 调用顺序即页面顺序，且必须与各节标题的编号一致
        self._demoDrawerArea(main_layout)
        self._demoScrollArea(main_layout)
        self._demoScrollPage(main_layout)
        self._demoSplitter(main_layout)
        self._demoDivider(main_layout)
        self._demoGroupBox(main_layout)
        self._demoFlowLayout(main_layout)
        self._demoDrawer(main_layout)

    def _demoDrawerArea(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "01. PyQt6ElaWidgetTools - ElaDrawerArea 抽屉区域", self._demoDrawerArea
            )
        )
        self._addInfoText("点击标题栏或开关展开/收起抽屉", parent_layout)
        self._drawer_area = ElaDrawerArea(self)
        self._drawer_area.setHeaderHeight(50)
        header_widget = ElaThemeWidget(self._drawer_area)
        header_layout = QHBoxLayout(header_widget)
        header_title = ElaText("抽屉标题", header_widget)
        header_title.setTextPixelSize(14)
        header_layout.addWidget(header_title)
        self._drawer_switch = ElaToggleSwitch(header_widget)
        self._drawer_switch_text = ElaText("关", header_widget)
        self._drawer_switch_text.setTextPixelSize(14)

        def on_toggled(toggled):
            # setIsToggled 同步开关时原生会回发 toggled，状态一致时跳过避免回声
            if toggled == self._drawer_area.getIsExpand():
                return
            if toggled:
                self._drawer_area.expand()
            else:
                self._drawer_area.collapse()

        def on_expand_state_changed(is_expand):
            # 点击标题栏切换时，回向同步开关与文字（setIsToggled 值不变时不发信号，无循环）
            self._drawer_switch_text.setText("开" if is_expand else "关")
            self._drawer_switch.setIsToggled(is_expand)

        self._drawer_switch.toggled.connect(on_toggled)
        self._drawer_area.expandStateChanged.connect(on_expand_state_changed)
        header_layout.addWidget(self._drawer_switch_text)
        header_layout.addWidget(self._drawer_switch)
        self._drawer_area.setDrawerHeader(header_widget)
        drawer_widget = ElaThemeWidget(self._drawer_area)
        drawer_layout = QHBoxLayout(drawer_widget)
        for i in range(3):
            checkbox = ElaCheckBox(f"抽屉项目 {i + 1}", drawer_widget)
            drawer_layout.addWidget(checkbox)
        self._drawer_area.addDrawer(drawer_widget)
        parent_layout.addWidget(self._drawer_area)

    def _demoScrollArea(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "02. PyQt6ElaWidgetTools - ElaScrollArea 滚动区域", self._demoScrollArea
            )
        )
        self._addInfoText("区域内包含多个组件，可滚动查看", parent_layout)
        scroll_area = ElaScrollArea(self)
        scroll_area.setFixedHeight(200)
        scroll_area.setWidgetResizable(True)
        scroll_content = ElaThemeWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(10, 10, 10, 10)
        scroll_layout.setSpacing(10)
        for i in range(15):
            item = ElaText(f"滚动区域内的项目 {i + 1}", scroll_content)
            item.setTextPixelSize(14)
            scroll_layout.addWidget(item)
        scroll_layout.addStretch()
        scroll_area.setWidget(scroll_content)
        parent_layout.addWidget(scroll_area)
        parent_layout.addSpacing(20)

    def _demoScrollPage(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "03. PyQt6ElaWidgetTools - ElaScrollPage 分段页容器",
                self._demoScrollPage,
            )
        )
        self._addInfoText(
            "整页多段内容的容器。注意两点：① 内部是 StackedWidget，"
            "一次只显示一段，靠 navigation(index) 切段（不是全部堆在一起滚）；"
            "② 段标题取自该段控件的 windowTitle，为空时自动叫 Page_0 / Page_1……",
            parent_layout,
        )

        page = ElaScrollPage(self)
        page.setFixedHeight(260)
        page.setPageTitleSpacing(12)
        for index in range(3):
            block = ElaThemeWidget()
            # 段标题 = 这段的 windowTitle（空的话 C++ 会自动命名成 Page_N）
            block.setWindowTitle(f"第 {index + 1} 段")
            block_layout = QVBoxLayout(block)
            block_layout.setContentsMargins(10, 10, 10, 10)
            block_layout.setSpacing(6)
            head = ElaText(f"这是第 {index + 1} 段", block)
            head.setTextPixelSize(15)
            block_layout.addWidget(head)
            for line in range(3):
                text = ElaText(f"第 {index + 1} 段 · 第 {line + 1} 行", block)
                text.setTextPixelSize(14)
                block_layout.addWidget(text)
            block_layout.addStretch()
            page.addCentralWidget(block)
        parent_layout.addWidget(page)

        jump_layout = QHBoxLayout()
        jump_layout.setSpacing(15)
        for index in range(3):
            jump = ElaPushButton(f"跳到第 {index + 1} 段", self)
            jump.setFixedWidth(120)
            jump.clicked.connect(lambda _=False, i=index: page.navigation(i))
            jump_layout.addWidget(jump)

        title_btn = ElaPushButton("隐藏段标题", self)
        title_btn.setFixedWidth(140)
        self._scroll_page_titles = {"on": True}

        def _on_toggle_titles():
            self._scroll_page_titles["on"] = not self._scroll_page_titles["on"]
            page.setTitleVisible(self._scroll_page_titles["on"])
            title_btn.setText(
                "隐藏段标题" if self._scroll_page_titles["on"] else "显示段标题"
            )

        title_btn.clicked.connect(_on_toggle_titles)
        jump_layout.addWidget(title_btn)
        jump_layout.addStretch()
        parent_layout.addLayout(jump_layout)
        parent_layout.addSpacing(20)

    def _demoSplitter(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "04. pyqt6_ela_pro - ElaSplitter 分隔器", self._demoSplitter
            )
        )
        self._addInfoText(
            "ELA 主题风格的分割器，支持水平和垂直方向，自动响应主题切换",
            parent_layout,
        )
        widget1 = ElaThemeWidget(self)
        widget1.setMinimumSize(50, 50)
        layout1 = QVBoxLayout(widget1)
        text1 = ElaText("面板 1", widget1)
        text1.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text1.setTextPixelSize(14)
        layout1.addWidget(text1)

        widget2 = ElaThemeWidget(self)
        widget2.setMinimumSize(50, 50)
        layout2 = QVBoxLayout(widget2)
        text2 = ElaText("面板 2", widget2)
        text2.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text2.setTextPixelSize(14)
        layout2.addWidget(text2)

        widget3 = ElaThemeWidget(self)
        widget3.setMinimumSize(50, 50)
        layout3 = QVBoxLayout(widget3)
        text3 = ElaText("面板 3", widget3)
        text3.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text3.setTextPixelSize(14)
        layout3.addWidget(text3)

        splitter = create_ela_splitter([widget1, widget2, widget3], Qt.Orientation.Horizontal)
        splitter.setMinimumHeight(80)
        parent_layout.addWidget(splitter)
        parent_layout.addSpacing(12)

        # Vertical splitter
        v1 = ElaThemeWidget(self)
        v1.setMinimumSize(50, 50)
        l1 = QVBoxLayout(v1)
        t1 = ElaText("面板 A", v1)
        t1.setAlignment(Qt.AlignmentFlag.AlignCenter)
        t1.setTextPixelSize(14)
        l1.addWidget(t1)

        v2 = ElaThemeWidget(self)
        v2.setMinimumSize(50, 50)
        l2 = QVBoxLayout(v2)
        t2 = ElaText("面板 B", v2)
        t2.setAlignment(Qt.AlignmentFlag.AlignCenter)
        t2.setTextPixelSize(14)
        l2.addWidget(t2)

        vsplitter = create_ela_splitter([v1, v2], Qt.Orientation.Vertical)
        vsplitter.setMinimumHeight(160)
        parent_layout.addWidget(vsplitter)
        parent_layout.addSpacing(20)

    def _demoDivider(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "05. pyqt6_ela_pro - ElaDivider 分割线", self._demoDivider
            )
        )
        self._addInfoText(
            "Ant Design 风格分割线，支持水平/垂直、带文字、实线/虚线",
            parent_layout,
        )
        parent_layout.addSpacing(8)

        row = QHBoxLayout()
        row.setSpacing(20)
        for t, o in [("Left", "left"), ("Center", "center"), ("Right", "right")]:
            col = QVBoxLayout()
            lbl = ElaText(t, self)
            lbl.setTextPixelSize(12)
            col.addWidget(lbl)
            col.addWidget(ElaDivider(text=t, orientation=o, parent=self))
            row.addLayout(col)
        row.addStretch()
        parent_layout.addLayout(row)
        parent_layout.addSpacing(8)

        row = QHBoxLayout()
        row.setSpacing(20)
        col = QVBoxLayout()
        l1 = ElaText("Plain", self)
        l1.setTextPixelSize(12)
        col.addWidget(l1)
        col.addWidget(ElaDivider(parent=self))
        row.addLayout(col)
        col = QVBoxLayout()
        l2 = ElaText("Dashed", self)
        l2.setTextPixelSize(12)
        col.addWidget(l2)
        col.addWidget(ElaDivider(variant="dashed", parent=self))
        row.addLayout(col)
        col = QVBoxLayout()
        l3 = ElaText("Dashed w/ text", self)
        l3.setTextPixelSize(12)
        col.addWidget(l3)
        col.addWidget(ElaDivider(text="OR", variant="dashed", parent=self))
        row.addLayout(col)
        row.addStretch()
        parent_layout.addLayout(row)
        parent_layout.addSpacing(12)

        row = QHBoxLayout()
        row.setSpacing(20)
        info = ElaText("Vertical:", self)
        info.setTextPixelSize(12)
        row.addWidget(info)
        for t, o in [("Top", "top"), ("Center", "center"), ("Bottom", "bottom")]:
            w = QWidget(self)
            w.setFixedSize(60, 100)
            wl = QHBoxLayout(w)
            wl.addStretch()
            wl.addWidget(ElaDivider(text=t, orientation=o, vertical=True, parent=w))
            wl.addStretch()
            row.addWidget(w)
        row.addStretch()
        parent_layout.addLayout(row)
        parent_layout.addSpacing(20)

    def _demoGroupBox(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "06. pyqt6_ela_pro - ElaGroupBox 分组框", self._demoGroupBox
            )
        )
        self._addInfoText(
            "Ant Design 风格分组框，圆角边框 + 居中标题，支持放置子控件",
            parent_layout,
        )
        parent_layout.addSpacing(8)

        row = QHBoxLayout()
        row.setSpacing(20)

        gb1 = ElaGroupBox("基本信息", parent=self)
        gb1.setFixedSize(220, 160)
        l1 = QVBoxLayout(gb1)
        l1.setContentsMargins(12, 20, 12, 12)
        l1.setSpacing(6)
        name_label = ElaText("姓名: 张三", gb1)
        name_label.setTextPixelSize(13)
        l1.addWidget(name_label)
        age_label = ElaText("年龄: 28", gb1)
        age_label.setTextPixelSize(13)
        l1.addWidget(age_label)
        city_label = ElaText("城市: 北京", gb1)
        city_label.setTextPixelSize(13)
        l1.addWidget(city_label)
        row.addWidget(gb1)

        gb2 = ElaGroupBox("联系方式", parent=self)
        gb2.setFixedSize(220, 160)
        l2 = QVBoxLayout(gb2)
        l2.setContentsMargins(12, 20, 12, 12)
        l2.setSpacing(6)
        email_label = ElaText("邮箱: user@example.com", gb2)
        email_label.setTextPixelSize(13)
        l2.addWidget(email_label)
        phone_label = ElaText("电话: 138-0000-0000", gb2)
        phone_label.setTextPixelSize(13)
        l2.addWidget(phone_label)
        row.addWidget(gb2)

        row.addStretch()
        parent_layout.addLayout(row)
        parent_layout.addSpacing(20)

    def _demoFlowLayout(self, parent_layout):
        from PyQt6.QtWidgets import QWidget

        parent_layout.addLayout(
            self._createHeaderRow(
                "07. PyQt6ElaWidgetTools - ElaFlowLayout 流式布局", self._demoFlowLayout
            )
        )
        self._addInfoText(
            "自适应换行的流式布局容器，控件超出容器宽度时自动折行", parent_layout
        )
        container = QWidget(self)
        flow = ElaFlowLayout(container)
        colors = [
            ("#1677ff", "#e6f4ff"),
            ("#52c41a", "#f6ffed"),
            ("#fa8c16", "#fff7e6"),
            ("#722ed1", "#f9f0ff"),
            ("#13c2c2", "#e6fffb"),
            ("#eb2f96", "#fff0f6"),
            ("#fa541c", "#fff2e8"),
            ("#2f54eb", "#f0f5ff"),
            ("#a0d911", "#fcffe6"),
            ("#fadb14", "#feffe6"),
            ("#f5222d", "#fff1f0"),
            ("#0067c0", "#e5eff9"),
        ]
        for i, (border, bg) in enumerate(colors):
            btn = ElaPushButton(f"标签 {i + 1}", container)
            btn.setFixedWidth(80 + (i % 3) * 30)
            flow.addWidget(btn)
        container.setLayout(flow)
        parent_layout.addWidget(container)
        parent_layout.addSpacing(20)

    def _demoSiSideDrawer(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "01. ela_ext - ElaDrawer 四方向抽屉", self._demoSiSideDrawer
            )
        )
        self._addInfoText("SiliconUI 风格抽屉，支持上下左右四个方向滑入", parent_layout)
        # PyQt6/Qt6：``QFont().defaultFamily()`` 首次调用要 190ms（会去解析系统默认字体，
        # 触发字体引擎初始化）；应用字体的族名是零成本的（0.01ms）且就是同一个意图。
        default_font_family = QApplication.font().family()
        for name, pos, size in [
            ("左侧抽屉", ElaDrawerPositionType.Left, 300),
            ("右侧抽屉", ElaDrawerPositionType.Right, 380),
            ("顶部抽屉", ElaDrawerPositionType.Top, 200),
            ("底部抽屉", ElaDrawerPositionType.Bottom, 200),
        ]:
            drawer = ElaDrawer(position=pos, drawer_size=size, parent=self)
            content = ElaThemeWidget()
            content_layout = QVBoxLayout(content)
            content_layout.setContentsMargins(16, 16, 16, 16)
            content_layout.setSpacing(12)
            title = ElaText(name, content)
            title.setTextPixelSize(18)
            title.setFont(QFont(default_font_family, 18, QFont.Weight.Bold))
            content_layout.addWidget(title)
            desc = ElaText(f"这是一个{name}，可以放置设置项、表单等内容。", content)
            desc.setTextPixelSize(14)
            content_layout.addWidget(desc)
            content_layout.addStretch()
            close_btn = ElaButton(
                "关闭抽屉", variant="solid", color="primary", parent=content
            )
            close_btn.setFixedWidth(120)
            close_btn.clicked.connect(drawer.closeDrawer)
            content_layout.addWidget(close_btn)
            drawer.setContentWidget(content)
            self._drawers[name] = drawer
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(15)
        for name, drawer in self._drawers.items():
            btn = ElaPushButton(name, self)
            btn.setFixedWidth(100)
            btn.clicked.connect(drawer.showDrawer)
            btn_layout.addWidget(btn)
        btn_layout.addStretch()
        parent_layout.addLayout(btn_layout)
        parent_layout.addSpacing(20)

    def _demoDrawer(self, parent_layout):
        parent_layout.addWidget(self._createSectionHeader("=== ela_ext - 抽屉组件 ==="))
        self._demoSiSideDrawer(parent_layout)
