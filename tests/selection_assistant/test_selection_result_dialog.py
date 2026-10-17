"""ElaSelectionResultDialog 测试。

重点压在**回合状态机**上 —— 那是 Cherry Studio 实际坏掉的地方
（``ActionUtils.ts:85`` 传了空 ``requestOptions``，从未注册过 ``AbortSignal``，
停止按钮点了不真停，只靠 renderer 进程死亡顺带杀掉 fetch）。所以三条取消路径
（停止按钮 / 关窗 / 流式中 Esc）都必须发 ``stopRequested``，且**半句话不能算
结果**（``finished`` 不发、复制禁用）。

上游 ``ElaWidget``（标题栏 / 阴影 / 缩放 / 置顶按钮）由 C++ 负责，本文件只测
本组件自己的契约。
"""

from __future__ import annotations

import pytest
from _qthelpers import wait_for_clipboard as _wait_for_clipboard
from PyQt6 import sip
from PyQt6.QtCore import QCoreApplication, QEvent, QPoint, QRect, QSize, Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QApplication
from PyQt6ElaWidgetTools import ElaIconType, ElaThemeType, eTheme

from pyqt6_ela_pro import ElaSelectionResultDialog
from pyqt6_ela_pro.selection_assistant.result_dialog import (
    _EDGE_GAP,
    _PREVIEW_SOURCE_MAX,
    _PREVIEW_TIP_WIDTH,
)

_SOURCE = "这是一段被划词选中的文本"
_ANCHOR = QPoint(300, 200)


def _make(make):
    """造对话框并登记到 ``qt_cleanup``（无父顶层窗必须登记，见 AGENTS.md）。"""
    dialog = make(ElaSelectionResultDialog)
    dialog.openFor("translate", "翻译", _SOURCE, _ANCHOR, ElaIconType.IconName.Language)
    return dialog


def _press_escape(dialog) -> None:
    """直接派发 Esc 键（offscreen 下 QTest 的命中路由不可靠）。"""
    event = QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier
    )
    QApplication.sendEvent(dialog, event)


def _press_ctrl_c(dialog) -> None:
    event = QKeyEvent(
        QEvent.Type.KeyPress,
        Qt.Key.Key_C,
        Qt.KeyboardModifier.ControlModifier,
    )
    QApplication.sendEvent(dialog, event)


def _press_ctrl_shift_c(dialog) -> None:
    event = QKeyEvent(
        QEvent.Type.KeyPress,
        Qt.Key.Key_C,
        Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
    )
    QApplication.sendEvent(dialog, event)


class TestOpen:
    def test_open_for_sets_state(self, make):
        dialog = _make(make)
        assert dialog.isVisible() is True
        assert dialog.actionId() == "translate"
        assert dialog.selectedText() == _SOURCE
        assert dialog.windowTitle() == "翻译"
        assert dialog.isStreaming() is False
        assert dialog.hasResult() is False
        assert dialog.resultText() == ""

    def test_initial_controls_reflect_idle_state(self, make):
        dialog = _make(make)
        assert dialog._stop_button.isVisible() is False
        assert dialog._copy_button.isVisible() is True
        assert dialog._copy_button.isEnabled() is False  # 没有结果不能复制
        assert dialog._plain_copy_button.isVisible() is True
        assert dialog._plain_copy_button.isEnabled() is False
        assert dialog._regen_button.isEnabled() is False  # 宿主还没发过请求
        assert dialog._ring.isVisible() is False

    def test_open_for_returns_turn_token(self, make):
        dialog = _make(make)
        first = dialog.currentTurn()
        second = dialog.openFor("explain", "解释", _SOURCE, _ANCHOR)
        assert second > first

    def test_empty_selection_clears_stale_preview_tooltip(self, make):
        """换一次空原文必须摘掉上一轮的悬浮提示（否则弹出上一轮原文）。"""
        from pyqt6_ela_pro import tooltips

        dialog = _make(make)
        dialog._preview_text.setFullText(_SOURCE)
        assert dialog._preview_text in tooltips._filter_dict, "提示本该已绑定"

        dialog.openFor("explain", "解释", "", _ANCHOR)

        assert dialog._preview_text.fullText() == ""
        assert dialog._preview_text not in tooltips._filter_dict, (
            "旧 tooltip 还挂着，悬停空白预览行会弹出上一轮原文"
        )

    def test_open_for_resets_previous_result(self, make):
        dialog = _make(make)
        dialog.setResult("旧结果")
        assert dialog.hasResult() is True
        dialog.openFor("summary", "总结", "新原文", _ANCHOR)
        assert dialog.resultText() == ""
        assert dialog.hasResult() is False
        assert dialog.actionId() == "summary"


