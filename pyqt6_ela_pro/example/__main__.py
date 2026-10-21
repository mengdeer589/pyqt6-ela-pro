"""[pyqt6_ela_pro] 模块示例脚本

侧边栏是**两级**的：一级是可折叠的 expander（按主题分组），展开后是页面 /
分类。分组依据是「这组页面回答的是同一个问题」—— 此前 23 个页面平铺，
「AI 对话」的五个能力域被基础控件挤到看不见，而「基础控件 / 容器展示」其实是
同一个东西（原生控件全集）被按一条用户记不住的线切开了。

**``addExpanderNode`` 在 PyQt6 里返回 ``(NodeResult, key)``。** C++ 那边的
``QString& expanderKey`` 是出参，sip 把它整条从签名里删掉了、key 改由
**返回值**给出。所以：

- key 是**拿回来**的，不是传进去的；
- **第二个位置参数是图标，不是 key** —— 传个空串进去会被当成
  ``targetExpanderKey``，查不到就返回 ``TargetNodeInvalid``，节点建了但 key
  是空的，后面所有二级页面全挂不上，**且不抛异常**。

主窗口同时是 ElaWindow **应用外壳**的活示例：右侧 dock（页面导航 / 运行日志 /
说明）、工具栏、状态栏、AppBar 右键菜单、内容区顶栏的页面搜索、页脚节点
（关于 / 设置）与关闭确认 —— 每一处都只是对 ``ElaWindow`` 公开 API 的调用，
可以整段照抄。

（参考实现：``PyElaWidgetTools/example/mainwindow.py``。）
"""

import os
import sys
import traceback

from pyqt6_ela_pro import ElaSplashScreen

os.environ["QT_LOGGING_RULES"] = "*.debug=false;qt.qpa.fonts.warning=false"

from PyQt6.QtCore import Qt, QTimer, qVersion
from PyQt6.QtGui import (
    QColor,
    QLinearGradient,
    QPainter,
    QPixmap,
    QStandardItem,
    QStandardItemModel,
)
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from PyQt6ElaWidgetTools import (
    eApp,
    eTheme,
    ElaDockWidget,
    ElaIconType,
    ElaListView,
    ElaMenu,
    ElaNavigationType,
    ElaPivot,
    ElaPlainTextEdit,
    ElaStatusBar,
    ElaSuggestBox,
    ElaText,
    ElaThemeType,
    ElaToggleSwitch,
    ElaToolBar,
    ElaWindow,
    ElaWindowType,
)
from pyqt6_ela_pro import (
    ElaButton,
    ElaDialogBase,
    ElaMotionModeType,
    __version__,
    motion,
)
from pyqt6_ela_pro.example import (
    AnimationIconPage,
    AppShellPage,
    BlueprintPage,
    ButtonsMenusPage,
    ChartLibPage,
    ChartsPage,
    ChatAgentPage,
    ChatGuidePage,
    ChatInputPage,
    ChatOverviewPage,
    ChatPersistPage,
    ChatSessionPage,
    ComboBoxPage,
    ContainerLayoutPage,
    DataTablePage,
    DrawerTooltipPage,
    EmbedPage,
    InputSelectPage,
    MarkdownPage,
    ProgressFeedbackPage,
    SelectionAssistantPage,
    TerminalPage,
    ViewsListPage,
    WindowShellPage,
)
from pyqt6_ela_pro.example.base_page import ExamplePage
from pyqt6_ela_pro.example.page_window import openPageInNewWindow

#: 导航栏显示模式循环顺序（工具栏按钮逐档切换）
_NAV_MODES = (
    ElaNavigationType.NavigationDisplayMode.Auto,
    ElaNavigationType.NavigationDisplayMode.Maximal,
    ElaNavigationType.NavigationDisplayMode.Compact,
    ElaNavigationType.NavigationDisplayMode.Minimal,
)
_NAV_MODE_TEXTS = ("自动", "最大", "紧凑", "最小")
_MOTION_TEXTS = ("完整", "精简", "关闭")
#: ``ElaDialogBase`` 中间按钮的 ``done`` 码（`middleButtonClicked` → `done(2)`）
_DIALOG_MIDDLE_BUTTON = 2


