"""剪贴板取词（``pyqt6_ela_pro.selection_assistant``）。

通过模拟 ``Ctrl+C`` + 剪贴板文本变化读取当前选区文本，全程异步（QTimer），
不阻塞 UI：

1. 延迟 ``captureDelayMs``（先让事件循环处理完挂起的剪贴板更新，同时等源
   应用处理完 mouse-up）；
2. 记录基准文本与基准剪贴板**是否含非文本格式**（**不写剪贴板**，避免污染 /
   丢失用户剪贴板——Qt/Windows 下写入空探针会导致后续写入丢失）；
3. 发送 Ctrl+C（**这一步真的向前台窗口注入按键**；闸门见
   :func:`~pyqt6_ela_pro.selection_assistant._native.send_copy`：修饰键按下
   或距上次注入过近时不注入，本步骤按「无选区」收尾），以 ``pollMs`` 轮询：
   文本非空且不同于基准 → 取词成功；
4. 超时（``clipboardTimeoutMs``）视为没有选区，剪贴板从未被改动；
5. 成功后按 ``restoreClipboard``（默认开启）延迟 ``restoreDelayMs`` 恢复
   基准文本（基准为空时 ``clear()``）。

**恢复的三道校验**（任一不过就跳过恢复并发 ``restoreSkipped``，原因见
``lastRestoreSkipReason()``）：

1. 文本与「我们放进去的那份」不同 → 用户在延时窗口里复制了别的内容；
2. 剪贴板**序列号**变了（哪怕文本相同 —— 用户又复制了一遍同样的内容）；
   序列号取不到时本道跳过，回退纯文本比较；
3. 基准剪贴板含**无法还原**的内容（图片 / 文件 / HTML / 表格）→ 宁可把
   注入进来的文本留着，也绝不 ``clear()`` 掉用户复制的东西。

信号：``captured(text)`` / ``failed()`` / ``restoreSkipped()``。
恢复只还原文本，非文本格式（图片等）不保留。若选中文本与用户原剪贴板内容
完全相同且序列号不可用，无法与「未复制」区分，将视为无选区（已知限制）。

命名规范与库内一致（``camelCase``）。
"""

from __future__ import annotations

import time
from typing import Optional

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtWidgets import QApplication

from ._native import clipboard_sequence_number, send_copy

#: 默认发送 Ctrl+C 前的等待（毫秒，等源应用处理完 mouse-up）
_DEFAULT_CAPTURE_DELAY_MS = 80
#: 默认剪贴板轮询间隔（毫秒）
_DEFAULT_POLL_MS = 10
#: 默认取词超时（毫秒）
_DEFAULT_TIMEOUT_MS = 250
#: 默认取词成功后恢复剪贴板的延迟（毫秒）
_DEFAULT_RESTORE_DELAY_MS = 120

#: 跳过恢复的原因常量（``lastRestoreSkipReason()`` 的返回值）
SKIP_USER_COPIED = "user-copied"
SKIP_CLIPBOARD_CHANGED = "clipboard-changed"
SKIP_NON_TEXT_BASELINE = "non-text-baseline"


def _has_non_text_format(clipboard) -> bool:
    """剪贴板里是否有**取词链路无法还原**的内容（图片 / 文件 / HTML / 表格）。

    取词只读 ``clipboard().text()``，恢复也只写回纯文本。基准里若本来是
    图片或文件列表，恢复就只能 ``clear()`` —— 用户复制的东西直接消失，
    Ctrl+V 什么都粘不出来（静默数据丢失）。提前识别，让恢复整条跳过。
    """
    try:
        mime = clipboard.mimeData()
    except Exception:  # noqa: BLE001 - 剪贴板不可用时按「无信息」处理
        return False
    if mime is None:
        return False
    for probe in ("hasImage", "hasUrls", "hasHtml", "hasTable"):
        try:
            if getattr(mime, probe)():
                return True
        except Exception:  # noqa: BLE001 - 单个探针失败不影响其余
            continue
    return False