class TestStream:
    def test_stream_accumulates_and_settles(self, make):
        dialog = _make(make)
        finished = []
        dialog.finished.connect(lambda aid, text: finished.append((aid, text)))

        turn = dialog.beginStream()
        assert dialog.isStreaming() is True
        dialog.appendMarkdown("**粗体**", turn)
        dialog.appendMarkdown(" 和 ", turn)
        dialog.appendMarkdown("正文", turn)
        assert dialog.resultText() == "**粗体** 和 正文"

        dialog.endStream(turn)
        assert dialog.isStreaming() is False
        assert dialog.hasResult() is True
        assert dialog._copy_button.isEnabled() is True
        assert finished == [("translate", "**粗体** 和 正文")]

    def test_stream_toggles_footer_controls(self, make):
        dialog = _make(make)
        turn = dialog.beginStream()
        assert dialog._stop_button.isVisible() is True
        assert dialog._copy_button.isVisible() is False
        assert dialog._ring.isVisible() is True
        dialog.endStream(turn)
        assert dialog._stop_button.isVisible() is False
        assert dialog._copy_button.isVisible() is True
        assert dialog._ring.isVisible() is False

    def test_begin_stream_clears_previous_error(self, make):
        dialog = _make(make)
        dialog.setError("boom")
        assert dialog.errorText() == "boom"
        dialog.beginStream()
        assert dialog.errorText() == ""
        assert dialog._error_row.isVisible() is False

    def test_set_error_while_streaming_ends_the_viewer(self, make, qapp):
        """流式中途报错必须把查看器也收尾（否则光标还在闪、半截内容不落屏）。"""
        dialog = _make(make)
        dialog.beginStream()
        dialog.appendMarkdown("已经写了一半")
        assert dialog.isStreaming() is True

        dialog.setError("连接超时")

        assert dialog.isStreaming() is False
        assert dialog._viewer.isStreaming() is False, "查看器仍在流式态"
        assert "已经写了一半" in dialog._viewer.toPlainText(), (
            "报错时那半截内容仍要落屏（否则正文一片空白）"
        )
        assert dialog.hasResult() is False, "半句话不算结果"

    def test_set_result_settles_without_streaming(self, make):
        dialog = _make(make)
        finished = []
        dialog.finished.connect(lambda aid, text: finished.append((aid, text)))
        dialog.setResult("一次性结果")
        assert dialog.isStreaming() is False
        assert dialog.hasResult() is True
        assert dialog.resultText() == "一次性结果"
        assert finished == [("translate", "一次性结果")]

    def test_empty_result_is_not_settled_content(self, make):
        dialog = _make(make)
        dialog.setResult("   \n  ")
        # 空白不算结果：复制必须仍禁用，否则能把空气复制走
        assert dialog._copy_button.isEnabled() is False


class TestStaleChunks:
    """迟到分片闸门：被中止的回合之后宿主仍可能推几片在途。"""

    def test_append_after_stop_is_dropped(self, make):
        dialog = _make(make)
        turn = dialog.beginStream()
        dialog.appendMarkdown("AAA", turn)
        dialog._on_stop_clicked()
        dialog.appendMarkdown("STALE", turn)
        assert dialog.resultText() == "AAA"

    def test_append_with_old_turn_token_is_dropped(self, make):
        dialog = _make(make)
        old_turn = dialog.beginStream()
        dialog.appendMarkdown("OLD", old_turn)
        new_turn = dialog.beginStream()
        dialog.appendMarkdown("NEW", new_turn)
        # 拿旧回合的 token 推片必须无效
        dialog.appendMarkdown("STALE", old_turn)
        assert dialog.resultText() == "NEW"

    def test_end_stream_with_old_turn_token_is_dropped(self, make):
        dialog = _make(make)
        old_turn = dialog.beginStream()
        dialog.appendMarkdown("OLD", old_turn)
        new_turn = dialog.beginStream()
        dialog.appendMarkdown("NEW", new_turn)
        finished = []
        dialog.finished.connect(lambda aid, text: finished.append((aid, text)))
        dialog.endStream(old_turn)
        assert finished == []
        assert dialog.isStreaming() is True


