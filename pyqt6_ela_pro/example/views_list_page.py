"""视图与列表示例页。"""

from PyQt6.QtGui import QStandardItem, QStandardItemModel
from PyQt6ElaWidgetTools import ElaListView, ElaTableView, ElaTreeView

from .base_page import ExamplePage


class ViewsListPage(ExamplePage):
    """视图与列表示例页。"""

    PAGE_TITLE = "视图与列表"

    def _addDemoContent(self, main_layout):
        self._demoTreeView(main_layout)
        self._demoTableView(main_layout)
        self._demoListView(main_layout)

    def _demoTreeView(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "01. PyQt6ElaWidgetTools - ElaTreeView 树视图", self._demoTreeView
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
                "02. PyQt6ElaWidgetTools - ElaTableView 表格视图", self._demoTableView
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
                "03. PyQt6ElaWidgetTools - ElaListView 列表视图", self._demoListView
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
