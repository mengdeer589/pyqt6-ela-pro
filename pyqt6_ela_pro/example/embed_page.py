"""外部内容嵌入

把**外部窗口**接进 Qt 布局：`ElaWindowEmbedder`（任意原生窗口）与
`ElaBrowserEmbedder`（内嵌 Chrome，多实例共享同一浏览器进程）。

这一页合并了原来的「窗口嵌入」和「浏览器嵌入」两页 —— 之前「窗口嵌入」的
第 02 节就在演示 `ElaBrowserEmbedder`，侧边栏却还有一个独立的「浏览器嵌入」
条目，用户根本分不清两者什么关系。现在分三节：

- `01` 窗口嵌入：`SetParent` + 客户区尺寸换算（高 DPI 缩放的老坑）
- `02` 浏览器嵌入：单页内嵌 + 共享会话的窗口认领
- `03` 多 URL 测试台：一次开多个面板，压共享会话那条路径
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)
from PyQt6ElaWidgetTools import (
    ElaComboBox,
    ElaLineEdit,
    ElaPlainTextEdit,
    ElaPushButton,
    ElaText,
    ElaThemeType,
    eTheme,
)
from pyqt6_ela_pro import ElaBrowserEmbedder, ElaButton, ElaWindowEmbedder
from pyqt6_ela_pro._styles import ColorText, setPlainFrame
from pyqt6_ela_pro.window_embedder import win32gui as _win32gui
from .base_page import ExamplePage
import os
from pathlib import Path

BROWSER_PATH = Path(
    os.environ.get(
        "ELA_BROWSER_PATH",
        r"Supermium\chrome.exe",
    )
)

TEST_URLS = [
    "https://www.bilibili.com",
    "https://www.baidu.com",
    "https://www.qq.com",
]


class _BrowserPanel(QWidget):
    """单个浏览器面板"""

    def __init__(
        self, title: str, url: str, browser_path: Path, debug_port: int, parent=None
    ):
        super().__init__(parent)
        self.setObjectName(f"BrowserPanel_{debug_port}")
        self._seen_cookie_urls: set[str] = set()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        header = ElaText(title, self)
        header.setTextPixelSize(14)
        layout.addWidget(header)

        row = QHBoxLayout()
        row.setSpacing(6)
        self._url_input = ElaLineEdit()
        self._url_input.setFixedHeight(28)
        self._url_input.setText(url)
        row.addWidget(self._url_input)

        embed_btn = ElaPushButton("嵌入")
        embed_btn.setFixedWidth(50)
        embed_btn.clicked.connect(self._embed)
        row.addWidget(embed_btn)

        load_btn = ElaPushButton("加载")
        load_btn.setFixedWidth(50)
        load_btn.clicked.connect(self._load_url)
        row.addWidget(load_btn)

        file_btn = ElaPushButton("打开文件")
        file_btn.setFixedWidth(70)
        file_btn.clicked.connect(self._open_file)
        row.addWidget(file_btn)

        release_btn = ElaPushButton("释放")
        release_btn.setFixedWidth(50)
        release_btn.clicked.connect(self._release)
        row.addWidget(release_btn)

        cookie_btn = ElaPushButton("Cookie")
        cookie_btn.setFixedWidth(60)
        cookie_btn.clicked.connect(self._show_cookie)
        row.addWidget(cookie_btn)

        layout.addLayout(row)

        self._browser = ElaBrowserEmbedder(
            webview_path=browser_path,
            debug_port=debug_port,
            browser_args=[
                f"--user-data-dir={Path.cwd() / 'runtime' / 'cache' / f'browser_{debug_port}'}"
            ],
            parent=self,
        )
        self._browser.enable_cookie_jar()
        layout.addWidget(self._browser, 1)

        self._log = ElaPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setFixedHeight(50)
        layout.addWidget(self._log)

        self._browser.windowEmbedded.connect(
            lambda h: self._on_event(f"已嵌入 0x{h:X}")
        )
        self._browser.windowReleased.connect(
            lambda h: self._on_event(f"已释放 0x{h:X}")
        )
        self._browser.embedError.connect(lambda m: self._on_event(f"错误: {m}"))
        self._browser.embedCompleted.connect(
            lambda ok: self._on_event("CDP 就绪" if ok else "CDP 失败")
        )
        self._browser.fileDropped.connect(
            lambda path: self._on_event(f"文件拖入: {path}")
        )
        self._browser.loadStarted.connect(lambda: self._on_event("[CDP] 页面开始加载"))
        self._browser.loadFinished.connect(lambda: self._on_event("[CDP] 页面加载完成"))
        self._browser.domContentReady.connect(
            lambda: self._on_event("[CDP] DOM 解析完成")
        )
        self._browser.pageError.connect(
            lambda url, text: self._on_event(f"[CDP] JS 异常: {url} {text}")
        )
        # 网络请求日志太嘈杂，默认不显示；需要时可取消注释
        # self._browser.networkRequest.connect(
        #     lambda url, method, rtype: self._on_event(f"[CDP] 请求: {method} {url} ({rtype})")
        # )
        # self._browser.networkResponse.connect(
        #     lambda url, status, rtype: self._on_event(f"[CDP] 响应: {status} {url} ({rtype})")
        # )
        self._browser.consoleMessage.connect(
            lambda level, text: self._on_event(f"[CDP] 控制台 [{level}]: {text}")
        )
        self._browser.cookieSent.connect(self._on_cookie_sent)
        self._browser.cookieReceived.connect(self._on_cookie_received)
        self._browser.credentialDetected.connect(self._on_credential)

    def _on_event(self, msg: str):
        # print(msg)
        self._append_log(msg)

    def _append_log(self, msg: str):
        try:
            self._log.appendPlainText(msg)
        except Exception:
            pass

    def _on_cookie_sent(self, url: str, cookie: str):
        print(f"[Cookie] 请求携带: {url} → {cookie}")
        key = f"sent:{url}"
        if key not in self._seen_cookie_urls:
            self._seen_cookie_urls.add(key)
            self._on_event(f"[Cookie] 请求携带: {url} → {cookie[:120]}")

    def _on_cookie_received(self, url: str, cookie: str):
        print(f"[Cookie] 服务器设置: {url} → {cookie}")
        key = f"recv:{url}"
        if key not in self._seen_cookie_urls:
            self._seen_cookie_urls.add(key)
            self._on_event(f"[Cookie] 服务器设置: {url} → {cookie[:120]}")

    def _on_credential(self, url: str, hdr: str, val: str):
        print(f"[凭据] {url} [{hdr}]: {val}")
        self._on_event(f"[凭据] {url} [{hdr}]: {val[:60]}")

    def _embed(self):
        url = self._url_input.text().strip()
        self._append_log(f"嵌入: {url}")
        try:
            self._browser.embed(url, connect_cdp=True)
        except Exception as e:
            self._append_log(f"错误: {e}")

    def _load_url(self):
        url = self._url_input.text().strip()
        self._append_log(f"加载: {url}")
        try:
            self._browser.load_url(url)
        except Exception as e:
            self._append_log(f"错误: {e}")

    def _open_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 HTML 文件", "", "HTML 文件 (*.html *.htm);;所有文件 (*)"
        )
        if path:
            self._append_log(f"加载本地文件: {path}")
            try:
                self._browser.load_url(Path(path))
            except Exception as e:
                self._append_log(f"错误: {e}")

    def _release(self):
        try:
            self._browser.release()
            self._append_log("已释放")
        except Exception as e:
            self._append_log(f"错误: {e}")

    def _show_cookie(self):
        header = self._browser.get_cookie_header()
        if header:
            print(f"\n{'=' * 60}")
            print("[Cookie Jar] 当前收集到:")
            for domain, cookies in self._browser._cookie_store.items():
                print(f"  [{domain}]")
                for name, val in cookies.items():
                    print(f"    {name} = {val}")
            print(f"\n[Header] {header}")
            print(f"{'=' * 60}\n")
            self._on_event(f"[Cookie] 已输出到终端，共 {len(header)} 字符")
        else:
            self._on_event("[Cookie] cookie jar 为空，请先嵌入页面")

    def release(self):
        self._browser.release()


class EmbedPage(ExamplePage):
    """外部内容嵌入示例页。"""

    PAGE_TITLE = "外部内容嵌入"

    def __init__(self, parent=None):
        self._browser_available = False
        try:
            ElaBrowserEmbedder._checkDependencies()
            self._browser_available = True
        except ImportError:
            self._browser_available = False
        # 缺 pywin32 时整套控件都不建，``_showStatus`` 会摸到它 —— 先置 None 并判空
        self._infoText = None
        # 浏览器嵌入控件延后到 _addDemoContent 里建：ElaBrowserEmbedder 的构造在
        # 依赖不全时会抛 ImportError，而示例页是被主窗口逐个构造的
        self._browser = None
        super().__init__(parent)

    def _addDemoContent(self, main_layout):
        """缺可选依赖时**降级**，不要让整页崩掉。

        ``ElaWindowEmbedder.__init__`` / ``ElaBrowserEmbedder._checkDependencies()``
        在没有 pywin32 时抛 ``ImportError``。示例页是被主窗口**逐个构造**的，
        这里抛出去会让主窗口初始化中断 —— 用户看到的是「应用起不来」，
        而不是「这一页的功能需要装个可选依赖」。
        """
        if _win32gui is None:
            hint = ElaText(
                "本页功能需要可选依赖 pywin32（窗口枚举 / SetParent / CDP）。\n"
                "当前环境未安装，已跳过全部演示。\n"
                "安装后即可使用：uv pip install pywin32",
                self,
            )
            hint.setTextPixelSize(14)
            main_layout.addWidget(hint)
            return
        self._demoWindowEmbedder(main_layout)
        self._demoBrowserEmbedder(main_layout)

    def _showStatus(self, msg):
        if self._infoText is None:
            return
        self._infoText.setText(msg)
        self._infoText.adjustSize()

    def _embedCurrentWindow(self):
        index = self._windowCombo.currentIndex()
        if index < 0:
            self._showStatus("请先选择要嵌入的窗口")
            return

        mode = self._modeCombo.currentIndex()

        if mode == 0:
            hwnd = self._windowCombo.currentData()
            if hwnd:
                self._embedder.embedByHwnd(hwnd)
        elif mode == 1:
            title = self._windowCombo.currentText()
            if title:
                self._embedder.embedByTitle(title)
        elif mode == 2:
            class_name = self._windowCombo.currentText()
            if class_name:
                self._embedder.embedByClass(class_name)

    def _getAllWindows(self):
        """枚举可嵌入的顶层窗口。

        **用库里的 ``window_embedder.win32gui``（没装 pywin32 时是 ``None``），
        不要裸 ``import win32gui``**：示例在缺可选依赖的环境里必须**降级**，
        而不是让整个应用起不来 —— 之前这里裸 import，主窗口构造到一半直接
        ``ModuleNotFoundError`` 抛出，剩下 22 个页面都看不到。
        """
        self._windowsList = []
        if _win32gui is None:
            self._windowCombo.clear()
            self._windowCombo.addItem("未安装 pywin32，无法枚举窗口", None)
            self._showStatus(
                "缺少 pywin32：窗口枚举与嵌入不可用，请运行 uv pip install pywin32"
            )
            return

        def enum_callback(hwnd, _):
            if _win32gui.IsWindow(hwnd) and _win32gui.IsWindowVisible(hwnd):
                title = _win32gui.GetWindowText(hwnd)
                if title:
                    class_name = _win32gui.GetClassName(hwnd)
                    self._windowsList.append((hwnd, title, class_name))
            return True

        try:
            _win32gui.EnumWindows(enum_callback, None)
        except Exception:
            pass
        self._windowsList.sort(key=lambda x: x[1].lower())

    def _onEmbedError(self, msg):
        self._showStatus(f"错误: {msg}")

    def _onEmbedTimeout(self):
        self._showStatus("嵌入超时")

    def _refreshWindowCombo(self):
        self._windowCombo.clear()
        mode = self._modeCombo.currentIndex()

        if mode == 0:
            for hwnd, title, class_name in self._windowsList:
                display_text = f"0x{hwnd:X} | {title} | {class_name}"
                self._windowCombo.addItem(display_text, hwnd)
        elif mode == 1:
            seen_titles = set()
            for hwnd, title, class_name in self._windowsList:
                if title not in seen_titles:
                    seen_titles.add(title)
                    self._windowCombo.addItem(title, (title, None))
        elif mode == 2:
            seen_classes = set()
            for hwnd, title, class_name in self._windowsList:
                if class_name not in seen_classes:
                    seen_classes.add(class_name)
                    self._windowCombo.addItem(class_name, (class_name, None))

    def _onModeChanged(self, index):
        self._refreshWindowCombo()

    def _onWindowEmbedded(self, hwnd):
        self._showStatus(f"窗口已嵌入: 0x{hwnd:X}")

    def _onWindowNotFound(self, msg):
        self._showStatus(msg)

    def _onWindowReleased(self, hwnd):
        self._showStatus(f"窗口已释放: 0x{hwnd:X}")

    def _onWindowSelected(self, index):
        pass

    def _refreshWindows(self):
        self._getAllWindows()
        self._refreshWindowCombo()
        self._showStatus("窗口列表已刷新")

    def _releaseWindow(self):
        if self._embedder.hasEmbeddedWindow:
            self._embedder.release()
        else:
            self._showStatus("没有嵌入的窗口")

    def _demoWindowEmbedder(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "01. ElaWindowEmbedder - 窗口嵌入", self._demoWindowEmbedder
            )
        )
        self._addInfoText(
            "将外部窗口嵌入到 QWidget 中，支持通过 hwnd、窗口标题或类名嵌入。\n"
            "支持文件拖入拦截，拖入的文件路径会显示在状态栏中",
            parent_layout,
        )

        self._getAllWindows()

        mode_layout = QHBoxLayout()
        mode_layout.setSpacing(10)
        mode_label = ElaText("嵌入模式:", self)
        mode_label.setTextPixelSize(14)
        mode_layout.addWidget(mode_label)

        self._modeCombo = ElaComboBox(self)
        self._modeCombo.addItems(["按句柄 (Hwnd)", "按标题 (Title)", "按类名 (Class)"])
        self._modeCombo.setFixedWidth(150)
        self._modeCombo.currentIndexChanged.connect(self._onModeChanged)
        mode_layout.addWidget(self._modeCombo)

        self._windowCombo = ElaComboBox(self)
        self._windowCombo.setFixedWidth(300)
        self._refreshWindowCombo()
        self._windowCombo.currentIndexChanged.connect(self._onWindowSelected)
        mode_layout.addWidget(self._windowCombo)

        refresh_btn = ElaPushButton("刷新窗口列表", self)
        refresh_btn.setFixedWidth(100)
        refresh_btn.clicked.connect(self._refreshWindows)
        mode_layout.addWidget(refresh_btn)

        mode_layout.addStretch()
        parent_layout.addLayout(mode_layout)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(15)

        self._embedBtn = ElaPushButton("嵌入窗口", self)
        self._embedBtn.setFixedWidth(100)
        self._embedBtn.clicked.connect(self._embedCurrentWindow)
        btn_layout.addWidget(self._embedBtn)

        release_btn = ElaPushButton("释放窗口", self)
        release_btn.setFixedWidth(100)
        release_btn.clicked.connect(self._releaseWindow)
        btn_layout.addWidget(release_btn)

        btn_layout.addStretch()
        parent_layout.addLayout(btn_layout)

        self._embedderContainer = QFrame(self)
        self._embedderContainer.setFrameShape(QFrame.Shape.NoFrame)
        # 嵌入区是「外部窗口落地的洞」：底色压到 PopupBase 让它与页面底色分开，
        # 1px 描边用 PopupBorder。**取 eTheme 令牌而不是写死 #2b2b2b / #444**
        # —— 写死的话深色主题下会变成一块比页面还亮的补丁（主题切换也不跟随）。
        _mode = eTheme.getThemeMode()
        setPlainFrame(
            self._embedderContainer,
            eTheme.getThemeColor(_mode, ElaThemeType.ThemeColor.PopupBase),
            eTheme.getThemeColor(_mode, ElaThemeType.ThemeColor.PopupBorder),
        )
        self._embedderContainer.setFixedHeight(300)
        parent_layout.addWidget(self._embedderContainer)
        _embedderContainerLay = QHBoxLayout(self._embedderContainer)

        self._embedder = ElaWindowEmbedder(self._embedderContainer)
        self._embedder.windowEmbedded.connect(self._onWindowEmbedded)
        self._embedder.windowReleased.connect(self._onWindowReleased)
        self._embedder.windowNotFound.connect(self._onWindowNotFound)
        self._embedder.embedError.connect(self._onEmbedError)
        self._embedder.embedTimeout.connect(self._onEmbedTimeout)
        self._embedder.fileDropped.connect(
            lambda path: self._showStatus(f"文件拖入: {path}")
        )
        _embedderContainerLay.addWidget(self._embedder)
        # ElaText 上不了非主题色（paintEvent 会重置 palette），占位文案要用 ColorText
        self._infoText = ColorText(
            '嵌入区域 - 从下拉框选择窗口后点击"嵌入窗口"',
            self._embedderContainer,
        )
        self._infoText.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._infoText.setTextPixelSize(13)
        self._infoText.setTextColor(
            eTheme.getThemeColor(_mode, ElaThemeType.ThemeColor.BasicTextCategory)
        )
        self._infoText.setFixedSize(350, 30)

        parent_layout.addSpacing(30)

    def _demoBrowserEmbedder(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "02. ElaBrowserEmbedder - 浏览器嵌入", self._demoBrowserEmbedder
            )
        )
        self._addInfoText(
            "嵌入浏览器窗口，支持 CDP 控制。继承自 ElaWindowEmbedder，"
            "额外依赖 psutil 和 websocket-client。点「启动浏览器」会真的拉起一个"
            "Chrome 应用窗口并嵌进下面的框里；点「释放」会收掉浏览器进程。",
            parent_layout,
        )

        # 构造与信号接线**就地写在本方法体内**：每节标题的「</> 代码」按钮展示的
        # 就是本方法的源码，拆进 _newBrowserEmbedder 等于把读者要学的东西藏起来。
        # 降级分支只跳过「真的实例化」，代码本身照样完整 —— 依赖没装时读者看到的
        # 仍然是「怎么用」，而不是一段功能罗列。
        mode = eTheme.getThemeMode()
        container = QFrame(self)
        container.setFrameShape(QFrame.Shape.NoFrame)
        setPlainFrame(
            container,
            eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.PopupBase),
            eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.PopupBorder),
        )
        container.setFixedHeight(300)
        parent_layout.addWidget(container)
        container_layout = QHBoxLayout(container)

        if not self._browser_available:
            hint = ElaText(
                "未检测到 ElaBrowserEmbedder 的可选依赖（pywin32 / psutil / "
                "websocket-client），已跳过控件创建。\n"
                "安装后即可运行：uv pip install pywin32 psutil websocket-client",
                self,
            )
            hint.setTextPixelSize(14)
            container_layout.addWidget(hint)
            parent_layout.addSpacing(20)
            return

        self._browser = ElaBrowserEmbedder(container)
        # 信号全部转成一行状态文字 —— 嵌入器本身是外部输入面（CDP），调试时能
        # 看见事件流比什么都重要。注意错误信号有**三个**且各司其职：``embedError``
        # 是嵌入阶段出错、``pageError`` 是页面里的 JS 异常、``consoleMessage`` 是
        # 控制台输出，只接一个会漏。``embedCompleted`` 尤其要接：**浏览器起不来时
        # 只发信号不抛异常**，不接就表现为「点了没反应」。
        self._browser.loadStarted.connect(lambda: self._showStatus("loadStarted"))
        self._browser.loadFinished.connect(lambda: self._showStatus("loadFinished"))
        self._browser.domContentReady.connect(
            lambda: self._showStatus("domContentReady")
        )
        self._browser.consoleMessage.connect(
            lambda level, text: self._showStatus(f"console[{level}] {text[:60]}")
        )
        self._browser.pageError.connect(
            lambda url, msg: self._showStatus(f"pageError {url}: {msg[:60]}")
        )
        self._browser.embedCompleted.connect(
            lambda ok: self._showStatus(f"embedCompleted({ok})")
        )
        self._browser.embedError.connect(self._onEmbedError)
        self._browser.embedTimeout.connect(self._onEmbedTimeout)
        container_layout.addWidget(self._browser)

        info = ColorText("浏览器嵌入区域", container)
        info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info.setTextPixelSize(13)
        info.setTextColor(
            eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.BasicTextCategory)
        )
        info.setFixedSize(350, 30)

        row = QWidget(self)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(10)
        launch_btn = ElaButton("启动浏览器", variant="solid", size="small", parent=row)
        launch_btn.clicked.connect(
            lambda: self._browser.load_url("https://example.com")
        )
        row_layout.addWidget(launch_btn)
        reload_btn = ElaButton("刷新", variant="outlined", size="small", parent=row)
        reload_btn.clicked.connect(lambda: self._browser.reload())
        row_layout.addWidget(reload_btn)
        back_btn = ElaButton("后退", variant="text", size="small", parent=row)
        back_btn.clicked.connect(lambda: self._browser.runJS("history.back()"))
        row_layout.addWidget(back_btn)
        release_btn = ElaButton("释放", variant="text", size="small", parent=row)
        release_btn.clicked.connect(lambda: self._browser.release())
        row_layout.addWidget(release_btn)
        row_layout.addStretch(1)
        parent_layout.addWidget(row)
        parent_layout.addSpacing(20)

    def _demoAllUrls(self, main_layout):
        if not self._browser_available:
            info = ElaText(
                "浏览器嵌入功能需要 pywin32，请运行: uv pip install pywin32",
                self,
            )
            info.setTextPixelSize(14)
            main_layout.addWidget(info)
            return

        if not BROWSER_PATH.exists():
            info = ElaText(
                f"浏览器不存在: {BROWSER_PATH}\n请设置环境变量 ELA_BROWSER_PATH 指向 chrome.exe",
                self,
            )
            info.setTextPixelSize(14)
            main_layout.addWidget(info)
            return

        rows_layout = QVBoxLayout()
        rows_layout.setSpacing(10)

        for i, url in enumerate(TEST_URLS):
            panel = _BrowserPanel(
                title=f"浏览器 {i + 1}",
                url=url,
                browser_path=BROWSER_PATH,
                debug_port=9223 + i,
                parent=self,
            )
            panel.setMinimumHeight(680)
            rows_layout.addWidget(panel)
            self._panels.append(panel)

        main_layout.addLayout(rows_layout)
