"""划词结果对话框（``pyqt6_ela_pro.selection_assistant``）。

:class:`ElaSelectionResultDialog` 是划词动作条点中「翻译 / 解释 / 总结」这类
**要跑模型**的动作后弹出的浮动窗，实时显示大模型流式返回的 Markdown，
结束后可复制（**``Ctrl+C`` = 纯文本**；Markdown 源走「复制 Markdown」/
``Ctrl+Shift+C``）/ 重新生成。参照 Cherry Studio 的 selection action window。

**基类是上游 :class:`~PyQt6ElaWidgetTools.ElaWidget.ElaWidget`，不是自绘
``QWidget``**：ElaWidget 自带 ElaAppBar（图标 + 标题 + 窗口按钮）、窗口阴影
（``QEvent::Show`` 时补 ``WS_THICKFRAME``，Win7 另加 ``CS_DROPSHADOW``）、
拖动与边缘缩放、Mica 背景、主题适配。所以本组件**零 QSS、零 ``paintEvent``
自绘、零阴影边距常量** —— ``ElaSelectionPopup`` / ``ElaNotifyPopup`` 里那套手写
圆角 + 阴影是因为它们是**弹层**不是窗口，窗口别学。

窗口按钮只留「置顶 + 关闭」：置顶按钮（``StayTopButtonHint``，上游画的是图钉）
就是这种浮动面板该有的 pin，顺带白拿。焦点行为**抢焦点**（与 Cherry 的 action
window 一致）：Esc / Ctrl+C 快捷键和按钮点击都需要它，代价是源应用的选区高亮
消失 —— 划词原文会在正文上方单行展示，用户不至于完全失去上下文。

**组件不碰网络。** 流式内容全部由宿主推进（:meth:`beginStream` /
:meth:`appendMarkdown` / :meth:`endStream` / :meth:`setError`）；取消走
:attr:`~ElaSelectionResultDialog.stopRequested` 信号，**宿主必须在那里 abort
自己的后端**。Cherry Studio 在这一点上是坏的 —— ``ActionUtils.ts:85`` 传了空
``requestOptions``，从头到尾没注册过 ``AbortSignal``，停止按钮点了不真停，
只是靠 renderer 进程死亡顺带杀掉 fetch；Qt 里宿主线程照跑，所以这里把
「关窗即中止」做成一等公民（:meth:`closeEvent`）。

回合状态机：每次 :meth:`openFor` 递增 ``_turn_id``；所有结束路径（标题栏 ✕ /
Esc / 停止 / 重新生成 / 再次 :meth:`openFor`）汇到唯一的 :meth:`_endTurn`：

1. 按 turn id 丢弃**迟到分片**（被中止的回合之后宿主仍可能推几片在途）；
2. 仍在流式时发 :attr:`stopRequested`；
3. 只在**正常落定**（:meth:`endStream` / :meth:`setResult`）时发
   :attr:`finished` —— 半句话不算结果，复制保持禁用。

命名规范与库内一致（``camelCase``）。
"""

from __future__ import annotations

import functools
from typing import Optional

from .._internal import is_deleted
from PyQt6.QtCore import QEvent, QPoint, QRect, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from PyQt6ElaWidgetTools import (
    ElaAppBarType,
    ElaIcon,
    ElaIconType,
    ElaProgressRing,
    ElaWidget,
)

from .._internal import connect_theme_signal, disconnect_theme
from .._styles import ColorText
from .._theme import ElaStatusRoleType, currentMode, statusColor, textMuted
from ..ela_button import ElaButton
from ..ela_markdown_viewer import ElaMarkdownViewer
from ..tooltips import ElaToolTipPositionType, remove_tooltip, set_tooltip

#: 默认窗口尺寸（app bar 的高度由 ElaWidget 自己让出，不计入）
_DEFAULT_SIZE = QSize(520, 420)
#: 最小窗口尺寸
_MIN_SIZE = QSize(320, 200)
#: 距屏幕工作区边缘的最小间距（像素）
_EDGE_GAP = 6
#: 内容区内边距
_PAD = 12
#: 落点偏移（弹窗水平居中于落点后，再往下让一点；放不下就翻到上方）
_PLACE_OFFSET = QPoint(0, 18)
#: app bar 高度（Cherry 同值；ElaWidget 默认 45）
_APP_BAR_HEIGHT = 32
#: 状态行忙碌指示的边长
_RING_SIZE = 16
#: 标题栏图标的物理边长
_TITLE_ICON_PX = 18
#: 原文预览参与省略计算的字符上限。省略到控件宽度（几百 px ≈ 几十个汉字）之后
#: 更后面的内容永远露不出来，所以一次划词几百万字时也不必让 ``elidedText`` 在
#: 全文上扫 —— 只喂前 400 字给它，QString 拷贝与扫描都变成常数级
_PREVIEW_SOURCE_MAX = 400
#: 原文预览悬浮提示的字符上限。折行有界（见 ``_PREVIEW_TIP_WIDTH``）后不能
#: 再喂两千字：``ElaToolTip`` 要排版 + 自绘绘制全文，且几十行高的提示框本身
#: 就不可读。完整原文由 :meth:`_PreviewText.fullText` 提供，宿主想要就取。
_PREVIEW_TIP_MAX = 400
#: 原文预览悬浮提示的最大宽度（折行，避免拉成远宽于屏幕的单行横条）
_PREVIEW_TIP_WIDTH = 480
#: ``WS_THICKFRAME`` 撑高的高度上限（像素）。实测 +31（与 app bar 高度无关）；
#: 留一点余量给不同 DPI / 系统度量，但远小于用户拖一次边框的幅度。
_WM_GROW_MAX_PX = 64