class TestStopPaths:
    """三条取消路径都必须真中止 —— 这是 Cherry 缺的那一环。"""

    @pytest.mark.parametrize("path", ["stop_button", "close", "escape"])
    def test_cancel_emits_stop_requested(self, make, path):
        dialog = _make(make)
        stops = []
        dialog.stopRequested.connect(stops.append)
        turn = dialog.beginStream()
        dialog.appendMarkdown("半句话", turn)

        if path == "stop_button":
            dialog._stop_button.click()
        elif path == "close":
            dialog.closeDialog()
        else:
            _press_escape(dialog)

        assert stops == ["translate"], f"{path} 未触发 stopRequested"
        assert dialog.isStreaming() is False

    @pytest.mark.parametrize("path", ["stop_button", "close", "escape"])
    def test_partial_text_is_not_a_result(self, make, path):
        dialog = _make(make)
        finished = []
        dialog.finished.connect(lambda aid, text: finished.append((aid, text)))
        turn = dialog.beginStream()
        dialog.appendMarkdown("半句话", turn)

        if path == "stop_button":
            dialog._stop_button.click()
        elif path == "close":
            dialog.closeDialog()
        else:
            _press_escape(dialog)

        # 半截内容保留可见，但**不算结果**：不发 finished、复制禁用
        assert finished == []
        assert dialog.hasResult() is False
        assert dialog._copy_button.isEnabled() is False
        assert dialog.resultText() == "半句话"

    def test_stop_keeps_window_open(self, make):
        dialog = _make(make)
        dialog.beginStream()
        dialog._stop_button.click()
        assert dialog.isVisible() is True
        assert dialog._stop_button.isVisible() is False
        assert dialog._copy_button.isVisible() is True

    @pytest.mark.parametrize("path", ["stop_button", "close", "escape"])
    def test_stopped_partial_text_is_actually_rendered(self, make, qapp, path):
        """停止后正文必须**看得见**那半截，不能是空盒子。

        回归：ElaMarkdownViewer 把分片攒在 QTimer 里按节流提交，用户在定时器
        触发前点停止，缓冲里那半截就永远没进文档 —— 状态行写着「已停止」而正文
        全白。``_endTurn("stopped")`` 因此要显式冲掉查看器缓冲。
        """
        dialog = _make(make)
        turn = dialog.beginStream()
        dialog.appendMarkdown("## 标题\n\n已经收到的一段正文。", turn)

        if path == "stop_button":
            dialog._stop_button.click()
        elif path == "close":
            dialog.closeDialog()
        else:
            _press_escape(dialog)
        qapp.processEvents()

        # 刻意不调查看器任何私有方法：冲刷必须由 _endTurn 自己同步做完
        assert "已经收到的一段正文。" in dialog._viewer.toPlainText(), (
            f"{path} 停止后正文没渲染出来"
        )

    def test_close_while_streaming_emits_stop_then_closed(self, make):
        dialog = _make(make)
        order = []
        dialog.stopRequested.connect(lambda aid: order.append(("stop", aid)))
        dialog.closed.connect(lambda aid: order.append(("closed", aid)))
        dialog.beginStream()
        dialog.closeDialog()
        # 顺序有讲究：先发 stopRequested（让宿主有机会 abort），再发 closed
        assert order == [("stop", "translate"), ("closed", "translate")]
        assert dialog.isVisible() is False

    def test_escape_when_idle_closes(self, make):
        dialog = _make(make)
        closed = []
        dialog.closed.connect(closed.append)
        _press_escape(dialog)
        assert closed == ["translate"]
        assert dialog.isVisible() is False

    def test_close_when_idle_does_not_ask_for_stop(self, make):
        dialog = _make(make)
        stops = []
        dialog.stopRequested.connect(stops.append)
        dialog.closeDialog()
        assert stops == []

    def test_reopen_while_streaming_stops_previous_turn(self, make):
        dialog = _make(make)
        stops = []
        dialog.stopRequested.connect(stops.append)
        dialog.beginStream()
        dialog.openFor("summary", "总结", "别的原文", _ANCHOR)
        # 带上**旧**动作 id，宿主才知道要停哪个请求
        assert stops == ["translate"]
        assert dialog.actionId() == "summary"
        assert dialog.isStreaming() is False


