"""
[pyqt6_ela_pro] 示例页面基类
"""

import os
import inspect
import re as _re
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QVBoxLayout,
    QHBoxLayout,
    QPlainTextEdit,
    QPushButton,
    QApplication,
    QWidget,
)
from PyQt6.QtGui import (
    QFont,
    QColor,
    QShowEvent,
    QTextCharFormat,
    QTextCursor,
)
from PyQt6ElaWidgetTools import (
    ElaPlainTextEdit,
    ElaScrollArea,
    ElaText,
    ElaIconType,
    ElaMessageBar,
    ElaMessageBarType,
    ElaThemeType,
    eTheme,
)
from pyqt6_ela_pro import (
    ElaThemeWidget,
    ElaDialogBase,
    ElaButton,
    setResizeReflowDeferred,
)

RESOURCE_PATH = os.path.join(os.path.dirname(__file__), "resource", "images")


def _res(filename):
    return os.path.join(RESOURCE_PATH, filename)


class ExamplePage(ElaThemeWidget):
    """示例页面基类，提供通用布局结构"""

    PAGE_TITLE = "[ela_ext] 示例页面"

    #: 内容会往窗口挂**原生子窗口**（如 `_GLViewport = QOpenGLWidget`）的页面置 True：
    #: 这类页必须在 `window.show()` 之前构建（见 `__main__`）—— 给已显示的顶层窗口挂
    #: 原生子窗口会让 Windows/Qt 重建顶层 HWND，视觉上主窗口会「闪一次」。
    PRE_SHOW_BUILD = False

    def __init__(self, parent=None):
        super().__init__(parent)
        self._demo_built = False
        self._setupUI()
        # 侧边栏收缩/展开是上游 4 条并发的 255ms 属性动画：每帧都会 resize 本页 → 内容
        # 每帧重排/重绘（实测单帧 8.6ms，慢机掉帧）。库里的 setResizeReflowDeferred 在
        # 连续 resize 期间把本页钉住，静止 120ms 后一次性放开（单帧 → 0.0ms）。
        setResizeReflowDeferred(self)

    def _setupUI(self):
        self._scrollArea = ElaScrollArea(self)
        self._scrollArea.setWidgetResizable(True)
        self._scrollArea.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)

        # 脚手架先建、内容惰性构建：24 页全量 eager 构造要 1.2s 且全压在启动路径上
        # （耗时基线是 PySide6 时代测的；「少建控件 = 少付构造开销」与绑定无关）。
        # 内容改为首次显示时构建（``buildDemoContent``），启动后由宿主后台逐页预热。
        self._scrollWidget = ElaThemeWidget()
        self._mainLayout = QVBoxLayout(self._scrollWidget)
        self._mainLayout.setContentsMargins(20, 20, 20, 20)
        self._mainLayout.setSpacing(15)
        self._scrollArea.setWidget(self._scrollWidget)

        containerLayout = QVBoxLayout(self)
        containerLayout.addWidget(self._scrollArea)

    def buildDemoContent(self):
        """构建页面内容（幂等）。``showEvent`` 会调用，宿主也可在空闲时提前预热。"""
        if self._demo_built:
            return
        self._demo_built = True
        self._addDemoContent(self._mainLayout)
        self._mainLayout.addStretch()

    def showEvent(self, event: QShowEvent) -> None:
        self.buildDemoContent()
        super().showEvent(event)

    def _addDemoContent(self, main_layout):
        raise NotImplementedError("子类必须实现 _addDemoContent 方法")

    def _createSectionHeader(self, title):
        section = ElaText(title, self)
        section.setTextPixelSize(18)
        font = QFont()
        font.setPixelSize(18)
        font.setBold(True)
        section.setFont(font)
        return section

    def _addInfoText(self, text, parent_layout):
        info = ElaText(text, self)
        info.setTextPixelSize(14)
        parent_layout.addWidget(info)

    def _createHeaderRow(self, title, method):
        """创建带代码查看按钮的节标题行（标题 + 伸缩 + 代码按钮）。"""
        row = QHBoxLayout()
        row.setSpacing(8)
        btn = ElaButton("</> 代码", variant="text", color="primary", parent=self)
        btn.setFixedWidth(85)
        btn.clicked.connect(lambda: self._show_code(method))
        row.addWidget(btn)
        row.addWidget(self._createSectionHeader(title))
        return row

    def _show_code(self, method):
        self._build_code_dialog(method).exec()

    def _build_code_dialog(self, method):
        """构造「示例代码」对话框（尺寸走 ``_code_dialog_size``，不经 autoFit）。"""
        try:
            source = inspect.getsource(method)
        except (OSError, TypeError):
            source = "无法获取源码"
        dlg = ElaDialogBase(title="示例代码", parent=self.window())
        dlg.setLeftButtonText("关闭")
        for btn in dlg.findChildren(QPushButton):
            if btn.text() == "确定":
                btn.hide()
                break
        # 用 ElaPlainTextEdit 而不是裸 QPlainTextEdit，两个问题一次解决：
        #   - 右键菜单：它覆写了 contextMenuEvent（ElaPlainTextEdit.cpp:100-140），
        #     里面就是 ElaMenu + addElaIconAction（复制 / 全选），不再是原生菜单；
        #   - 滚动条：构造时上下都换成了 ElaScrollBar（:22-23），跟随主题。
        # 代价是背景**由主题决定**（ElaPlainTextEditStyle.cpp:41 用 BasicBaseAlpha
        # 画，盖不住容器的 setSolidBackground、也不吃 Palette.Base —— 实测设了仍是
        # 系统色 #a8a8a8）→ 高亮配色因此分亮 / 暗两套（见 _STYLE_DARK/_STYLE_LIGHT）。
        edit = ElaPlainTextEdit()
        edit.setReadOnly(True)
        edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        edit.setFrameShape(QPlainTextEdit.Shape.NoFrame)
        font = QFont("Consolas", 10)
        font.setStyleHint(QFont.StyleHint.Monospace)
        edit.setFont(font)
        edit.document().setDefaultFont(font)
        # 逐 token 显式上色，**不依赖 Palette.Text**：主题切换会把 Text 刷回
        # 主题 BasicText（themeModeChanged → onThemeChanged）
        _insert_colored_code(edit.document(), source)
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(4)
        container_layout.addWidget(edit)
        copy_btn = ElaButton(
            "复制代码",
            icon=ElaIconType.IconName.Copy,
            iconSize=16,
            variant="solid",
            color="primary",
            parent=container,
        )
        copy_btn.clicked.connect(
            lambda: (
                QApplication.clipboard().setText(source),
                ElaMessageBar.success(
                    ElaMessageBarType.PositionPolicy.TopRight,
                    "",
                    "代码已复制到剪贴板",
                    1000,
                    dlg,
                ),
            )
        )
        container_layout.addWidget(copy_btn)
        dlg._paramLay.setContentsMargins(15, 25, 15, 2)
        dlg.setParamWidget(container)
        # 关掉 autoFit 再定尺寸：它会在 showEvent 里把宽度夹到 620px、高度按内容
        # 撑（代码框 sizeHint 很矮），resize() 写了也白写 —— 这正是原先「弹框太小」的根因。
        dlg.setAutoFit(False)
        dlg.resize(*self._code_dialog_size())
        return dlg

    def _code_dialog_size(self):
        """代码对话框尺寸：跟随宿主窗口按比例放大，再夹到窗口与屏幕可用区内。

        ``ElaContentDialog`` 的遮罩只覆盖宿主窗口、弹框居中其上，所以尺寸不能超过
        窗口（会压到桌面上）；屏幕再小也只能取可用区。
        """
        owner = self.window()
        screen = owner.screen() or QApplication.primaryScreen()
        width = max(900, round(owner.width() * 0.86))
        height = max(650, round(owner.height() * 0.86))
        width = min(width, owner.width() - 32)
        height = min(height, owner.height() - 32)
        if screen is not None:
            available = screen.availableGeometry()
            width = min(width, available.width() - 80)
            height = min(height, available.height() - 80)
        return max(640, width), max(480, height)


