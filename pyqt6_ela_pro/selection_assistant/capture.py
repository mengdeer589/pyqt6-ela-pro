"""剪贴板取词：模拟 Ctrl+C 并轮询剪贴板变化，全程异步。

取词只认文本（图片忽略）；恢复用注入前的完整 mime 快照。
不拦截键盘：用户自己的 Ctrl+C / Ctrl+V 不会被吞，恢复时若修饰键按下会跳过。
"""

from __future__ import annotations

import time
from typing import Optional

from PyQt6.QtCore import QMimeData, QObject, QTimer, pyqtSignal
from PyQt6.QtGui import QTextDocumentFragment
from PyQt6.QtWidgets import QApplication

from ._native import (
    _warn_once,
    any_modifier_down,
    clipboard_sequence_number,
    send_copy,
)

#: 默认发送 Ctrl+C 前的等待（毫秒，等源应用处理完 mouse-up）
_DEFAULT_CAPTURE_DELAY_MS = 80
#: 默认剪贴板轮询间隔（毫秒）
_DEFAULT_POLL_MS = 10
#: 默认取词超时（毫秒）
_DEFAULT_TIMEOUT_MS = 250
#: 默认取词成功后恢复剪贴板的延迟（毫秒）
_DEFAULT_RESTORE_DELAY_MS = 120
#: 检测到图片但还没有文本时额外等待的毫秒数（大图首次写入可能超过基础超时）
_IMAGE_TEXT_GRACE_MS = 600
#: 拿到文本后等序列号稳定的毫秒数（序列号可能晚于文本更新）
_SETTLE_MS = 30

#: 跳过恢复的原因常量（``lastRestoreSkipReason()`` 的返回值）
SKIP_USER_COPIED = "user-copied"
SKIP_CLIPBOARD_CHANGED = "clipboard-changed"
SKIP_NON_TEXT_BASELINE = "non-text-baseline"
SKIP_USER_ACTIVE = "user-active"

#: 图片占位符（``QTextDocumentFragment`` 把图片转成纯文本时用它）
_OBJECT_REPLACEMENT = "\ufffc"
#: 需要按图片读取的 mime 格式
_IMAGE_FORMATS = frozenset(
    {"application/x-qt-image", "image/png", "image/bmp", "image/jpeg", "image/webp"}
)


def _mime_has_non_text(mime) -> bool:
    """mime 里是否有文本之外的内容（图片 / 文件 / HTML / Markdown / OLE 等）。"""
    if mime is None:
        return False
    for probe in ("hasImage", "hasUrls", "hasHtml", "hasTable"):
        try:
            if getattr(mime, probe)():
                return True
        except Exception:  # noqa: BLE001 - 单个探针失败不影响其余
            continue
    try:
        # 任何 text/plain 之外的格式都按「有非文本」处理：宁可少还原，
        # 也不把 Word 的 OLE / RTF 等格式当成纯文本清掉
        return bool(set(mime.formats()) - {"text/plain"})
    except Exception:  # noqa: BLE001
        return False


def _has_non_text_format(clipboard) -> bool:
    """剪贴板里是否有**只靠文本无法还原**的内容。"""
    try:
        return _mime_has_non_text(clipboard.mimeData())
    except Exception:  # noqa: BLE001 - 剪贴板不可用时按「无信息」处理
        return False


def _mime_has_image(mime) -> bool:
    if mime is None:
        return False
    try:
        return bool(mime.hasImage())
    except Exception:  # noqa: BLE001
        return False


def _strip_object_replacement(text: str) -> str:
    return text.replace(_OBJECT_REPLACEMENT, "")


