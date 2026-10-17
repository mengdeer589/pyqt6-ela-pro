"""dock 内容槽的所有权协议与快照隔离。

三条曾经的缺陷：

1. :class:`ElaChatInputDock` **自己发明了一套所有权**（无条件 ``deleteLater()``），
   既不用 :class:`~pyqt6_ela_pro.ContentSlot`（AGENTS.md 要求带内容槽的容器一律
   用它），也没有 ``sip.isdeleted`` 守卫 —— 宿主若已自行销毁传进来的控件，
   ``clear()`` 会抛 ``RuntimeError``（从 Qt 槽里调即 0xC0000409）。
2. 换内容 / ``clear()`` 时旧控件被无条件删除，调用方拿不回句柄。
3. :meth:`ElaChatQueueDock.messages` 只做 ``dict(item)`` 浅拷贝，``attachments``
   仍是内部那个 list 对象 —— 改快照会改到内部状态。
"""

from __future__ import annotations

import pytest
from PyQt6 import sip
from PyQt6.QtCore import QCoreApplication, QEvent
from PyQt6.QtWidgets import QWidget

from pyqt6_ela_pro import ElaWidgetOwnershipType
from pyqt6_ela_pro.chat.docks import ElaChatInputDock, ElaChatQueueDock


def _flush_deferred_delete(qapp, obj) -> None:
    """``processEvents()`` **不**派发 ``DeferredDelete``（见 AGENTS.md）。"""
    qapp.processEvents()
    QCoreApplication.sendPostedEvents(obj, QEvent.Type.DeferredDelete)
    qapp.processEvents()


class TestInputDockOwnership:
    def test_borrowed_is_returned_not_deleted(self, qapp, make):
        dock = make(ElaChatInputDock)
        panel = make(QWidget)
        assert dock.setWidget(panel) is True
        assert dock.ownership() == ElaWidgetOwnershipType.Borrowed

        dock.clear()
        qapp.processEvents()
        assert not sip.isdeleted(panel), "Borrowed 必须交还调用方，不得删除"
        assert panel.parent() is None
        assert dock.widget() is None

    def test_owned_is_deleted(self, qapp, make):
        dock = make(ElaChatInputDock)
        panel = QWidget()
        assert dock.setWidget(panel, ownership=ElaWidgetOwnershipType.Owned) is True
        dock.clear()
        _flush_deferred_delete(qapp, panel)
        assert sip.isdeleted(panel), "Owned 必须由容器 deleteLater"

    def test_replacing_disposes_the_old_widget_by_its_own_policy(self, qapp, make):
        """回归：换内容时旧控件曾被直接丢弃（Owned 永不删、Borrowed 变无主孤儿）。"""
        dock = make(ElaChatInputDock)
        old, new = make(QWidget), make(QWidget)
        dock.setWidget(old, ownership=ElaWidgetOwnershipType.Owned)
        assert dock.setWidget(new) is True
        _flush_deferred_delete(qapp, old)
        assert sip.isdeleted(old), "Owned 的旧控件应被删除"
        assert dock.widget() is new

    def test_replacing_returns_a_borrowed_old_widget(self, qapp, make):
        dock = make(ElaChatInputDock)
        old, new = make(QWidget), make(QWidget)
        dock.setWidget(old)  # 默认 Borrowed
        assert dock.setWidget(new) is True
        assert not sip.isdeleted(old), "Borrowed 的旧控件必须交还调用方"
        assert old.parent() is None
        assert dock.widget() is new

    def test_clear_survives_a_host_deleted_widget(self, qapp, make):
        """回归：曾抛 ``RuntimeError: wrapped C/C++ object ... has been deleted``。"""
        dock = make(ElaChatInputDock)
        panel = QWidget()
        dock.setWidget(panel)
        sip.delete(panel)  # 宿主自己先删了
        qapp.processEvents()
        dock.clear()  # 不得抛
        assert dock.widget() is None

    def test_external_destroy_collapses_the_dock(self, qapp, make):
        dock = make(ElaChatInputDock)
        seen = []
        dock.changed.connect(seen.append)
        panel = QWidget()
        dock.setWidget(panel)
        assert seen == [True]

        sip.delete(panel)
        qapp.processEvents()
        assert dock.widget() is None
        assert dock.replacesInput() is False
        assert seen[-1] is False

    def test_replaces_input_tracks_the_replace_flag(self, qapp, make):
        dock = make(ElaChatInputDock)
        assert dock.replacesInput() is False
        dock.setWidget(make(QWidget), replace=True)
        assert dock.replacesInput() is True
        dock.setWidget(make(QWidget), replace=False)
        assert dock.replacesInput() is False

    def test_set_none_collapses(self, qapp, make):
        dock = make(ElaChatInputDock)
        panel = make(QWidget)
        dock.setWidget(panel)
        assert dock.setWidget(None) is True
        assert dock.widget() is None

    def test_rejects_self_and_ancestor(self, qapp, make):
        dock = make(ElaChatInputDock)
        assert dock.setWidget(dock) is False, "不能把自己挂进自己"

        # 把 dock 放进 outer，再把 outer 挂进 dock —— outer 是 dock 的祖先
        outer = make(QWidget)
        inner_dock = make(ElaChatInputDock, outer)
        assert inner_dock.setWidget(outer) is False, "不能把 dock 的祖先挂进自己"

    def test_rejects_non_widget(self, qapp, make):
        dock = make(ElaChatInputDock)
        assert dock.setWidget("not a widget") is False  # type: ignore[arg-type]

    def test_title_still_works(self, qapp, make):
        dock = make(ElaChatInputDock)
        dock.setTitle("标题")
        assert dock.title() == "标题"
        dock.setTitle("")
        assert dock.title() == ""


