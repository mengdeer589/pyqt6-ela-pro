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

（参考实现：``PyElaWidgetTools/example/mainwindow.py``。）
"""

import os
import sys
import traceback

from pyqt6_ela_pro import ElaSplashScreen

os.environ["QT_LOGGING_RULES"] = "*.debug=false;qt.qpa.fonts.warning=false"

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import QApplication
from PyQt6ElaWidgetTools import (
    eApp,
    ElaDockWidget,
    ElaIconType,
    ElaListView,
    ElaText,
    ElaWindow,
)
from pyqt6_ela_pro.example import (
    AnimationIconPage,
    AppShellPage,
    ApplicationComponentsPage,
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
)
from pyqt6_ela_pro.example.base_page import ExamplePage


class ExampleWindow(ElaWindow):
    """示例主窗口（两级侧边栏）。"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("pyqt6_ela_pro 组件示例")
        self.resize(1200, 800)

        self.setUserInfoCardTitle("组件演示")
        self.setUserInfoCardSubTitle("pyqt6_ela_pro@example.com")

        try:
            self._buildSidebar()
        except Exception:
            print(traceback.format_exc())

        self._buildDocks()

    # ── 侧边栏 ────────────────────────────────────────────────────────
    def _buildSidebar(self) -> None:
        icon = ElaIconType.IconName

        # ── 基础组件：按「用户会怎么找」分，不按「控件 vs 容器」分 ──
        _, basic = self.addExpanderNode("基础组件", icon.List)
        self.addPageNode("输入与选择", InputSelectPage(self), basic, icon.Pen)
        self.addPageNode("下拉框组件", ComboBoxPage(self), basic, icon.ListUl)
        self.addPageNode("容器与布局", ContainerLayoutPage(self), basic, icon.Square)
        self.addPageNode("视图与列表", ViewsListPage(self), basic, icon.TableList)
        self.addPageNode("按钮与菜单", ButtonsMenusPage(self), basic, icon.CircleNotch)
        self.addPageNode("进度与反馈", ProgressFeedbackPage(self), basic, icon.Gauge)
        self.expandNavigationNode(basic)

        # ── 数据与图表：绑数据源的东西都归这里 ──
        _, data = self.addExpanderNode("数据与图表", icon.ChartLine)
        self.addPageNode("表格", DataTablePage(self), data, icon.Table)
        self.addPageNode("图表（第三方库）", ChartLibPage(self), data, icon.ChartPie)
        self.addPageNode(
            "ElaChartWidget 图表引擎", ChartsPage(self), data, icon.ChartLine
        )
        self.expandNavigationNode(data)

        # ── 内容渲染 ──
        _, render = self.addExpanderNode("内容渲染", icon.FileCode)
        self.addPageNode("Markdown 渲染", MarkdownPage(self), render, icon.FileCode)
        self.expandNavigationNode(render)

        # ── AI 对话：按**能力域**切，不按「应用场景」切 ──
        # 原来分「基础对话 / Agent 能力 / 多话题对话」三页，是按使用场景分的，
        # 结果同一个组件的能力被打散在三处、每页还各演一遍权限审批。现在改成：
        # 「长什么样」/「怎么接」/「agent 多了什么」/「多话题」/「落库与性能」，
        # 五页各自回答一个问题。
        _, chat = self.addExpanderNode("AI 对话", icon.Comments)
        self.addPageNode("聊天组件总览", ChatOverviewPage(self), chat, icon.Paragraph)
        self.addPageNode("输入区能力", ChatInputPage(self), chat, icon.Comment)
        self.addPageNode("Agent 能力", ChatAgentPage(self), chat, icon.ShieldHalved)
        self.addPageNode("会话管理", ChatSessionPage(self), chat, icon.ClipboardList)
        self.addPageNode("持久化与性能", ChatPersistPage(self), chat, icon.Database)
        # 默认展开：这是本示例的重点组件，收起来等于把它藏了
        self.expandNavigationNode(chat)

        # ── 窗口与应用外壳 ──
        _, shell = self.addExpanderNode("窗口与应用外壳", icon.WindowRestore)
        self.addPageNode("应用框架", ApplicationComponentsPage(self), shell, icon.Grid)
        self.addPageNode("弹窗与提示", DrawerTooltipPage(self), shell, icon.Bell)
        self.addPageNode("启动与托盘", AppShellPage(self), shell, icon.Plug)
        self.expandNavigationNode(shell)

        # ── 系统交互与嵌入 ──
        _, system = self.addExpanderNode("系统交互与嵌入", icon.Terminal)
        self.addPageNode("外部内容嵌入", EmbedPage(self), system, icon.Globe)
        self.addPageNode("终端输出", TerminalPage(self), system, icon.Terminal)
        self.addPageNode(
            "划词助手", SelectionAssistantPage(self), system, icon.Highlighter
        )
        self.expandNavigationNode(system)

        # ── 动效与图形 ──
        _, motion = self.addExpanderNode("动效与图形", icon.Play)
        self.addPageNode("动画与图标", AnimationIconPage(self), motion, icon.Play)
        self.addPageNode("节点图编辑器", BlueprintPage(self), motion, icon.Circle)
        self.expandNavigationNode(motion)

        # ── 参考文档：纯文档页（表格 + 代码块），和可交互 demo 不是一回事 ──
        _, docs = self.addExpanderNode("参考文档", icon.BookOpen)
        self.addPageNode("聊天组件 API 指南", ChatGuidePage(self), docs, icon.BookOpen)
        self.expandNavigationNode(docs)

    # ── DockWidget 停靠面板演示 ────────────────────────────────────────
    def _buildDocks(self) -> None:
        dock1 = ElaDockWidget("页面导航", self)
        dock1.setObjectName("DockPageNav")
        nav_list = ElaListView()
        nav_model = QStandardItemModel()
        for name in ["输入与选择", "下拉框组件", "表格", "弹窗与提示"]:
            nav_model.appendRow(QStandardItem(name))
        nav_list.setModel(nav_model)
        dock1.setWidget(nav_list)
        dock1.setMinimumWidth(180)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock1)

        dock2 = ElaDockWidget("说明", self)
        dock2.setObjectName("DockInfo")
        info_text = ElaText(
            "pyqt6_ela_pro 组件示例\n\n"
            "左侧导航栏切换页面，\n"
            "右侧面板可拖拽分离或重新停靠。\n\n"
            "所有演示代码位于:\npyqt6_ela_pro/example/",
        )
        info_text.setTextPixelSize(13)
        info_text.setWordWrap(True)
        info_text.setMinimumWidth(180)
        dock2.setWidget(info_text)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock2)
        self.tabifyDockWidget(dock1, dock2)
        dock1.raise_()


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
        # Qt6 的一次性字体解析（~190ms，见 splash_screen._warmTextStack），这里只需要
        # 驱动事件循环 + 更新进度文案。
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
