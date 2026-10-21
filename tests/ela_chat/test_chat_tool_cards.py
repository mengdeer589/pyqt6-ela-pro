"""工具卡 / 思考行 / meta / 错误卡等分层部件测试（对齐 opencode 语义）。"""

from __future__ import annotations

import random

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget
from PyQt6ElaWidgetTools import ElaIconType

from pyqt6_ela_pro.chat import (
    ElaChatPartKindType,
    ElaChatReasoningStyleType,
    ElaChatBubble,
    ElaChatRoleType,
    ElaChatToolCall,
    ElaChatToolStatusType,
    ElaChatView,
    ReasoningBlock,
    ToolGroupPanel,
)
from pyqt6_ela_pro.chat.blocks import (
    ContextToolGroupCard,
    ErrorCard,
    MessageMeta,
    ThinkingRow,
    ToolCallCard,
    _HeadingScanner,
    _preview_value,
    extractReasoningHeading,
    formatDuration,
    toolArgumentPairs,
    toolIconName,
    toolSubtitle,
    toolSubtitleParts,
)
from pyqt6_ela_pro.tooltips import _tooltip_dict


class TestToolHelpers:
    def test_tool_argument_pairs_bounds_large_containers(self):
        big = {"files": [{"path": f"/a/{i}"} for i in range(5000)]}
        pairs = toolArgumentPairs(big)
        assert len(pairs) == 1
        assert pairs[0].startswith("files=[")
        # 只预览前 8 项：靠后的元素不能出现在摘要里
        assert "/a/4999" not in pairs[0]
        assert _preview_value(list(range(100))).endswith("(+92 项)")
        assert _preview_value({"k": [1, 2]}) == '{"k":[1,2]}'
        assert _preview_value([1, 2, 3]) == "[1,2,3]"

    def test_subtitle_priority(self):
        assert toolSubtitle("read", '{"path": "a.py"}') == "a.py"
        assert toolSubtitle("grep", '{"pattern": "x", "path": "b.py"}') == "b.py"
        assert toolSubtitle("shell", '{"command": "ls -la"}') == "ls -la"
        assert toolSubtitle("unknown", "不是 JSON") == "不是 JSON"
        assert toolSubtitle("unknown", "") == ""

    def test_argument_pairs(self):
        # 不做排除：调用方自己决定（显式优于隐式自动探测）
        raw = toolArgumentPairs('{"a": 1, "b": "x", "c": true, "d": 4}', limit=9)
        assert raw == ["a=1", "b=x", "c=True", "d=4"]
        # 默认 limit=3
        assert toolArgumentPairs('{"a": 1, "b": "x", "c": true, "d": 4}') == [
            "a=1",
            "b=x",
            "c=True",
        ]
        assert toolArgumentPairs('{"a": 1}', limit=3) == ["a=1"]
        # excludeKey 排除指定键（副标题已展示过的那个）
        assert toolArgumentPairs(
            '{"a": 1, "b": "x", "c": true, "d": 4}', limit=9, excludeKey="b"
        ) == ["a=1", "c=True", "d=4"]
        # 非 JSON 的半截参数走「原文」通道：只进副标题，参数摘要为空
        # （键是空串，会被 ``not key`` 过滤掉）
        assert toolSubtitleParts('"path": "src/a') == ("", '"path": "src/a')
        assert toolArgumentPairs('"path": "src/a') == []

    def test_icon_and_duration(self):

        assert toolIconName("read") == ElaIconType.IconName.Glasses
        assert toolIconName("unknown") == ElaIconType.IconName.Cube
        assert formatDuration(3200) == "3.2s"
        assert formatDuration(0) == ""
        assert formatDuration(80000) == "1m 20s"

    def test_extract_heading(self):
        assert extractReasoningHeading("## 标题\n正文") == "标题"
        assert extractReasoningHeading("**重点**\n更多") == "重点"
        assert extractReasoningHeading("") == ""
        # 普通正文不返回首行（避免与思考正文重复展示）
        assert extractReasoningHeading("普通一行") == ""
        assert extractReasoningHeading("- 列表第一项") == ""

    def test_heading_scanner_matches_full_scan(self):
        """随机分片下增量扫描结果与全量抽取完全一致（含优先级）。"""
        fragments = (
            "# ",
            "## ",
            "### ",
            "####### ",
            "标题",
            "重点",
            "普通一行",
            "**",
            "**重点**",
            "**未闭合",
            "  ",
            "\t",
            "\n",
            "\n\n",
            "---",
            "===",
            "--",
            "=",
            "> ",
            "- 列表",
            "1. 项",
            "`代码`",
            "*斜体*",
            "***",
            "文字#后",
            " # ",
            "标题 ",
            "\r",
            "\r\n",
            "\r\r\n",
            "**粗**尾",
            "尾**粗**",
            "# 尾**粗*****",
            "# 行首\t # \r\r\n",
            "#### - - -\t### ###### ###### \r\r\n##",
        )
        rng = random.Random(20260920)
        for _ in range(500):
            text = "".join(rng.choice(fragments) for _ in range(rng.randint(0, 12)))
            scanner = _HeadingScanner()
            index = 0
            while index < len(text):
                size = rng.randint(1, 5)
                scanner.push(text[index : index + size])
                index += size
            assert scanner.result() == extractReasoningHeading(text), repr(text)

    def test_heading_scanner_priority_and_edges(self):
        assert _HeadingScanner().push("# 一级") == "一级"
        scanner = _HeadingScanner()
        scanner.push("**粗体**\n# 后到的 ATX")
        assert scanner.result() == "后到的 ATX"  # ATX 优先级高于加粗
        scanner = _HeadingScanner()
        scanner.push("标题\n=")
        assert scanner.result() == ""
        scanner.push("==")
        assert scanner.result() == "标题"
        assert _HeadingScanner().push("x" * 300) == ""
        assert _HeadingScanner().push("普通") == ""

        # 超长**标题**行两边一致（都视为不可能）：此前 scanner 跳过、全量抽取
        # 仍返回标题（属性测试的片段最长 ~10 字符，漏掉了这条）
        long_bold = "**" + "x" * 300 + "**"
        assert extractReasoningHeading(long_bold) == ""
        assert _HeadingScanner().push(long_bold) == ""

        # 超长行跳过后仍能识别后续标题（含分片跨换行）
        scanner = _HeadingScanner()
        scanner.push("x" * 300)
        scanner.push("\n# 恢复标题")
        assert scanner.result() == "恢复标题"
        scanner = _HeadingScanner()
        scanner.push("y" * 300 + "\n")
        scanner.push("**加粗标题**")
        assert scanner.result() == "加粗标题"


