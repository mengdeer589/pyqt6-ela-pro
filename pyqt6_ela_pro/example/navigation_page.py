"""导航与工具示例页。"""

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import QHBoxLayout, QWidget
from PyQt6ElaWidgetTools import (
    ElaBreadcrumbBar,
    ElaKeyBinder,
    ElaPivot,
    ElaPushButton,
    ElaScrollBar,
    ElaSuggestBox,
    ElaTabBar,
    ElaTabWidget,
    ElaText,
)
from pyqt6_ela_pro import ElaPagination, ElaSelectorBar, ElaSteps

from .base_page import ExamplePage


class NavigationToolsPage(ExamplePage):
    """导航与工具示例页。"""

    PAGE_TITLE = "导航与工具"

    def _addDemoContent(self, main_layout):
        main_layout.addWidget(self._createSectionHeader("=== 导航与标签 ==="))
        self._demoBreadcrumbBar(main_layout)
        self._demoPivot(main_layout)
        self._demoTabBar(main_layout)
        self._demoTabWidget(main_layout)
        self._demoSelectorBar(main_layout)

        main_layout.addWidget(self._createSectionHeader("=== 输入与辅助 ==="))
        self._demoSuggestBox(main_layout)
        self._demoKeyBinder(main_layout)
        self._demoScrollBar(main_layout)

        main_layout.addWidget(self._createSectionHeader("=== 流程 ==="))
        self._demoSteps(main_layout)
        self._demoPagination(main_layout)

    def _demoBreadcrumbBar(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "01. PyQt6ElaWidgetTools - ElaBreadcrumbBar 面包屑导航",
                self._demoBreadcrumbBar,
            )
        )
        self._addInfoText("面包屑导航组件，支持点击切换", parent_layout)
        breadcrumb = ElaBreadcrumbBar(self)
        breadcrumb_list = [f"项目{i}" for i in range(1, 8)]
        breadcrumb.setBreadcrumbList(breadcrumb_list)
        parent_layout.addWidget(breadcrumb)
        parent_layout.addSpacing(20)

    def _demoPivot(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "02. PyQt6ElaWidgetTools - ElaPivot Pivot标签", self._demoPivot
            )
        )
        self._addInfoText(
            "Pivot标签组件，适合切换视图；V3.0 起可用 setTextPixelSize / "
            "setCurrentTitle / clearPivot",
            parent_layout,
        )
        pivot = ElaPivot(self)
        pivot.setPivotSpacing(8)
        pivot.setMarkWidth(75)
        pivot.appendPivot("本地歌曲")
        pivot.appendPivot("下载歌曲")
        pivot.appendPivot("下载视频")
        pivot.appendPivot("正在下载")
        pivot.setCurrentIndex(0)
        parent_layout.addWidget(pivot)
        nav = QHBoxLayout()
        nav.setSpacing(8)
        for text, callback in (
            ("字号 12", lambda: pivot.setTextPixelSize(12)),
            ("字号 20", lambda: pivot.setTextPixelSize(20)),
            ("跳到「下载视频」", lambda: pivot.setCurrentTitle("下载视频")),
            ("clearPivot", pivot.clearPivot),
        ):
            btn = ElaPushButton(text, self)
            btn.setFixedWidth(120)
            btn.clicked.connect(callback)
            nav.addWidget(btn)
        nav.addStretch()
        parent_layout.addLayout(nav)
        parent_layout.addSpacing(20)

    def _demoTabBar(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "03. PyQt6ElaWidgetTools - ElaTabBar 标签栏", self._demoTabBar
            )
        )
        self._addInfoText(
            "标签栏组件；页签溢出时用 locateCurrentTab() 把当前页签滚进视野",
            parent_layout,
        )
        tab_bar = ElaTabBar(self)
        for i in range(1, 11):
            tab_bar.addTab(f"标签{i}")
        parent_layout.addWidget(tab_bar)
        nav = QHBoxLayout()
        nav.setSpacing(8)
        for text, callback in (
            ("切到第 8 个", lambda: tab_bar.setCurrentIndex(7)),
            ("定位当前页签", tab_bar.locateCurrentTab),
        ):
            btn = ElaPushButton(text, self)
            btn.setFixedWidth(120)
            btn.clicked.connect(callback)
            nav.addWidget(btn)
        nav.addStretch()
        parent_layout.addLayout(nav)
        parent_layout.addSpacing(20)

    def _demoTabWidget(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "04. PyQt6ElaWidgetTools - ElaTabWidget 标签页", self._demoTabWidget
            )
        )
        self._addInfoText(
            "标签页组件；setTabSize 自定义页签尺寸，locateCurrentTab 滚动到当前页签",
            parent_layout,
        )
        tab_widget = ElaTabWidget(self)
        tab_widget.setFixedHeight(200)
        tab_widget.setIsTabTransparent(True)
        for i in range(1, 11):
            page = ElaText(f"新标签页{i}", self)
            page.setAlignment(Qt.AlignmentFlag.AlignCenter)
            font_page = page.font()
            font_page.setPixelSize(32)
            page.setFont(font_page)
            tab_widget.addTab(page, f"新标签页{i}")
        parent_layout.addWidget(tab_widget)
        nav = QHBoxLayout()
        nav.setSpacing(8)
        for text, callback in (
            ("切到第 8 个", lambda: tab_widget.setCurrentIndex(7)),
            ("定位当前页签", tab_widget.locateCurrentTab),
            ("页签宽 140", lambda: tab_widget.setTabSize(QSize(140, 30))),
        ):
            btn = ElaPushButton(text, self)
            btn.setFixedWidth(120)
            btn.clicked.connect(callback)
            nav.addWidget(btn)
        nav.addStretch()
        parent_layout.addLayout(nav)
        parent_layout.addSpacing(20)

    def _demoSelectorBar(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "05. pyqt6_ela_pro - ElaSelectorBar 分段控件", self._demoSelectorBar
            )
        )
        self._addInfoText(
            "互斥分段 + 三关键帧指示器（移动后绽开）；支持键盘与溢出。",
            parent_layout,
        )
        bar = ElaSelectorBar(self)
        bar.addItems(["概览", "组件", "示例"])
        bar.setSelectedIndex(1)
        bar.setFixedWidth(520)
        parent_layout.addWidget(bar)
        parent_layout.addSpacing(20)

    def _demoSuggestBox(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "01. PyQt6ElaWidgetTools - ElaSuggestBox 建议框", self._demoSuggestBox
            )
        )
        self._addInfoText("输入时显示建议列表", parent_layout)
        suggest_box = ElaSuggestBox(self)
        suggest_box.setFixedWidth(300)
        suggest_box.addSuggestion("Python")
        suggest_box.addSuggestion("JavaScript")
        suggest_box.addSuggestion("C++")
        suggest_box.addSuggestion("Java")
        suggest_box.addSuggestion("Go")
        suggest_box.addSuggestion("Rust")
        suggest_box.addSuggestion("TypeScript")
        parent_layout.addWidget(suggest_box)
        parent_layout.addSpacing(20)

    def _demoKeyBinder(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "02. PyQt6ElaWidgetTools - ElaKeyBinder 快捷键提示",
                self._demoKeyBinder,
            )
        )
        self._addInfoText("显示快捷键绑定的标签组件", parent_layout)
        parent_layout.addSpacing(10)
        binder_container = QWidget(self)
        binder_layout = QHBoxLayout(binder_container)
        binder1 = ElaKeyBinder(self)
        binder1.setBinderKeyText("Ctrl + S")
        binder1.setBorderRadius(4)
        binder_layout.addWidget(binder1)
        binder2 = ElaKeyBinder(self)
        binder2.setBinderKeyText("Ctrl + C")
        binder2.setBorderRadius(4)
        binder_layout.addWidget(binder2)
        binder3 = ElaKeyBinder(self)
        binder3.setBinderKeyText("Ctrl + V")
        binder3.setBorderRadius(4)
        binder_layout.addWidget(binder3)
        parent_layout.addWidget(binder_container)
        parent_layout.addSpacing(20)

    def _demoScrollBar(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "03. PyQt6ElaWidgetTools - ElaScrollBar 滚动条",
                self._demoScrollBar,
            )
        )
        self._addInfoText("滚动条组件", parent_layout)
        scroll_layout = QHBoxLayout()
        scroll_layout.setSpacing(15)
        scroll_bar = ElaScrollBar(self)
        scroll_bar.setFixedHeight(100)
        scroll_layout.addWidget(scroll_bar)
        scroll_layout.addStretch()
        parent_layout.addLayout(scroll_layout)
        parent_layout.addSpacing(20)

    def _demoSteps(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "01. pyqt6_ela_pro - ElaSteps 步骤条（水平 / 竖直）", self._demoSteps
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

    def _demoPagination(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "02. pyqt6_ela_pro - ElaPagination 分页", self._demoPagination
            )
        )
        pag = ElaPagination(parent=self)
        pag.setTotalPages(100)
        pag.setJumperVisible(True)
        pag.currentPageChanged.connect(lambda p: print(f"跳转到第 {p} 页"))
        parent_layout.addWidget(pag)
        parent_layout.addSpacing(20)