class TestFooterActions:
    def test_copy_writes_settled_result(self, make, requires_clipboard):
        dialog = _make(make)
        copied = []
        dialog.copied.connect(copied.append)
        dialog.setResult("可复制内容")
        dialog._copy_button.click()
        assert copied == ["translate"]
        assert (
            _wait_for_clipboard(None, "可复制内容", dialog._copy_button.click)
            == "可复制内容"
        )

    def test_copy_refused_for_partial_text(self, make, requires_clipboard):
        dialog = _make(make)
        copied = []
        dialog.copied.connect(copied.append)
        turn = dialog.beginStream()
        dialog.appendMarkdown("半句话", turn)
        dialog._on_stop_clicked()
        dialog._on_copy()  # 按钮禁用也拦一道
        assert copied == []

    def test_copy_plain_text_strips_markdown(self, make, requires_clipboard):
        """「复制纯文本」写的是**渲染后**的文本（Markdown 标记被解析掉）。"""
        dialog = _make(make)
        plain = []
        dialog.plainCopied.connect(plain.append)
        dialog.setResult("# 标题\n\n**粗体**正文")
        dialog._plain_copy_button.click()
        assert plain == ["translate"]
        got = _wait_for_clipboard(
            None, "标题\n粗体正文", dialog._plain_copy_button.click
        )
        assert got == "标题\n粗体正文"

    def test_copy_plain_refused_for_partial_text(self, make, requires_clipboard):
        dialog = _make(make)
        plain = []
        dialog.plainCopied.connect(plain.append)
        turn = dialog.beginStream()
        dialog.appendMarkdown("半句话", turn)
        dialog._on_stop_clicked()
        dialog.copyPlainText()  # 半句话不算结果
        assert plain == []
        assert dialog._plain_copy_button.isEnabled() is False

    def test_ctrl_shift_c_copies_markdown_source(self, make, requires_clipboard):
        """``Ctrl+Shift+C`` = 原始 Markdown 源（与「复制 Markdown」按钮同源）。"""
        dialog = _make(make)
        dialog.setResult("**加粗**")
        _press_ctrl_shift_c(dialog)
        got = _wait_for_clipboard(
            None, "**加粗**", lambda: _press_ctrl_shift_c(dialog)
        )
        assert got == "**加粗**"

    def test_ctrl_shift_c_ignored_while_streaming(self, make, requires_clipboard):
        dialog = _make(make)
        sentinel = "__markdown_streaming_guard__"
        QApplication.clipboard().setText(sentinel)
        assert (
            _wait_for_clipboard(
                None, sentinel, lambda: QApplication.clipboard().setText(sentinel)
            )
            == sentinel
        )
        dialog.beginStream()
        _press_ctrl_shift_c(dialog)
        # 流式期间 Markdown 复制键无效（半句话不进剪贴板）：只轮询，绝不重发哨兵
        assert _wait_for_clipboard(None, sentinel) == sentinel

    def test_ctrl_c_copies_plain_text_by_default(self, make, requires_clipboard):
        """``Ctrl+C`` 是默认复制 = **纯文本**（去掉 Markdown 标记）。"""
        dialog = _make(make)
        dialog.setResult("# 标题\n\n**粗体**正文")
        _press_ctrl_c(dialog)
        got = _wait_for_clipboard(
            None, "标题\n粗体正文", lambda: _press_ctrl_c(dialog)
        )
        assert got == "标题\n粗体正文"

    def test_ctrl_c_ignored_while_streaming(self, make, requires_clipboard):
        dialog = _make(make)
        # 先确认哨兵落盘，再验「按 Ctrl+C 没动剪贴板」——
        # 直接断言 != 在写被丢弃 / 读失败时会白过
        sentinel = "__streaming_guard_sentinel__"
        QApplication.clipboard().setText(sentinel)
        assert (
            _wait_for_clipboard(
                None, sentinel, lambda: QApplication.clipboard().setText(sentinel)
            )
            == sentinel
        )
        dialog.beginStream()
        _press_ctrl_c(dialog)
        # 流式期间复制键无效（半句话不进剪贴板）：只轮询，绝不重发哨兵
        assert _wait_for_clipboard(None, sentinel) == sentinel

    def test_regenerate_emits_with_action_id(self, make):
        dialog = _make(make)
        regens = []
        dialog.regenerateRequested.connect(regens.append)
        dialog.setResult("结果")
        dialog._regen_button.click()
        assert regens == ["translate"]

    def test_regenerate_disabled_while_streaming(self, make):
        dialog = _make(make)
        regens = []
        dialog.regenerateRequested.connect(regens.append)
        dialog.beginStream()
        assert dialog._regen_button.isEnabled() is False
        dialog._on_regenerate()
        assert regens == []

    @pytest.mark.parametrize("stage", ["stopped", "error"])
    def test_regenerate_available_after_stop_or_error(self, make, stage):
        """出错与被中止之后「重新生成」必须可用 —— 那正是用户下一步要按的钮。

        回归：判据原先挂在 ``_settled`` 上，于是报错页与停止页上这个按钮是灰的，
        等于把重试入口藏起来了。
        """
        dialog = _make(make)
        regens = []
        dialog.regenerateRequested.connect(regens.append)
        turn = dialog.beginStream()
        dialog.appendMarkdown("半句话", turn)
        if stage == "stopped":
            dialog._stop_button.click()
        else:
            dialog.setError("boom")
        assert dialog._regen_button.isEnabled() is True
        dialog._regen_button.click()
        assert regens == ["translate"]

    def test_regenerate_disabled_before_any_request(self, make):
        # openFor 之后宿主还没发过请求，此时没有「重来」可言
        dialog = _make(make)
        assert dialog._regen_button.isEnabled() is False