class TestToolCallCard:
    def test_header_labels_no_wrap_no_overlap(self, qapp, make):
        """窄卡片下标题 / 副标题 / 参数摘要单行省略，不换行叠字。

        先把调用**置为完成**再校验布局：运行中参数摘要是隐藏的（参数分片
        流式到达，半截参数会误导且引起整行宽度跳变），隐藏控件不参与布局，
        拿它的 geometry 做重叠断言没有意义。完成后三个标签都可见，才是
        真正需要保证不叠字的场景。
        """

        host = make(QWidget)
        host.resize(360, 200)
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        card = make(
            ToolCallCard,
            name="glob_file",
            arguments='{"pattern": "**/*.py", "limit": 100}',
        )
        layout.addWidget(card)
        layout.addStretch(1)
        host.show()
        card.setResult("找到 12 个文件", ok=True)
        qapp.processEvents()
        for _ in range(10):
            qapp.processEvents()

        labels = (card._title_label, card._subtitle_label, card._args_label)
        for label in labels:
            assert label.wordWrap() is False
            assert "\n" not in label.text()
        assert all(label.isVisible() for label in labels), "完成后三者都应可见"
        rects = [label.geometry() for label in labels]
        for left, right in zip(rects, rects[1:]):
            assert left.right() <= right.left() + 1
        qapp.processEvents()

    def test_args_hidden_while_running_shown_after_done(self, qapp, make):
        """运行中隐藏参数摘要（避免半截参数 + 宽度跳变），完成后出现。"""

        host = QWidget()
        host.resize(420, 200)
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        card = make(
            ToolCallCard,
            name="glob_file",
            arguments='{"pattern": "**/*.py", "limit": 100}',
        )
        layout.addWidget(card)
        layout.addStretch(1)
        host.show()
        qapp.processEvents()

        assert card._args_label.isVisible() is False
        card.setResult("找到 12 个文件", ok=True)
        qapp.processEvents()
        assert card._args_label.isVisible() is True
        qapp.processEvents()

    def test_collapse_updates_ancestor_layout_immediately(self, qapp, make):
        """收起时同步重排祖先布局链（避免逐帧收缩造成视觉抖动）。"""

        host = QWidget()
        host.resize(400, 300)
        layout = QVBoxLayout(host)
        card = make(ToolCallCard, name="read", arguments='{"path": "a.py"}')
        card.setResult("结果行\n" * 6)
        layout.addWidget(card)
        below = QLabel("后续内容", host)
        layout.addWidget(below)
        layout.addStretch(1)
        host.show()
        qapp.processEvents()

        collapsed_height = card.height()
        collapsed_y = below.y()
        card.setOpened(True)
        qapp.processEvents()
        assert below.y() > collapsed_y

        card.setOpened(False)
        # 不经过事件循环：整条祖先链已收缩为最终状态
        assert card.height() == collapsed_height
        assert below.y() == collapsed_y

    def test_default_collapsed_and_pending_locked(self, qapp, make):
        card = make(
            ToolCallCard, name="read", arguments='{"path": "a.py"}', toolCallId="t1"
        )
        assert card.isOpened() is False
        assert card.isExpandable() is True  # 默认 running 可展开
        assert card.isBusy() is True

        card.setStatus(ElaChatToolStatusType.Pending)
        assert card.isExpandable() is False
        card.setOpened(True)
        assert card.isOpened() is False

        card.setStatus(ElaChatToolStatusType.Running)
        assert card.isExpandable() is True
        card.setOpened(True)
        assert card.isOpened() is True

    def test_allow_open_while_pending(self, qapp, make):
        card = make(ToolCallCard, name="shell", toolCallId="t1")
        card.setStatus(ElaChatToolStatusType.Pending)
        assert card.isExpandable() is False
        card.setAllowOpenWhilePending(True)
        assert card.isExpandable() is True

    def test_result_and_error_style(self, qapp, make):
        card = make(ToolCallCard, name="grep", arguments='{"pattern": "x"}')
        card.setResult("结果内容")
        call = card.toolCall()
        assert call.isDone
        assert card.isBusy() is False
        # 隐藏进度环必须同时停掉动画，避免空转
        assert card._busy.getIsBusying() is False

        card.setResult("失败了", ok=False)
        assert card.status() == ElaChatToolStatusType.Error
        assert card.isOpened() is True
        assert card.result() == "失败了"

    def test_body_deferred(self, qapp, make):
        card = make(ToolCallCard, name="read", arguments='{"path": "a.py"}')
        assert card._body_built is False
        card.setStatus(ElaChatToolStatusType.Running)
        card.setOpened(True)
        assert card._body_built is True

    def test_update_result_by_id(self, qapp, make):
        card = make(ToolCallCard, tool_call=ElaChatToolCall(id="t9", name="read"))
        card.updateResult("t9", "内容")
        assert card.toolCall().result == "内容"