#: 状态行文案（落定且有正文时状态行整行隐藏）
_TEXT_PREPARING = "准备中…"
_TEXT_STREAMING = "生成中…"
_TEXT_STOPPED = "已停止"
_TEXT_FAILED = "生成失败"


def _cleanup_on_destroy(dialog, _object=None) -> None:  # noqa: ANN001
    """对话框析构时收尾：断掉 ``eTheme.themeModeChanged`` 上的连接。

    **必须是普通函数，不能是绑定方法** —— PyQt6 不调用「绑定到发出信号的那个
    对象自己」的 ``destroyed`` 槽（见 AGENTS.md 与 ``assistant._cleanup_on_destroy``）。

    显式断的理由：这是**无父顶层窗**，进程退出期 ``deleteLater()`` 未必被派发，
    单例信号上残留的连接会在下一次切主题时打进已释放的 C++ 对象。
    """
    if is_deleted(dialog):
        return
    try:
        disconnect_theme(dialog)
    except Exception:  # noqa: BLE001 - 析构路径不允许异常逃逸
        pass


class _PreviewText(ColorText):
    """划词原文的单行预览（按**可用宽度**省略，完整内容进悬浮提示）。

    ``ColorText`` 本身不省略（它是 ``QLabel``，没有 elide 支持）。这里在
    ``resizeEvent`` 里用 ``QFontMetrics.elidedText`` 重算 —— 省略结果依赖字体
    度量，``windows`` 与 ``offscreen`` 两个平台算出来不一样，所以**测试不能钉
    省略位置**，只能钉「全文始终拿得到」（:meth:`fullText`）与「不换行」。
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setTextPixelSize(12)
        # 外部数据：ElaText 默认 AutoText 会把 `<b>x</b>` / `x<br>y` 真解析成
        # 富文本，必须显式按纯文本显示。
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._full_text = ""
        #: 归一化后（换行折成空格）的全文，``setFullText`` 时算一次即可
        self._flat = ""

    def setFullText(self, text: str) -> None:  # noqa: N802 (Qt 命名)
        """设置完整原文（内部按宽度省略显示）。"""
        self._full_text = text or ""
        # 归一化**只做一次**：``resizeEvent`` 会反复进 ``_refresh_elide``，
        # 每次都 split()/join() 一遍全文 = O(n) × resize 次数，拖一次窗口边
        # 就能把 CPU 吃掉。
        self._flat = " ".join(self._full_text.split())
        # 悬浮提示同样截断：ElaToolTip 要把整段排版并自绘绘制，几十万字会卡住；
        # 且**必须折行**（默认单行会把 400 字拉成几千像素宽的横条，屏幕外全看不见）
        tip = self._flat
        if len(tip) > _PREVIEW_TIP_MAX:
            tip = tip[:_PREVIEW_TIP_MAX] + "…"
        if tip:
            set_tooltip(
                self,
                tip,
                ElaToolTipPositionType.Top,
                maxWidth=_PREVIEW_TIP_WIDTH,
                wordWrap=True,
            )
        else:
            # 空原文必须**摘掉**上一轮的提示：同一个对话框复用（openFor 换一次
            # 划词）时，留着旧 tooltip 会让空白预览行弹出上一轮的原文。
            remove_tooltip(self)
        self._refresh_elide()

    def fullText(self) -> str:  # noqa: N802 (Qt 命名)
        """完整原文（不省略）—— 宿主要拿全文从这里取，不要从显示文本反推。"""
        return self._full_text

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        super().resizeEvent(event)
        self._refresh_elide()

    def _refresh_elide(self) -> None:
        # 省略的计算源也只取前若干字：省略到控件宽度（几百 px ≈ 几十个汉字）之后
        # 更后面的内容永远露不出来，让 elidedText 在几十万字上扫一遍纯属浪费。
        source = self._flat[:_PREVIEW_SOURCE_MAX]
        if len(self._flat) > _PREVIEW_SOURCE_MAX:
            source += "…"
        if not source:
            super().setText("")
            return
        width = max(0, self.width() - 2)
        # 宽度还没定下来时（首帧布局；``Ignored`` 策略下 0 宽也是合法状态）
        # **绝不能把全文塞进 QLabel** —— 一次性划词几百万字时首帧会直接卡住。
        # 这里先按源上限给一版保守值，等拿到真实宽度再收窄。
        if width <= 0:
            super().setText(source)
            return
        super().setText(
            self.fontMetrics().elidedText(source, Qt.TextElideMode.ElideRight, width)
        )


class ElaSelectionResultDialog(ElaWidget):
    """划词结果对话框：流式显示大模型返回内容（可独立复用）。

    典型用法::

        from pyqt6_ela_pro import ElaSelectionResultDialog

        dialog = ElaSelectionResultDialog()
        dialog.stopRequested.connect(backend.abort)        # ★ 必须接
        dialog.regenerateRequested.connect(lambda aid: run(aid))

        def on_action(actionId, text, pos):
            if actionId == "translate":
                dialog.openFor(actionId, "翻译", text, pos)
                run(actionId)

    :param parent: 父组件（一般留 ``None`` —— 这是独立浮动窗）
    """

    #: 回合正常落定（参数：动作 id、完整结果 Markdown 源）
    finished = pyqtSignal(str, str)
    #: 对话框关闭（参数：动作 id）
    closed = pyqtSignal(str)
    #: 请求中止后端（参数：动作 id）—— **宿主必须在这里 abort**
    stopRequested = pyqtSignal(str)
    #: 请求重新生成（参数：动作 id）
    regenerateRequested = pyqtSignal(str)
    #: 结果已写入剪贴板（参数：动作 id）
    copied = pyqtSignal(str)
    #: 结果的**纯文本**已写入剪贴板（去掉 Markdown 标记；参数：动作 id）
    plainCopied = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("划词结果")
        self.setAppBarHeight(_APP_BAR_HEIGHT)
        # 默认还带返回 / 前进 / 主题 / 最小化 / 最大化五个按钮，这里只留置顶 + 关闭。
        # PyQt6 绑定里没有 ``ButtonFlags`` 组合类型（只有单个 ``ButtonType``），
        # 组合必须逐位开：先清零，再逐位 ``setWindowButtonFlag``。
        self.setWindowButtonFlags(ElaAppBarType.ButtonType.NoneButtonHint)
        self.setWindowButtonFlag(ElaAppBarType.ButtonType.StayTopButtonHint, True)
        self.setWindowButtonFlag(ElaAppBarType.ButtonType.CloseButtonHint, True)
        self.setIsStayTop(True)
        # Qt.WindowType.Tool 让它不进任务栏、不进 Alt-Tab（Cherry 的 skipTaskbar）。
        # **必须在首次 show 之前设**：ElaAppBar 的 eventFilter 在 ``QEvent::Show``
        # 分支里给 HWND 打 ``WS_THICKFRAME``（Win7 再加 ``CS_DROPSHADOW``），
        # show 之后再改 window flags 会重建 HWND，那些样式要等下一次 show 才补。
        self.setWindowFlag(Qt.WindowType.Tool, True)
        self.setMinimumSize(_MIN_SIZE)
        self.resize(_DEFAULT_SIZE)

        self._action_id = ""
        self._icon_name = None
        self._selected_text = ""
        self._result_text = ""
        self._turn_id = 0
        self._streaming = False
        self._settled = False
        #: 本回合是否动过手（beginStream / setResult / setError 任一发生过）——
        #: 「重新生成」的可用判据，见 _sync_controls
        self._turn_started = False
        self._error = ""
        self._anchor: Optional[QPoint] = None
        #: 用户可见期间调过的窗口尺寸（下次 openFor 沿用；不含工作区夹取的结果）
        self._preferred_size = QSize(_DEFAULT_SIZE)
        #: 定位过程中为 True —— 此时的 resize 是程序夹取，不是用户意图
        self._placing = False
        #: ``WS_THICKFRAME`` 撑高（宽度不变、高度 +31）的判定材料：
        #: ``_wm_grow_pending`` 是「可能还有一次撑高没落地」，
        #: ``_wm_grow_request`` 是 ``_place`` 请求的尺寸（按形状识别撑高），
        #: ``_user_resizing`` 记录用户是否亲手拖过边框（拖过就一定是用户意图）。
        self._wm_grow_pending = False
        self._wm_grow_request: Optional[QSize] = None
        self._user_resizing = False

        self._build_ui()
        self._sync_controls()
        connect_theme_signal(self)
        self.destroyed.connect(functools.partial(_cleanup_on_destroy, self))
        self._apply_theme(currentMode())

    # ── UI ─────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        # ElaWidget 的**窗口内容边距**被 ElaAppBar 设成 (0, appBarHeight, 0, 0)，
        # 正文自动落在标题栏之下。所以外层布局一个像素的边距都不许动 ——
        # QLayout.setContentsMargins 会写回 QWidget.setContentsMargins，一调就把
        # appBar 让出的顶部空间清掉、正文压到标题栏上。卡内边距因此走内嵌容器。
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        body = QWidget(self)
        inner = QVBoxLayout(body)
        inner.setContentsMargins(_PAD, _PAD, _PAD, _PAD)
        inner.setSpacing(8)
        outer.addWidget(body)

        # 状态行：忙碌指示 + 阶段文案
        status = QHBoxLayout()
        status.setContentsMargins(0, 0, 0, 0)
        status.setSpacing(6)
        self._ring = ElaProgressRing(body)
        self._ring.setFixedSize(_RING_SIZE, _RING_SIZE)
        status.addWidget(self._ring)
        self._status_text = ColorText(_TEXT_PREPARING, body)
        self._status_text.setTextPixelSize(12)
        status.addWidget(self._status_text)
        status.addStretch(1)
        inner.addLayout(status)

        # 划词原文：抢焦点后源应用选区高亮没了，这一行是唯一的上下文
        self._preview_text = _PreviewText(body)
        inner.addWidget(self._preview_text)

        # 正文：Markdown 渲染 + 流式追加（贴底自动跟随、用户上滚后保持阅读位置）
        self._viewer = ElaMarkdownViewer(body)
        self._viewer.setStickToBottom(True)
        self._viewer.setBorderRadius(6)
        inner.addWidget(self._viewer, 1)

        # 错误行：仅 setError 后可见
        self._error_row = QWidget(body)
        error_layout = QHBoxLayout(self._error_row)
        error_layout.setContentsMargins(0, 0, 0, 0)
        error_layout.setSpacing(6)
        self._error_text = ColorText("", self._error_row)
        self._error_text.setTextPixelSize(12)
        self._error_text.setTextFormat(Qt.TextFormat.PlainText)
        error_layout.addWidget(self._error_text, 1)
        self._error_row.setVisible(False)
        inner.addWidget(self._error_row)

        # 页脚：流式中只有「停止」，空闲时是「重新生成 / 复制 / 关闭」
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(8)
        footer.addStretch(1)
        self._regen_button = ElaButton(
            "重新生成",
            icon=ElaIconType.IconName.RotateRight,
            variant="text",
            size="small",
            parent=body,
        )
        self._regen_button.clicked.connect(self._on_regenerate)
        footer.addWidget(self._regen_button)
        self._copy_button = ElaButton(
            "复制 Markdown",
            icon=ElaIconType.IconName.Copy,
            variant="text",
            size="small",
            parent=body,
        )
        self._copy_button.clicked.connect(self._on_copy)
        footer.addWidget(self._copy_button)
        # 纯文本复制：渲染后的文本（去掉 Markdown 标记），与「复制」的原始源并列
        self._plain_copy_button = ElaButton(
            "复制纯文本",
            icon=ElaIconType.IconName.FileLines,
            variant="text",
            size="small",
            parent=body,
        )
        self._plain_copy_button.clicked.connect(self.copyPlainText)
        footer.addWidget(self._plain_copy_button)
        self._close_button = ElaButton(
            "关闭",
            icon=ElaIconType.IconName.Xmark,
            variant="text",
            size="small",
            parent=body,
        )
        self._close_button.clicked.connect(self.closeDialog)
        footer.addWidget(self._close_button)
        self._stop_button = ElaButton(
            "停止",
            icon=ElaIconType.IconName.Stop,
            variant="solid",
            size="small",
            parent=body,
        )
        self._stop_button.clicked.connect(self._on_stop_clicked)
        footer.addWidget(self._stop_button)
        inner.addLayout(footer)

        # 只用库内 ElaToolTip（不设 setToolTip，避免任何原生提示框）
        set_tooltip(self._stop_button, "停止生成（Esc）", ElaToolTipPositionType.Top)
        set_tooltip(
            self._copy_button,
            "复制 Markdown 源（Ctrl+Shift+C）",
            ElaToolTipPositionType.Top,
        )
        set_tooltip(
            self._plain_copy_button,
            "复制纯文本（去掉 Markdown 标记，Ctrl+C）",
            ElaToolTipPositionType.Top,
        )
        set_tooltip(self._regen_button, "用同样的输入重新生成", ElaToolTipPositionType.Top)

        # 标题栏的 ✕ **不用**接：上游 ``IsDefaultClosed`` 默认 true，点它就是
        # ``window()->close()``（ElaAppBarPrivate.cpp:52-56），会正常走到
        # ``closeEvent`` —— 与 Esc、页脚「关闭」共用同一个收尾入口。
        # 只有把 ``setIsDefaultClosed(False)`` 时上游才改发 ``closeButtonClicked``。

    # ── 公开 API：打开与回合 ──────────────────────────────────────

    def openFor(
        self,
        actionId: str,
        title: str,
        selectedText: str,
        anchor: Optional[QPoint] = None,
        icon=None,
    ) -> int:
        """为一次划词动作打开对话框，返回本次回合的 turn token。

        **上一回合若仍在流式，会先中止它**（发 :attr:`stopRequested` 带上旧动作
        id）—— 一次只处理一个回合，否则迟到分片会串进新动作。

        :param actionId: 动作 id（原样回传给各信号，供宿主区分行为）
        :param title: 标题栏文字（通常是动作名，如「翻译」）
        :param selectedText: 划词原文，显示在正文上方的预览行
        :param anchor: 落点全局逻辑坐标（与 ``actionTriggered`` 的 pos 同源），
            传了才重新定位。**``None`` 表示复用当前位置** —— 「重新生成」是同一次
            划词的重跑，用户多半已经把窗口挪到顺手的位置了，再用锚点重算一遍
            等于把窗子从他眼前抽走。纯重跑其实更该直接调 :meth:`beginStream`
            （连标题与原文都不用重设），``anchor=None`` 是给想复用 ``openFor``
            整条链路的宿主留的出口
        :param icon: 标题栏图标（``ElaIconType.IconName``；``None`` 则不显示）
        :returns: 本回合的 turn token，传给 :meth:`appendMarkdown` /
            :meth:`endStream` 可彻底挡掉迟到分片
        """
        if self._streaming:
            self._endTurn("replaced")
        self._turn_id += 1
        self._action_id = str(actionId or "")
        self._icon_name = icon
        self._selected_text = selectedText or ""
        self._result_text = ""
        self._streaming = False
        self._settled = False
        self._turn_started = False
        self._error = ""
        self.setWindowTitle(str(title or "划词结果"))
        self.setWindowIcon(self._title_icon())
        self._viewer.clear()
        self._preview_text.setFullText(self._selected_text)
        self._error_text.setText("")
        self._error_row.setVisible(False)
        self._sync_controls()
        # **先 show 再定位**：上游 ElaAppBar 在 QEvent::Show 里给 HWND 补
        # WS_THICKFRAME，Qt 会因此把窗口**首次**撑高约 31px（实测与 app bar
        # 高度无关，offscreen 无窗口管理器则不涨）。show 之前算好的位置会因此
        # 差出这 31px，锚点贴屏幕下沿时整块溢出屏幕外。
        was_visible = self.isVisible()
        self.show()
        if anchor is not None:
            self._anchor = QPoint(anchor)
            self._place()
        elif not was_visible:
            # 没给锚点且本来是关着的：总得给个位置，用上次锚点 / 屏幕中心兜底
            self._place()
        # 已经在可见状态且没给锚点 → 一个像素都不动（重新生成不该挪窗子）
        self.raise_()
        self.activateWindow()
        return self._turn_id

    def beginStream(self) -> int:
        """开始流式回合（清空正文并显示忙碌指示），返回 turn token。"""
        self._turn_id += 1
        self._streaming = True
        self._settled = False
        self._turn_started = True
        self._result_text = ""
        self._error = ""
        self._error_text.setText("")
        self._error_row.setVisible(False)
        self._viewer.beginStream()
        self._sync_controls()
        return self._turn_id

    def appendMarkdown(self, chunk: str, turn: Optional[int] = None) -> None:
        """流式追加一段 Markdown。

        :param chunk: Markdown 片段
        :param turn: :meth:`beginStream` 返回的 token。**省略时用当前回合** ——
            宿主若可能先后推多个回合（被中止的回合还有几片在途），必须传，否则
            迟到分片会落进新一轮。token 不匹配时**静默丢弃**。
        """
        if turn is not None and int(turn) != self._turn_id:
            return
        if not self._streaming:
            return
        self._result_text += chunk
        self._viewer.appendMarkdown(chunk)

    def endStream(self, turn: Optional[int] = None) -> None:
        """结束流式回合并落定结果（发 :attr:`finished`）。

        不发 :attr:`stopRequested` —— 这是正常完成，不是中止。
        """
        if turn is not None and int(turn) != self._turn_id:
            return
        if not self._streaming:
            return
        self._streaming = False
        self._settled = True
        self._viewer.endStream()
        self._sync_controls()
        self.finished.emit(self._action_id, self._result_text)

    def setResult(self, text: str) -> None:
        """一次性设置完整结果（非流式，等价于 begin + append + end）。"""
        self._turn_id += 1
        self._streaming = False
        self._settled = True
        self._turn_started = True
        self._result_text = str(text or "")
        self._error = ""
        self._error_text.setText("")
        self._error_row.setVisible(False)
        self._viewer.setMarkdown(self._result_text)
        self._sync_controls()
        self.finished.emit(self._action_id, self._result_text)

    def setError(self, message: str) -> None:
        """显示错误并结束回合（复制保持禁用 —— 没有可用结果）。

        **必须冲掉查看器的流式态**（判据是「本回合是否流式过」，与
        :meth:`_endTurn` 一致）：流式中途出错时，``ElaMarkdownViewer`` 还在
        流式缓冲里、流式光标还在闪，用户看到的是「已经报错了，正文却还在
        打字」，而且那半截内容要等下一次 flush 才落屏。
        """
        wasStreaming = self._streaming or self._viewer.isStreaming()
        self._streaming = False
        self._settled = False
        self._turn_started = True
        self._error = str(message or "")
        self._error_text.setText(self._error)
        self._error_row.setVisible(bool(self._error))
        if wasStreaming and self._aliveViewer():
            # 只做「停缓冲 + 全量重渲染」，不碰 ``_settled`` 与 ``finished``：
            # 半句话仍然不算结果（正文可见 ≠ 可复制）。
            self._viewer.endStream()
        self._sync_controls()

    def _aliveViewer(self) -> bool:  # noqa: N802 (与 Qt 命名一致)
        """查看器包装器还活着（宿主可能在回合中途销毁整个对话框）。"""
        try:
            return not is_deleted(self._viewer)
        except (RuntimeError, TypeError):
            return False

    def clearError(self) -> None:
        """清除错误行。"""
        self._error = ""
        self._error_text.setText("")
        self._error_row.setVisible(False)

    def errorText(self) -> str:
        """当前错误文案（无错误时为空串）。"""
        return self._error

    def isStreaming(self) -> bool:
        """当前回合是否仍在流式。"""
        return self._streaming

    def hasResult(self) -> bool:
        """是否有一份**已落定**的结果（可复制 / 可重新生成）。"""
        return self._settled and bool(self._result_text.strip())

    def resultText(self) -> str:
        """当前结果的 Markdown 源（被中止时是已收到的部分，且 ``hasResult()`` 为假）。"""
        return self._result_text

    def copyPlainText(self) -> None:  # noqa: N802 (Qt 命名)
        """复制**纯文本结果**（渲染后的文本，去掉 Markdown 标记）。

        **这是默认复制**：``Ctrl+C`` 与页脚「复制纯文本」都走这里；要原始
        Markdown 源用 :meth:`_on_copy`（页脚「复制 Markdown」/ ``Ctrl+Shift+C``，
        发 :attr:`copied`）。没有落定结果时不做任何事（半句话不复制）。
        """
        if not self.hasResult():
            return
        clipboard = QApplication.clipboard()
        if clipboard is None:
            return
        clipboard.setText(self._viewer.toPlainText())
        self.plainCopied.emit(self._action_id)

    def actionId(self) -> str:  # noqa: N802 (Qt 命名)
        """当前动作 id（由 :meth:`openFor` 设置）。"""
        return self._action_id

    def selectedText(self) -> str:
        """本次划词的原文。"""
        return self._selected_text

    def currentTurn(self) -> int:  # noqa: N802 (Qt 命名)
        """当前 turn token。"""
        return self._turn_id

    def closeDialog(self) -> None:
        """关闭对话框（仍在流式会先发 :attr:`stopRequested`）。"""
        self.close()

    # ── 事件 ────────────────────────────────────────────────────

    def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        """Esc 分流：流式中=停止（留在窗口里），空闲时=关闭。

        ``Ctrl+C`` = **纯文本**（默认，与「复制纯文本」按钮同源）；
        ``Ctrl+Shift+C`` = Markdown 源（「复制 Markdown」按钮的快捷键）。
        """
        key = event.key()
        ctrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        if key == Qt.Key.Key_Escape:
            if self._streaming:
                self._on_stop_clicked()
            else:
                self.closeDialog()
            event.accept()
            return
        if key == Qt.Key.Key_C and ctrl:
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                if self._copy_button.isEnabled():
                    self._on_copy()
            elif self._plain_copy_button.isEnabled():
                self.copyPlainText()
            event.accept()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        """关窗即中止。

        Cherry Studio 没有任何 unload / abort 处理，关窗只是销毁 renderer
        进程顺带把 fetch 带走（``SelectionService.ts`` 全文无 abort）；Qt 里宿主的
        后端线程照跑，所以这里必须显式发 :attr:`stopRequested`，否则就是
        「面板关掉了但模型还在烧 token」。标题栏 ✕ / Esc / 页脚「关闭」/ 程序化
        ``close()`` 全部汇到这里，是唯一的收尾路径。
        """
        self._endTurn("closed")
        super().closeEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        super().resizeEvent(event)
        # 记住用户在**可见期间**手动调过的尺寸，下次 openFor 沿用。三个排除项：
        # 定位过程中的程序夹取（``_placing``）、隐藏时的 resize（构造与首帧布局
        # 阶段都会发）、以及上游补 ``WS_THICKFRAME`` 撑高那一次（见下）。
        if self._placing or not self.isVisible():
            return
        if self._wm_grow_pending:
            # 上游在 ``QEvent::Show`` 里补的 ``WS_THICKFRAME`` 会把窗口**撑高
            # 约 31px**，而这一次 resize **投递时机不确定**：有时同步落在
            # ``_place()`` 内（被 ``_placing`` 盖住），有时被 Qt 排进事件队列、
            # 在 ``_placing`` 复位之后才到（实测两种都发生过），有时**干脆不来**。
            # 所以不能无条件把「下一次可见期 resize」当撑高（那会吞掉用户打开后
            # 第一次调尺寸），按形状 + 用户是否拖过边框判定：
            #   撑高 = 宽度与 ``_place`` 请求值相同、高度多出 1~_WM_GROW_MAX_PX、
            #   且用户没亲手拖过边框（拖过 = ``NonClientAreaMouseButtonPress``）。
            requested = self._wm_grow_request
            self._wm_grow_pending = False
            self._wm_grow_request = None
            if (
                not self._user_resizing
                and requested is not None
                and self.width() == requested.width()
                and 0 < self.height() - requested.height() <= _WM_GROW_MAX_PX
            ):
                return
        self._preferred_size = QSize(self.size())

    def event(self, event) -> bool:  # noqa: N802 (Qt 命名)
        """记录用户是否亲手拖过窗口边框。

        拖边框是**非客户区**按下（``NonClientAreaMouseButtonPress``）；据此把
        随后的 resize 与上游补 ``WS_THICKFRAME`` 的撑高区分开（见 ``resizeEvent``）。
        """
        if event.type() == QEvent.Type.NonClientAreaMouseButtonPress:
            self._user_resizing = True
        return super().event(event)

    # ── 内部：回合收尾 ────────────────────────────────────────────

    def _endTurn(self, reason: str) -> None:
        """所有结束路径的唯一入口。

        ``reason``：

        - ``"stopped"`` —— 用户中止（停止按钮 / 流式中 Esc / 关窗）：**留在窗口
          里**，半截内容保留但不算结果（复制保持禁用）；
        - ``"closed"`` —— 关闭窗口；
        - ``"replaced"`` —— 新的 :meth:`openFor` 顶掉了本回合。
        """
        was_streaming = self._streaming
        self._streaming = False
        if was_streaming:
            self.stopRequested.emit(self._action_id)
        if was_streaming:
            # **必须冲掉查看器的流式缓冲**，否则用户看到的是空盒子 / 半截旧文：
            # ElaMarkdownViewer 把分片攒在 QTimer 里按节流提交，用户在定时器
            # 触发前点「停止」或直接关窗，缓冲里那半截就永远没进文档（截图实测：
            # 状态行写着「已停止」而正文全白）。判据是 ``was_streaming`` 而不是
            # ``reason == "stopped"`` —— 关窗走的是 ``reason == "closed"``，
            # 只判 stopped 会漏掉「生成中直接关窗」这条最常见的路径。
            #
            # 调的是**查看器**的 ``endStream``：它只做「停缓冲 + 全量重渲染 +
            # 发 ``streamFinished``」，不碰本组件的 ``_settled`` 与 ``finished``，
            # 所以「半句话不算结果」的契约不受影响（正文可见 ≠ 可复制）。
            self._viewer.endStream()
        if reason in ("stopped", "replaced"):
            self._settled = False
        self._sync_controls()
        if reason == "closed":
            self.closed.emit(self._action_id)

    def _on_stop_clicked(self) -> None:
        if not self._streaming:
            return
        self._endTurn("stopped")

    def _on_regenerate(self) -> None:
        if not self._regen_button.isEnabled():
            return
        self.regenerateRequested.emit(self._action_id)

    def _on_copy(self) -> None:
        # 复制只在**已落定**时可用 —— 复制半句话是错的（Cherry 也只在 onFinish
        # 里填 contentToCopy，从不给半截）。
        if not self.hasResult():
            return
        clipboard = QApplication.clipboard()
        if clipboard is None:
            return
        clipboard.setText(self._result_text)
        self.copied.emit(self._action_id)

    # ── 内部：控件状态 ────────────────────────────────────────────

    def _sync_controls(self) -> None:
        """按当前状态刷新忙碌指示 / 状态行 / 页脚按钮。"""
        streaming = self._streaming
        self._ring.setIsBusying(streaming)
        self._ring.setVisible(streaming)

        has_text = bool(self._result_text.strip())
        if streaming:
            status = _TEXT_STREAMING
        elif self._error:
            status = _TEXT_FAILED
        elif has_text and not self._settled:
            status = _TEXT_STOPPED  # 有内容但没落定 = 被中止了
        elif has_text:
            status = ""  # 已落定，状态行无事可说
        else:
            status = _TEXT_PREPARING
        self._status_text.setText(status)
        self._status_text.setVisible(bool(status))

        self._stop_button.setVisible(streaming)
        for button in (
            self._regen_button,
            self._copy_button,
            self._plain_copy_button,
            self._close_button,
        ):
            button.setVisible(not streaming)
        self._copy_button.setEnabled(self.hasResult())
        self._plain_copy_button.setEnabled(self.hasResult())
        # 「重新生成」只要**这个回合动过手**就可用 —— 判据刻意不是 `_settled`：
        # 出错与被中止之后用户最想干的就是重试，把按钮留着灰的等于把重试入口
        # 藏起来了（截图实测：报错页与停止页上「重新生成」都是灰的）。
        # `openFor` 之后仍然禁用：那时宿主还没发过请求，没有「重来」可言。
        self._regen_button.setEnabled(
            not streaming and self._turn_started and bool(self._action_id)
        )

    # ── 内部：图标 ────────────────────────────────────────────────

    def _title_icon(self) -> QIcon:
        """标题栏图标：当前主题正文色上色的动作图标。

        ``ElaAppBar`` 在 ``windowIcon().isNull()`` 时整块隐藏图标位，所以无图标
        直接给空 ``QIcon`` 即可，不需要额外开关。没调 ``eApp.init()`` 时
        ``getElaIcon`` 返回的是全透明 pixmap（图标「画不出来」），那是宿主的
        责任，不该让开窗失败。
        """
        if self._icon_name is None:
            return QIcon()
        try:
            return ElaIcon.getInstance().getElaIcon(
                self._icon_name, textMuted(currentMode())
            )
        except Exception:  # noqa: BLE001 - 图标不可用不该炸掉整个对话框
            return QIcon()

    # ── 内部：定位 ────────────────────────────────────────────────

    def _place(self) -> None:
        """落到锚点附近：水平居中于落点、默认在下方，下方放不下翻到上方。

        必须在 :meth:`show` **之后**调用（见 :meth:`openFor` 的说明：上游补
        ``WS_THICKFRAME`` 会让窗口首次撑高约 31px）。

        最后水平 / 垂直夹回 ``availableGeometry()``（排除任务栏）—— 与
        :meth:`ElaSelectionPopup.popupAt` / :meth:`ElaToolTip.showAt` 同一套规则。

        **夹取按画框（``frameGeometry``）而不是客户区**：上游在首次 ``show``
        时补的 ``WS_THICKFRAME`` 让**不可见拖拽边框**比客户区高 32px / 宽 2px
        （实测）。按 ``self.width()/height()`` 算，锚点贴工作区右下角时画框底部
        溢出 42px 到屏幕外。

        而且那圈边距**不是常数**：实测同一个窗口先测得 top=31，移动后又变成 0
        （无边框窗 + THICKFRAME 的 DWM 报告随状态变），所以**不能用「客户区 +
        固定常量」推算**。做法是「先按客户区算 → move → 量真实画框 → 按溢出量
        纠正一次」：平移是线性的，一次纠正即到位。
        """
        area = self._work_area()
        width = max(
            _MIN_SIZE.width(),
            min(self._preferred_size.width(), area.width() - 2 * _EDGE_GAP),
        )
        height = max(
            _MIN_SIZE.height(),
            min(self._preferred_size.height(), area.height() - 2 * _EDGE_GAP),
        )
        # **整个「按工作区夹取 + 摆位」过程都是程序行为**，`_placing` 必须
        # 覆盖到 move 之后：THICKFRAME 的纠正步会再发一次 resize（见
        # ``_nudge_inside_work_area``），它同样不能被记成用户偏好。
        # （原先只在 ``resize()`` 前后置位，随后 ``move()`` 与纠正步都在保护
        # 之外，那两步触发的 resize 会把夹取结果写进偏好。）
        self._placing = True
        try:
            self.resize(width, height)
            # 以 resize 之后的**真实**尺寸摆位（布局的 minimumSizeHint 可能把
            # 请求值顶大，工作区又小的时候还会再收一次）
            width, height = self.width(), self.height()

            anchor = self._anchor if self._anchor is not None else area.center()
            x = anchor.x() - width // 2 + _PLACE_OFFSET.x()
            y = anchor.y() + _PLACE_OFFSET.y()
            if y + height > area.bottom() + 1:
                y = anchor.y() - height - _PLACE_OFFSET.y()
            x = max(
                area.left() + _EDGE_GAP, min(x, area.right() - width - _EDGE_GAP + 1)
            )
            y = max(area.top(), min(y, area.bottom() - height + 1))
            self.move(int(x), int(y))
            # 纠正画框溢出：THICKFRAME 的那圈不可见边框不体现在 size() 里，
            # 但它才是屏幕上真正占的矩形（见上方 docstring 的实测数据）
            self._nudge_inside_work_area(area)
            # 记账：拿到**正好**是请求的尺寸，说明上游补的 WS_THICKFRAME 撑高
            # 还在事件队列里没落地 —— 那一次 resize 不是用户意图，别记进偏好
            # （见 resizeEvent）。反之尺寸已经被撑过了（或布局顶大了），就说明
            # 撑高同步发生过了 / 本平台没有窗口管理器，此后可见期的每次 resize
            # 都该按用户意图处理。
            #
            # 只记布尔不够：撑高**可能永远不来**（投递时机不确定），若把「下一次
            # 可见期 resize」无条件当撑高，用户打开后第一次调尺寸就被吞掉。所以
            # 同时记下请求尺寸，由 ``resizeEvent`` 按形状 + 用户是否拖过边框判断
            # （实测撑高 = 宽度不变、高度 +31）。
            self._wm_grow_request = QSize(width, height)
            self._user_resizing = False
            self._wm_grow_pending = self.width() == width and self.height() == height
        finally:
            self._placing = False

    def _nudge_inside_work_area(self, area: QRect) -> None:
        """按真实 ``frameGeometry`` 把窗口纠正回工作区内（纯平移，幂等）。

        必须在 ``_placing`` 保护内调用（纠正也是程序行为，不是用户意图）。

        「一次纠正即到位」靠的是**平移的线性性**：``move()`` 对一个无边框 +
        ``WS_THICKFRAME`` 窗口作用在**画框**原点上（实测：``move(100,100)``
        之后 ``frameGeometry().topLeft()`` 恰为 (100,100)），所以按当前画框
        溢出量反向平移即精确落位。

        窗口比工作区还高时上下都溢出，无法同时满足 —— 此时对齐**顶部**而不是
        居中：多出来的部分落在屏幕外是没法避免的，但标题栏必须留在可视区里
        （居中会让标题栏直接被顶出屏幕）。
        """
        frame = self.frameGeometry()
        dx = dy = 0
        if frame.right() > area.right() - _EDGE_GAP:
            dx = area.right() - _EDGE_GAP - frame.right()
        elif frame.left() < area.left() + _EDGE_GAP:
            dx = area.left() + _EDGE_GAP - frame.left()
        if frame.height() >= area.height():
            # 比工作区还高：对齐顶部（见 docstring）
            dy = area.top() + _EDGE_GAP - frame.top()
        elif frame.bottom() > area.bottom() - _EDGE_GAP:
            dy = area.bottom() - _EDGE_GAP - frame.bottom()
        elif frame.top() < area.top() + _EDGE_GAP:
            dy = area.top() + _EDGE_GAP - frame.top()
        if dx or dy:
            self.move(self.x() + dx, self.y() + dy)

    def _work_area(self) -> QRect:
        screen = None
        if self._anchor is not None:
            screen = QApplication.screenAt(self._anchor)
        if screen is None:
            screen = QApplication.primaryScreen()
        if screen is None:
            return QRect(0, 0, 1920, 1080)
        return screen.availableGeometry()

    # ── 主题 ────────────────────────────────────────────────────

    def _apply_theme(self, mode) -> None:  # noqa: ANN001
        """重刷自绘颜色的子控件与标题栏图标。

        ``ColorText`` 的显式色是**快照**（``ElaText`` 在 C++ 里连着
        ``themeModeChanged`` 把 palette 刷回 BasicText），所以切主题必须重新
        ``setTextColor``。``ElaWidget`` 自己会 ``update()``，这里只管子控件。
        """
        self._status_text.setTextColor(textMuted(mode))
        self._preview_text.setTextColor(textMuted(mode))
        self._error_text.setTextColor(statusColor(mode, ElaStatusRoleType.Error))
        self.setWindowIcon(self._title_icon())

    def _onThemeChanged(self, mode) -> None:  # noqa: N802 (Qt 命名)
        self._apply_theme(mode)


__all__ = ["ElaSelectionResultDialog"]
