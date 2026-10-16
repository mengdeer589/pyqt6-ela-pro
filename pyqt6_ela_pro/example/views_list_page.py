"""视图与列表

树 / 表 / 列表 / 选项卡这类「一堆同类项怎么组织」。

数据表格（ElaDataTable / ElaParquetTable）不在这里 —— 那是**绑定
数据源**的组件，归「数据与图表」分组；这一页只放结构性视图。
"""

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import QHBoxLayout, QWidget
from PyQt6.QtGui import QStandardItem, QStandardItemModel
from PyQt6ElaWidgetTools import (
    ElaBreadcrumbBar,
    ElaKeyBinder,
    ElaListView,
    ElaPivot,
    ElaPushButton,
    ElaScrollBar,
    ElaSuggestBox,
    ElaTabBar,
    ElaTabWidget,
    ElaTableView,
    ElaText,
    ElaToolBar,
    ElaToolButton,
    ElaTreeView,
)
from .base_page import ExamplePage


class ViewsListPage(ExamplePage):
    """视图与列表示例页。"""

    PAGE_TITLE = "视图与列表"

    def __init__(self, parent=None):
        super().__init__(parent)

    def _addDemoContent(self, main_layout):
        self._demoTreeView(main_layout)
        self._demoTableView(main_layout)
        self._demoListView(main_layout)
        self._demoSuggestBox(main_layout)
        self._demoKeyBinder(main_layout)
        self._demoScrollBar(main_layout)
        self._demoToolBar(main_layout)
        self._demoBreadcrumbBar(main_layout)
        self._demoPivot(main_layout)
        self._demoTabBar(main_layout)
        self._demoTabWidget(main_layout)

    def _demoTreeView(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "03. PyQt6ElaWidgetTools - ElaTreeView 树视图", self._demoTreeView
            )
        )
        self._addInfoText("树视图组件，支持多层级展示", parent_layout)
        tree_view = ElaTreeView(self)
        tree_view.setFixedHeight(200)
        model = QStandardItemModel()
        root_item = model.invisibleRootItem()
        for i in range(3):
            parent_item = QStandardItem(f"文件夹 {i + 1}")
            for j in range(3):
                child_item = QStandardItem(f"文件 {j + 1}.txt")
                parent_item.appendRow(child_item)
            root_item.appendRow(parent_item)
        tree_view.setModel(model)
        parent_layout.addWidget(tree_view)
        parent_layout.addSpacing(20)

    def _demoTableView(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "04. PyQt6ElaWidgetTools - ElaTableView 表格视图", self._demoTableView
            )
        )
        self._addInfoText("表格视图组件，支持行列数据展示", parent_layout)
        from PyQt6.QtCore import Qt

        table_view = ElaTableView(self)
        table_view.setFixedHeight(200)
        model = QStandardItemModel(5, 3)
        model.setHorizontalHeaderLabels(["姓名", "年龄", "城市"])
        hh = table_view.horizontalHeader()
        if hh:
            hh.setDefaultAlignment(
                Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
            )
        data = [
            ["张三", "25", "北京"],
            ["李四", "30", "上海"],
            ["王五", "28", "广州"],
            ["赵六", "35", "深圳"],
            ["钱七", "22", "杭州"],
        ]
        for row, row_data in enumerate(data):
            for col, value in enumerate(row_data):
                item = QStandardItem(value)
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
                )
                model.setItem(row, col, item)
        table_view.setModel(model)
        parent_layout.addWidget(table_view)
        parent_layout.addSpacing(20)

    def _demoListView(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "05. PyQt6ElaWidgetTools - ElaListView 列表视图", self._demoListView
            )
        )
        self._addInfoText("列表视图组件", parent_layout)
        list_view = ElaListView(self)
        list_view.setFixedHeight(150)
        model = QStandardItemModel()
        for i in range(10):
            item = QStandardItem(f"列表项 {i + 1}")
            model.appendRow(item)
        list_view.setModel(model)
        parent_layout.addWidget(list_view)
        parent_layout.addSpacing(20)

    def _demoSuggestBox(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "03. PyQt6ElaWidgetTools - ElaSuggestBox 建议框", self._demoSuggestBox
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
                "09. PyQt6ElaWidgetTools - ElaKeyBinder 快捷键提示", self._demoKeyBinder
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
                "10. PyQt6ElaWidgetTools - ElaScrollBar 滚动条", self._demoScrollBar
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

    def _demoToolBar(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "11. PyQt6ElaWidgetTools - ElaToolBar 工具栏", self._demoToolBar
            )
        )
        self._addInfoText("工具栏组件，可在工具栏中添加各种组件", parent_layout)
        parent_layout.addSpacing(10)
        toolbar = ElaToolBar(self)
        for i in range(5):
            tool_btn = ElaToolButton(self)
            tool_btn.setText(f"工具{i + 1}")
            tool_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            toolbar.addWidget(tool_btn)
        toolbar.addSeparator()
        for i in range(3):
            tool_btn = ElaToolButton(self)
            tool_btn.setText(f"操作{i + 1}")
            tool_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            toolbar.addWidget(tool_btn)
        parent_layout.addWidget(toolbar)
        parent_layout.addSpacing(20)

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