class TestContextToolGroup:
    def test_group_summary_and_rows(self, qapp, make):
        group = make(ContextToolGroupCard)
        group.addToolCall(
            ElaChatToolCall(id="1", name="read", arguments='{"path": "a.py"}')
        )
        group.addToolCall(
            ElaChatToolCall(id="2", name="grep", arguments='{"pattern": "x"}')
        )
        group.addToolCall(
            ElaChatToolCall(id="3", name="read", arguments='{"path": "b.py"}')
        )
        assert group.count() == 3
        assert group.summary() == "2 个文件 · 1 次搜索"
        assert group.toolCall("2").name == "grep"
        group.updateResult("2", "命中 3 处")
        assert group.toolCall("2").isDone
        group.finish()
        assert group.title() == "已探索"
        assert group.isBusy() is False


class TestToolGroupPanel:
    def test_inline_surface_matches_reasoning(self, qapp, make):
        """外层面板与思考块同为内联样式，**标题颜色也一致**。

        曾经给工具面板标题叠过强调色以「稍作区分」，实际两头不讨好：0.35 的
        混合比在深色主题下算出 ``#c1eaff``，极淡的青在 13px 小字里读不出着色
        过，浅色主题下却是明显的 ``#002443`` —— 只有深色暴露，结果是同一层级
        里两种几乎一样的亮色。两者靠「>」箭头与文案区分即可（见
        ``ToolGroupPanel._apply_theme`` 的说明与
        ``tests/ela_chat/test_chat_tool_theme.py``）。
        """
        panel = make(ToolGroupPanel)
        reasoning = make(ReasoningBlock)
        assert panel.surfaceVisible() is False
        assert panel.surfaceVisible() == reasoning.surfaceVisible()
        assert panel._title_label.textColor() == reasoning._title_label.textColor()

    def test_panel_counts_and_running(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        first = bubble.addToolCall("read", '{"path": "a.py"}')
        panel = bubble.toolPanel()
        assert panel is not None
        assert panel.isHidden() is False
        assert panel.title() == "工具调用 (0/1)"
        assert panel.isBusy() is True

        bubble.setToolCallResult(first, "文件内容")
        assert panel.title() == "工具调用 (1)"
        assert panel.isBusy() is False
        assert panel.counts() == (1, 1)

        second = bubble.addToolCall("shell", '{"command": "ls"}')
        assert panel.title() == "工具调用 (1/2)"
        bubble.setToolCallResult(second, "写入失败", ok=False)
        assert panel.title() == "工具调用 (2)"
        assert panel.isBusy() is False
        assert panel._busy.getIsBusying() is False

    def test_collapsed_title_summarizes_calls(self, qapp, make):
        """折叠态不能只写「工具调用 (N)」：要能一眼看到调用了什么。"""
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        bubble.resize(800, 400)
        bubble.show()
        qapp.processEvents()
        first = bubble.addToolCall("read", '{"path": "a.py"}')
        panel = bubble.toolPanel()
        text = panel.summary()
        assert "read" in text
        assert "a.py" in text

        bubble.setToolCallResult(first, "内容")
        assert panel.title() == "工具调用 (1)"
        assert 'style="color:' in panel._title_label.text()
        second = bubble.addToolCall("shell", '{"command": "ls"}')
        bubble.setToolCallResult(second, "ok")
        text = panel.summary()
        assert "read" in text
        assert "shell" in text
        assert panel.title() == "工具调用 (2)"

    def test_cards_inside_panel(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        first = bubble.addToolCall("read", '{"path": "a.py"}')
        second = bubble.addToolCall("glob", '{"pattern": "*"}')
        third = bubble.addToolCall("shell", '{"command": "ls"}')
        panel = bubble.toolPanel()
        assert bubble._tool_cards[first].parentWidget() is panel.toolContainer()
        assert bubble._tool_cards[third].parentWidget() is panel.toolContainer()
        # 连续上下文工具仍归组
        assert bubble._tool_cards[first] is bubble._tool_cards[second]
        assert type(bubble._tool_cards[first]).__name__ == "ContextToolGroupCard"

    def test_panel_toggle_emits_bubble_signal(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        bubble.addToolCall("shell", '{"command": "ls"}')
        events = []
        bubble.toolToggled.connect(lambda: events.append(1))
        bubble.toolPanel().setOpened(True)
        assert events == [1]

    def test_clear_removes_panel(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        bubble.addToolCall("shell", '{"command": "ls"}')
        assert bubble.toolPanel() is not None
        bubble.clearToolCalls()
        assert bubble.toolPanel() is None
        assert bubble.toolCallCount() == 0


class TestThinkingAndMeta:
    def _host(self, make, widget):
        host = make(QWidget)
        widget.setParent(host)
        return host

    def test_thinking_row(self, qapp, make):
        row = make(ThinkingRow)
        self._host(make, row)
        row.begin()
        assert row.isHidden() is False
        row.setHeading("分析问题")
        assert row.heading() == "分析问题"
        row.end()
        assert row.isHidden()

    def test_message_meta(self, qapp, make):
        meta = make(MessageMeta)
        self._host(make, meta)
        assert meta.isHidden()
        meta.setDuration(3200)
        assert meta.isHidden() is False
        assert "耗时 3.2s" in meta._label.text()
        meta.setTitle("模型")
        assert "模型" in meta._label.text()

    def test_error_card(self, qapp, make):
        card = make(ErrorCard)
        assert card.isHidden()
        card.setMessage("连接超时")
        assert card.message() == "连接超时"
        card.setMessage("")
        assert card.isHidden()


class TestReasoningStyles:
    def test_collapse_style_uses_single_view(self, qapp, make):
        """折叠形态只用 ReasoningBlock（标题 + 进度环），不叠加思考行。"""
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        bubble.beginReasoning()
        bubble.appendReasoning("第一行正文\n第二行正文")
        block = bubble.reasoningBlock()
        assert block.isOpened() is True
        assert block.isBusy() is True
        assert bubble._thinking_row is None

        bubble.endReasoning(800)
        assert block.isOpened() is False
        assert block.isBusy() is False
        assert "思考完成 (0.8s)" in block.title()
        assert bubble.reasoning() == "第一行正文\n第二行正文"

    def test_collapse_style(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        assert bubble.reasoningStyle() == ElaChatReasoningStyleType.Collapse
        bubble.beginReasoning()
        bubble.appendReasoning("## 拆解\n步骤一")
        bubble.endReasoning(900)
        assert bubble.reasoning() == "## 拆解\n步骤一"
        assert bubble.reasoningBlock().isOpened() is False
        assert "思考完成 (0.9s)" in bubble.reasoningBlock().title()

    def test_inline_style(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        bubble.setReasoningStyle(ElaChatReasoningStyleType.Inline)
        assert bubble.reasoningStyle() == ElaChatReasoningStyleType.Inline
        bubble.beginReasoning()
        bubble.appendReasoning("内联推理内容")
        assert bubble.reasoning() == "内联推理内容"
        viewer = bubble.inlineReasoningViewer()
        assert "内联推理内容" in viewer.markdown()
        bubble.endReasoning(500)
        assert bubble.thinkingRow().isHidden()

    def test_switch_style_rebuilds_content(self, qapp, make):
        """切换形态原位重建：内容 / 耗时保留，不丢数据。"""
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        bubble.setReasoning("旧内容", durationMs=800)
        bubble.setReasoningStyle(ElaChatReasoningStyleType.Inline)
        assert bubble.reasoningStyle() == ElaChatReasoningStyleType.Inline
        assert bubble.reasoning() == "旧内容"
        assert "旧内容" in bubble.inlineReasoningViewer().markdown()

        bubble.setReasoningStyle(ElaChatReasoningStyleType.Collapse)
        assert bubble.reasoningStyle() == ElaChatReasoningStyleType.Collapse
        assert bubble.reasoning() == "旧内容"
        assert "旧内容" in bubble.reasoningBlock().text()
        assert "思考完成 (0.8s)" in bubble.reasoningBlock().title()

    def test_switch_style_mid_stream_keeps_streaming(self, qapp, make):
        """流式中切换形态：已收文本保留、标题重建，继续追加正常。"""
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        bubble.beginStream()
        bubble.beginReasoning()
        bubble.appendReasoning("# 分析步骤\n前半")
        bubble.setReasoningStyle(ElaChatReasoningStyleType.Inline)
        assert bubble.reasoning() == "# 分析步骤\n前半"
        viewer = bubble.inlineReasoningViewer()
        assert viewer.isStreaming() is True
        assert "前半" in viewer.markdown()
        assert bubble.thinkingRow().heading() == "分析步骤"

        bubble.appendReasoning("后半")
        assert bubble.reasoning() == "# 分析步骤\n前半后半"
        bubble.endReasoning(400)
        assert viewer.isStreaming() is False
        assert bubble.thinkingRow().isHidden()


class TestBubbleMetaAndHover:
    def test_duration_and_meta(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        bubble.setDuration(12300)
        assert bubble.duration() == 12300
        assert "耗时 12.3s" in bubble.meta()._label.text()

    def test_actions_hover_reveal(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.User, "hi")
        assert bubble.actionsHoverReveal() is True
        # 占位保留（RetainSizeWhenHidden），避免悬浮时消息区跳动；
        # 隐藏态连绘制一起停掉（QGraphicsOpacityEffect(0) 仍会离屏渲染）。
        assert bubble.actions().isHidden() is True
        assert bubble._actions_effect.opacity() == 0.0
        assert bubble.actions().sizePolicy().retainSizeWhenHidden() is True
        bubble.setActionsHoverReveal(False)
        assert bubble._actions_effect.opacity() == 1.0
        assert bubble.actions().isHidden() is False

    def test_action_tooltips_bound(self, qapp, make):

        bubble = make(ElaChatBubble, ElaChatRoleType.User, "hi")
        for key in ("copy", "undo"):
            button = bubble.actions().toolButton(key)
            assert button.toolTip()
            assert button in _tooltip_dict

    def test_hidden_actions_mouse_transparent(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.User, "hi")
        copy_button = bubble.actions().toolButton("copy")
        transparent = Qt.WidgetAttribute.WA_TransparentForMouseEvents
        assert copy_button.testAttribute(transparent) is True
        bubble._set_actions_revealed(True)
        assert copy_button.testAttribute(transparent) is False
        # 动态追加的自定义动作同样继承穿透状态
        bubble._set_actions_revealed(False)
        custom = bubble.actions().addCustomAction("fav", tooltip="收藏")
        assert custom.testAttribute(transparent) is True

    def test_hover_does_not_shift_layout(self, qapp, make):

        view = make(ElaChatView)
        view.resize(600, 400)
        view.show()
        qapp.processEvents()
        messageId = view.addMessage(ElaChatRoleType.User, "hi")
        qapp.processEvents()
        bubble = view.bubble(messageId)
        content = view.contentWidget()
        before = content.sizeHint().height()
        before_actions_height = bubble.actions().height()
        bubble._set_actions_revealed(True)
        qapp.processEvents()
        assert content.sizeHint().height() == before
        assert bubble.actions().height() == before_actions_height

    def test_tool_grouping_in_bubble(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        first = bubble.addToolCall("read", '{"path": "a.py"}')
        second = bubble.addToolCall("glob", '{"pattern": "*"}')
        third = bubble.addToolCall("shell", '{"command": "ls"}')
        assert type(bubble._tool_cards[first]).__name__ == "ContextToolGroupCard"
        assert bubble._tool_cards[first] is bubble._tool_cards[second]
        assert type(bubble._tool_cards[third]).__name__ == "ToolCallCard"
        assert bubble.toolCallCount() == 3
        assert [call.name for call in bubble.toolCalls()] == [
            "read",
            "glob",
            "shell",
        ]
        bubble.clearToolCalls()
        assert bubble.toolCallCount() == 0

    def test_tool_grouping_disabled(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        bubble.setToolGrouping(False)
        first = bubble.addToolCall("read", '{"path": "a.py"}')
        second = bubble.addToolCall("glob", '{"pattern": "*"}')
        assert type(bubble._tool_cards[first]).__name__ == "ToolCallCard"
        assert type(bubble._tool_cards[second]).__name__ == "ToolCallCard"


class TestReasoningReplacement:
    def test_set_reasoning_replaces_and_closes_previous(self, qapp, make):
        """``setReasoning`` 先收尾在途段再复用：不丢缓冲、不留永久转圈。"""
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        bubble.beginStream()
        bubble.beginReasoning()
        bubble.appendReasoning("旧内容")
        bubble.setReasoning("新内容")

        parts = [p for p in bubble.parts() if p.kind == ElaChatPartKindType.Reasoning]
        assert len(parts) == 1
        assert parts[0].text == "新内容"
        assert bubble.reasoning() == "新内容"

        bubble.endStream()
        assert bubble.reasoning() == "新内容"


class TestDefaultOpenBody:
    def test_default_open_builds_body_when_shown(self, qapp, make):
        """初始展开的卡首次显示就要有正文（不能箭头朝下却空白）。"""
        card = make(
            ToolCallCard, name="bash", arguments='{"cmd": "ls"}', defaultOpen=True
        )
        card.resize(640, 200)
        card.show()
        qapp.processEvents()
        assert card._body_built is True
        assert card.bodyLayout().count() > 0

    def test_default_open_builds_body_on_message_id(self, qapp, make):
        card = make(ToolCallCard, name="bash", arguments="{}", defaultOpen=True)
        card.setMessageId(7)
        assert card._body_built is True


class TestConstructorParentFirst:
    def test_parent_is_first_positional(self, qapp, make):
        host = make(QWidget)
        card = make(ToolCallCard, host)
        assert card.parent() is host

    def test_shell_like_tools_allow_open_while_pending(self, qapp, make):
        """shell 类清单与默认展开策略共用 blocks.SHELL_TOOLS，不再两处漂移。"""
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        bubble.setToolGrouping(False)

        shell_card = bubble._tool_cards[bubble.addToolCall("run", '{"cmd": "ls"}')]
        shell_card.setStatus(ElaChatToolStatusType.Pending)
        assert shell_card.isExpandable() is True

        read_card = bubble._tool_cards[bubble.addToolCall("read", '{"path": "a"}')]
        read_card.setStatus(ElaChatToolStatusType.Pending)
        assert read_card.isExpandable() is False