class ElaClipboardCapture(QObject):
    """模拟 ``Ctrl+C`` 的异步取词器（不阻塞 UI，不预先改动剪贴板）。"""

    #: 取词成功（参数：选中文本）
    captured = pyqtSignal(str)
    #: 取词失败 / 无选区 / 注入被闸门拦下（未向前台发按键）
    failed = pyqtSignal()
    #: 剪贴板**未被还原** —— 用户改过剪贴板，或基准含无法还原的非文本内容
    #: （宿主可据此提示；具体原因见 :meth:`lastRestoreSkipReason`）
    restoreSkipped = pyqtSignal()

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._restore = True
        self._capture_delay_ms = _DEFAULT_CAPTURE_DELAY_MS
        self._poll_ms = _DEFAULT_POLL_MS
        self._timeout_ms = _DEFAULT_TIMEOUT_MS
        self._restore_delay_ms = _DEFAULT_RESTORE_DELAY_MS

        self._active = False
        self._need_restore = False
        self._old_text = ""
        # 取词链路放进剪贴板的那份内容；恢复时用它判断「有没有被用户改过」
        self._captured_text = ""
        # 基准剪贴板是否含无法还原的非文本内容（图片 / 文件 / HTML）
        self._baseline_non_text = False
        # 取词成功那一刻的剪贴板序列号；恢复时用它判「文本相同但用户又复制过」
        self._capture_seq = 0
        self._skip_reason = ""
        self._deadline = 0.0

        self._delay_timer = QTimer(self)
        self._delay_timer.setSingleShot(True)
        self._delay_timer.timeout.connect(self._on_send_copy)

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(self._poll_ms)
        self._poll_timer.timeout.connect(self._poll)

        self._restore_timer = QTimer(self)
        self._restore_timer.setSingleShot(True)
        self._restore_timer.timeout.connect(self._restore_clipboard)

    # -- 配置 --------------------------------------------------------------

    def setRestoreClipboard(self, on: bool) -> None:
        """设置取词成功后是否恢复原剪贴板（默认开启）。"""
        self._restore = bool(on)

    def restoreClipboard(self) -> bool:
        """取词成功后是否恢复原剪贴板。"""
        return self._restore

    def setCaptureDelayMs(self, ms: int) -> None:
        """设置发送 Ctrl+C 前的等待毫秒数。"""
        self._capture_delay_ms = max(0, int(ms))

    def captureDelayMs(self) -> int:
        """发送 Ctrl+C 前的等待毫秒数。"""
        return self._capture_delay_ms

    def setPollMs(self, ms: int) -> None:
        """设置剪贴板轮询间隔毫秒数。"""
        self._poll_ms = max(1, int(ms))
        self._poll_timer.setInterval(self._poll_ms)

    def pollMs(self) -> int:
        """剪贴板轮询间隔毫秒数。"""
        return self._poll_ms

    def setTimeoutMs(self, ms: int) -> None:
        """设置取词超时毫秒数。"""
        self._timeout_ms = max(1, int(ms))

    def timeoutMs(self) -> int:
        """取词超时毫秒数。"""
        return self._timeout_ms

    def setRestoreDelayMs(self, ms: int) -> None:
        """设置成功取词后恢复剪贴板的延迟毫秒数。"""
        self._restore_delay_ms = max(0, int(ms))

    def restoreDelayMs(self) -> int:
        """成功取词后恢复剪贴板的延迟毫秒数。"""
        return self._restore_delay_ms

    # -- 流程 --------------------------------------------------------------

    def isCapturing(self) -> bool:
        """是否正在取词。"""
        return self._active

    def capture(self) -> None:
        """开始一次异步取词（进行中重复调用会先取消上一次）。"""
        # 上一次取词可能已经排了「恢复原剪贴板」的延时定时器。若不先结算就
        # 重置 _old_text=""，那次定时器触发时 _restore_clipboard() 会走
        # clipboard.clear() 分支，把用户原有的剪贴板内容清掉且无法恢复。
        if self._need_restore:
            self._restore_timer.stop()
            self._restore_clipboard()
        if self._active:
            self.cancel()
        self._active = True
        self._old_text = ""
        self._captured_text = ""
        self._baseline_non_text = False
        self._capture_seq = 0
        self._skip_reason = ""
        self._deadline = time.monotonic() + self._timeout_ms / 1000.0
        self._delay_timer.start(self._capture_delay_ms)

    def cancel(self) -> None:
        """取消进行中的取词。

        剪贴板本身从未被改动（注入发生在 ``_on_send_copy``，而它只在
        ``_active`` 时执行），所以这里**不需要**恢复；但 ``_capture_seq`` /
        ``_skip_reason`` 要复位，否则会带着上一次的状态进入下一次取词。
        """
        if not self._active:
            return
        self._active = False
        self._delay_timer.stop()
        self._poll_timer.stop()
        self._restore_timer.stop()
        self._capture_seq = 0
        self._skip_reason = ""

    # -- 内部 --------------------------------------------------------------

    def _on_send_copy(self) -> None:
        if not self._active:
            return
        clipboard = QApplication.clipboard()
        self._old_text = clipboard.text()
        self._baseline_non_text = _has_non_text_format(clipboard)
        try:
            injected = send_copy()
        except Exception:
            self._finish("", ok=False)
            return
        if not injected:
            # 注入被 send_copy 的闸门拦下（修饰键按下 / 距上次注入过近）：
            # 剪贴板从头到尾没被碰过，按「无选区」收尾即可
            self._finish("", ok=False)
            return
        self._poll_timer.start()
        self._poll()

    def _poll(self) -> None:
        if not self._active:
            return
        text = QApplication.clipboard().text()
        if text and text != self._old_text:
            self._finish(text, ok=True)
        elif time.monotonic() >= self._deadline:
            self._finish("", ok=False)

    def _finish(self, text: str, ok: bool) -> None:
        self._active = False
        self._delay_timer.stop()
        self._poll_timer.stop()
        if ok and self._restore:
            self._need_restore = True
            # 记下「我们自己放进剪贴板的那份」，供恢复时判断有没有被用户改过
            self._captured_text = text
            # 记下这一刻的序列号：用户在恢复窗口里又复制了同样的文本时，
            # 只有序列号能区分（纯文本比较会认为「没人动过」）
            self._capture_seq = clipboard_sequence_number()
            self._restore_timer.start(self._restore_delay_ms)
        if ok:
            self.captured.emit(text)
        else:
            self.failed.emit()

    def _restore_clipboard(self) -> None:
        """把剪贴板还原成取词**之前**的内容（三道校验，见模块 docstring）。

        宁可**不还原**，也绝不能覆盖用户在这段延时窗口里复制的内容 ——
        静默丢数据比「剪贴板没还原」更糟。三道校验依次是：

        1. 文本与「我们放进去的那份」不同 → 用户复制了别的内容；
        2. 文本相同但剪贴板序列号变了 → 用户又复制了一遍**同样的**内容
           （序列号不可用时本道跳过，回退纯文本比较）；
        3. 基准剪贴板含无法还原的非文本内容（图片 / 文件 / HTML）。
        """
        if not self._need_restore:
            return
        self._need_restore = False
        clipboard = QApplication.clipboard()
        if clipboard.text() != self._captured_text:
            self._skip_restore(SKIP_USER_COPIED)
            return
        seq = clipboard_sequence_number()
        if seq and seq != self._capture_seq:
            # 序列号变了 = 有人在这段延时窗口里动过剪贴板。文本相同也
            # 不还原（用户可能又复制了一遍同样的内容）。
            # **注意不要拿 ``self._capture_seq`` 做真值门**：它是
            # ``_finish`` 里取的快照，而 ``_finish`` 之后测试 / 宿主还会
            # 再 ``setText`` 一次来模拟「剪贴板里是我们放的那份」—— 那一步
            # 本身就把序列号推进了，只判「两边都非 0」会把正常还原也拦掉。
            self._skip_restore(SKIP_CLIPBOARD_CHANGED)
            return
        if self._baseline_non_text:
            # 基准里有我们还原不了的东西：宁可把注入进来的文本留着，也
            # 不能 clear() 掉用户复制的内容（那会让 Ctrl+V 直接粘不出来）
            self._skip_restore(SKIP_NON_TEXT_BASELINE)
            return
        self._skip_reason = ""
        if self._old_text:
            clipboard.setText(self._old_text)
        else:
            clipboard.clear()

    def _skip_restore(self, reason: str) -> None:
        """跳过恢复并记录原因（原因常量见模块顶部）。"""
        self._skip_reason = reason
        self.restoreSkipped.emit()

    def lastRestoreSkipReason(self) -> str:
        """最近一次跳过恢复的原因；成功恢复或无跳过时为空串。

        取值 :data:`SKIP_USER_COPIED` / :data:`SKIP_CLIPBOARD_CHANGED` /
        :data:`SKIP_NON_TEXT_BASELINE`。给宿主做差异化提示用（例如
        「你复制的内容含图片，已保持现状」）。
        """
        return self._skip_reason


__all__ = [
    "ElaClipboardCapture",
    "SKIP_CLIPBOARD_CHANGED",
    "SKIP_NON_TEXT_BASELINE",
    "SKIP_USER_COPIED",
]