class ExampleWindow(ElaWindow):
    """示例主窗口（两级侧边栏 + 应用外壳）。"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("pyqt6_ela_pro 组件示例")
        self.resize(1280, 820)
        # 显式最小尺寸（**不能省**）：切导航栏显示模式时上游会给导航栏做 255ms 的
        # ``setFixedWidth`` 动画，窗口的「布局最小宽度」跟着逐帧变大 —— 最大化 / 屏幕
        # 受限时 Qt 每帧都要改窗口尺寸，终端刷一串 ``QWindowsWindow::setGeometry``
        # 警告，窗口还会被越撑越大（实测第二块屏上每切一次 +160px）。显式最小尺寸一旦
        # 设置，Qt 就不再拿布局最小值顶窗口；页面都在滚动区里，缩到 800 宽布局也不坏。
        self.setMinimumSize(800, 560)

        self.setUserInfoCardTitle("组件演示")
        self.setUserInfoCardSubTitle("pyqt6_ela_pro@example.com")

        #: [(分组, 页面标题, 页面控件)] —— dock / AppBar 菜单 / 搜索共用同一份清单
        self._page_entries: list[tuple[str, str, QWidget]] = []
        #: 宿主侧建出来的页面新窗口（Python 页面不能由 C++ 复制，见 page_window.py）
        self._page_windows: list[QWidget] = []
        self._about_key = ""
        self._settings_key = ""
        self._close_confirm_enabled = True
        self._background_enabled = False

        try:
            self._buildSidebar()
        except Exception:
            print(traceback.format_exc())

        self._buildDocks()
        self._buildSearchBar()
        self._buildToolBar()
        self._buildStatusBar()
        self._buildAppBarMenu()
        self._installCloseGuard()
        self.navigationNodeClicked.connect(self._on_navigation_node_clicked)
        # Python 页面无法被 C++ ``QMetaObject::newInstance()`` 复制：
        # 右键「在新窗口中打开」改发请求信号，由宿主建窗（见 ``page_window.py``）。
        self.pageOpenInNewWindowRequested.connect(self._open_page_in_new_window)
        self._sync_page_nav()
        self.moveToCenter()

    # ── 侧边栏 ────────────────────────────────────────────────────────
    def _buildSidebar(self) -> None:
        icon = ElaIconType.IconName

        # ── 基础组件：按「用户会怎么找」分，不按「控件 vs 容器」分 ──
        _, basic = self.addExpanderNode("基础组件", icon.List)
        self._addPage("基础组件", "输入与选择", InputSelectPage(self), basic, icon.Pen)
        self._addPage("基础组件", "下拉框组件", ComboBoxPage(self), basic, icon.ListUl)
        self._addPage(
            "基础组件", "容器与布局", ContainerLayoutPage(self), basic, icon.Square
        )
        self._addPage(
            "基础组件", "视图与列表", ViewsListPage(self), basic, icon.TableList
        )
        self._addPage(
            "基础组件", "按钮与菜单", ButtonsMenusPage(self), basic, icon.CircleNotch
        )
        self._addPage(
            "基础组件", "进度与反馈", ProgressFeedbackPage(self), basic, icon.Gauge
        )
        self.expandNavigationNode(basic)

        # ── 数据与图表：绑数据源的东西都归这里 ──
        _, data = self.addExpanderNode("数据与图表", icon.ChartLine)
        self._addPage("数据与图表", "表格", DataTablePage(self), data, icon.Table)
        self._addPage(
            "数据与图表", "图表（第三方库）", ChartLibPage(self), data, icon.ChartPie
        )
        self._addPage(
            "数据与图表",
            "ElaChartWidget 图表引擎",
            ChartsPage(self),
            data,
            icon.ChartLine,
        )
        self.expandNavigationNode(data)

        # ── 内容渲染 ──
        _, render = self.addExpanderNode("内容渲染", icon.FileCode)
        self._addPage(
            "内容渲染", "Markdown 渲染", MarkdownPage(self), render, icon.FileCode
        )
        self.expandNavigationNode(render)

        # ── AI 对话：按**能力域**切，不按「应用场景」切 ──
        # 原来分「基础对话 / Agent 能力 / 多话题对话」三页，是按使用场景分的，
        # 结果同一个组件的能力被打散在三处、每页还各演一遍权限审批。现在改成：
        # 「长什么样」/「怎么接」/「agent 多了什么」/「多话题」/「落库与性能」，
        # 五页各自回答一个问题。
        _, chat = self.addExpanderNode("AI 对话", icon.Comments)
        self._addPage(
            "AI 对话", "聊天组件总览", ChatOverviewPage(self), chat, icon.Paragraph
        )
        self._addPage("AI 对话", "输入区能力", ChatInputPage(self), chat, icon.Comment)
        self._addPage(
            "AI 对话", "Agent 能力", ChatAgentPage(self), chat, icon.ShieldHalved
        )
        self._addPage(
            "AI 对话", "会话管理", ChatSessionPage(self), chat, icon.ClipboardList
        )
        self._addPage(
            "AI 对话", "持久化与性能", ChatPersistPage(self), chat, icon.Database
        )
        # 默认展开：这是本示例的重点组件，收起来等于把它藏了
        self.expandNavigationNode(chat)

        # ── 窗口与应用外壳 ──
        _, shell = self.addExpanderNode("窗口与应用外壳", icon.WindowRestore)
        self._addPage(
            "窗口与应用外壳",
            "ElaWindow 应用外壳",
            WindowShellPage(self),
            shell,
            icon.WindowRestore,
        )
        self._addPage(
            "窗口与应用外壳", "弹窗与提示", DrawerTooltipPage(self), shell, icon.Bell
        )
        self._addPage(
            "窗口与应用外壳", "启动与托盘", AppShellPage(self), shell, icon.Plug
        )
        self.expandNavigationNode(shell)

        # ── 系统交互与嵌入 ──
        _, system = self.addExpanderNode("系统交互与嵌入", icon.Terminal)
        self._addPage(
            "系统交互与嵌入", "外部内容嵌入", EmbedPage(self), system, icon.Globe
        )
        self._addPage(
            "系统交互与嵌入", "终端输出", TerminalPage(self), system, icon.Terminal
        )
        self._addPage(
            "系统交互与嵌入",
            "划词助手",
            SelectionAssistantPage(self),
            system,
            icon.Highlighter,
        )
        self.expandNavigationNode(system)

        # ── 动效与图形 ──
        _, motion_expander = self.addExpanderNode("动效与图形", icon.Play)
        self._addPage(
            "动效与图形",
            "动画与图标",
            AnimationIconPage(self),
            motion_expander,
            icon.Play,
        )
        self._addPage(
            "动效与图形",
            "节点图编辑器",
            BlueprintPage(self),
            motion_expander,
            icon.Circle,
        )
        self.expandNavigationNode(motion_expander)

        # ── 参考文档：纯文档页（表格 + 代码块），和可交互 demo 不是一回事 ──
        _, docs = self.addExpanderNode("参考文档", icon.BookOpen)
        self._addPage(
            "参考文档", "聊天组件 API 指南", ChatGuidePage(self), docs, icon.BookOpen
        )
        self.expandNavigationNode(docs)

        # ── 页脚节点：固定在导航栏底部（不受分组影响）──
        # ``addFooterNode`` 与 ``addExpanderNode`` 同款：key 由**返回值**给出
        result, self._about_key = self.addFooterNode("关于", 0, icon.CircleInfo)
        self._check_node(result, "页脚节点「关于」")
        result, self._settings_key = self.addFooterNode("设置", 0, icon.GearComplex)
        self._check_node(result, "页脚节点「设置」")

    def _addPage(
        self, group: str, title: str, page: QWidget, expander_key: str, awesome
    ) -> None:
        """注册页面并登记进 ``_page_entries``（dock / 菜单 / 搜索都读它）。"""
        self._check_node(
            self.addPageNode(title, page, expander_key, awesome),
            f"页面「{group} / {title}」",
        )
        self._page_entries.append((group, title, page))

    @staticmethod
    def _check_node(result, label: str) -> None:
        """侧边栏注册失败一律返回非零、绝不抛异常 —— 这里把它显式报出来。"""
        if result != ElaNavigationType.NodeResult.Success:
            print(f"[示例] 侧边栏节点注册失败：{label} -> {result}", file=sys.stderr)

    def _open_page_in_new_window(self, node_key: str) -> None:
        """宿主侧建窗：Python 页面无法被 C++ ``QMetaObject::newInstance()`` 复制。"""
        shell = openPageInNewWindow(self, node_key)
        if shell is not None:
            self._page_windows.append(shell)

    # ── DockWidget 停靠面板 ────────────────────────────────────────────
    def _buildDocks(self) -> None:
        """右侧停靠区：页面导航（真实清单）/ 运行日志 / 说明。

        导航在上、日志在下（``splitDockWidget``），说明与日志 tab 化 —— 默认只占
        一列宽度，拖出去 / 换位置后布局由 QMainWindow 记忆（``saveState``）。
        """
        right = Qt.DockWidgetArea.RightDockWidgetArea

        self._nav_dock = nav_dock = ElaDockWidget("页面导航", self)
        self._nav_list = nav_list = ElaListView()
        nav_model = QStandardItemModel(nav_list)
        for group, title, _page in self._page_entries:
            item = QStandardItem(f"{group} · {title}")
            item.setEditable(False)
            item.setToolTip(f"{group} / {title}")
            nav_model.appendRow(item)
        nav_list.setModel(nav_model)
        nav_list.clicked.connect(self._on_page_nav_clicked)
        nav_dock.setWidget(nav_list)
        nav_dock.setMinimumWidth(190)
        self.addDockWidget(right, nav_dock)

        self._log_dock = log_dock = ElaDockWidget("运行日志", self)
        # 用 ElaPlainTextEdit 而不是 ElaTerminalView：日志只要「一行一条」，
        # 终端视图的 append 是「写入当前行」（没有 \n 就并进上一行）且自带一整条
        # 工具栏，放在 dock 里既费高度又容易误用。
        self._log_view = ElaPlainTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setFrameShape(QPlainTextEdit.Shape.NoFrame)
        log_dock.setWidget(self._log_view)
        log_dock.setMinimumWidth(190)
        self.addDockWidget(right, log_dock)

        self._info_dock = info_dock = ElaDockWidget("说明", self)
        info_text = ElaText(
            "dock 由 QMainWindow 掌管：拖动标题栏可换位置 / 悬浮，拖到另一个 dock 上会\n"
            "合成标签页，右键停靠区空白处可切换显隐。\n\n"
            "页面导航对应当前页面（点击跳转）；运行日志记录外壳动作。",
            info_dock,
        )
        info_text.setTextPixelSize(13)
        info_text.setTextFormat(Qt.TextFormat.PlainText)
        info_text.setWordWrap(True)
        info_text.setMinimumWidth(180)
        info_dock.setWidget(info_text)
        self.addDockWidget(right, info_dock)

        self.splitDockWidget(nav_dock, log_dock, Qt.Orientation.Vertical)
        self.tabifyDockWidget(log_dock, info_dock)
        log_dock.raise_()
        # 一列宽（否则 dock 会按 list view 的 sizeHint 吃掉半个窗口）+ 上下高度
        self.resizeDocks([nav_dock], [260], Qt.Orientation.Horizontal)
        self.resizeDocks([nav_dock, log_dock], [300, 260], Qt.Orientation.Vertical)

        self._log("外壳已就绪：右键 AppBar 打开菜单，顶部搜索框可直接跳页")

    def _on_page_nav_clicked(self, index) -> None:
        row = index.row()
        if 0 <= row < len(self._page_entries):
            self._navigate_page(self._page_entries[row][2])

    def _sync_page_nav(self, page_key: str | None = None) -> None:
        """把页面导航 dock 的高亮对到 ``page_key``（缺省取当前页）。

        别用「当前 widget 的 key」兜底导航时的同步：``setStackSwitchMode`` 的
        Popup / Scale 等模式是**动画结束后**才 ``setCurrentIndex``（默认 Popup
        ~180ms），信号发出这一刻读到的还是上一页。
        """
        key = page_key or self.getCurrentNavigationPageKey()
        model = self._nav_list.model()
        if model is None:
            return
        for row, (_group, _title, page) in enumerate(self._page_entries):
            if page.property("ElaPageKey") == key:
                self._nav_list.setCurrentIndex(model.index(row, 0))
                return

    # ── 工具栏 / 状态栏 ───────────────────────────────────────────────
    def _buildToolBar(self) -> None:
        icon = ElaIconType.IconName
        bar = ElaToolBar("示例工具栏", self)
        bar.setAllowedAreas(Qt.ToolBarArea.TopToolBarArea)
        bar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        bar.setToolBarSpacing(3)

        bar.addElaIconAction(icon.House, "回到首页").triggered.connect(self._goto_home)
        bar.addElaIconAction(icon.MoonStars, "切换主题").triggered.connect(
            self._toggle_theme
        )
        bar.addElaIconAction(icon.Bars, "切换导航栏显示模式").triggered.connect(
            self._cycle_nav_mode
        )
        bar.addSeparator()
        for dock, text, dock_icon in (
            (self._nav_dock, "页面导航", icon.List),
            (self._log_dock, "运行日志", icon.Terminal),
            (self._info_dock, "说明", icon.CircleInfo),
        ):
            action = bar.addElaIconAction(dock_icon, f"显示 / 隐藏「{text}」")
            dock.toggleViewAction().setText(text)
            action.triggered.connect(dock.toggleViewAction().trigger)
        bar.addSeparator()
        bar.addElaIconAction(icon.GearComplex, "外壳设置").triggered.connect(
            self._open_settings
        )

        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, bar)

    def _buildStatusBar(self) -> None:
        status = ElaStatusBar(self)
        self._status_page = ElaText("", status)
        self._status_page.setTextPixelSize(14)
        self._status_page.setTextFormat(Qt.TextFormat.PlainText)
        self._status_page.setWordWrap(False)
        status.addWidget(self._status_page)

        # 提示要**短且不折行**：``ElaText`` 默认 wordWrap=True，折行的第二行会被
        # 状态栏的固定高度裁掉（dock 区占宽后尤其明显）。
        hint = ElaText("右键 AppBar 打开菜单", status)
        hint.setTextPixelSize(13)
        hint.setTextFormat(Qt.TextFormat.PlainText)
        hint.setWordWrap(False)
        status.addPermanentWidget(hint)
        self.setStatusBar(status)

        key = self.getCurrentNavigationPageKey()
        title = self.getNavigationNodeTitle(key) if key else ""
        self._status_page.setText(f"当前页面：{title}" if title else "就绪")

    # ── AppBar 自定义右键菜单 ─────────────────────────────────────────
    def _buildAppBarMenu(self) -> None:
        """AppBar 右键 / Alt+Space 弹出的菜单（替换原生系统菜单）。"""
        menu = self._app_bar_menu = ElaMenu(self)
        menu.setMenuItemHeight(28)

        groups: dict[str, ElaMenu] = {}
        for group, title, page in self._page_entries:
            sub = groups.get(group)
            if sub is None:
                sub = groups[group] = menu.addMenu(group)
            sub.addAction(title).triggered.connect(
                lambda _checked=False, p=page: self._navigate_page(p)
            )

        menu.addSeparator()
        menu.addElaIconAction(ElaIconType.IconName.House, "回到首页").triggered.connect(
            self._goto_home
        )
        menu.addElaIconAction(
            ElaIconType.IconName.MoonStars, "切换主题"
        ).triggered.connect(self._toggle_theme)
        menu.addElaIconAction(
            ElaIconType.IconName.GearComplex, "外壳设置"
        ).triggered.connect(self._open_settings)
        menu.addElaIconAction(
            ElaIconType.IconName.CircleInfo, "关于"
        ).triggered.connect(self._open_about)
        menu.addSeparator()
        menu.addAction("恢复原生系统菜单").triggered.connect(
            lambda: self.setCustomMenu(None)
        )

        self.setCustomMenu(menu)

    # ── 内容区顶栏（setCentralCustomWidget）：页面搜索 ────────────────
    def _buildSearchBar(self) -> None:
        """内容区顶栏：页面搜索（数据来自 ``getNavigationSuggestDataList``）+ 回首页。"""
        container = QWidget(self)
        layout = QHBoxLayout(container)
        layout.setContentsMargins(10, 8, 10, 4)
        layout.setSpacing(8)

        home_button = ElaButton(
            "首页",
            icon=ElaIconType.IconName.House,
            variant="text",
            color="primary",
            parent=container,
        )
        home_button.clicked.connect(self._goto_home)
        layout.addWidget(home_button)

        # ``ElaSuggestBox`` 的建议数据与导航同源：窗口把导航节点导成 SuggestData
        # 列表，点击后从 ``getSuggestData()`` 取回 ``ElaPageKey`` 再 navigation。
        box = self._search_box = ElaSuggestBox(container)
        box.setPlaceholderText("搜索页面：输入分组名或页面名")
        box.setFixedHeight(32)
        box.setFixedWidth(360)
        box.addSuggestion(self.getNavigationSuggestDataList())
        box.suggestionClicked.connect(self._on_suggestion_clicked)
        layout.addWidget(box)
        layout.addStretch(1)

        self.setCentralCustomWidget(container)

    def _on_suggestion_clicked(self, suggest_data) -> None:
        key = suggest_data.getSuggestData().get("ElaPageKey", "")
        if key:
            self.navigation(key)

    # ── 关闭确认 ──────────────────────────────────────────────────────
    def _installCloseGuard(self) -> None:
        """拦截 AppBar 关闭按钮（``setIsDefaultClosed(False)`` + ``closeButtonClicked``）。"""
        self.setIsDefaultClosed(False)
        self.closeButtonClicked.connect(self._on_close_requested)

    def _on_close_requested(self) -> None:
        """AppBar 关闭按钮：二次确认（可关，见「设置」）。

        用 ``ElaContentDialog`` 系的 ``ElaDialogBase``（= 上游示例拦截关闭时用的
        那个组件）：**居中卡片 + 整窗遮罩**，还自带「最小化」中键。
        ``ElaConfirmDialog`` 是贴锚点浮出的轻量确认条 —— 锚点是整扇窗口时会被
        算到屏幕外再夹回来，落点很怪，不适合这里。
        """
        if not self._close_confirm_enabled:
            self.close()
            return

        dialog = ElaDialogBase(title="退出示例", middleText="最小化", parent=self)
        dialog.setLeftButtonText("取消")
        dialog.setRightButtonText("退出")
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        text = ElaText("确定关闭 pyqt6_ela_pro 组件示例窗口？", panel)
        text.setTextPixelSize(14)
        text.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(text)
        dialog.setParamWidget(panel)

        result = dialog.exec()
        if result == QDialog.DialogCode.Accepted:
            self.close()
        elif result == _DIALOG_MIDDLE_BUTTON:
            self.showMinimized()

    # ── 页脚节点：关于 / 设置 ─────────────────────────────────────────
    @staticmethod
    def _readonly_dialog(title: str, parent: QWidget) -> ElaDialogBase:
        """只读信息弹框：隐藏「确定」，只留「关闭」。"""
        dialog = ElaDialogBase(title=title, parent=parent)
        dialog.setLeftButtonText("关闭")
        for btn in dialog.findChildren(QPushButton):
            if btn.text() == "确定":
                btn.hide()
                break
        return dialog

    def _open_about(self) -> None:
        dialog = self._readonly_dialog("关于", self)
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        lines = (
            f"pyqt6_ela_pro {__version__}",
            "基于 PyQt6ElaWidgetTools 0.13.0 的 Ela 风格扩展组件库",
            f"Qt {qVersion()} · Python {sys.version.split()[0]}",
            "",
            "每个演示节标题旁的「</> 代码」按钮会展示该节 demo 方法自身的源码。",
        )
        for line in lines:
            text = ElaText(line, panel)
            text.setTextPixelSize(13)
            text.setTextFormat(Qt.TextFormat.PlainText)
            layout.addWidget(text)
        dialog.setParamWidget(panel)
        dialog.exec()

    def _open_settings(self) -> None:
        """外壳设置：导航栏模式 / 背景图 / 动效策略 / 关闭确认。

        控件用**上游现成的**：分段用 ``ElaPivot``、开关用 ``ElaToggleSwitch``；
        **主题不在这里** —— AppBar 右上角与工具栏都有主题按钮，在模态弹框里切主题
        会撞上 ElaWindow 的整窗切换动画（覆盖层 + AppBar 按钮临时锁定），且本页
        的开关状态没法跟着回滚。所有开关即时生效，关掉后状态保留。
        """
        dialog = self._readonly_dialog("外壳设置", self)
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        mode_pivot = ElaPivot(panel)
        mode_pivot.setTextPixelSize(14)
        mode_pivot.setMarkWidth(24)
        for text in _NAV_MODE_TEXTS:
            mode_pivot.appendPivot(text)
        mode_pivot.setCurrentIndex(self._nav_mode_index())
        mode_pivot.pivotClicked.connect(self._on_nav_mode_index_changed)
        layout.addWidget(self._setting_row("导航栏显示模式", mode_pivot, panel))

        background = ElaToggleSwitch(panel)
        background.setIsToggled(self._background_enabled)
        background.toggled.connect(self._set_background_enabled)
        layout.addWidget(self._setting_row("窗口背景渐变", background, panel))

        policy_pivot = ElaPivot(panel)
        policy_pivot.setTextPixelSize(14)
        policy_pivot.setMarkWidth(24)
        for text in _MOTION_TEXTS:
            policy_pivot.appendPivot(text)
        policy_pivot.setCurrentIndex(int(motion.mode()))
        policy_pivot.pivotClicked.connect(
            lambda index: motion.setMode(ElaMotionModeType(index))
        )
        layout.addWidget(self._setting_row("动效策略", policy_pivot, panel))

        confirm = ElaToggleSwitch(panel)
        confirm.setIsToggled(self._close_confirm_enabled)
        confirm.toggled.connect(self._set_close_confirm_enabled)
        layout.addWidget(self._setting_row("关闭时二次确认", confirm, panel))

        reset = ElaButton("恢复默认", variant="outlined", parent=panel)
        reset.clicked.connect(
            lambda: self._reset_shell_settings(
                mode_pivot, background, policy_pivot, confirm
            )
        )
        layout.addWidget(reset)
        layout.addStretch(1)

        dialog.setParamWidget(panel)
        dialog.exec()

    @staticmethod
    def _setting_row(label: str, control: QWidget, parent: QWidget) -> QWidget:
        row = QWidget(parent)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        text = ElaText(label, row)
        text.setTextPixelSize(14)
        text.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(text)
        layout.addStretch(1)
        layout.addWidget(control)
        return row

    def _reset_shell_settings(
        self,
        mode_pivot: ElaPivot,
        background: ElaToggleSwitch,
        policy_pivot: ElaPivot,
        confirm: ElaToggleSwitch,
    ) -> None:
        """恢复默认 + **把弹框里的控件一起同步**。

        只改窗口状态不同步控件，会出现「界面说深色、实际已经浅色」这种自相矛盾的
        中间态（用户报的「恢复默认后不对」就是这类）。
        """
        self.setNavigationBarDisplayMode(ElaNavigationType.NavigationDisplayMode.Auto)
        self._set_background_enabled(False)
        motion.setMode(ElaMotionModeType.Full)
        self._set_close_confirm_enabled(True)
        mode_pivot.setCurrentIndex(0)
        background.setIsToggled(False)
        policy_pivot.setCurrentIndex(int(ElaMotionModeType.Full))
        confirm.setIsToggled(True)
        self._log("外壳设置已恢复默认")

    # ── 外壳动作 ──────────────────────────────────────────────────────
    def _log(self, text: str) -> None:
        view = getattr(self, "_log_view", None)
        if view is not None:
            view.appendPlainText(f"[INFO] {text}")

    def _navigate_page(self, page: QWidget) -> None:
        key = page.property("ElaPageKey")
        if key:
            self.navigation(key)

    def _goto_home(self) -> None:
        if self._page_entries:
            self._navigate_page(self._page_entries[0][2])

    def _set_theme(self, dark: bool) -> None:
        eTheme.setThemeMode(
            ElaThemeType.ThemeMode.Dark if dark else ElaThemeType.ThemeMode.Light
        )
        self._log("切换为" + ("深色" if dark else "浅色") + "主题")

    def _toggle_theme(self) -> None:
        self._set_theme(eTheme.getThemeMode() == ElaThemeType.ThemeMode.Light)

    def _nav_mode_index(self) -> int:
        mode = self.getNavigationBarDisplayMode()
        return list(_NAV_MODES).index(mode) if mode in _NAV_MODES else 0

    def _on_nav_mode_index_changed(self, index: int) -> None:
        if 0 <= index < len(_NAV_MODES):
            self.setNavigationBarDisplayMode(_NAV_MODES[index])
            self._log(f"导航栏显示模式：{_NAV_MODE_TEXTS[index]}")

    def _cycle_nav_mode(self) -> None:
        index = (self._nav_mode_index() + 1) % len(_NAV_MODES)
        self.setNavigationBarDisplayMode(_NAV_MODES[index])
        self._log(f"导航栏显示模式：{_NAV_MODE_TEXTS[index]}")

    def _set_close_confirm_enabled(self, on: bool) -> None:
        self._close_confirm_enabled = bool(on)
        self._log("关闭二次确认：" + ("开" if on else "关"))

    def _set_background_enabled(self, on: bool) -> None:
        """窗口背景：``setWindowPixmap`` + ``setWindowPaintMode``（亮 / 暗各一张）。

        仓库不带图片资源，示例用 QPainter 现画一张渐变（页面区不透明，实际可见
        的是导航栏与应用栏那一带 —— 与上游示例同款效果）。
        """
        self._background_enabled = bool(on)
        if on:
            for mode in (ElaThemeType.ThemeMode.Light, ElaThemeType.ThemeMode.Dark):
                self.setWindowPixmap(mode, self._make_background_pixmap(mode))
            self.setWindowPaintMode(ElaWindowType.PaintMode.Pixmap)
        else:
            self.setWindowPaintMode(ElaWindowType.PaintMode.Normal)
        self._log("窗口背景渐变：" + ("开" if on else "关"))

    def _make_background_pixmap(self, mode) -> QPixmap:
        dark = mode == ElaThemeType.ThemeMode.Dark
        pixmap = QPixmap(640, 640)
        gradient = QLinearGradient(0, 0, 640, 640)
        if dark:
            gradient.setColorAt(0.0, QColor("#16233a"))
            gradient.setColorAt(1.0, QColor("#3a2340"))
        else:
            gradient.setColorAt(0.0, QColor("#bcd7ff"))
            gradient.setColorAt(1.0, QColor("#ffe0ba"))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(pixmap.rect(), gradient)
        painter.end()
        return pixmap

    # ── 导航联动（状态栏 / dock / 日志都挂在这一条信号上）─────────────
    def _on_navigation_node_clicked(self, node_type, node_key: str) -> None:
        if node_key == self._about_key:
            self._open_about()
            return
        if node_key == self._settings_key:
            self._open_settings()
            return
        if node_type != ElaNavigationType.NavigationNodeType.PageNode:
            return
        self._sync_page_nav(node_key)
        title = self.getNavigationNodeTitle(node_key)
        self._status_page.setText(f"当前页面：{title}")
        self._log(f"打开页面「{title}」")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    eApp.init()
    #
    splash = ElaSplashScreen()
    splash.setTitle("pyqt6_ela_pro")
    splash.setSubTitle("组件示例")
    splash.show()

    # 注意：不能在 QTimer 事件回调中 show() 顶层窗口（多页面窗口首帧渲染
    # 与回调上下文产生竞态导致 Qt 崩溃），故 splash 展示用 processEvents
    # 手动驱动，窗口在事件循环开始前的主路径构建 / 显示。
    messages = [
        "正在加载组件...",
        "正在初始化主题...",
        "正在构建页面...",
        "正在准备就绪...",
    ]
    import time as _time

    t_start = _time.monotonic()
    step = [0]
    while _time.monotonic() - t_start < 0.5:
        # splash 的职责就是遮住启动期工作：``ElaSplashScreen`` 会在自己出现后自动付掉
        # Qt6 的一次性字体引擎解析（~190ms）、首个图标字体（~30ms）与 Pygments 导入
        # （~35ms，见 splash_screen._warmTextStack），这里只需要驱动事件循环 + 更新进度文案。
        app.processEvents()
        _time.sleep(0.02)
        if step[0] < len(messages):
            splash.setValue(int((step[0] + 1) / len(messages) * 100))
            splash.setStatusText(messages[step[0]])
            step[0] += 1
    splash.close()

    window = ExampleWindow()
    # 少数页面的内容会往窗口挂**原生子窗口**（blueprint 的 GL 视口，见
    # ``ExamplePage.PRE_SHOW_BUILD``）：必须在 show 之前建好 —— 给已显示的顶层窗口挂
    # 原生子窗口时 Windows/Qt 会重建顶层 HWND，视觉上就是主窗口「闪一次」（实测在
    # 后台预热里 T+1.8s，类名 Qt6xxQWindowIcon → Qt6xxQWindowOwnDCIcon）。
    for _page in window.findChildren(ExamplePage):
        if getattr(_page, "PRE_SHOW_BUILD", False):
            _page.buildDemoContent()
    window.show()

    # 启动后逐页预热：每 tick 只建一页（内容惰性构建，见 ``ExamplePage._setupUI``），
    # 避免长阻塞；用户已经打开过的页会跳过。定时器是 window 的子对象（随窗口销毁）。
    _pages = list(window.findChildren(ExamplePage))
    _cursor = [0]

    def _warm_next() -> None:
        while _cursor[0] < len(_pages):
            page = _pages[_cursor[0]]
            _cursor[0] += 1
            if page.isVisible() or page._demo_built:
                continue
            page.buildDemoContent()
            _warm_timer.start(40)
            return

    _warm_timer = QTimer(window)
    _warm_timer.setSingleShot(True)
    _warm_timer.timeout.connect(_warm_next)
    _warm_timer.start(250)

    rc = app.exec()
    # 退出前显式销毁并冲刷删除队列：让各组件的清理钩子（断开全局主题信号等）
    # 在解释器退出前完成，避免进程退出时的 Qt 清理竞态崩溃
    window.deleteLater()
    app.processEvents()
    sys.exit(rc)
