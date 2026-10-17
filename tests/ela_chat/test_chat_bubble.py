"""ElaChatBubble 分层气泡组件测试（用户 / 助手 / 系统三种角色）。"""

from __future__ import annotations

import pytest
from _qthelpers import wait_for_clipboard as _wait_for_clipboard
from _qthelpers import wait_until as _wait_until
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPalette
from PyQt6.QtWidgets import QWidget
from PyQt6ElaWidgetTools import ElaThemeType

from pyqt6_ela_pro.chat._theme import muted_color

from pyqt6_ela_pro.chat import (
    DISCLAIMER_TEXT,
    ElaChatBubble,
    ElaChatPart,
    ElaChatPartKindType,
    ElaChatPermission,
    ElaChatPermissionStatusType,
    ElaChatReasoningStyleType,
    ElaChatRoleType,
    ElaChatStats,
    ElaChatStatusType,
    ElaChatToolStatusType,
    ElaChatWidget,
)


class TestUserBubble:
    def test_plain_text_and_selectable(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.User, "<b>不是 HTML</b>")
        assert bubble.role() == ElaChatRoleType.User
        assert bubble.text() == "<b>不是 HTML</b>"
        assert bubble._label.textFormat() == Qt.TextFormat.PlainText
        assert (
            bubble._label.textInteractionFlags()
            & Qt.TextInteractionFlag.TextSelectableByMouse
        )

    def test_layers_present(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.User, "hi")
        # 头部层（头像在头部内）+ 正文层 + 底部操作层
        assert bubble.header().role() == ElaChatRoleType.User
        assert bubble.header().avatar() is not None
        assert bubble._body is not None
        assert bubble.actions().keys() == ["copy", "undo"]

    def test_max_width_ratio(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.User, "一段比较长的文本" * 5)
        bubble.resize(600, 80)
        bubble.show()
        qapp.processEvents()
        bubble.setMaxWidthRatio(0.5)
        assert bubble.maxWidthRatio() == 0.5
        assert bubble._body.maximumWidth() <= int(600 * 0.5) + 1

    def test_set_text_and_append(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.User, "a")
        bubble.setText("b")
        bubble.appendText("c")
        assert bubble.text() == "bc"

    def test_title_timestamp_status(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.User, "hi")
        bubble.setTitle("我")
        bubble.setTimestamp("12:00:01")
        bubble.setStatus(ElaChatStatusType.Stopped)
        header = bubble.header()
        assert bubble.title() == "我"
        assert bubble.timestamp() == "12:00:01"
        assert header.title() == "我"
        assert header.timestamp() == "12:00:01"
        assert header.statusText() == "已停止"

    def test_copy_action_copies_clipboard(self, qapp, requires_clipboard, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.User, "复制我")
        copied = []
        bubble.copyRequested.connect(lambda: copied.append(1))
        copy_button = bubble.actions().toolButton("copy")
        copy_button.click()
        assert copied == [1]
        # Windows 上这次写可能被静默丢弃（实测读回空串、只轮询等不来）：必须重发才落盘
        assert _wait_for_clipboard(qapp, "复制我", copy_button.click) == "复制我"

    def test_undo_action_signal(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.User, "hi")
        undone = []
        bubble.undoRequested.connect(lambda: undone.append(1))
        bubble.actions().toolButton("undo").click()
        assert undone == [1]

    def test_attachments_layer(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.User, "hi")
        assert bubble.attachments() == []
        bubble.addAttachment("a.pdf", "C:/tmp/a.pdf", 2048)
        bubble.setAttachments([{"name": "b.txt", "path": "C:/tmp/b.txt", "size": 10}])
        attachments = bubble.attachments()
        assert len(attachments) == 1
        assert attachments[0].name == "b.txt"
        assert attachments[0].displaySize == "10 B"
        bubble.clearAttachments()
        assert bubble.attachments() == []

    def test_attachment_chips_right_aligned_and_fit(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.User, "hi")
        bubble.resize(700, 220)
        bubble.show()
        qapp.processEvents()
        bubble.addAttachment("算法笔记.pdf", "C:/tmp/notes.pdf", 345678)
        for _ in range(5):
            qapp.processEvents()
        strip = bubble.attachmentStrip()
        assert strip.alignment() == Qt.AlignmentFlag.AlignRight
        chip = strip._cards[0]
        # 文本 + 左右内边距 + 关闭按钮宽度，不能被裁掉
        text_width = chip.fontMetrics().horizontalAdvance(chip.text())
        assert chip.width() >= text_width + 32
        assert chip.geometry().right() <= strip.width()

    def test_bubble_width_follows_text(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.User, "你好")
        bubble.resize(600, 160)
        bubble.show()
        qapp.processEvents()
        narrow = bubble._body.width()
        bubble.setText("很长的内容" * 20)
        qapp.processEvents()
        wide = bubble._body.width()
        assert wide > narrow
        assert wide <= int(600 * 0.72) + 1


