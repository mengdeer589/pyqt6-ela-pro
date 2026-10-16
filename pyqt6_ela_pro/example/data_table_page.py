"""表格

绑定数据源的高性能表格：基础用法 / 异步加载 / 单元格样式 / 表头排序，
以及直接看 Parquet 文件的 ElaParquetTable。

与「视图与列表」的分界是**数据从哪来**：这一页的表格绑 model，
那边是手工塞 item 的结构性视图（树 / 表 / 列表 / 选项卡）。
"""

import random
from PyQt6.QtWidgets import QFileDialog, QHBoxLayout
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont
from PyQt6ElaWidgetTools import ElaPushButton, ElaText
from pyqt6_ela_pro import ElaDataTable
from .base_page import ExamplePage

try:
    import pyqtgraph  # noqa: F401

    _HAS_PYQTGRAPH = True
except ImportError:
    _HAS_PYQTGRAPH = False

try:
    import matplotlib  # noqa: F401

    _HAS_MATPLOTLIB = True
except ImportError:
    _HAS_MATPLOTLIB = False


class DataTablePage(ExamplePage):
    """表格示例页。"""

    PAGE_TITLE = "表格"

    def __init__(self, parent=None):
        self._basicTable = None
        self._asyncTable = None
        self._styleTable = None
        self._sortTable = None
        self._sortingEnabled = False
        super().__init__(parent)

    def _addDemoContent(self, main_layout):
        self._demoBasicTable(main_layout)
        self._demoAsyncTable(main_layout)
        self._demoStyleTable(main_layout)
        self._demoSortTable(main_layout)
        self._demoParquetTable(main_layout)

    def _demoBasicTable(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "01. ela_ext - ElaDataTable 基础表格", self._demoBasicTable
            )
        )
        self._addInfoText(
            "使用 setTableData() 填充静态数据，支持列表和字典两种格式", parent_layout
        )
        self._basicTable = ElaDataTable(self)
        self._basicTable.setFixedHeight(200)
        data = [
            ["姓名", "年龄", "城市", "职业"],
            ["张三", "28", "北京", "工程师"],
            ["李四", "34", "上海", "设计师"],
            ["王五", "25", "广州", "产品经理"],
            ["赵六", "31", "深圳", "数据分析师"],
        ]
        self._basicTable.setTableData(data, center_columns={1})
        self._basicTable.setColumnWidths({0: 120, 1: 80, 2: 100})
        parent_layout.addWidget(self._basicTable)
        parent_layout.addSpacing(30)

    def _onAsyncLoaded(self):
        self._asyncTable.setColumnWidths({0: 80, 1: 150, 2: 100, 3: 120})

    def _onRefreshAsyncTable(self):
        large_data = [
            ["行号", "数据", "状态", "金额"],
        ]
        for i in range(100):
            large_data.append(
                [
                    str(i + 1),
                    f"数据项_{i}_{random.randint(1000, 9999)}",
                    "正常" if random.randint(0, 2) != 0 else "异常",
                    f"{random.uniform(500, 5000):.2f}",
                ]
            )
        self._asyncTable.setTableDataAsync(large_data, callback=self._onAsyncLoaded)

    def _demoAsyncTable(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "02. ela_ext - ElaDataTable 异步加载", self._demoAsyncTable
            )
        )
        self._addInfoText(
            "使用 setTableDataAsync() 在后台线程加载大量数据", parent_layout
        )
        self._asyncTable = ElaDataTable(self)
        self._asyncTable.setFixedHeight(200)
        large_data = [
            ["行号", "数据", "状态", "金额"],
        ]
        for i in range(100):
            large_data.append(
                [
                    str(i + 1),
                    f"数据项_{i}",
                    "正常" if i % 3 != 0 else "异常",
                    f"{1000 + i * 50:.2f}",
                ]
            )
        self._asyncTable.setTableDataAsync(large_data, callback=self._onAsyncLoaded)
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(15)
        refresh_btn = ElaPushButton("重新加载", self)
        refresh_btn.setFixedWidth(100)
        refresh_btn.clicked.connect(self._onRefreshAsyncTable)
        btn_layout.addWidget(refresh_btn)
        btn_layout.addStretch()
        parent_layout.addWidget(self._asyncTable)
        parent_layout.addLayout(btn_layout)
        parent_layout.addSpacing(30)

    def _demoStyleTable(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "03. ela_ext - ElaDataTable 单元格样式", self._demoStyleTable
            )
        )
        self._addInfoText(
            "设置前景色、背景色、字体、对齐方式、行背景高亮", parent_layout
        )
        self._styleTable = ElaDataTable(self)
        self._styleTable.setFixedHeight(250)
        data = [
            ["商品", "销量", "库存", "状态"],
            ["iPhone 15", "1250", "320", "热销"],
            ["MacBook Pro", "480", "85", "热销"],
            ["iPad Air", "720", "150", "正常"],
            ["Apple Watch", "360", "210", "滞销"],
            ["AirPods Pro", "890", "95", "热销"],
        ]
        self._styleTable.setTableData(data, center_columns={1, 2})
        self._styleTable.setColumnWidths({0: 150, 1: 100, 2: 100, 3: 100})
        for row in range(1, self._styleTable.rowCount() + 1):
            status_item = self._styleTable.item(row, 3)
            if status_item:
                status_text = status_item.text()
                if status_text == "热销":
                    self._styleTable.setItemForeground(row, 3, QColor(255, 87, 34))
                    self._styleTable.setItem(row, 3, "🔴 热销", center=True)
                elif status_text == "滞销":
                    self._styleTable.setItemForeground(row, 3, QColor(76, 175, 80))
                    self._styleTable.setItem(row, 3, "🟢 滞销", center=True)
                else:
                    self._styleTable.setItem(row, 3, "🟡 正常", center=True)
        self._styleTable.setRowBackground(1, QColor(255, 243, 224))
        self._styleTable.setRowBackground(4, QColor(232, 245, 233))
        bold_font = QFont()
        bold_font.setBold(True)
        self._styleTable.setItemFont(0, 0, bold_font)
        self._styleTable.setItemFont(1, 0, bold_font)
        for row in range(1, self._styleTable.rowCount() + 1):
            sales_item = self._styleTable.item(row, 1)
            if sales_item:
                sales_value = int(sales_item.text())
                if sales_value > 1000:
                    self._styleTable.setItemForeground(row, 1, QColor(255, 87, 34))
        parent_layout.addWidget(self._styleTable)
        parent_layout.addSpacing(20)

    def _onSetAlignment(self, column: int, alignment: Qt.AlignmentFlag):
        self._sortTable.setColumnAlignment(column, alignment)

    def _onToggleSort(self):
        self._sortingEnabled = not self._sortingEnabled
        self._sortTable.setSortingEnabled(self._sortingEnabled)
        self._sortToggleBtn.setText("关闭排序" if self._sortingEnabled else "开启排序")
        self._sortInfoLabel.setText(
            f"排序功能: {'开启' if self._sortingEnabled else '关闭'}"
        )

    def _demoSortTable(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "04. ela_ext - ElaDataTable 表头排序", self._demoSortTable
            )
        )
        self._addInfoText(
            "点击表头可排序，再次点击切换升序/降序，支持对齐方式设置", parent_layout
        )
        self._sortTable = ElaDataTable(self)
        self._sortTable.setFixedHeight(250)
        data = [
            ["姓名", "年龄", "城市", "销量"],
            ["张三", "28", "北京", "1250"],
            ["李四", "34", "上海", "890"],
            ["王五", "25", "广州", "720"],
            ["赵六", "31", "深圳", "1100"],
            ["孙七", "29", "杭州", "650"],
            ["周八", "33", "成都", "980"],
        ]
        self._sortTable.setTableData(data)
        self._sortTable.setColumnWidths({0: 100, 1: 80, 2: 100, 3: 80})
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(15)
        self._sortToggleBtn = ElaPushButton("开启排序", self)
        self._sortToggleBtn.setFixedWidth(100)
        self._sortToggleBtn.clicked.connect(self._onToggleSort)
        btn_layout.addWidget(self._sortToggleBtn)
        self._sortInfoLabel = ElaText("排序功能: 关闭", self)
        self._sortInfoLabel.setTextPixelSize(14)
        btn_layout.addWidget(self._sortInfoLabel)
        btn_layout.addSpacing(20)
        self._alignLabel = ElaText("第0列对齐:", self)
        self._alignLabel.setTextPixelSize(14)
        btn_layout.addWidget(self._alignLabel)
        align_left_btn = ElaPushButton("靠左", self)
        align_left_btn.setFixedWidth(60)
        align_left_btn.clicked.connect(lambda: self._onSetAlignment(0, Qt.AlignmentFlag.AlignLeft))
        btn_layout.addWidget(align_left_btn)
        align_center_btn = ElaPushButton("居中", self)
        align_center_btn.setFixedWidth(60)
        align_center_btn.clicked.connect(
            lambda: self._onSetAlignment(0, Qt.AlignmentFlag.AlignCenter)
        )
        btn_layout.addWidget(align_center_btn)
        align_right_btn = ElaPushButton("靠右", self)
        align_right_btn.setFixedWidth(60)
        align_right_btn.clicked.connect(lambda: self._onSetAlignment(0, Qt.AlignmentFlag.AlignRight))
        btn_layout.addWidget(align_right_btn)
        btn_layout.addStretch()
        parent_layout.addWidget(self._sortTable)
        parent_layout.addLayout(btn_layout)
        parent_layout.addSpacing(20)

    def _onOpenParquet(self):
        if not self._parquet_available:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 Parquet 文件", "", "Parquet (*.parquet);;所有文件 (*)"
        )
        if not path:
            return
        try:
            self._parquet_table.loadData(path)
            self._parquet_table.setVisible(True)
            if self._parquet_info:
                self._parquet_info.deleteLater()
                self._parquet_info = None
        except ImportError as e:
            from PyQt6ElaWidgetTools import ElaMessageBar, ElaMessageBarType

            ElaMessageBar.error(
                ElaMessageBarType.PositionPolicy.Top,
                "缺少依赖",
                f"需要 polars 库: {e}",
                5000,
                self,
            )
        except Exception as e:
            from PyQt6ElaWidgetTools import ElaMessageBar, ElaMessageBarType

            ElaMessageBar.error(
                ElaMessageBarType.PositionPolicy.Top,
                "加载失败",
                str(e),
                5000,
                self,
            )

    def _onSetParquetPageSize(self, size):
        if self._parquet_table and self._parquet_available:
            self._parquet_table.setPageSize(size)

    def _demoParquetTable(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "05. ela_ext - ElaParquetTable Parquet 文件查看", self._demoParquetTable
            )
        )
        self._addInfoText(
            "分页浏览 Parquet 文件，显示列统计信息。需要安装 polars",
            parent_layout,
        )
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        open_btn = ElaPushButton("打开 Parquet 文件", self)
        open_btn.setFixedWidth(130)
        open_btn.clicked.connect(self._onOpenParquet)
        btn_layout.addWidget(open_btn)
        size_label = ElaText("每页行数:", self)
        size_label.setTextPixelSize(14)
        btn_layout.addWidget(size_label)
        for s in [50, 100, 200, 500, 1000, 2000]:
            btn = ElaPushButton(str(s), self)
            btn.setFixedWidth(50)
            btn.clicked.connect(lambda checked, x=s: self._onSetParquetPageSize(x))
            btn_layout.addWidget(btn)
        btn_layout.addStretch()
        parent_layout.addLayout(btn_layout)
        parent_layout.addSpacing(10)

        from pyqt6_ela_pro import ElaParquetTable

        try:
            self._parquet_table = ElaParquetTable(page_size=50, parent=self)
            self._parquet_table.setFixedHeight(350)
            self._parquet_table.setVisible(False)
            parent_layout.addWidget(self._parquet_table)
            self._parquet_available = True
        except ImportError:
            self._parquet_table = None
            self._parquet_available = False

        self._parquet_info = ElaText("请点击上方按钮选择 .parquet 文件", self)
        self._parquet_info.setTextPixelSize(14)
        parent_layout.addWidget(self._parquet_info)
        parent_layout.addSpacing(20)