class TestError:
    def test_error_row_shows_message(self, make):
        dialog = _make(make)
        dialog.setError("网络超时")
        assert dialog.errorText() == "网络超时"
        assert dialog._error_row.isVisible() is True
        assert dialog.hasResult() is False
        assert dialog._copy_button.isEnabled() is False

    def test_error_does_not_emit_stop(self, make):
        # 宿主已经自己收尾了，再发 stopRequested 会让它去 abort 一个已结束的请求
        dialog = _make(make)
        stops = []
        dialog.stopRequested.connect(stops.append)
        dialog.beginStream()
        dialog.setError("boom")
        assert stops == []

    def test_clear_error_hides_row(self, make):
        dialog = _make(make)
        dialog.setError("boom")
        dialog.clearError()
        assert dialog.errorText() == ""
        assert dialog._error_row.isVisible() is False

    def test_error_text_is_plain_text(self, make):
        # 错误文案来自网络，必须按纯文本显示（ElaText 默认 AutoText 会解析富文本）
        dialog = _make(make)
        assert dialog._error_text.textFormat() == Qt.TextFormat.PlainText


class TestPlacement:
    def test_window_fits_work_area_for_corner_anchor(self, make, qapp):
        area = QApplication.primaryScreen().availableGeometry()
        dialog = make(ElaSelectionResultDialog)
        # 锚点贴在工作区右下角：必须翻到上方并夹回工作区，不能溢出屏幕。
        # 回归：上游在 QEvent::Show 里补 WS_THICKFRAME 会把窗口**首次**撑高约
        # 31px，先算位置再 show 就会差出这 31px（所以 openFor 是先 show 再定位）
        dialog.openFor(
            "translate", "翻译", _SOURCE, QPoint(area.right() - 2, area.bottom() - 2)
        )
        qapp.processEvents()
        assert area.contains(dialog.frameGeometry())

    def test_window_fits_work_area_for_top_corner_anchor(self, make, qapp):
        area = QApplication.primaryScreen().availableGeometry()
        dialog = make(ElaSelectionResultDialog)
        dialog.openFor(
            "translate", "翻译", _SOURCE, QPoint(area.left() + 2, area.top() + 2)
        )
        qapp.processEvents()
        assert area.contains(dialog.frameGeometry())

    def test_placement_resize_is_not_remembered_as_preference(self, make, qapp):
        # 定位时按工作区夹取出来的尺寸不该被记成「用户偏好」，否则偏好会被
        # 这次夹取的结果污染（换小屏开一次之后尺寸再也涨不回去）
        area = QApplication.primaryScreen().availableGeometry()
        dialog = make(ElaSelectionResultDialog)
        preferred = QSize(area.width() * 3, area.height() * 3)
        dialog._preferred_size = QSize(preferred)
        dialog.openFor("translate", "翻译", _SOURCE, area.center())
        qapp.processEvents()
        # 窗口确实被夹到工作区内，而偏好原封不动
        assert dialog.width() <= area.width()
        assert QSize(dialog._preferred_size) == preferred

    def test_user_resize_is_remembered(self, make, qapp):
        # 断言「用户可见期调过尺寸会被记住」，但**不能断言请求值 == 实际值**：
        # 布局的 heightForWidth 下限会顶大请求（实测宽度 640 处下限是 542，
        # 而请求只有 511）—— 那是 Qt 的正常行为。`_preferred_size` 记的是用户
        # 真正看到的尺寸，所以拿实际尺寸对。
        dialog = _make(make)
        qapp.processEvents()  # 让 WS_THICKFRAME 的撑高先落地，后面读数才稳定
        before = QSize(dialog.size())
        grown = before + QSize(120, 60)
        dialog.resize(grown)
        qapp.processEvents()
        after = QSize(dialog.size())
        assert QSize(dialog._preferred_size) == after
        assert after.width() >= grown.width(), "宽度不该被布局缩小"
        assert after.height() > before.height(), "这次 resize 没生效"

    def test_hidden_resize_is_not_remembered(self, make, qapp):
        # 隐藏时的 resize 是程序行为（构造 / 首帧布局都会发）
        dialog = _make(make)
        before = QSize(dialog._preferred_size)
        dialog.hide()
        dialog.resize(QSize(640, 500))
        qapp.processEvents()
        assert QSize(dialog._preferred_size) == before

    def test_nudge_is_idempotent_and_frame_based(self, make, qapp):
        """``_nudge_inside_work_area`` 按**画框**纠偏，且重复调用不再动。

        回归：原先只按客户区（``self.width()/height()``）摆位，而上游在首次
        ``show`` 时补的 ``WS_THICKFRAME`` 让画框比客户区高 32px / 宽 2px
        （实测），锚点贴工作区右下角时画框底部溢出 42px 到屏幕外。
        """
        area = QApplication.primaryScreen().availableGeometry()
        dialog = make(ElaSelectionResultDialog)
        dialog.openFor(
            "translate", "翻译", _SOURCE, QPoint(area.right() - 2, area.bottom() - 2)
        )
        qapp.processEvents()

        frame = QRect(dialog.frameGeometry())
        assert frame.right() <= area.right() - _EDGE_GAP + 1
        assert frame.bottom() <= area.bottom() - _EDGE_GAP + 1

        dialog._nudge_inside_work_area(area)
        qapp.processEvents()
        assert QRect(dialog.frameGeometry()) == frame, "纠正步必须幂等"

    def test_wm_grow_is_not_recorded_as_user_resize(self, make, qapp):
        """``WS_THICKFRAME`` 那次撑高**投递时机不确定**，两种都要挡住。

        回归：撑高有时同步落在 ``_place()`` 内（被 ``_placing`` 盖住），有时被
        Qt 排进事件队列、在 ``_placing`` 复位之后才到。原先只靠 ``_placing``，
        后一种就把撑高后的尺寸记成了用户偏好（实测 1908x1020 → 记成 1908x1051）。
        """
        area = QApplication.primaryScreen().availableGeometry()
        dialog = make(ElaSelectionResultDialog)
        preferred = QSize(area.width() * 3, area.height() * 3)
        dialog._preferred_size = QSize(preferred)
        dialog.openFor("translate", "翻译", _SOURCE, area.center())
        # 多跑几轮事件循环：撑高无论落在哪一帧都不该被记成偏好
        for _ in range(5):
            qapp.processEvents()
        assert QSize(dialog._preferred_size) == preferred

    def test_wm_grow_flag_clears_after_one_resize(self, make, qapp):
        """撑高只发生一次 —— 之后用户的 resize 必须照常被记住。

        反过来锁死「无条件忽略第一次 resize」这种错误修法：那会让用户第一次
        调尺寸就丢。
        """
        dialog = _make(make)
        qapp.processEvents()
        dialog._wm_grow_pending = True
        dialog.resize(QSize(700, 560))
        qapp.processEvents()
        assert dialog._wm_grow_pending is False
        assert QSize(dialog._preferred_size) == QSize(dialog.size())

        again = QSize(dialog.size()) + QSize(40, 40)
        dialog.resize(again)
        qapp.processEvents()
        assert QSize(dialog._preferred_size) == QSize(dialog.size())
        assert dialog._preferred_size != QSize(700, 560) or dialog.size() != QSize(
            700, 560
        )

    def test_over_tall_window_aligns_to_top(self, make, qapp):
        """窗口比工作区还高时对齐**顶部**（标题栏必须留在可视区里）。

        上下同时溢出时无法都满足，居中会让标题栏直接被顶出屏幕 —— 对一个自带
        app bar 的对话框来说那是「打开就看不见标题、连 × 都点不到」。

        直接 ``setMinimumHeight`` 造出超高窗口再调纠正步，不走 ``openFor``：
        ``_place`` 会把高度夹到 ``area.height() - 2 * _EDGE_GAP``，本来造不出
        这个状态（真实触发路径是 ``WS_THICKFRAME`` 把画框顶出一截，而那圈边距
        实测不是常数、不能拿来构造前提）。
        """
        area = QApplication.primaryScreen().availableGeometry()
        dialog = make(ElaSelectionResultDialog)
        dialog.setMinimumHeight(area.height() + 200)
        dialog.resize(area.width() - 2 * _EDGE_GAP, area.height() + 200)
        dialog.move(area.left(), area.bottom())
        qapp.processEvents()

        dialog._nudge_inside_work_area(area)
        qapp.processEvents()
        assert QRect(dialog.frameGeometry()).top() == area.top() + _EDGE_GAP


