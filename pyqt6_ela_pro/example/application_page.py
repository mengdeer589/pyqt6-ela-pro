"""
[pyqt6_ela_pro] 应用级组件演示页面 — PyQt6ElaWidgetTools 原生
"""

from PyQt6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from PyQt6.QtCore import Qt
from PyQt6ElaWidgetTools import (
    ElaAppBar,
    ElaNavigationType,
    ElaStatusBar,
    ElaNavigationBar,
    ElaText,
)
from pyqt6_ela_pro import ElaThemeWidget
from .base_page import ExamplePage


class ApplicationComponentsPage(ExamplePage):
    """ela 应用级组件演示页面"""

    PAGE_TITLE = "应用组件"

    def __init__(self, parent=None):
        super().__init__(parent)

    def _addDemoContent(self, main_layout):
        self._demoAppBar(main_layout)
        self._demoStatusBar(main_layout)
        self._demoNavigationBar(main_layout)

    def _demoAppBar(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow("01. ElaAppBar - 应用栏", self._demoAppBar)
        )
        self._addInfoText("应用栏组件", parent_layout)
        app_bar = ElaAppBar(self)
        app_bar.setFixedHeight(50)
        parent_layout.addWidget(app_bar)
        parent_layout.addSpacing(20)

    def _demoStatusBar(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow("02. ElaStatusBar - 状态栏", self._demoStatusBar)
        )
        self._addInfoText("状态栏组件", parent_layout)
        status_bar = ElaStatusBar(self)
        parent_layout.addWidget(status_bar)
        parent_layout.addSpacing(20)

    def _demoNavigationBar(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "03. PyQt6ElaWidgetTools - ElaNavigationBar 导航栏",
                self._demoNavigationBar,
            )
        )
        self._addInfoText(
            "独立的导航栏组件，支持用户信息卡片、导航节点、展开/折叠模式",
            parent_layout,
        )
        container = QWidget(self)
        container.setFixedHeight(360)
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        nav = ElaNavigationBar(container)
        nav.setFixedWidth(220)
        nav.setUserInfoCardTitle("演示用户")
        nav.setUserInfoCardSubTitle("user@example.com")
        # 上游只收枚举成员（传裸 int 抛 TypeError: argument 1 has unexpected type 'int'）
        nav.setDisplayMode(ElaNavigationType.NavigationDisplayMode.Maximal)

        content = ElaThemeWidget(container)
        content_layout = QVBoxLayout(content)
        content_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info = ElaText("点击左侧导航节点", content)
        info.setTextPixelSize(16)
        content_layout.addWidget(info)

        nav.navigationNodeClicked.connect(lambda key: info.setText(f"已选择: {key}"))

        layout.addWidget(nav)
        layout.addWidget(content, 1)
        parent_layout.addWidget(container)
        parent_layout.addSpacing(20)
