"""批量加载的懒渲染：先渲染最新一屏，更早的消息在滚动到顶部时分页补齐。

用户打开历史会话时视线停在底部，因此 ``endBatch`` 先渲染最新的
``_BATCH_EAGER_COUNT`` 条；其余留在 ``_lazy_ids``，滚到接近顶部时按页渲染并
补偿滚动位置。数据快照（``messages()`` / ``message()``）不依赖渲染，始终完整。
"""

from __future__ import annotations

from _qthelpers import wait_until as _wait_until
from pyqt6_ela_pro.chat import ElaChatPartKindType, ElaChatRoleType, ElaChatView

MD = "## 标题\n\n这是**回答**，包含 `代码` 与列表：\n\n- 项目一\n- 项目二\n"


def _batch_view(make, qapp, count: int = 100):
    view = make(ElaChatView)
    view.resize(480, 320)
    view.show()
    qapp.processEvents()
    events = []
    view.batchRenderFinished.connect(lambda: events.append(True))
    view.beginBatch()
    ids = [view.addMessage(ElaChatRoleType.Assistant, MD) for _ in range(count)]
    view.endBatch()
    assert _wait_until(
        qapp,
        lambda: not view.bubble(ids[-1]).renderDeferred(),
        timeout_ms=5000,
    )
    assert events == [True]
    assert _wait_until(
        qapp,
        lambda: view._scroll.verticalScrollBar().maximum() > 0,
        timeout_ms=5000,
    )
    return view, ids


class TestBatchLazyRendering:
    def test_latest_rendered_older_deferred(self, qapp, make):
        view, ids = _batch_view(make, qapp)
        assert not view.bubble(ids[-1]).renderDeferred()
        assert view.bubble(ids[0]).renderDeferred() is True
        assert view._lazy_ids == sorted(view._lazy_ids)
        # 懒加载队列只包含未渲染的旧消息
        assert view._lazy_ids
        assert min(view._lazy_ids) < max(ids)

    def test_snapshot_complete_without_rendering(self, qapp, make):
        view, ids = _batch_view(make, qapp)
        lazy_id = view._lazy_ids[-1]
        assert view.bubble(lazy_id).renderDeferred() is True
        message = view.message(lazy_id)
        assert message.text == MD
        # 快照读路径会结算 parts（数据齐全，不依赖 viewer 是否渲染）
        assert [part.kind for part in message.parts] == [ElaChatPartKindType.Text]

    def test_pages_drain_all_messages(self, qapp, make):
        view, ids = _batch_view(make, qapp)
        for _ in range(len(ids)):
            if not view._lazy_ids:
                break
            view._load_older_page()
        assert not view._lazy_ids
        assert all(not view.bubble(mid).renderDeferred() for mid in ids)

    def test_clear_resets_lazy_state(self, qapp, make):
        view, _ids = _batch_view(make, qapp)
        assert view._lazy_ids
        view.clear()
        assert view._lazy_ids == []
        assert view._pending_anchor is None
        assert view._lazy_timer.isActive() is False