class TestChatWidgetDockPassthrough:
    """``ElaChatWidget`` 的公开入口要透传 ownership 并返回成功与否。"""

    def test_set_dock_widget_returns_bool(self, qapp, make):
        from pyqt6_ela_pro.chat import ElaChatWidget

        chat = make(ElaChatWidget)
        panel = make(QWidget)
        assert chat.setDockWidget(panel) is True
        assert chat.clearDock() is None  # 旧签名保持：清空不返回
        qapp.processEvents()
        assert not sip.isdeleted(panel), "默认 Borrowed：clearDock 不删宿主控件"

    def test_set_dock_widget_owned(self, qapp, make):
        from pyqt6_ela_pro.chat import ElaChatWidget

        chat = make(ElaChatWidget)
        panel = QWidget()
        assert chat.setDockWidget(panel, ownership=ElaWidgetOwnershipType.Owned) is True
        chat.clearDock()
        _flush_deferred_delete(qapp, panel)
        assert sip.isdeleted(panel)


class TestQueueDockSnapshotIsIsolated:
    def test_messages_returns_copies(self, qapp, make):
        dock = make(ElaChatQueueDock)
        dock.setMessages([{"id": "1", "text": "t", "attachments": [{"name": "a.png"}]}])

        snapshot = dock.messages()
        snapshot[0]["text"] = "改了"
        snapshot[0]["attachments"].append({"name": "注入"})
        snapshot[0]["attachments"][0]["name"] = "也改了"

        fresh = dock.messages()
        assert fresh[0]["text"] == "t"
        assert len(fresh[0]["attachments"]) == 1
        assert fresh[0]["attachments"][0]["name"] == "a.png"

    def test_messages_entry_dicts_are_not_shared(self, qapp, make):
        dock = make(ElaChatQueueDock)
        dock.setMessages([{"id": "1", "text": "t", "attachments": []}])
        assert dock.messages()[0] is not dock.messages()[0]

    def test_count_and_toggle_still_work(self, qapp, make):
        dock = make(ElaChatQueueDock)
        dock.setMessages([{"id": "1", "text": "a"}, {"id": "2", "text": "b"}])
        assert dock.count() == 2
        dock.setExpanded(True)
        assert dock.isExpanded() is True


@pytest.mark.parametrize("replace", [True, False])
def test_set_widget_is_idempotent_on_the_same_widget(qapp, make, replace):
    """同一控件重复挂载只换策略，不重复 reparent（ContentSlot 的既有契约）。"""
    dock = make(ElaChatInputDock)
    panel = make(QWidget)
    assert dock.setWidget(panel, replace=replace) is True
    assert dock.setWidget(panel, replace=replace) is True
    assert dock.widget() is panel