class TestCopyNotification:
    """点击底部「复制」后的 ``ElaMessageBar`` 成功提示（默认开，可关）。

    sip 把 C++ 建的 ``ElaMessageBar`` 子控件按基类 ``QWidget`` 暴露，
    ``findChildren(ElaMessageBar)`` 恒为空 —— 只能按 ``objectName()`` 过滤。
    """

    @staticmethod
    def _bars(bubble):
        return [
            widget
            for widget in bubble.window().findChildren(QWidget)
            if widget.objectName() == "ElaMessageBar"
        ]

    def test_default_enabled_shows_message_bar(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.User, "复制我")
        assert bubble.copyNotificationEnabled() is True
        bubble.actions().toolButton("copy").click()
        qapp.processEvents()
        assert self._bars(bubble), "默认开启时复制应弹 ElaMessageBar"

    def test_disabled_skips_message_bar(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.User, "复制我")
        bubble.setCopyNotificationEnabled(False)
        assert bubble.copyNotificationEnabled() is False
        bubble.actions().toolButton("copy").click()
        qapp.processEvents()
        assert not self._bars(bubble)

    def test_reenabled_shows_again(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.User, "复制我")
        bubble.setCopyNotificationEnabled(False)
        bubble.setCopyNotificationEnabled(True)
        bubble.actions().toolButton("copy").click()
        qapp.processEvents()
        assert self._bars(bubble)


