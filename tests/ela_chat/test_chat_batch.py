"""批量加载与渐进渲染测试（``beginBatch`` / ``endBatch``）。"""

from __future__ import annotations

from _qthelpers import wait_until as _wait_until

from pyqt6_ela_pro.chat import (
    ElaChatPartKindType,
    ElaChatRoleType,
    ElaChatView,
    ElaChatWidget,
)

MD = "## 标题\n\n这是**回答**，包含 `代码` 与列表：\n\n- 项目一\n- 项目二\n"


class TestBatchRendering:
    def test_defers_markdown_until_end(self, qapp, make):
        view = make(ElaChatView)
        view.resize(480, 320)
        view.show()
        qapp.processEvents()

        view.beginBatch()
        assert view.isBatchActive() is True
        first = view.addMessage(ElaChatRoleType.Assistant, MD)
        second = view.addMessage(ElaChatRoleType.Assistant, MD)
        bubble = view.bubble(first)
        assert bubble.renderDeferred() is True
        assert bubble.hasPendingRender() is True
        # 延迟期间：快照 text 正确，parts 尚未同步，viewer 未渲染
        assert view.message(first).text == MD
        assert view.message(first).parts == ()
        assert bubble.markdownViewer().markdown() == ""
        view.endBatch()
        assert view.isBatchActive() is False

        assert _wait_until(
            qapp,
            lambda: (
                "标题" in view.bubble(first).markdownViewer().markdown()
                and "标题" in view.bubble(second).markdownViewer().markdown()
            ),
        )
        message = view.message(first)
        assert message.text == MD
        assert [part.kind for part in message.parts] == [ElaChatPartKindType.Text]
        assert view.bubble(first).hasPendingRender() is False

    def test_batch_finished_signal_once(self, qapp, make):
        view = make(ElaChatView)
        view.resize(480, 320)
        view.show()
        qapp.processEvents()
        events = []
        view.batchRenderFinished.connect(lambda: events.append(True))

        view.beginBatch()
        view.addMessage(ElaChatRoleType.Assistant, MD)
        view.endBatch()
        assert _wait_until(qapp, lambda: bool(events))
        assert events == [True]

    def test_nested_batch_starts_once(self, qapp, make):
        view = make(ElaChatView)
        view.resize(480, 320)
        view.show()
        qapp.processEvents()
        events = []
        view.batchRenderFinished.connect(lambda: events.append(True))

        view.beginBatch()
        view.beginBatch()
        messageId = view.addMessage(ElaChatRoleType.Assistant, MD)
        view.endBatch()
        assert view.isBatchActive() is True
        assert view.bubble(messageId).renderDeferred() is True
        view.endBatch()
        assert view.isBatchActive() is False
        assert _wait_until(qapp, lambda: bool(events))
        assert events == [True]

    def test_outside_batch_renders_immediately(self, qapp, make):
        view = make(ElaChatView)
        view.resize(480, 320)
        view.show()
        qapp.processEvents()
        messageId = view.addMessage(ElaChatRoleType.Assistant, MD)
        assert view.bubble(messageId).renderDeferred() is False
        assert "标题" in view.bubble(messageId).markdownViewer().markdown()

    def test_batch_user_message_not_deferred(self, qapp, make):
        view = make(ElaChatView)
        view.resize(480, 320)
        view.show()
        qapp.processEvents()
        view.beginBatch()
        messageId = view.addMessage(ElaChatRoleType.User, "用户消息")
        assert view.bubble(messageId).renderDeferred() is False
        view.endBatch()
        assert view.message(messageId).text == "用户消息"

    def test_widget_passthrough(self, qapp, make):
        chat = make(ElaChatWidget)
        chat.resize(480, 320)
        chat.show()
        qapp.processEvents()
        events = []
        chat.batchRenderFinished.connect(lambda: events.append(True))
        chat.chatView().beginBatch()
        assert chat.chatView().isBatchActive() is True
        messageId = chat.addMessage(ElaChatRoleType.Assistant, MD)
        chat.chatView().endBatch()
        assert chat.chatView().isBatchActive() is False
        assert _wait_until(qapp, lambda: bool(events))
        assert "标题" in chat.chatView().message(messageId).text

    def test_batch_renders_latest_then_lazy_older(self, qapp, make):
        """先渲染最新的一屏；更早的消息留给滚动懒加载（不阻塞首屏）。"""
        view = make(ElaChatView)
        view.resize(480, 320)
        view.show()
        qapp.processEvents()
        count = 200
        view.beginBatch()
        ids = [view.addMessage(ElaChatRoleType.Assistant, MD) for _ in range(count)]
        view.endBatch()
        assert view.count() == count
        assert _wait_until(
            qapp,
            lambda: not view.bubble(ids[-1]).renderDeferred(),
            timeout_ms=5000,
        )
        # 最新的一定渲染完；最老的留在懒加载队列里（数据快照仍然完整）
        assert view.bubble(ids[0]).renderDeferred() is True
        assert view._lazy_ids, "应有未渲染的旧消息"
        assert view.message(ids[0]).text == MD
        assert view.message(ids[0]).parts != ()
        # 手动排空懒加载页（等价于逐屏向上滚动）
        for _ in range(count):
            if not view._lazy_ids:
                break
            view._load_older_page()
        assert not view._lazy_ids
        assert all(not view.bubble(mid).renderDeferred() for mid in ids)
        assert view.message(ids[0]).parts != ()