class TestRegenerateDoesNotMove:
    """点「重新生成」不该把窗子从用户眼前挪走。

    回归：``openFor`` 原先无条件 ``_place()`` 按选区落点重新定位，而宿主在
    重新生成时往往会复用整条 ``openFor`` 链路 —— 于是用户刚拖到顺手位置的窗口
    被抽回划词落点。
    """

    def test_open_for_without_anchor_keeps_position(self, make, qapp):
        dialog = _make(make)
        dialog.move(640, 300)
        qapp.processEvents()
        parked = QPoint(dialog.pos())

        dialog.openFor("translate", "翻译", _SOURCE)  # 不给锚点 = 复用位置
        qapp.processEvents()
        assert QPoint(dialog.pos()) == parked

    def test_regenerate_flow_keeps_position(self, make, qapp):
        # 端到端：先落定 → 用户把窗子挪走 → 点重新生成（走 beginStream 链路）
        dialog = _make(make)
        dialog.setResult("结果")
        dialog.move(600, 280)
        qapp.processEvents()
        parked = QPoint(dialog.pos())

        dialog.regenerateRequested.emit("translate")  # 宿主自行决定重跑方式
        turn = dialog.beginStream()
        dialog.appendMarkdown("重来", turn)
        dialog.endStream(turn)
        qapp.processEvents()
        assert QPoint(dialog.pos()) == parked

    def test_open_for_with_anchor_still_repositions(self, make, qapp):
        # 给了锚点就必须重新定位 —— 这是「新划词」路径的行为，不能被上面那条带跑
        dialog = _make(make)
        dialog.move(0, 0)
        qapp.processEvents()
        area = QApplication.primaryScreen().availableGeometry()
        target = QPoint(area.left() + 120, area.top() + 120)
        dialog.openFor("translate", "翻译", _SOURCE, target)
        qapp.processEvents()
        assert QPoint(dialog.pos()) != QPoint(0, 0)
        assert dialog._anchor == target

    def test_first_open_without_anchor_still_gets_a_position(self, make, qapp):
        # 关着的时候不给锚点也必须有位置（用屏幕中心兜底），不能停在 0,0
        dialog = make(ElaSelectionResultDialog)
        dialog.openFor("translate", "翻译", _SOURCE)
        qapp.processEvents()
        assert dialog.isVisible() is True
        assert dialog.pos() != QPoint(0, 0)


