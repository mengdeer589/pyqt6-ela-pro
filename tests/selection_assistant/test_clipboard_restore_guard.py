"""B4：剪贴板取词链路与 SVG 缓存的两条契约。

1. **剪贴板恢复不得覆盖用户在延时窗口里新复制的内容**。原先
   ``_restore_clipboard`` 无条件把 ``_old_text`` 写回去，于是「取词后切到
   资源管理器按 Ctrl+C」那一次复制**被静默丢弃** —— 用户按 Ctrl+V 拿到的是
   几百毫秒前的旧内容。这种数据丢失比「剪贴板没还原」更糟。
2. **SVG 渲染缓存里存的必须是 ``QImage`` 而不是 ``QPixmap``**。``QPixmap``
   在 PyQt5 里是活对象且缓存直接把它当返回值交出去：调用方一句
   ``svg_to_pixmap(...).fill(red)`` 就把缓存里那一份改了，**之后所有拿到该
   缓存的调用方看到的都是被改过的图**（实测复现）。
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QCoreApplication, Qt
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import QApplication

from pyqt6_ela_pro import svg_icon as svg_mod
from pyqt6_ela_pro.selection_assistant.capture import ElaClipboardCapture

SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16">'
    '<rect x="2" y="2" width="12" height="12" fill="<<<COLOR_CODE>>>"/>'
    "</svg>"
)


@pytest.fixture
def clipboard(requires_clipboard):
    """本会话剪贴板不可用时跳过（见 conftest ``requires_clipboard``）。

    ``setText`` 之后必须让事件循环跑一圈才读得回 —— Windows 会话里
    ``QClipboard`` 的所有权交接是异步的，立刻 ``text()`` 会拿到空串。
    **不要断言剪贴板为空**（进程级共享状态会被上个用例污染）。
    """

    class _Clipboard:
        def __init__(self):
            self._cb = QApplication.clipboard()

        def setText(self, text: str) -> None:
            self._cb.setText(text)
            for _ in range(5):
                QCoreApplication.processEvents()

        def text(self) -> str:
            return self._cb.text()

        def clear(self) -> None:
            self._cb.clear()
            for _ in range(5):
                QCoreApplication.processEvents()

    return _Clipboard()


def _capture_with(capture: ElaClipboardCapture, captured: str) -> None:
    """把取词流程直接推到 ``_finish(ok=True)``（不依赖真剪贴板 / 真 Ctrl+C）。

    **调用前必须先把 ``captured`` 写进剪贴板**：``_finish`` 会取一次剪贴板
    序列号作为「注入那份」的基准（恢复时用它判「用户有没有又动过剪贴板」）。
    真实链路里是「注入 Ctrl+C → 源应用写剪贴板 → 轮询发现变化 → _finish」，
    所以基准取在写入之后；这里若先 ``_finish`` 再 ``setText``，那次写入本身
    会把序列号推进，恢复期就误判成「用户改过剪贴板」而跳过还原。
    """
    capture._active = True
    capture._finish(captured, ok=True)


@pytest.fixture
def fake_clipboard(monkeypatch):
    """确定性剪贴板桩（真实剪贴板的读回 / 序列号时序不确定，会让断言偶发假红）。

    返回 ``(cb, state)``；``state["n"]`` 是序列号，任何写入都推进它。
    """
    from pyqt6_ela_pro.selection_assistant import capture as capture_mod

    state = {"n": 1000, "text": ""}

    class _FakeClipboard:
        def text(self) -> str:
            return state["text"]

        def setText(self, text: str) -> None:  # noqa: N802
            state["text"] = text
            state["n"] += 1

        def clear(self) -> None:
            state["text"] = ""
            state["n"] += 1

    cb = _FakeClipboard()

    class _FakeApp:
        @staticmethod
        def clipboard() -> _FakeClipboard:
            return cb

    monkeypatch.setattr(capture_mod, "QApplication", _FakeApp)
    monkeypatch.setattr(capture_mod, "clipboard_sequence_number", lambda: state["n"])
    return cb, state


class TestClipboardRestoreDoesNotClobberNewerCopy:
    def test_restores_when_clipboard_still_holds_our_copy(self, fake_clipboard):
        cb, _ = fake_clipboard
        capture = ElaClipboardCapture()
        capture._old_text = "用户原本的内容"
        cb.setText("取词拿到的文本")
        _capture_with(capture, "取词拿到的文本")
        capture._restore_clipboard()
        assert capture.lastRestoreSkipReason() == ""
        assert cb.text() == "用户原本的内容"

    def test_keeps_user_newer_copy(self, fake_clipboard):
        """用户在延时窗口里又复制了一次 —— 那份必须留下。"""
        cb, _ = fake_clipboard
        capture = ElaClipboardCapture()
        capture._old_text = "用户原本的内容"
        cb.setText("取词拿到的文本")
        _capture_with(capture, "取词拿到的文本")
        cb.setText("用户后来复制的东西")  # 用户又复制了一次
        capture._restore_clipboard()
        assert capture.lastRestoreSkipReason() == "user-copied"
        assert cb.text() == "用户后来复制的东西", (
            "用户的新复制被静默丢弃了（用户 Ctrl+V 会拿到旧内容）"
        )

    def test_same_text_but_newer_copy_keeps_user_action(self, fake_clipboard):
        """用户在延时窗口里又复制了**同样的**文本 —— 纯文本比较看不出来。

        这就是「Ctrl+C 撞上用户自己按的 Ctrl+C」那条：文本完全相同，但用户
        确实重新复制了一次（可能换了个来源程序、格式更丰富）。序列号能判别。
        """
        cb, _ = fake_clipboard
        capture = ElaClipboardCapture()
        capture._old_text = "原文"
        cb.setText("同样的内容")
        _capture_with(capture, "同样的内容")
        # 用户又复制了一遍同样的文本：文本没变，序列号变了
        cb.setText("同样的内容")
        capture._restore_clipboard()
        assert capture.lastRestoreSkipReason() in (
            "clipboard-changed",
            "user-copied",
        ), "序列号或文本判据应识别出剪贴板被再次写入"

    def test_non_text_baseline_is_never_cleared(self, fake_clipboard):
        """基准剪贴板含图片等非文本内容时**跳过恢复**，绝不 ``clear()``。

        否则用户复制的图片被清空，Ctrl+V 直接粘不出来（静默数据丢失）。
        """
        cb, _ = fake_clipboard
        capture = ElaClipboardCapture()
        capture._old_text = ""
        capture._baseline_non_text = True
        cb.setText("TAKEN")
        _capture_with(capture, "TAKEN")
        capture._restore_clipboard()
        assert capture.lastRestoreSkipReason() == "non-text-baseline"
        assert cb.text() == "TAKEN", "注入进来的文本应留着，而不是清空剪贴板"

    def test_emits_restore_skipped_only_when_skipped(self, fake_clipboard):
        cb, _ = fake_clipboard
        capture = ElaClipboardCapture()
        events: list[str] = []
        capture.restoreSkipped.connect(lambda: events.append("skipped"))

        capture._old_text = "A"
        cb.setText("TAKEN")
        _capture_with(capture, "TAKEN")
        capture._restore_clipboard()
        assert events == [], "正常还原不该发这个信号"

        capture._old_text = "B"
        cb.setText("TAKEN2")
        _capture_with(capture, "TAKEN2")
        cb.setText("USER_NEW")
        capture._restore_clipboard()
        assert events == ["skipped"]

    def test_empty_original_is_not_cleared_when_user_copied(self, fake_clipboard):
        """原内容为空时走 ``clear()``；但前提同样要「剪贴板还是我们放的那份」。"""
        cb, _ = fake_clipboard
        capture = ElaClipboardCapture()
        capture._old_text = ""
        cb.setText("TAKEN")
        _capture_with(capture, "TAKEN")
        cb.setText("USER_NEW")
        capture._restore_clipboard()
        assert cb.text() == "USER_NEW"

    def test_empty_original_is_cleared_when_unchanged(self, fake_clipboard):
        cb, _ = fake_clipboard
        capture = ElaClipboardCapture()
        capture._old_text = ""
        cb.setText("TAKEN")
        _capture_with(capture, "TAKEN")
        capture._restore_clipboard()
        assert capture.lastRestoreSkipReason() == "", "正常还原不该跳过"
        assert cb.text() == ""

    def test_no_restore_flag_does_not_arm_the_timer(self, clipboard):
        capture = ElaClipboardCapture()
        capture.setRestoreClipboard(False)
        capture._active = True
        capture._finish("TAKEN", ok=True)
        assert capture._need_restore is False

    def test_failed_capture_does_not_arm_the_timer(self, clipboard):
        capture = ElaClipboardCapture()
        capture._active = True
        capture._finish("", ok=False)
        assert capture._need_restore is False

    def test_restoring_twice_is_a_noop(self, fake_clipboard):
        cb, _ = fake_clipboard
        capture = ElaClipboardCapture()
        capture._old_text = "ORIGINAL"
        cb.setText("TAKEN")
        _capture_with(capture, "TAKEN")
        capture._restore_clipboard()
        cb.setText("TAKEN")
        capture._restore_clipboard()  # 已结清（``_need_restore`` 一次性）
        assert cb.text() == "TAKEN"

    def test_capture_resets_the_markers(self, clipboard):
        capture = ElaClipboardCapture()
        capture._old_text = "OLD"
        capture._captured_text = "STALE"
        capture._active = False
        clipboard.setText("SENTINEL")
        capture.capture()
        assert capture._old_text == ""
        assert capture._captured_text == ""
        assert capture._baseline_non_text is False
        assert capture.lastRestoreSkipReason() == ""

    def test_cancel_resets_the_markers(self, clipboard):
        capture = ElaClipboardCapture()
        clipboard.setText("TAKEN")
        capture._active = True
        capture._finish("TAKEN", ok=True)  # _finish 会把 _active 置 False
        capture._capture_seq = 12345
        capture._active = True
        capture.cancel()
        assert capture._capture_seq == 0
        assert capture.lastRestoreSkipReason() == ""


class TestSvgCacheIsNotHandedOutAsALivePixmap:
    def test_cache_stores_qimage_not_qpixmap(self):
        cached = svg_mod._render_svg_image(SVG, 16, "#ff0000")
        assert isinstance(cached, QImage), (
            f"缓存里存的是 {type(cached).__name__}，必须是 QImage"
        )

    def test_each_call_returns_a_fresh_pixmap(self):
        first = svg_mod.svg_to_pixmap(SVG, 16, "#00ff00")
        second = svg_mod.svg_to_pixmap(SVG, 16, "#00ff00")
        assert isinstance(first, QPixmap)
        assert first is not second, "同一参数两次调用返回同一个 QPixmap = 缓存的活对象"

    def test_caller_mutation_does_not_poison_the_cache(self):
        before = svg_mod.svg_to_pixmap(SVG, 16, "#0000ff").toImage()
        original = before.pixelColor(8, 8)
        svg_mod.svg_to_pixmap(SVG, 16, "#0000ff").fill(Qt.GlobalColor.red)
        after = svg_mod.svg_to_pixmap(SVG, 16, "#0000ff").toImage().pixelColor(8, 8)
        assert after.rgba() == original.rgba(), (
            f"调用方 fill(red) 污染了缓存：{original.name()} -> {after.name()}"
        )

    def test_caller_mutation_is_visible_to_that_caller_only(self):
        mine = svg_mod.svg_to_pixmap(SVG, 16, "#123456")
        expected = mine.toImage().pixelColor(8, 8).name()
        mine.fill(Qt.GlobalColor.green)
        assert mine.toImage().pixelColor(8, 8).name() == "#00ff00", "fill 应生效"
        theirs = svg_mod.svg_to_pixmap(SVG, 16, "#123456")
        assert theirs.toImage().pixelColor(8, 8).name() == expected, (
            "别人的那份被我的 fill 染绿了"
        )

    def test_svg_to_image_is_the_thread_safe_form(self):
        image = svg_mod.svg_to_image(SVG, 16, "#00ffff")
        assert isinstance(image, QImage)
        assert not image.isNull()

    def test_svg_to_image_returns_a_copy(self):
        first = svg_mod.svg_to_image(SVG, 16, "#00ffff")
        second = svg_mod.svg_to_image(SVG, 16, "#00ffff")
        assert first is not second, "QImage 也是活对象，出参同样要给副本"

    def test_color_placeholder_is_substituted(self):
        image = svg_mod.svg_to_image(SVG, 16, "#00ff00")
        centre = image.pixelColor(8, 8)
        assert centre.green() > 200 and centre.red() < 60, (
            f"色占位符没替换上，中心像素 {centre.name()}"
        )

    def test_render_is_cached(self):
        svg_mod._render_svg_image.cache_clear()
        svg_mod.svg_to_image(SVG, 16, "#010203")
        svg_mod.svg_to_image(SVG, 16, "#010203")
        assert svg_mod._render_svg_image.cache_info().currsize == 1

    def test_icon_still_builds(self):
        icon = svg_mod.svg_to_icon(SVG, 16, "#ff8800")
        assert not icon.isNull()
        assert icon.availableSizes()