# ── 彩色代码插入到 QTextDocument ──────────────────────────────

_KEYWORDS = {
    "and",
    "as",
    "assert",
    "async",
    "await",
    "break",
    "class",
    "continue",
    "def",
    "del",
    "elif",
    "else",
    "except",
    "finally",
    "for",
    "from",
    "global",
    "if",
    "import",
    "in",
    "is",
    "lambda",
    "nonlocal",
    "not",
    "or",
    "pass",
    "raise",
    "return",
    "try",
    "while",
    "with",
    "yield",
    "True",
    "False",
    "None",
}
_BUILTINS = {
    "abs",
    "all",
    "any",
    "bin",
    "bool",
    "callable",
    "chr",
    "classmethod",
    "dict",
    "dir",
    "divmod",
    "enumerate",
    "eval",
    "filter",
    "float",
    "format",
    "getattr",
    "globals",
    "hasattr",
    "hash",
    "help",
    "hex",
    "id",
    "input",
    "int",
    "isinstance",
    "issubclass",
    "iter",
    "len",
    "list",
    "locals",
    "map",
    "max",
    "min",
    "next",
    "object",
    "oct",
    "open",
    "ord",
    "pow",
    "print",
    "property",
    "range",
    "repr",
    "reversed",
    "round",
    "set",
    "setattr",
    "slice",
    "sorted",
    "staticmethod",
    "str",
    "sum",
    "super",
    "tuple",
    "type",
    "vars",
    "zip",
}

_TOKEN_RE = _re.compile(
    r"""(?P<comment>\#.*)"""
    r"""|(?P<decorator>@\w+)"""
    r"""|(?P<string>(?:f|r)?(?:"[^"\\]*(?:\\.[^"\\]*)*"|'[^'\\]*(?:\\.[^'\\]*)*'))"""
    r"""|(?P<number>\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b)"""
    r"""|(?P<operator>\.\.\.|->|\*\*=?|<<=?|>>=?|//=?|[+\-*/%&|^~<>!=]=?|[:.,;])"""
    r"""|(?P<ident>\b\w+\b)"""
    r"""|(?P<other>.)"""
)