def _text_from_mime(mime) -> str:
    """从剪贴板 mime 取纯文本：plain → markdown → html；图片占位符剥掉。"""
    if mime is None:
        return ""
    try:
        text = mime.text() or ""
    except Exception:  # noqa: BLE001 - 剪贴板内容不可信
        text = ""
    text = _strip_object_replacement(text)
    if text.strip():
        return text

    try:
        markdown = mime.data("text/markdown")
    except Exception:  # noqa: BLE001
        markdown = None
    if markdown is not None:
        try:
            raw = bytes(markdown)
        except Exception:  # noqa: BLE001
            raw = b""
        if raw:
            try:
                text = QTextDocumentFragment.fromMarkdown(
                    raw.decode("utf-8", "replace")
                ).toPlainText()
            except Exception:  # noqa: BLE001
                text = ""
            text = _strip_object_replacement(text)
            if text.strip():
                return text

    try:
        html = mime.html() or ""
    except Exception:  # noqa: BLE001
        html = ""
    if html:
        try:
            text = QTextDocumentFragment.fromHtml(html).toPlainText()
        except Exception:  # noqa: BLE001
            text = ""
        text = _strip_object_replacement(text)
        if text.strip():
            return text
    return ""


def _clone_mime_data(source) -> Optional[QMimeData]:
    """深拷贝剪贴板 mime（文本 / HTML / 图片 / 文件 / 其他格式）。"""
    clone = QMimeData()
    if source is None:
        return clone
    try:
        formats = source.formats()
    except Exception:  # noqa: BLE001
        return None
    for fmt in formats:
        try:
            if fmt == "text/plain":
                text = source.text()
                if text:
                    clone.setText(text)
            elif fmt == "text/html":
                html = source.html()
                if html:
                    clone.setHtml(html)
            elif fmt == "text/uri-list":
                urls = source.urls()
                if urls:
                    clone.setUrls(urls)
            elif fmt in _IMAGE_FORMATS:
                image = source.imageData()
                if image is not None:
                    clone.setImageData(image)
            elif fmt.startswith('application/x-qt-windows-mime;value="'):
                # Word / Office 的 OLE、EMF 等内部格式原样写回可能失效，
                # 恢复时只保留文本 / HTML / 图片 / 文件这些通用格式
                continue
            else:
                data = source.data(fmt)
                if data is not None and bytes(data):
                    clone.setData(fmt, data)
        except Exception:  # noqa: BLE001 - 单个格式失败不影响其余
            continue
    return clone