class TestAssistantBubble:
    def test_markdown_viewer_embedded(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant, "**粗体**")
        viewer = bubble.markdownViewer()
        assert viewer is not None
        assert viewer.embeddedMode() is True
        assert viewer.markdown().strip() == "**粗体**"

    def test_text_viewer_trims_trailing_margin(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant, "一行正文")
        viewer = bubble.markdownViewer()
        assert viewer is not None
        # 聊天正文查看器启用文末空白裁剪（正文 → 后续分段的间距与其它分段一致）
        assert viewer.embeddedTrimBottom() is True

        bubble.resize(520, 200)
        bubble.show()
        qapp.processEvents()
        document = viewer.document()
        last_rect = document.documentLayout().blockBoundingRect(document.lastBlock())
        assert viewer.height() < document.size().height()
        assert viewer.height() >= last_rect.bottom()

    def test_stream_flow(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        finished = []
        bubble.streamFinished.connect(lambda: finished.append(bubble.status()))
        bubble.beginStream()
        assert bubble.isStreaming()
        assert bubble.status() == ElaChatStatusType.Streaming
        # 阶段一：等待模型首个输出（TTFT）
        assert bubble.header().statusKind() == ElaChatStatusType.Queued
        assert bubble.header().statusText() == "排队中…"
        bubble.appendText("# 标题")
        # 阶段二：收到首个分片即转「生成中」
        assert bubble.header().statusKind() == ElaChatStatusType.Streaming
        assert bubble.header().statusText() == "生成中…"
        bubble.appendText("\n\n正文")
        assert _wait_until(qapp, lambda: "正文" in bubble.text())
        bubble.endStream()
        assert not bubble.isStreaming()
        assert bubble.status() == ElaChatStatusType.Done
        assert finished == [ElaChatStatusType.Done]

    def test_stream_placeholder(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        bubble.beginStream()
        assert bubble.markdownViewer().placeholderText() == "正在生成…"
        bubble.endStream(ElaChatStatusType.Stopped)
        assert bubble.status() == ElaChatStatusType.Stopped

    def test_non_assistant_begin_stream_noop(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.User, "hi")
        bubble.beginStream()
        assert not bubble.isStreaming()
        bubble.endStream()
        assert bubble.status() == ElaChatStatusType.Done

    def test_two_phase_status_reasoning_first(self, qapp, make):
        """思考先到也算「模型已开始输出」：排队中 → 生成中。"""
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        bubble.beginStream()
        assert bubble.header().statusText() == "排队中…"
        bubble.appendReasoning("先想想")
        assert bubble.header().statusKind() == ElaChatStatusType.Streaming
        assert bubble.header().statusText() == "生成中…"
        bubble.endStream()

    def test_two_phase_status_tool_first(self, qapp, make):
        """工具调用先到同样触发阶段切换。"""
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        bubble.beginStream()
        assert bubble.header().statusKind() == ElaChatStatusType.Queued
        bubble.addToolCall("read", "{}")
        assert bubble.header().statusKind() == ElaChatStatusType.Streaming
        bubble.endStream()

    def test_two_phase_status_stop_before_first_token(self, qapp, make):
        """首个输出前停止：直接进终态，不留「排队中」。"""
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        bubble.beginStream()
        bubble.endStream(ElaChatStatusType.Stopped)
        assert bubble.header().statusKind() == ElaChatStatusType.Stopped
        assert bubble.header().statusText() == "已停止"

    def test_two_phase_status_via_widget(self, qapp, make):
        """widget 回合路径：beginAssistantMessage → 排队中；首个分片 → 生成中。"""

        chat = make(ElaChatWidget)
        messageId = chat.beginAssistantMessage()
        view = chat.chatView()
        bubble = view.bubble(messageId)
        assert bubble.header().statusText() == "排队中…"
        view.appendText(messageId, "第一片")
        assert bubble.header().statusText() == "生成中…"
        chat.endAssistantMessage(messageId)
        assert bubble.header().statusText() == ""
        qapp.processEvents()

    def test_reasoning_layer(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        bubble.beginReasoning()
        block = bubble.reasoningBlock()
        assert block.isOpened()
        bubble.appendReasoning("先看条件")
        bubble.appendReasoning("再推导")
        assert bubble.reasoning() == "先看条件再推导"
        bubble.endReasoning(1500)
        assert not block.isOpened()
        assert "思考完成 (1.5s)" in block.title()

    def test_tool_call_layer(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        callId = bubble.addToolCall("read_file", '{"path": "a.txt"}')
        assert bubble.toolCallCount() == 1
        running = bubble.toolCall(callId)
        assert running.name == "read_file"
        assert running.status == ElaChatToolStatusType.Running
        bubble.setToolCallResult(callId, "文件内容")
        done = bubble.toolCall(callId)
        assert done.isDone and done.result == "文件内容"
        bubble.clearToolCalls()
        assert bubble.toolCallCount() == 0

    def test_stats_layer(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        stats = ElaChatStats(
            prompt_tokens=10,
            completion_tokens=20,
            total_tokens=30,
            ttft_ms=250.0,
            tps=12.5,
        )
        bubble.setStepStats(stats)
        assert bubble.stats() is stats
        assert bubble.statsBadge().isVisible() is False  # 未 show，父链不可见
        assert "首字 250 ms" in stats.tooltip()

    def test_error_layer(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        bubble.setError("连接超时")
        assert bubble.error() == "连接超时"
        assert bubble.status() == ElaChatStatusType.Error
        bubble.clearError()
        assert bubble.error() == ""

    def test_actions_keys(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        assert bubble.actions().keys() == ["copy", "regenerate"]

    def test_header_title_font_stack(self, qapp, make):
        """标题字体走 ``QFont`` 字体栈（拉丁 Segoe UI、中文逐字形回退），不用 QSS。"""
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        label = bubble.header()._title_label
        assert list(label.font().families())[:2] == ["Segoe UI", "Microsoft YaHei UI"]
        assert label.font().pixelSize() == 13
        # ElaText 自带一条透明底规则（C++ 构造里设的），这里只断言我们没再写字体 / 颜色 QSS
        assert "font-family" not in label.styleSheet()
        assert "font-size" not in label.styleSheet()

    def test_avatar_icon_offset_aligns_to_device_pixels(self, qapp):
        """头像位图落点要对齐设备像素网格（高 DPI 下发虚 / 偏移的根因）。"""
        from pyqt6_ela_pro.chat.blocks import AVATAR_SIZE, _AvatarBadge

        badge = _AvatarBadge(ElaChatRoleType.Assistant)
        badge.resize(AVATAR_SIZE, AVATAR_SIZE)
        logical = AVATAR_SIZE * 0.62
        for dpr in (1.0, 1.25, 1.5, 2.0):
            offset = badge._device_aligned_offset(logical, logical, dpr)
            # 落点 × dpr 必须为整数，否则 1:1 位图会被 SmoothPixmapTransform 重采样
            assert (offset.x() * dpr).is_integer(), (dpr, offset)
            assert (offset.y() * dpr).is_integer(), (dpr, offset)
            # 同时仍然居中（误差不超过一个设备像素）
            assert abs(offset.x() - (AVATAR_SIZE - logical) / 2) <= 1 / dpr + 1e-9
        badge.deleteLater()

    def test_disclaimer_label(self, qapp, make):
        """底部「内容由 AI 生成，仅供参考」：只助手消息有，随整行显隐，可改可关。"""
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        assert bubble.disclaimer() == DISCLAIMER_TEXT
        assert bubble.disclaimerVisible() is True

        bubble.setDisclaimer("本回答由 AI 生成")
        assert bubble.disclaimer() == "本回答由 AI 生成"

        # 流式期间跟着整条底部行一起隐藏（与操作按钮 / 用量同一套规则）
        bubble.beginStream()
        assert bubble.footer().isHidden() is True
        assert bubble.disclaimerVisible() is False
        bubble.endStream()
        assert bubble.disclaimerVisible() is True

        bubble.setDisclaimerVisible(False)
        assert bubble.disclaimerVisible() is False
        bubble.setDisclaimer("")  # 空串 → 自动隐藏
        assert bubble.disclaimer() == ""
        assert bubble.disclaimerVisible() is False

    def test_user_bubble_has_no_disclaimer(self, qapp, make):
        """「AI 生成」提示只属于助手消息 —— 用户消息没有这个标签。"""
        bubble = make(ElaChatBubble, ElaChatRoleType.User, "我发的")
        assert bubble.disclaimer() == DISCLAIMER_TEXT  # 文案仍是全局设置
        assert bubble.disclaimerVisible() is False

    def test_invalid_status_falls_back_to_done(self, qapp, make):
        """状态是字符串枚举：非法值（如大小写笔误）一律回落 Done，不污染状态机。"""
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        bubble.beginStream()
        assert bubble.status() == ElaChatStatusType.Streaming

        bubble.setStatus("Done")  # 笔误：应为 ElaChatStatusType.Done
        assert bubble.status() == ElaChatStatusType.Done
        assert bubble.footer().isHidden() is False  # 按 Done 收尾，底部行正常回来

        bubble.setStatus("bogus")
        assert bubble.status() == ElaChatStatusType.Done
        bubble.setStatus(ElaChatStatusType.Stopped)
        assert bubble.status() == ElaChatStatusType.Stopped

    def test_footer_hidden_while_streaming(self, qapp, make):
        """底部行（复制 / 重新生成 / 用量 / 耗时）整行只在回合有结果之后出现。"""
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        assert bubble.footer().isHidden() is False  # 静态消息（Done）→ 正常显示

        bubble.beginStream()
        assert bubble.footer().isHidden() is True
        bubble.appendText("正在写…")
        assert bubble.footer().isHidden() is True  # 流式期间一直不出现
        for key in ("copy", "regenerate"):
            assert bubble.actions().toolButton(key).isVisibleTo(bubble) is False

        bubble.endStream()
        assert bubble.footer().isHidden() is False
        for key in ("copy", "regenerate"):
            assert bubble.actions().toolButton(key).isVisibleTo(bubble) is True

    def test_footer_visible_after_stop_and_error(self, qapp):
        """停止 / 出错之后底部行要回来（这两种结果都需要复制与重新生成）。"""
        for status in (ElaChatStatusType.Stopped, ElaChatStatusType.Error):
            bubble = ElaChatBubble(ElaChatRoleType.Assistant)
            bubble.beginStream()
            bubble.endStream(status)
            assert bubble.footer().isHidden() is False
            assert bubble.actions().toolButton("regenerate").isVisibleTo(bubble) is True
            bubble.deleteLater()

    def test_stats_badge_hidden_during_tool_steps(self, qapp, make):
        """智能体调工具的过程中不显示词元用量：中途数字不是最终值、还会来回跳。"""
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        bubble.beginStream()
        bubble.setStepStats(ElaChatStats(total_tokens=120))
        badge = bubble.statsBadge()
        assert badge is not None
        assert badge.isVisibleTo(bubble) is False  # 第一步用量 → 不显示
        bubble.addToolCall("read_file", '{"path": "a.py"}', "call-1")  # 中间工具步骤
        bubble.beginStep()
        bubble.setStepStats(ElaChatStats(total_tokens=180))
        assert bubble.statsBadge().isVisibleTo(bubble) is False

        bubble.endStream()
        assert bubble.statsBadge().isVisibleTo(bubble) is True  # 回合结束才出现
        assert bubble.stats().total_tokens == 300  # 各步求和

    def test_stats_badge_hidden_in_steps_mode_too(self, qapp, make):
        """调试用的 ``"steps"`` 模式同样等回合结束 —— 过程里不摆用量。"""
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        bubble.setStatsMode("steps")
        bubble.beginStream()
        bubble.setStepStats(ElaChatStats(total_tokens=10))
        assert bubble.statsBadge().isVisibleTo(bubble) is False
        bubble.endStream()
        assert bubble.statsBadge().isVisibleTo(bubble) is True

    def test_attachment_strip_left_aligned(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        assert bubble.attachmentStrip().alignment() == Qt.AlignmentFlag.AlignLeft


class TestSystemBubble:
    def test_centered_and_header_hidden(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.System, "会话已开始")
        assert bubble.header().isHidden()
        assert bubble._label.alignment() == Qt.AlignmentFlag.AlignCenter
        holder_layout = bubble._label.parentWidget().layout()
        assert holder_layout.itemAt(0).spacerItem() is not None
        assert holder_layout.itemAt(holder_layout.count() - 1).spacerItem() is not None
        # 系统消息文本走 palette 上色（禁 QSS 后不再有 color: 规则）
        assert bubble._label.palette().color(
            QPalette.ColorRole.WindowText
        ) == muted_color(bubble._theme_mode, 0.45)
        assert bubble.actions().isHidden()


class TestAppearance:
    def test_avatar_visibility(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant, "hi")
        bubble.show()
        qapp.processEvents()
        assert bubble.avatarVisible()
        avatar = bubble.header().avatar()
        assert avatar.isVisible()
        bubble.setAvatarVisible(False)
        assert not bubble.avatarVisible()
        assert not avatar.isVisible()

    def test_hidden_avatar_frees_width(self, qapp, make):
        """头像隐藏后不占宽度：用户气泡最大宽度应随之变大。"""
        bubble = make(ElaChatBubble, ElaChatRoleType.User, "内容" * 20)
        bubble.resize(400, 200)
        bubble.show()
        qapp.processEvents()
        shown = bubble._body.maximumWidth()
        bubble.setAvatarVisible(False)
        assert bubble._body.maximumWidth() > shown

    def test_theme_switch_recolors_bubble(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.User, "hi")
        before = bubble._body._bg.name()
        bubble._onThemeChanged(ElaThemeType.ThemeMode.Dark)
        after = bubble._body._bg.name()
        assert after != before

    def test_role_fallback(self, qapp, make):
        bubble = make(ElaChatBubble, "unknown-role", "hi")
        assert bubble.role() == ElaChatRoleType.Assistant


class TestReadGettersArePure:
    """「取控件」不是写操作：读取不得凭空造分段 / 改展示形态。"""

    def test_markdown_viewer_does_not_create_part(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        assert bubble.markdownViewer() is None
        assert bubble.parts() == ()

    def test_reasoning_getters_do_not_create_parts(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        with pytest.raises(RuntimeError):
            bubble.reasoningBlock()
        with pytest.raises(RuntimeError):
            bubble.inlineReasoningViewer()
        assert bubble.parts() == ()
        assert bubble.reasoningStyle() == ElaChatReasoningStyleType.Collapse

    def test_markdown_viewer_none_for_done_message_without_text(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        bubble.addToolCall("read", "{}")
        assert bubble.markdownViewer() is None
        assert [p.kind for p in bubble.parts()] == ["tool"]


class TestPermissionGuards:
    def test_resolve_is_idempotent(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        bubble.beginPermission(ElaChatPermission(request_id="r1", action="edit"))
        assert bubble.resolvePermission("r1", "allowed") is True
        # 已落定：不再改写用户答案、不再重发信号
        assert bubble.resolvePermission("r1", "rejected") is False
        settled = [p.permission for p in bubble.parts() if p.permission is not None][0]
        assert settled.status == ElaChatPermissionStatusType.Allowed

    def test_set_text_empty_keeps_no_part(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        bubble.setText("")
        assert bubble.parts() == ()

    def test_set_parts_normalizes_empty_ids(self, qapp, make):
        """损坏数据缺 id：两条空 id 分段不能互相覆盖。"""
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        assert bubble.setParts(
            [
                ElaChatPart(id="", kind=ElaChatPartKindType.Text, text="A"),
                ElaChatPart(id="", kind=ElaChatPartKindType.Text, text="B"),
            ]
        )
        ids = [part.id for part in bubble.parts()]
        assert len(ids) == 2
        assert len(set(ids)) == 2
        assert bubble.text() == "AB"
