"""回归测试：聊天组件的**架构契约**。

这一组不再描述「两层如何协作」，而是**守住删掉转发层之后的架构**。

背景
----
``ElaChatWidget`` 曾经把 ``ElaChatView`` 的 54 个方法原样转发上来（只把
``messageId`` 从首位挪到末位）。代价是：

- 公开面翻倍（widget 101 个方法里 52 个无自有逻辑）；
- **同一个操作有两个签名**，宿主混用时本该是消息 id 的值会落到别的参数上，
  而 ``messageId`` 走默认值恰好解析成合法的当前流式消息 —— target 正常、
  不报错、不告警，只是数据写错地方。

删除转发层后，**消息操作只有 ``ElaChatView`` 一个入口**、只有一套签名，
上述整类问题从结构上消失。本测试用两条规则把它钉死：

1. ``ElaChatWidget`` 上**不允许**出现「纯转发到同名 view 方法」的方法；
2. ``ElaChatView`` 上带 ``messageId`` 的方法，``messageId`` 必须在**首位**。

外加类型校验（任何模式下非 int 的 id 都抛 ``TypeError``）与 strict 模式的
行为边界。
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from pyqt6_ela_pro.chat import ElaChatInput, ElaChatView, ElaChatWidget
from pyqt6_ela_pro.chat.message import ElaChatStats, ElaChatStatusType

_WIDGET_SOURCE = Path(inspect.getfile(ElaChatWidget)).with_suffix(".py")


def _chat(qapp) -> ElaChatWidget:
    chat = ElaChatWidget()
    chat.resize(700, 500)
    chat.show()
    qapp.processEvents()
    return chat


def _pure_forwarders(cls) -> list:
    """找出「只把参数转发给 ``self._view.<同名>()``」的方法。"""
    tree = ast.parse(inspect.getsource(cls))
    node = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.ClassDef) and n.name == cls.__name__
    )
    found = []
    for func in node.body:
        if not isinstance(func, ast.FunctionDef) or func.name.startswith("_"):
            continue
        # 有控制流 / 抛错 / 循环 => 有自身逻辑
        if any(
            isinstance(n, (ast.Raise, ast.Try, ast.While, ast.For, ast.If))
            for n in ast.walk(func)
        ):
            continue
        calls = [
            c
            for c in ast.walk(func)
            if isinstance(c, ast.Call)
            and isinstance(c.func, ast.Attribute)
            and isinstance(c.func.value, ast.Attribute)
            and c.func.value.attr == "_view"
        ]
        if len(calls) == 1 and calls[0].func.attr == func.name:
            found.append(func.name)
    return found


# ---------------------------------------------------------------- 架构规则
class TestNoPassThroughLayer:
    def test_widget_has_no_pure_forwarders(self):
        """widget 上不得再出现「纯转发到同名 view 方法」的方法。

        这是删除 54 个转发层后最关键的一条：不守住它，转发层会随新功能
        一点点长回来，两套签名与跨层混用问题随之复现。
        """
        found = _pure_forwarders(ElaChatWidget)
        assert not found, (
            "ElaChatWidget 重新出现了纯转发方法："
            f"{found}。消息操作只应通过 chatView() 暴露 —— "
            "widget 保留的是「输入区 + 回合编排」这一层自己的职责。"
        )

    def test_view_message_id_is_first(self):
        """view 层：``messageId`` 一律在首位（唯一一套签名）。

        例外是**工厂方法**（``addMessage`` / ``addMessageFromDict``）：它们
        *创建*消息，此刻还没有已存在的消息可寻址，主参数是 ``role`` / ``data``。
        """
        factories = ("addMessage", "addMessageFromDict")
        violations = []
        for name in sorted(dir(ElaChatView)):
            if name.startswith("_") or name in factories:
                continue
            fn = getattr(ElaChatView, name, None)
            if not inspect.isfunction(fn):
                continue
            params = [p for p in inspect.signature(fn).parameters if p != "self"]
            if "messageId" in params and params[0] != "messageId":
                violations.append(f"{name}: {params}")
        assert not violations, "view 层 messageId 位置漂移：" + "; ".join(violations)

    def test_factory_methods_keep_message_id_optional_last(self):
        """工厂方法的例外是**显式**的，不是漏检 —— 签名变了要重新评估。"""
        for name, primary in (("addMessage", "role"), ("addMessageFromDict", "data")):
            params = [
                p
                for p in inspect.signature(getattr(ElaChatView, name)).parameters
                if p != "self"
            ]
            assert params[0] == primary and params[-1] == "messageId", (
                f"{name} 签名变成 {params} —— 请重新评估是否还算工厂方法例外"
            )

    def test_widget_keeps_its_own_responsibilities(self):
        """widget 仍必须保有「输入区 + 回合编排」这一层自己的东西。"""
        for name in (
            "chatView",
            "chatInput",
            "sendUserMessage",
            "beginAssistantMessage",
            "endAssistantMessage",
            "stopGeneration",
            "undoMessage",
            "undoLastUserMessage",
            "regenerateFrom",
            "retryMessage",
            "enqueueMessage",
            "sendNextQueued",
            "steerMessage",
            "drainSteer",
            "isGenerating",
            "streamingMessageId",
            "toolBar",
            "newTopicRequested",
        ):
            assert hasattr(ElaChatWidget, name), f"widget 丢失了 {name}"

    def test_view_docstring_lists_only_real_switches(self):
        """class docstring 的「性能开关」一栏不得列出 view 上不存在的名字。

        这条是被真实漂移逼出来的：docstring 长期把 ``setRenderDeferred`` /
        ``flushRender`` / ``hasPendingRender`` 列为 view 的性能开关，实际它们
        只在 :class:`ElaChatBubble` 上（view 仅在批量渲染路径里内部调用）。
        宿主照着 docstring 写 ``view.setRenderDeferred(True)`` 直接
        ``AttributeError``。docstring 是纯文档、无测试守护，最容易悄悄过期。
        """
        doc = inspect.getdoc(ElaChatView) or ""
        start = doc.find("**性能开关")
        assert start > 0, "view docstring 丢了「性能开关」一栏"
        section = doc[start : doc.find("3.", start)]
        for name in (
            "setRenderDeferred",
            "renderDeferred",
            "flushRender",
            "hasPendingRender",
        ):
            if name in section:
                # 允许出现，但必须明确说明「只在 bubble 上」
                assert "bubble" in section.lower(), (
                    f"docstring 的性能开关一栏提到 {name}，"
                    "但没说它其实只在 ElaChatBubble 上"
                )
        for name in (
            "beginBatch",
            "endBatch",
            "setViewportSuspension",
            "setResizeReflowDeferred",
        ):
            assert name in section, f"docstring 的性能开关一栏漏了 {name}"

    def test_message_operations_only_on_view(self):
        """典型消息操作只存在于 view 层。"""
        for name in (
            "appendText",
            "addToolCall",
            "messages",
            "message",
            "addMessageFromDict",
            "restoreMessages",
            "setStepStats",
        ):
            assert hasattr(ElaChatView, name), f"view 缺少 {name}"
            assert not hasattr(ElaChatWidget, name), (
                f"widget 又暴露了 {name} —— 会重新制造两套签名"
            )

    def test_agent_operations_only_on_view(self):
        """审批 / 压缩 / 插话回执是**消息内容**，只该在 view 层。

        它们改的是 ``parts`` 时间线（唯一真源），放到 widget 就是第二套入口 ——
        和当初那 54 个转发方法是同一类问题。
        """
        for name in (
            "beginPermission",
            "resolvePermission",
            "pendingPermissions",
            "permissionCard",
            "beginCompaction",
            "appendCompactionSummary",
            "endCompaction",
            "addSteerNotice",
            "clearMessageError",
            "messageError",
        ):
            assert hasattr(ElaChatView, name), f"view 缺少 {name}"
            assert not hasattr(ElaChatWidget, name), (
                f"widget 又暴露了 {name} —— 消息内容操作只应走 chatView()"
            )

    def test_context_usage_lives_on_input(self):
        """上下文占用圆环长在**输入区工具栏** → API 归 ``ElaChatInput``。

        它既不是消息内容（不该在 view —— 浮层版本会压住第一条消息的用户
        头像，且视图未显示时定位会卡在 ``(0, 0)``），也不该被 widget 转发。
        """
        for name in (
            "setContextUsage",
            "contextUsage",
            "contextUsagePercent",
            "contextUsageWidget",
            "setContextUsageVisible",
            "contextUsageVisible",
        ):
            assert hasattr(ElaChatInput, name), f"input 缺少 {name}"
            assert not hasattr(ElaChatWidget, name), (
                f"widget 又暴露了 {name} —— 输入区操作只应走 chatInput()"
            )
            assert not hasattr(ElaChatView, name), (
                f"view 还留着 {name} —— 占用圆环已归位到输入区工具栏"
            )


# ---------------------------------------------------------------- 类型校验
class TestMessageIdTypeIsEnforced:
    @pytest.mark.parametrize("bad", ["999", 1.0, True, 1.5, [1]])
    def test_non_int_id_always_raises(self, qapp, bad):
        """非 int 的 id **任何模式下**都抛。

        不存在的整数 id 可能是合法的迟到事件（该静默），但非整数 id 必然是
        调用方笔误 —— 静默吞掉只会让「id 传错」彻底隐形。
        """
        chat = _chat(qapp)
        view = chat.chatView()
        for strict in (False, True):
            view.setStrictIds(strict)
            with pytest.raises(TypeError):
                view.appendText(bad, "x")
        chat.deleteLater()
        qapp.processEvents()

    def test_valid_int_id_does_not_raise_on_type(self, qapp):
        chat = _chat(qapp)
        messageId = chat.chatView().addMessage("assistant", "")
        chat.chatView().setStrictIds(False)
        chat.chatView().appendText(messageId, "x")  # 不存在的整数 id -> 静默
        chat.deleteLater()
        qapp.processEvents()

    def test_error_message_is_actionable(self, qapp):
        chat = _chat(qapp)
        with pytest.raises(TypeError, match="messageId"):
            chat.chatView().appendText("999", "x")
        chat.deleteLater()
        qapp.processEvents()


# ---------------------------------------------------------------- strict
class TestStrictIds:
    def test_off_by_default(self, qapp):
        chat = _chat(qapp)
        assert chat.chatView().strictIds() is False
        chat.deleteLater()
        qapp.processEvents()

    @pytest.mark.parametrize(
        "call",
        [
            lambda v: v.appendText(999, "x"),
            lambda v: v.beginText(999),
            lambda v: v.endText(999),
            lambda v: v.endMessage(999),
            lambda v: v.beginReasoning(999),
            lambda v: v.appendReasoning(999, "x"),
            lambda v: v.endReasoning(999),
            lambda v: v.updateMessage(999, "t"),
            lambda v: v.setMessageError(999, "e"),
            lambda v: v.setMessageDuration(999, 1.0),
            lambda v: v.setStepStats(999, None),
            lambda v: v.beginStep(999),
            lambda v: v.addToolCall(999, "n"),
            lambda v: v.setToolCallResult(999, "c", "r"),
        ],
    )
    def test_off_silent_on_unknown_id(self, qapp, call):
        """默认关闭：未知整数 id 静默忽略（流式迟到事件的正确行为）。"""
        chat = _chat(qapp)
        call(chat.chatView())
        chat.deleteLater()
        qapp.processEvents()

    @pytest.mark.parametrize(
        "call",
        [
            lambda v: v.appendText(999, "x"),
            lambda v: v.beginText(999),
            lambda v: v.endMessage(999),
            lambda v: v.setMessageError(999, "e"),
            lambda v: v.setStepStats(999, None),
        ],
    )
    def test_on_raises_key_error(self, qapp, call):
        chat = _chat(qapp)
        chat.chatView().setStrictIds(True)
        with pytest.raises(KeyError):
            call(chat.chatView())
        chat.deleteLater()
        qapp.processEvents()

    def test_key_error_lists_existing_ids(self, qapp):
        chat = _chat(qapp)
        messageId = chat.chatView().addMessage("assistant", "")
        chat.chatView().setStrictIds(True)
        with pytest.raises(KeyError) as info:
            chat.chatView().appendText(999, "x")
        assert str(messageId) in str(info.value)
        chat.deleteLater()
        qapp.processEvents()

    def test_legal_id_works_in_strict_mode(self, qapp):
        chat = _chat(qapp)
        view = chat.chatView()
        messageId = view.beginMessage()
        view.setStrictIds(True)
        view.appendText(messageId, "strict 下正常")
        view.endMessage(messageId)
        qapp.processEvents()
        assert view.message(messageId).text == "strict 下正常"
        assert view.message(messageId).status == ElaChatStatusType.Done
        chat.deleteLater()
        qapp.processEvents()

    def test_internal_paths_stay_silent_even_in_strict_mode(self, qapp):
        """内部路径（滚动 / 挂起 / 分段同步）不得因 strict 抛错。

        它们在消息消失时**必须**继续静默，否则滚动到底部就炸。
        """
        chat = _chat(qapp)
        view = chat.chatView()
        for index in range(3):
            view.addMessage("assistant", f"内容 {index}")
        qapp.processEvents()
        view.setStrictIds(True)
        view._flush_pending_syncs()
        view._restore_all_suspended()
        view.scrollToBottom()
        view._follow_bottom()
        qapp.processEvents()

    def test_late_event_after_undo(self, qapp):
        """真实场景：消息被撤回后后端还在发分片 —— 默认静默忽略。"""
        chat = _chat(qapp)
        view = chat.chatView()
        messageId = view.beginMessage()
        view.appendText(messageId, "x")
        view.removeMessage(messageId)
        qapp.processEvents()
        view.appendText(messageId, "迟到分片")
        assert view.message(messageId) is None
        chat.deleteLater()
        qapp.processEvents()


# ---------------------------------------------------------------- 端到端
class TestEndToEnd:
    def test_full_turn_via_view_then_widget(self, qapp):
        """一轮完整流式：widget 管回合编排，view 管消息内容。"""
        chat = _chat(qapp)
        view = chat.chatView()

        messageId = chat.beginAssistantMessage()
        view.beginReasoning(messageId)
        for chunk in "分析中":
            view.appendReasoning(messageId, chunk)
        view.endReasoning(messageId, 300.0)
        for chunk in "**答案**":
            view.appendText(messageId, chunk)
        callId = view.addToolCall(messageId, "read", "{}")
        view.setToolCallResult(messageId, callId, "内容", ok=True)
        view.setStepStats(messageId, ElaChatStats(total_tokens=5))
        view.setMessageDuration(messageId, 1500.0)
        chat.endAssistantMessage(messageId)
        qapp.processEvents()

        message = chat.chatView().message(messageId)
        assert message.text == "**答案**"
        assert message.reasoning == "分析中"
        assert message.reasoning_ms == 300.0
        assert message.duration_ms == 1500.0
        assert [(c.name, c.status) for c in message.tool_calls] == [("read", "done")]
        assert message.stats.total_tokens == 5
        chat.deleteLater()
        qapp.processEvents()

    def test_storage_round_trip_through_view(self, qapp):
        chat = _chat(qapp)
        view = chat.chatView()
        messageId = chat.beginAssistantMessage()
        view.appendText(messageId, "落库内容")
        chat.endAssistantMessage(messageId)
        qapp.processEvents()
        rows = [m.toDict() for m in view.messages()]

        fresh = _chat(qapp)
        restoredId = fresh.chatView().addMessageFromDict(rows[0])
        qapp.processEvents()
        assert (
            fresh.chatView().message(restoredId).parts == view.message(messageId).parts
        )
        chat.deleteLater()
        fresh.deleteLater()
        qapp.processEvents()
