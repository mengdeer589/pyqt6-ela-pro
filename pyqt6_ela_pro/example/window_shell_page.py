"""[pyqt6_ela_pro] 「ElaWindow 应用外壳」演示页

本页操作的对象是**真实的主窗口**（``self.window()``，即 ``ElaWindow`` 实例）：

- 每一节 = 一个外壳能力的活开关 + ``</> 代码`` 按钮（展示本节 demo 方法源码）；
- 没有 ElaWindow 宿主时（单页预览 / 守卫测试），每节退化为一行说明文字。

为什么这些能力都直接作用在主窗口上：外壳能力只有在**有宿主窗口**时才存在
（导航栏模式、窗口按钮、停靠区、内容堆栈…），散件单独摆一页只能讲解、不能
演示 —— 而且 ``ElaAppBar`` 这类控件构造时就会接管宿主窗口（边距 / 事件过滤
器 / 窗口按钮），离开宿主没有「静态预览」这回事。
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QLinearGradient, QPainter, QPixmap
from PyQt6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from PyQt6ElaWidgetTools import (
    ElaAppBarType,
    ElaCheckBox,
    ElaDockWidget,
    ElaNavigationType,
    ElaSlider,
    ElaText,
    ElaThemeType,
    ElaWindow,
    ElaWindowType,
)

from pyqt6_ela_pro import ElaButton
from pyqt6_ela_pro.example.base_page import ExamplePage

_NAV_MODES = (
    ("自动（随宽度）", ElaNavigationType.NavigationDisplayMode.Auto),
    ("最大", ElaNavigationType.NavigationDisplayMode.Maximal),
    ("紧凑", ElaNavigationType.NavigationDisplayMode.Compact),
    ("最小", ElaNavigationType.NavigationDisplayMode.Minimal),
)

_STACK_MODES = (
    ("无动画", ElaWindowType.StackSwitchMode.None_),
    ("弹出", ElaWindowType.StackSwitchMode.Popup),
    ("缩放", ElaWindowType.StackSwitchMode.Scale),
    ("翻转", ElaWindowType.StackSwitchMode.Flip),
    ("模糊", ElaWindowType.StackSwitchMode.Blur),
)

_APP_BAR_BUTTONS = (
    ("侧边栏开关", ElaAppBarType.ButtonType.NavigationButtonHint),
    ("置顶", ElaAppBarType.ButtonType.StayTopButtonHint),
    ("主题", ElaAppBarType.ButtonType.ThemeChangeButtonHint),
    ("最大化", ElaAppBarType.ButtonType.MaximizeButtonHint),
)


class WindowShellPage(ExamplePage):
    """ElaWindow 外壳能力演示页（操作真实主窗口）。"""

    PAGE_TITLE = "ElaWindow 应用外壳"

    def _addDemoContent(self, main_layout):
        self._demoOverview(main_layout)
        self._demoNavigationBar(main_layout)
        self._demoAppBarButtons(main_layout)
        self._demoWindowBackground(main_layout)
        self._demoContentStack(main_layout)
        self._demoDockWidgets(main_layout)
        self._demoOpenInNewWindow(main_layout)
        self._demoCloseChain(main_layout)

    # ── 公共小工具 ─────────────────────────────────────────────────────
    def _host_window(self) -> ElaWindow | None:
        """宿主 ElaWindow；没有（守卫测试 / 单页预览）时返回 ``None``。

        页面必须在没有宿主时也能构造 —— ``tests/example/`` 的守卫会单独构造每一页。
        """
        window = self.window()
        return window if isinstance(window, ElaWindow) else None

    def _require_host(self, parent_layout) -> ElaWindow | None:
        window = self._host_window()
        if window is None:
            self._addInfoText(
                "本节需要一个 ElaWindow 宿主窗口：把本页 addPageNode 到 ElaWindow 后即可操作（示例进程里就是主窗口）。",
                parent_layout,
            )
        return window

    def _button_row(self, specs) -> QWidget:
        """一行小按钮：``specs`` = [(文本, 回调), ...]。"""
        row = QWidget(self)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        for text, slot in specs:
            btn = ElaButton(text, variant="outlined", size="small", parent=row)
            btn.clicked.connect(slot)
            layout.addWidget(btn)
        layout.addStretch(1)
        return row

    def _toggle_row(self, text, checked, slot) -> QWidget:
        row = QWidget(self)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        box = ElaCheckBox(text, row)
        box.setChecked(bool(checked))
        box.toggled.connect(slot)
        layout.addWidget(box)
        layout.addStretch(1)
        return row

    @staticmethod
    def _flag_on(flags, flag) -> bool:
        """位测试 ``getWindowButtonFlags()``。

        它返回的是**普通 Enum 的伪成员**（组合值如 255）：``&`` / ``|`` / ``int()``
        在这个绑定里都不可用，只有 ``.value`` 能读；组合值要回传时也用
        ``ElaAppBarType.ButtonType(组合值)`` 造伪成员（裸 int 会被拒）。
        """
        return bool(getattr(flags, "value", 0) & getattr(flag, "value", 0))

    # ── 01 外壳总览 ────────────────────────────────────────────────────
    def _demoOverview(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow("01. ElaWindow - 外壳总览", self._demoOverview)
        )
        self._addInfoText(
            "ElaWindow = AppBar（窗口按钮 / 右键菜单 / 自定义控件区） + ElaNavigationBar（页面树 + 页脚节点） + 内容堆栈（每页一个 QStackedWidget item）。本页所有开关都作用在真实主窗口上。",
            parent_layout,
        )
        window = self._require_host(parent_layout)
        if window is None:
            return

        self._overview_label = ElaText("", self)
        self._overview_label.setTextPixelSize(13)
        self._overview_label.setTextFormat(Qt.TextFormat.PlainText)
        parent_layout.addWidget(self._overview_label)
        parent_layout.addWidget(
            self._button_row(
                (
                    ("刷新信息", self._refresh_overview),
                    ("回主页", self._goto_first_page),
                )
            )
        )
        self._refresh_overview()
        parent_layout.addSpacing(20)

    def _refresh_overview(self):
        window = self._host_window()
        if window is None:
            return
        key = window.getCurrentNavigationPageKey()
        info = [
            f"AppBar 高度：{window.getAppBarHeight()}px",
            f"导航栏宽度：{window.getNavigationBarWidth()}px（当前显示模式 {window.getNavigationBarDisplayMode().name}）",
            f"导航栏可见：{window.getIsNavigationBarEnable()}",
            f"当前页面：{window.getNavigationNodeTitle(key) or '（停在中央自定义窗口）'}",
            f"窗口置顶：{window.getIsStayTop()} · 固定尺寸：{window.getIsFixedSize()}",
            f"关闭按钮走宿主回调：{not window.getIsDefaultClosed()}",
        ]
        self._overview_label.setText("\n".join(info))

    def _goto_first_page(self):
        window = self._host_window()
        if window is None:
            return
        for page_key in self._first_page_keys(window):
            window.navigation(page_key)
            return

    @staticmethod
    def _first_page_keys(window: ElaWindow):
        """从导航建议列表里取页面 key（= ElaWindow 自己的注册顺序）。"""
        for suggestion in window.getNavigationSuggestDataList():
            key = suggestion.getSuggestData().get("ElaPageKey", "")
            if key:
                yield key

    # ── 02 导航栏 ──────────────────────────────────────────────────────
    def _demoNavigationBar(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "02. ElaWindow - 导航栏显示模式 / 宽度 / 显隐", self._demoNavigationBar
            )
        )
        self._addInfoText(
            "四档显示模式里「自动」会随窗口宽度在最大 / 紧凑之间切换；AppBar 上的侧边栏按钮负责最大↔紧凑折叠。最小模式把导航栏隐藏到左边缘外，鼠标划过才浮出。注意切模式时上游会给导航栏做逐帧宽度动画，宿主窗口请设显式最小尺寸（示例主窗口设了 800x560），否则最大化窗口会被越切越大并刷 QWindowsWindow::setGeometry 警告。",
            parent_layout,
        )
        window = self._require_host(parent_layout)
        if window is None:
            return

        parent_layout.addWidget(
            self._button_row(
                [
                    (
                        text,
                        (
                            lambda _c=False, m=mode: window.setNavigationBarDisplayMode(
                                m
                            )
                        ),
                    )
                    for text, mode in _NAV_MODES
                ]
            )
        )

        row = QWidget(self)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        caption = ElaText("宽度", row)
        caption.setTextPixelSize(14)
        caption.setTextFormat(Qt.TextFormat.PlainText)
        slider = ElaSlider(Qt.Orientation.Horizontal, row)
        slider.setMinimum(180)
        slider.setMaximum(360)
        slider.setValue(window.getNavigationBarWidth())
        slider.setFixedWidth(220)
        value = ElaText(f"{window.getNavigationBarWidth()}px", row)
        value.setTextPixelSize(13)
        value.setTextFormat(Qt.TextFormat.PlainText)
        slider.valueChanged.connect(
            lambda v: (window.setNavigationBarWidth(v), value.setText(f"{v}px"))
        )
        layout.addWidget(caption)
        layout.addWidget(slider)
        layout.addWidget(value)
        layout.addStretch(1)
        parent_layout.addWidget(row)

        parent_layout.addWidget(
            self._button_row(
                (
                    (
                        "隐藏 / 显示导航栏",
                        lambda: window.setIsNavigationBarEnable(
                            not window.getIsNavigationBarEnable()
                        ),
                    ),
                )
            )
        )
        parent_layout.addSpacing(20)

    # ── 03 AppBar 按钮 / 窗口状态 ──────────────────────────────────────
    def _demoAppBarButtons(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "03. ElaWindow - AppBar 窗口按钮与窗口状态", self._demoAppBarButtons
            )
        )
        self._addInfoText(
            "窗口按钮是位标志：setWindowButtonFlag(flag, on) 逐个开关；隐藏全部按钮后 AppBar 只剩拖动与右键菜单。",
            parent_layout,
        )
        window = self._require_host(parent_layout)
        if window is None:
            return

        flags = window.getWindowButtonFlags()
        for text, flag in _APP_BAR_BUTTONS:
            parent_layout.addWidget(
                self._toggle_row(
                    f"AppBar 显示「{text}」按钮",
                    self._flag_on(flags, flag),
                    lambda on, f=flag: window.setWindowButtonFlag(f, bool(on)),
                )
            )

        parent_layout.addWidget(
            self._toggle_row(
                "窗口置顶（setIsStayTop）",
                window.getIsStayTop(),
                lambda on: window.setIsStayTop(bool(on)),
            )
        )
        parent_layout.addWidget(
            self._toggle_row(
                "固定尺寸（setIsFixedSize，关掉才能再拖边框）",
                window.getIsFixedSize(),
                lambda on: window.setIsFixedSize(bool(on)),
            )
        )

        row = QWidget(self)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        caption = ElaText("AppBar 高度", row)
        caption.setTextPixelSize(14)
        caption.setTextFormat(Qt.TextFormat.PlainText)
        height_slider = ElaSlider(Qt.Orientation.Horizontal, row)
        height_slider.setMinimum(28)
        height_slider.setMaximum(56)
        height_slider.setValue(window.getAppBarHeight())
        height_slider.setFixedWidth(220)
        height_value = ElaText(f"{window.getAppBarHeight()}px", row)
        height_value.setTextPixelSize(13)
        height_value.setTextFormat(Qt.TextFormat.PlainText)
        height_slider.valueChanged.connect(
            lambda v: (window.setAppBarHeight(v), height_value.setText(f"{v}px"))
        )
        layout.addWidget(caption)
        layout.addWidget(height_slider)
        layout.addWidget(height_value)
        layout.addStretch(1)
        parent_layout.addWidget(row)
        parent_layout.addSpacing(20)

    # ── 04 窗口背景与绘制模式 ──────────────────────────────────────────
    def _demoWindowBackground(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "04. ElaWindow - 窗口背景与绘制模式", self._demoWindowBackground
            )
        )
        self._addInfoText(
            "窗口背景有三种绘制模式：Normal（纯色）、Pixmap（按主题各一张位图，居中裁剪）、Movie（动图，需要 GIF 文件）。导航栏那一带是透明的，背景图在这里最明显。",
            parent_layout,
        )
        window = self._require_host(parent_layout)
        if window is None:
            return

        parent_layout.addWidget(
            self._button_row(
                (
                    (
                        "应用渐变背景（Pixmap）",
                        lambda: self._apply_background(window, True),
                    ),
                    ("恢复 Normal", lambda: self._apply_background(window, False)),
                )
            )
        )
        parent_layout.addSpacing(20)

    def _apply_background(self, window: ElaWindow, on: bool) -> None:
        """应用 / 恢复渐变背景。

        宿主自己带开关时（示例主窗口的 ``_set_background_enabled``）**走宿主的**，
        否则两处各自记状态、界面立刻自相矛盾；没有该钩子（普通 ElaWindow）就
        直接调公开 API。
        """
        host_toggle = getattr(window, "_set_background_enabled", None)
        if callable(host_toggle):
            host_toggle(on)
            return
        if on:
            pixmap = QPixmap(640, 640)
            gradient = QLinearGradient(0, 0, 640, 640)
            gradient.setColorAt(0.0, QColor("#ffd6a5"))
            gradient.setColorAt(0.5, QColor("#c7e0ff"))
            gradient.setColorAt(1.0, QColor("#b8f2e6"))
            painter = QPainter(pixmap)
            painter.fillRect(pixmap.rect(), gradient)
            painter.end()
            # 亮 / 暗各一张，切主题时 ElaWindow 自己取对应那张
            for mode in (ElaThemeType.ThemeMode.Light, ElaThemeType.ThemeMode.Dark):
                window.setWindowPixmap(mode, pixmap)
            window.setWindowPaintMode(ElaWindowType.PaintMode.Pixmap)
        else:
            window.setWindowPaintMode(ElaWindowType.PaintMode.Normal)

    # ── 05 内容堆栈 ────────────────────────────────────────────────────
    def _demoContentStack(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "05. ElaWindow - 内容堆栈（addCentralWidget）", self._demoContentStack
            )
        )
        self._addInfoText(
            "内容区是一个 QStackedWidget：索引 0 是导航外壳（导航栏 + 页面树），addCentralWidget 追加的是整块覆盖的「全屏页」。setCurrentStackIndex 走 ElaActionCommander，所以 AppBar 的前进 / 后退按钮能重放整页切换；切换动画由 setStackSwitchMode 决定（默认弹出，约 180ms 后落地）。",
            parent_layout,
        )
        window = self._require_host(parent_layout)
        if window is None:
            return
        self._demo_stack_widget: QWidget | None = None

        parent_layout.addWidget(
            self._button_row(
                (
                    ("加入内容堆栈", lambda: self._add_stack_page(window)),
                    ("显示堆栈页", lambda: self._show_stack_page(window, True)),
                    ("回到导航外壳", lambda: self._show_stack_page(window, False)),
                )
            )
        )
        parent_layout.addWidget(
            self._button_row(
                [
                    (text, (lambda _c=False, m=mode: window.setStackSwitchMode(m)))
                    for text, mode in _STACK_MODES
                ]
            )
        )
        parent_layout.addSpacing(20)

    def _add_stack_page(self, window: ElaWindow) -> None:
        if self._demo_stack_widget is None:
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.setContentsMargins(30, 30, 30, 30)
            layout.setSpacing(12)
            title = ElaText("这是一个通过 addCentralWidget 加入的内容堆栈页", page)
            title.setTextPixelSize(18)
            title.setTextFormat(Qt.TextFormat.PlainText)
            hint = ElaText(
                "整页覆盖导航外壳 —— 返回入口：本页按钮，或 AppBar 上的后退按钮（setCurrentStackIndex 记了命令）。",
                page,
            )
            hint.setTextPixelSize(13)
            hint.setTextFormat(Qt.TextFormat.PlainText)
            back = ElaButton("返回导航外壳（setCurrentStackIndex(0)）", parent=page)
            back.clicked.connect(lambda: window.setCurrentStackIndex(0))
            layout.addWidget(title)
            layout.addWidget(hint)
            layout.addWidget(back)
            layout.addStretch(1)
            window.addCentralWidget(page)
            self._demo_stack_widget = page
        self._show_stack_page(window, True)

    def _show_stack_page(self, window: ElaWindow, show: bool) -> None:
        if self._demo_stack_widget is None:
            return
        if not show:
            window.setCurrentStackIndex(0)
            return
        for index in range(1, 64):
            widget = window.getCentralWidget(index)
            if widget is self._demo_stack_widget:
                window.setCurrentStackIndex(index)
                return
            if widget is None:
                return

    # ── 06 DockWidget ──────────────────────────────────────────────────
    def _demoDockWidgets(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "06. ElaWindow - 停靠窗口（ElaDockWidget）", self._demoDockWidgets
            )
        )
        self._addInfoText(
            "停靠窗口由 QMainWindow 掌管：addDockWidget 指定停靠区，tabifyDockWidget 合成标签页，splitDockWidget 把区域切成上下两半，setDockNestingEnabled 才允许横向嵌套。右键停靠区空白处会列出全部 dock 的显隐项（ElaWindow.createPopupMenu）。",
            parent_layout,
        )
        window = self._require_host(parent_layout)
        if window is None:
            return
        self._demo_docks: list[ElaDockWidget] = []

        parent_layout.addWidget(
            self._button_row(
                (
                    ("添加演示 dock", lambda: self._add_dock(window)),
                    ("再加一个并 tab 化", lambda: self._add_dock_and_tab(window)),
                    ("移除演示 dock", lambda: self._remove_docks(window)),
                )
            )
        )
        parent_layout.addWidget(
            self._toggle_row(
                "允许停靠区嵌套（setDockNestingEnabled）",
                window.isDockNestingEnabled(),
                lambda on: window.setDockNestingEnabled(bool(on)),
            )
        )
        parent_layout.addSpacing(20)

    def _add_dock(self, window: ElaWindow) -> ElaDockWidget:
        dock = ElaDockWidget(f"演示面板 {len(self._demo_docks) + 1}", window)
        text = ElaText(
            "拖动标题栏可换停靠区 / 悬浮成独立窗口；拖到另一个 dock 的标签栏上会合页。",
            dock,
        )
        text.setTextPixelSize(13)
        text.setTextFormat(Qt.TextFormat.PlainText)
        text.setWordWrap(True)
        dock.setWidget(text)
        window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        self._demo_docks.append(dock)
        return dock

    def _add_dock_and_tab(self, window: ElaWindow) -> None:
        first = self._demo_docks[0] if self._demo_docks else self._add_dock(window)
        second = self._add_dock(window)
        window.tabifyDockWidget(first, second)
        second.raise_()

    def _remove_docks(self, window: ElaWindow) -> None:
        for dock in self._demo_docks:
            window.removeDockWidget(dock)
            dock.deleteLater()
        self._demo_docks = []

    # ── 07 页面在新窗口打开 ────────────────────────────────────────────
    def _demoOpenInNewWindow(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "07. ElaWindow - 页面在新窗口打开", self._demoOpenInNewWindow
            )
        )
        self._addInfoText(
            "允许后，右键侧边栏的任意页面节点会出现「在新窗口中打开」。Python 定义的页面无法被 C++ 的 QMetaObject 复制，组件会发 pageOpenInNewWindowRequested(nodeKey)，宿主用页面类造副本装进独立 ElaWidget 窗口（本示例主窗口的实现见 example/page_window.py）；上游 C++ 页面仍走自动开窗并另发 pageOpenInNewWindow(nodeKey)。关掉开关时右键不再出菜单。",
            parent_layout,
        )
        window = self._require_host(parent_layout)
        if window is None:
            return

        self._new_window_counts: dict[str, int] = {}
        self._new_window_label = ElaText("已打开的新窗口：0", self)
        self._new_window_label.setTextPixelSize(13)
        self._new_window_label.setTextFormat(Qt.TextFormat.PlainText)
        parent_layout.addWidget(self._new_window_label)
        window.pageOpenInNewWindow.connect(self._on_page_open_in_new_window)
        window.pageOpenInNewWindowRequested.connect(self._on_page_open_in_new_window)

        parent_layout.addWidget(
            self._toggle_row(
                "允许页面在新窗口打开（setIsAllowPageOpenInNewWindow）",
                window.getIsAllowPageOpenInNewWindow(),
                lambda on: window.setIsAllowPageOpenInNewWindow(bool(on)),
            )
        )
        parent_layout.addSpacing(20)

    def _on_page_open_in_new_window(self, node_key: str) -> None:
        """两条信号（自动开窗 / 宿主开窗）都只是「页面已在新窗口打开」的通知。

        计数用本页自己的字典：C++ 的 ``getPageOpenInNewWindowCount`` 只统计
        ``QMetaObject`` 复制出来的窗口，Python 页面走宿主建窗不会进它。
        """
        window = self._host_window()
        if window is None:
            return
        count = self._new_window_counts.get(node_key, 0) + 1
        self._new_window_counts[node_key] = count
        self._new_window_label.setText(
            f"已打开的新窗口：{count}（上次：{window.getNavigationNodeTitle(node_key)}）"
        )

    # ── 08 关闭链路 ────────────────────────────────────────────────────
    def _demoCloseChain(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "08. ElaWindow - 关闭链路（setIsDefaultClosed）", self._demoCloseChain
            )
        )
        self._addInfoText(
            "AppBar 关闭按钮默认直接关窗；setIsDefaultClosed(False) 后改为发 closeButtonClicked 信号，宿主接它做确认弹框 / 最小化 / 托盘化。本示例主窗口就用这条链路弹「退出确认」。",
            parent_layout,
        )
        window = self._require_host(parent_layout)
        if window is None:
            return

        parent_layout.addWidget(
            self._toggle_row(
                "关闭按钮交给宿主处理（setIsDefaultClosed(False)）",
                not window.getIsDefaultClosed(),
                lambda on: window.setIsDefaultClosed(not bool(on)),
            )
        )
        parent_layout.addWidget(
            self._button_row(
                (
                    (
                        "模拟点击关闭按钮（触发 closeButtonClicked）",
                        window.closeButtonClicked.emit,
                    ),
                )
            )
        )
        parent_layout.addSpacing(20)
