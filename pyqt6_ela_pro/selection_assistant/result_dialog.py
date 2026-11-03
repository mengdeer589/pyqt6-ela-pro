"""划词结果对话框：流式显示模型输出，支持复制 / 重新生成。

组件不碰网络，取消走 ``stopRequested``（宿主必须 abort 后端）；状态机与用法见
``docs/selection-assistant.md``。
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
#: app bar 高度（ElaWidget 默认 45）
_APP_BAR_HEIGHT = 32
#: 状态行忙碌指示的边长
_RING_SIZE = 16
#: 标题栏图标的物理边长
_TITLE_ICON_PX = 18
#: 原文预览参与省略计算的字符上限：省略到控件宽度后更远内容露不出来，
#: 只喂前 400 字让 ``elidedText`` 的拷贝与扫描保持常数级。
_PREVIEW_SOURCE_MAX = 400
#: 原文预览悬浮提示的字符上限。提示框要排版并自绘全文，太长既慢又不可读；
#: 完整原文由 :meth:`_PreviewText.fullText` 提供。
_PREVIEW_TIP_MAX = 400
#: 原文预览悬浮提示的最大宽度（折行，避免拉成远宽于屏幕的单行横条）
_PREVIEW_TIP_WIDTH = 480
#: ``WS_THICKFRAME`` 撑高的高度上限（像素）；上游通常 +31，留余量给不同 DPI，
#: 但远小于用户拖一次边框的幅度。
_WM_GROW_MAX_PX = 64

#: 状态行文案（落定且有正文时状态行整行隐藏）
_TEXT_PREPARING = "准备中…"
_TEXT_STREAMING = "生成中…"
_TEXT_STOPPED = "已停止"
_TEXT_FAILED = "生成失败"


def _cleanup_on_destroy(dialog, _object=None) -> None:  # noqa: ANN001
    """对话框析构时断开主题信号。
    必须是普通函数而非绑定方法；无父顶层窗在进程退出期不一定会派发
    ``deleteLater()``，残留连接会在下次切主题时打到已释放的 C++ 对象。
    """
    if is_deleted(dialog):
        return
    try:
        disconnect_theme(dialog)
    except Exception:  # noqa: BLE001 - 析构路径不允许异常逃逸
        pass


class _PreviewText(ColorText):
    """划词原文单行预览（按可用宽度省略，全文见 :meth:`fullText`）。

    省略位置依赖字体度量，测试只钉全文可取得与不换行。
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
        # Qt.WindowType.Tool：不进任务栏 / Alt-Tab。必须在首次 show 前设 ——
        # show 后改 flags 会重建 HWND，上游补的 ``WS_THICKFRAME`` / 阴影要等下次 show。
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
        #: ``WS_THICKFRAME`` 撑高的判定材料：``_wm_grow_pending`` 表示可能还有一次
        #: 撑高未落地，``_wm_grow_request`` 是 ``_place`` 请求的尺寸（按形状识别），
        #: ``_user_resizing`` 记录用户是否亲手拖过边框。
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
        # ElaWidget 的窗口内容边距由 ElaAppBar 设为 (0, appBarHeight, 0, 0)，
        # 正文自动落在标题栏下；外层布局不能动边距，否则顶部空间会被清掉。
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

        # 标题栏 ✕ 不用接：上游默认 ``IsDefaultClosed``，点它就是 ``window()->close()``，
        # 会正常走到 ``closeEvent``（与 Esc、页脚「关闭」同一入口）。

    # ── 公开 API：打开与回合 ──────────────────────────────────────

    def openFor(
        self,
        actionId: str,
        title: str,
        selectedText: str,
        anchor: Optional[QPoint] = None,
        icon=None,
    ) -> int:
        """为一次划词动作打开对话框，返回本回合的 turn token。

        上一回合仍在流式时先中止它，避免迟到分片串进新动作。

        :param actionId: 动作 id（原样回传给各信号）
        :param title: 标题栏文字（通常是动作名）
        :param selectedText: 划词原文，显示在正文上方
        :param anchor: 落点全局坐标；``None`` 表示复用当前位置
        :param icon: 标题栏图标（``None`` 不显示）
        :returns: 本回合 token，传给 :meth:`appendMarkdown` / :meth:`endStream` 挡迟到分片
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
        # 先 show 再定位：上游在 QEvent::Show 里补 WS_THICKFRAME，首次 show 会把
        # 窗口撑高约 31px；show 前算好的位置会差这 31px，锚点贴底时溢出屏幕。
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
        """显示错误并结束回合（复制保持禁用）。

        本回合流式过时必须冲掉查看器缓冲，否则错误行会与仍在闪的光标 / 半截正文并存。
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
        """复制纯文本结果（默认复制：``Ctrl+C`` 与页脚按钮）。

        没有落定结果时不复制（半句话不算结果）。
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
        """Esc：流式中停止，空闲时关闭；``Ctrl+C`` 复制纯文本，``Ctrl+Shift+C`` 复制 Markdown。"""
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
        """关窗即中止：显式发 ``stopRequested``，否则面板关了模型还在跑。"""
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
            # 上游补 WS_THICKFRAME 会把窗口撑高约 31px，投递时机不确定；按形状 +
            # 用户是否拖过边框判定，避免吞掉用户打开后的第一次调尺寸：
            # 撑高 = 宽度不变、高度多出 1~_WM_GROW_MAX_PX，且用户没拖过边框。
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
        """记录用户是否亲手拖过窗口边框（非客户区按下），用于区分撑高与用户 resize。"""
        if event.type() == QEvent.Type.NonClientAreaMouseButtonPress:
            self._user_resizing = True
        return super().event(event)

    # ── 内部：回合收尾 ────────────────────────────────────────────

    def _endTurn(self, reason: str) -> None:
        """所有结束路径的唯一入口。
        ``reason``：``stopped`` = 用户中止（保留半截内容但不算结果）；
        ``closed`` = 关窗；``replaced`` = 新 ``openFor`` 顶掉本回合。
        """
        was_streaming = self._streaming
        self._streaming = False
        if was_streaming:
            self.stopRequested.emit(self._action_id)
        if was_streaming:
            # 必须冲掉查看器的流式缓冲：分片攒在 QTimer 里，停止 / 关窗时半截
            # 内容还没进文档。判据用 was_streaming 而非 reason == "stopped"。
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
        # 复制只在已落定时可用：半句话不算结果。
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
        # 本回合动过手就允许重新生成（含出错 / 中止）；``openFor`` 后尚未发请求时不启用。
        self._regen_button.setEnabled(
            not streaming and self._turn_started and bool(self._action_id)
        )

    # ── 内部：图标 ────────────────────────────────────────────────

    def _title_icon(self) -> QIcon:
        """标题栏图标：当前主题正文色上色的动作图标。
        ``windowIcon()`` 为空时上游会隐藏图标位；没调 ``eApp.init()`` 时取到的是
        全透明 pixmap（宿主责任），不应让开窗失败。
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
        """落到锚点附近：水平居中、默认下方，放不下翻到上方，最后夹回工作区。
        必须在 :meth:`show` 之后调用（上游补 ``WS_THICKFRAME`` 会撑高约 31px）。
        夹取按 ``frameGeometry`` 而非客户区，且那圈不可见边框不是常数 —— 先按
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
        # 整个「夹取 + 摆位」过程都是程序行为，``_placing`` 必须覆盖到 move 之后：
        # THICKFRAME 的纠正步会再发一次 resize，不能记成用户偏好。
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
            # 但它才是屏幕上真正占的矩形（见上方 docstring）
            self._nudge_inside_work_area(area)
            # 拿到正好是请求尺寸，说明撑高还在事件队列里没落地；撑高也可能永远
            # 不来，所以同时记下请求尺寸，由 ``resizeEvent`` 按形状判断。
            self._wm_grow_request = QSize(width, height)
            self._user_resizing = False
            self._wm_grow_pending = self.width() == width and self.height() == height
        finally:
            self._placing = False

    def _nudge_inside_work_area(self, area: QRect) -> None:
        """按真实 ``frameGeometry`` 把窗口纠正回工作区内（纯平移，幂等）。
        必须在 ``_placing`` 保护内调用；``move()`` 作用于画框原点，按溢出量反向
        平移一次即可。窗口比工作区还高时对齐顶部，保证标题栏可见。
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
        """重刷子控件颜色与标题栏图标。

        ``ColorText`` 的显式色是快照，主题切换后必须重新 ``setTextColor``。
        """
        self._status_text.setTextColor(textMuted(mode))
        self._preview_text.setTextColor(textMuted(mode))
        self._error_text.setTextColor(statusColor(mode, ElaStatusRoleType.Error))
        self.setWindowIcon(self._title_icon())

    def _onThemeChanged(self, mode) -> None:  # noqa: N802 (Qt 命名)
        self._apply_theme(mode)


__all__ = ["ElaSelectionResultDialog"]