class TestTheme:
    def test_theme_switch_repaints_without_crash(self, make, qapp):
        dialog = _make(make)
        dialog.setResult("深浅色都要画得出来")
        previous = eTheme.getThemeMode()
        try:
            for mode in (ElaThemeType.ThemeMode.Dark, ElaThemeType.ThemeMode.Light):
                eTheme.setThemeMode(mode)
                qapp.processEvents()
                dialog.grab()
        finally:
            eTheme.setThemeMode(previous)
            qapp.processEvents()
        assert dialog.hasResult() is True

    def test_preview_text_uses_muted_color(self, make):
        dialog = _make(make)
        # ColorText 的显式色是快照：切主题后必须仍是非空颜色
        assert dialog._preview_text.textColor() is not None
        assert dialog._status_text.textColor() is not None

    def test_preview_keeps_full_text(self, make):
        dialog = _make(make)
        long_source = "很长的划词原文 " * 20
        dialog.openFor("translate", "翻译", long_source, _ANCHOR)
        # 显示按宽度省略，但全文始终拿得到（省略位置依赖字体度量，不可钉）
        assert dialog._preview_text.fullText() == long_source
        assert dialog.selectedText() == long_source

    def test_preview_label_never_holds_the_whole_selection(self, make):
        """一次性划词几百万字时，显示文本必须有上限。

        回归：``_refresh_elide`` 在 ``width <= 0`` 时（首帧布局；``Ignored``
        策略下 0 宽也是合法状态）原本走 ``setText(全文)`` —— 几十万字直接进
        QLabel，首帧卡住。判据钉在「显示文本长度有界」而不是具体省略位置。
        """
        dialog = _make(make)
        huge = "字" * 400_000
        dialog.openFor("translate", "翻译", huge, _ANCHOR)
        shown = dialog._preview_text.text()
        assert len(shown) <= _PREVIEW_SOURCE_MAX + 1  # +1 是补的省略号
        # 全文仍然完整保留给宿主（宿主要拿原文就取这里，不要从显示文本反推）
        assert dialog._preview_text.fullText() == huge
        assert dialog.selectedText() == huge

    def test_preview_label_bounded_before_layout(self, make):
        """宽度未定下来时也必须有界 —— 那正是上一条踩的 0 宽分支。"""
        dialog = make(ElaSelectionResultDialog)
        preview = dialog._preview_text
        preview.resize(0, 20)
        preview.setFullText("x" * 50_000)
        assert len(preview.text()) <= _PREVIEW_SOURCE_MAX + 1

    def test_preview_normalizes_once_not_per_resize(self, make):
        # 归一化（split/join 全文）只在 setFullText 做一次；resize 只在截断后的
        # 源上算 —— 否则拖一次窗口边就是 O(n) × resize 次数
        dialog = _make(make)
        preview = dialog._preview_text
        preview.setFullText("换行\n与\t制表   重复   空格" * 50)
        flat = preview._flat
        assert "\n" not in flat and "\t" not in flat and "  " not in flat
        for _ in range(5):
            preview.resize(200, 20)
        assert preview._flat == flat