#: 代码高亮配色：kind -> (前景色, 粗体, 斜体)
#:
#: **必须两套**，因为代码区的底色是**主题给的、我们改不了**：
#: ``ElaPlainTextEdit`` 的 ``ElaPlainTextEditStyle`` 直接用 ``BasicBaseAlpha`` 画背景
#: （``ElaPlainTextEditStyle.cpp:41``），既盖不住容器的 ``setSolidBackground``、
#: 也不吃 ``Palette.Base``（实测设了仍是系统色 ``#a8a8a8``）—— 亮色 ``#fafafa`` /
#: 暗色 ``#2d2d2d``。一套中调色不可能在两种底色上都够 4.5:1（注释绿最典型：
#: ``#6A9955`` 暗底 4.13、亮底 3.19，两边都不达标），所以按主题各选一套并按
#: WCAG 4.5:1 校验过。
_STYLE_DARK = {
    "comment": ("#8CC06E", False, True),
    "decorator": ("#DCDCAA", False, False),
    "string": ("#CE9178", False, False),
    "number": ("#B5CEA8", False, False),
    "kw": ("#569CD6", True, False),
    "builtin": ("#D8A0DF", False, False),
    "class": ("#4EC9B0", False, False),
    "method": ("#DCDCAA", False, False),
    "attr": ("#9CDCFE", False, False),
    "operator": ("#D4D4D4", False, False),
    "defclass": ("#4EC9B0", False, False),
    "default": ("#D4D4D4", False, False),
}

_STYLE_LIGHT = {
    "comment": ("#3F6B32", False, True),
    "decorator": ("#7A3E9D", False, False),
    "string": ("#A03E00", False, False),
    "number": ("#0F6E3D", False, False),
    "kw": ("#0B4F9E", True, False),
    "builtin": ("#7A3E9D", False, False),
    "class": ("#0F6E7A", False, False),
    "method": ("#7A5B00", False, False),
    "attr": ("#0B4F9E", False, False),
    "operator": ("#1F1F1F", False, False),
    "defclass": ("#0F6E7A", False, False),
    "default": ("#1F1F1F", False, False),
}


def _style_for_mode(mode):
    """按主题模式取一套高亮配色。"""
    return _STYLE_LIGHT if mode == ElaThemeType.ThemeMode.Light else _STYLE_DARK


def _make_fmt(color, bold=False, italic=False):
    f = QTextCharFormat()
    f.setForeground(QColor(color))
    if bold:
        f.setFontWeight(QFont.Weight.Bold)
    if italic:
        f.setFontItalic(True)
    return f


def _insert_colored_code(doc, source, style=None):
    """把源码按 ``style`` 逐 token 上色写进 ``doc``（``style`` 缺省按当前主题选）。"""
    if style is None:
        style = _style_for_mode(eTheme.getThemeMode())
    cur = QTextCursor(doc)
    newline_fmt = _make_fmt(*style["default"])
    for line in source.split("\n"):
        _insert_colored_line(cur, line, style)
        cur.insertText("\n", newline_fmt)


def _insert_colored_line(cur, raw, style):
    matches = list(_TOKEN_RE.finditer(raw))
    last = 0
    for i, m in enumerate(matches):
        if m.start() > last:
            cur.insertText(raw[last : m.start()], _make_fmt(*style["default"]))
        kind = m.lastgroup
        text = m.group()

        if kind == "ident":
            fmt = _make_fmt(*style[_ident_type(i, matches, raw)])
        elif kind == "other":
            # 空白也要**显式上色**：主题切换会把 Palette.Text 刷回主题
            # BasicText（themeModeChanged → onThemeChanged），依赖它的话
            # 亮色主题下缩进会变成近黑
            cur.insertText(text, _make_fmt(*style["default"]))
            last = m.end()
            continue
        elif kind == "operator":
            fmt = _make_fmt(*style["operator"])
        else:
            fmt = _make_fmt(*style[kind])

        cur.insertText(text, fmt)
        last = m.end()
    if last < len(raw):
        cur.insertText(raw[last:], _make_fmt(*style["default"]))


def _ident_type(i, matches, raw):
    """判断 ident 的颜色类别，基于上下文。"""
    text = matches[i].group()

    if text in _KEYWORDS or text == "self":
        return "kw"
    if text in _BUILTINS:
        return "builtin"

    after_dot = False
    for j in range(i - 1, -1, -1):
        tok = matches[j].group()
        if tok.strip() and tok != ".":
            break
        if tok == ".":
            after_dot = True
            break

    followed_by_paren = False
    for j in range(i + 1, len(matches)):
        tok = matches[j].group()
        if tok == "(":
            followed_by_paren = True
            break
        if tok.strip():
            break

    if after_dot:
        return "method" if followed_by_paren else "attr"
    if text and text[0].isupper():
        return "class"
    if followed_by_paren:
        return "method"

    prev = raw[: matches[i].start()].rstrip()
    if prev.endswith("def") or prev.endswith("class"):
        return "defclass"

    return "default"