def _clipboard_signature(clipboard) -> tuple:
    """剪贴板内容指纹：判断恢复窗口里用户是否又复制了别的东西。"""
    try:
        mime = clipboard.mimeData()
    except Exception:  # noqa: BLE001
        return ()
    if mime is None:
        return ()
    try:
        formats = tuple(sorted(mime.formats()))
    except Exception:  # noqa: BLE001
        formats = ()
    try:
        text = mime.text() or ""
    except Exception:  # noqa: BLE001
        text = ""
    try:
        html = mime.html() or ""
    except Exception:  # noqa: BLE001
        html = ""
    try:
        urls = tuple(url.toString() for url in mime.urls())
    except Exception:  # noqa: BLE001
        urls = ()
    image_key = 0
    try:
        image = mime.imageData()
        if image is not None and hasattr(image, "cacheKey"):
            image_key = int(image.cacheKey())
    except Exception:  # noqa: BLE001
        image_key = 0
    return (formats, text, html, urls, image_key)


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
        # 取词链路放进剪贴板的那份文本（已剥图片占位符）；发信号用
        self._captured_text = ""
        # 同一份的原始纯文本（含图片占位符）；恢复时用它判「剪贴板还是我们的」
        self._captured_raw_text: Optional[str] = None
        # 基准剪贴板是否含只靠文本无法还原的内容（克隆失败时的兜底）
        self._baseline_non_text = False
        # 注入前的完整剪贴板快照；能还原图片 / 文件 / HTML
        self._baseline_mime: Optional[QMimeData] = None
        self._baseline_seq = 0
        self._last_seen_seq = 0
        self._last_seen_text = ""
        self._saw_change = False
        self._image_grace_until = 0.0
        self._pending_text: Optional[str] = None
        self._pending_until = 0.0
        self._captured_signature: Optional[tuple] = None
        self._restore_from_failure = False
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

    def isCapturing(self) -> bool:
        """是否正在取词。"""
        return self._active

    def capture(self) -> None:
        """开始一次异步取词（进行中重复调用会先取消上一次）。"""
        # 上一次取词可能已排了恢复定时器；先结算，避免 _old_text 被重置后
        # 恢复走到 clear() 把用户剪贴板清掉。
        if self._need_restore:
            self._restore_timer.stop()
            self._restore_clipboard()
        if self._active:
            self.cancel()
        self._active = True
        self._old_text = ""
        self._captured_text = ""
        self._captured_raw_text = None
        self._baseline_non_text = False
        self._baseline_mime = None
        self._baseline_seq = 0
        self._last_seen_seq = 0
        self._last_seen_text = ""
        self._saw_change = False
        self._image_grace_until = 0.0
        self._pending_text = None
        self._pending_until = 0.0
        self._captured_signature = None
        self._restore_from_failure = False
        self._capture_seq = 0
        self._skip_reason = ""
        self._deadline = time.monotonic() + self._timeout_ms / 1000.0
        self._delay_timer.start(self._capture_delay_ms)

    def cancel(self) -> None:
        """取消进行中的取词。"""
        if not self._active:
            return
        self._active = False
        self._delay_timer.stop()
        self._poll_timer.stop()
        self._restore_timer.stop()
        self._capture_seq = 0
        self._skip_reason = ""
        self._baseline_mime = None
        self._saw_change = False
        self._image_grace_until = 0.0
        self._pending_text = None
        self._pending_until = 0.0
        self._captured_signature = None
        self._restore_from_failure = False
        self._captured_raw_text = None

    def _on_send_copy(self) -> None:
        if not self._active:
            return
        clipboard = QApplication.clipboard()
        self._old_text = clipboard.text()
        try:
            baseline_mime = clipboard.mimeData()
        except Exception:  # noqa: BLE001 - 剪贴板不可用时按空基准处理
            baseline_mime = None
        self._baseline_non_text = _mime_has_non_text(baseline_mime)
        self._baseline_mime = _clone_mime_data(baseline_mime)
        self._baseline_seq = clipboard_sequence_number()
        self._last_seen_seq = self._baseline_seq
        self._last_seen_text = self._old_text
        try:
            injected = send_copy()
        except Exception:  # noqa: BLE001 - 注入失败按无选区收尾
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
        try:
            clipboard = QApplication.clipboard()
            seq = clipboard_sequence_number()
            text_now = clipboard.text()
            # 序列号可能晚于 QClipboard.text() 更新，文本变化也要算一次
            changed = text_now != self._last_seen_text
            if seq and self._baseline_seq and seq != self._last_seen_seq:
                changed = True
            if changed:
                self._saw_change = True
                self._last_seen_text = text_now
                if seq:
                    self._last_seen_seq = seq
                try:
                    mime = clipboard.mimeData()
                except Exception:  # noqa: BLE001
                    mime = None
                text = _text_from_mime(mime)
                if text.strip():
                    # 文本与基准相同但序列号已变 = 用户重新复制了同样的内容；
                    # 序列号还没更新时先别把旧文本当成取词结果。
                    seq_changed = bool(
                        seq and self._baseline_seq and seq != self._baseline_seq
                    )
                    if text != self._old_text or seq_changed:
                        if text != self._pending_text:
                            self._pending_text = text
                            self._pending_until = (
                                time.monotonic() + _SETTLE_MS / 1000.0
                            )
                else:
                    self._pending_text = None
                if _mime_has_image(mime) and self._image_grace_until == 0.0:
                    self._image_grace_until = (
                        time.monotonic() + _IMAGE_TEXT_GRACE_MS / 1000.0
                    )
            if self._pending_text is not None:
                # 等序列号稳定后再结账，恢复快照才不会漏掉我们这次写入
                if time.monotonic() >= self._pending_until:
                    self._finish(self._pending_text, ok=True)
                return
            if time.monotonic() >= max(self._deadline, self._image_grace_until):
                self._finish("", ok=False)
        except Exception as exc:  # noqa: BLE001 - 定时器回调不得抛异常
            _warn_once("剪贴板取词轮询异常，已忽略：", exc)

    def _finish(self, text: str, ok: bool) -> None:
        self._active = False
        self._delay_timer.stop()
        self._poll_timer.stop()
        self._captured_text = text if ok else ""
        self._captured_raw_text = self._current_text()
        self._captured_signature = _clipboard_signature(QApplication.clipboard())
        if self._restore and (ok or self._saw_change):
            self._arm_restore(from_failure=not ok)
        if ok:
            self.captured.emit(text)
        else:
            self.failed.emit()

    @staticmethod
    def _current_text() -> str:
        try:
            return QApplication.clipboard().text()
        except Exception:  # noqa: BLE001
            return ""

    def _arm_restore(self, from_failure: bool = False) -> None:
        # 没有完整快照且基准含非文本内容：只还原文本会把它清掉，宁可跳过
        if self._baseline_mime is None and self._baseline_non_text:
            self._skip_restore(SKIP_NON_TEXT_BASELINE)
            return
        self._need_restore = True
        self._restore_from_failure = bool(from_failure)
        self._capture_seq = clipboard_sequence_number()
        self._restore_timer.start(self._restore_delay_ms)

    def _restore_clipboard(self) -> None:
        """把剪贴板还原成取词前的内容；用户改过剪贴板时宁可跳过。"""
        if not self._need_restore:
            return
        self._need_restore = False
        if any_modifier_down():
            # 用户正按着 Ctrl / Shift / Alt（很可能在 Ctrl+C / Ctrl+V）：
            # 不要在键盘操作中途改剪贴板
            self._skip_restore(SKIP_USER_ACTIVE)
            return
        baseline = self._baseline_mime
        self._baseline_mime = None
        clipboard = QApplication.clipboard()
        if self._captured_signature is not None and _clipboard_signature(
            clipboard
        ) != self._captured_signature:
            self._skip_restore(SKIP_USER_COPIED)
            return
        expected = (
            self._captured_text
            if self._captured_raw_text is None
            else self._captured_raw_text
        )
        if clipboard.text() != expected:
            self._skip_restore(SKIP_USER_COPIED)
            return
        if not self._restore_from_failure:
            seq = clipboard_sequence_number()
            if seq and seq != self._capture_seq:
                # 序列号变了 = 延时窗口内剪贴板被动过，文本相同也不还原。
                # 不要拿 _capture_seq 做真值门：它是 _finish 里的快照，
                # 之后宿主再 setText 也会推进序列号，会拦掉正常还原。
                self._skip_restore(SKIP_CLIPBOARD_CHANGED)
                return
        if baseline is not None:
            try:
                formats = set(baseline.formats())
            except Exception:  # noqa: BLE001
                formats = set()
            if formats - {"text/plain"}:
                clone = _clone_mime_data(baseline)
                if clone is not None and clone.formats():
                    try:
                        clipboard.setMimeData(clone)
                    except Exception as exc:  # noqa: BLE001 - 恢复失败不得抛
                        _warn_once("恢复剪贴板失败，已跳过：", exc)
                        return
                    self._skip_reason = ""
                    return
        if self._baseline_non_text and not self._old_text:
            # 快照里没有可安全还原的内容，且基准没有文本：留着注入的内容
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
        :data:`SKIP_NON_TEXT_BASELINE` / :data:`SKIP_USER_ACTIVE`。
        """
        return self._skip_reason


__all__ = [
    "ElaClipboardCapture",
    "SKIP_CLIPBOARD_CHANGED",
    "SKIP_NON_TEXT_BASELINE",
    "SKIP_USER_ACTIVE",
    "SKIP_USER_COPIED",
]