class TestRestorePartsDeferredRendering:
    """``restoreMessages`` 的主流形态（带 parts 的现代存档）也走渐进渲染。

    判据不是「text 是不是空串」—— 带 parts 的消息正文在 parts 里，早先因此
    全部同步渲染，几百条历史的批量加载在主线程一次性渲染全部 Markdown。
    """

    def test_parts_messages_are_deferred_and_filled(self, qapp, make):
        view = make(ElaChatView)
        view.resize(480, 320)
        view.show()
        qapp.processEvents()
        count = 60
        rows = [
            {
                "role": "assistant",
                "text": MD,
                "status": "done",
                "parts": [{"kind": "text", "text": MD, "status": "done", "step": 1}],
            }
            for _ in range(count)
        ]

        view.beginBatch()
        ids = view.restoreMessages(rows)
        view.endBatch()

        assert len(ids) == count
        # 最新的先渲染（首屏），更早的消息继续留在懒加载队列
        assert _wait_until(
            qapp,
            lambda: not view.bubble(ids[-1]).renderDeferred(),
            timeout_ms=5000,
        )
        assert view.bubble(ids[0]).renderDeferred() is True
        # 快照当场可读（导出 / 读路径不能等渲染排空）
        assert view.message(ids[0]).text == MD
        # 排空懒加载页后所有查看器都补上
        for _ in range(count):
            if not view._lazy_ids:
                break
            view._load_older_page()
        assert "标题" in view.bubble(ids[0]).markdownViewer().markdown()
        assert "标题" in view.bubble(ids[-1]).markdownViewer().markdown()


class TestClearDuringProgressiveRender:
    """渐进渲染未排空时 ``clear()``：视口刷新必须自己恢复。

    ``beginBatch`` 关掉了视口刷新，而恢复只写在 ``_finish_batch_render`` 里；
    ``clear()`` 把渲染队列清空、定时器停掉，那次 ``endBatch`` 之后没人会再走到
    那个函数 —— 视口就永久不再重绘（连空态和之后新增的消息都不显示）。
    """

    def test_clear_restores_viewport_updates(self, qapp, make):
        view = make(ElaChatView)
        view.resize(480, 320)
        view.show()
        qapp.processEvents()

        view.beginBatch()
        view.addMessage(ElaChatRoleType.Assistant, MD)
        view.endBatch()  # 队列非空 -> 启动渐进渲染定时器
        assert view._scroll.viewport().updatesEnabled() is False

        view.clear()

        assert view._scroll.viewport().updatesEnabled() is True
        qapp.processEvents()
        view.addMessage(ElaChatRoleType.Assistant, "清空之后的新消息")
        assert "清空之后的新消息" in view.message(view.messages()[-1].id).text

    def test_clear_inside_batch_is_settled_by_end_batch(self, qapp, make):
        view = make(ElaChatView)
        view.resize(480, 320)
        view.show()
        qapp.processEvents()

        view.beginBatch()
        view.addMessage(ElaChatRoleType.Assistant, MD)
        view.clear()
        assert view.isBatchActive() is True, "batch 深度归零是 endBatch 的职责"
        view.endBatch()

        assert view._scroll.viewport().updatesEnabled() is True