class TestPreviewTooltip:
    """原文悬浮提示必须有界：长文本折行，而不是拉成超宽单行横条。"""

    @staticmethod
    def _tooltip(dialog):
        from pyqt6_ela_pro.tooltips import _tooltip_dict

        return _tooltip_dict.get(dialog._preview_text)

    def test_long_preview_tooltip_wraps_within_max_width(self, make, qapp):
        dialog = _make(make)
        dialog.openFor(
            "translate",
            "翻译",
            "很长的划词原文，用于观察 tooltip 折行效果。" * 40,
            _ANCHOR,
        )
        qapp.processEvents()
        tooltip = self._tooltip(dialog)
        assert tooltip is not None
        assert tooltip.width() <= _PREVIEW_TIP_WIDTH
        # 单行是 32px；折行后必须更高，否则说明还是那条超宽横条
        assert tooltip.height() > 32

    def test_unbroken_ascii_tooltip_still_wraps(self, make, qapp):
        """无空格长串（URL / base64）按词边界折不开，也必须折而不是被裁。"""
        dialog = _make(make)
        dialog.openFor("translate", "翻译", "x" * 1200, _ANCHOR)
        qapp.processEvents()
        tooltip = self._tooltip(dialog)
        assert tooltip is not None
        assert tooltip.width() <= _PREVIEW_TIP_WIDTH
        assert tooltip.height() > 32

    def test_short_preview_tooltip_stays_single_line(self, make, qapp):
        dialog = _make(make)
        dialog.openFor("translate", "翻译", "短原文", _ANCHOR)
        qapp.processEvents()
        tooltip = self._tooltip(dialog)
        assert tooltip is not None
        assert tooltip.height() <= 32


class TestLifecycle:
    def test_destroy_leaves_no_top_level_window(self, make, qapp):
        dialog = make(ElaSelectionResultDialog)
        dialog.openFor("translate", "翻译", _SOURCE, _ANCHOR)
        qapp.processEvents()
        assert dialog.isVisible() is True

        dialog.deleteLater()
        # 无父顶层窗的 deleteLater 对 processEvents 不生效，必须显式冲刷
        QCoreApplication.sendPostedEvents(dialog, QEvent.Type.DeferredDelete)
        qapp.processEvents()
        assert sip.isdeleted(dialog) is True

    def test_python_sources_carry_no_qss(self):
        # 全库禁用 QSS。ElaWidget 的 C++ 构造函数自己会写一条
        # ``#ElaWidget{background-color:transparent;}``（那是上游内部实现，Python
        # 侧读得到 styleSheet 但不是我们写的），所以这里扫**源码**而不是读属性。
        import inspect

        from pyqt6_ela_pro.selection_assistant import result_dialog

        source = inspect.getsource(result_dialog)
        assert ".setStyleSheet(" not in source
