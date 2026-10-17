"""``pyqt6_ela_pro._ownership`` 的单元测试。

钉住的核心不变量：

1. **挂载期间必须 reparent** —— 否则内容不跟着宿主走（也是 ``Reparented`` 能还原的前提）。
2. **拒绝自挂 / 挂祖先** —— 那会构成循环。
3. **原 parent 必须在 reparent 之前记下**。
4. **外部销毁要自愈** —— ``destroyed`` 在 C++ 析构之后才发，槽里不能碰那个包装器。
5. **``take`` 永不删除、返回无父控件**。
"""

from __future__ import annotations

import pytest
from PyQt6 import sip
from PyQt6.QtCore import QCoreApplication, QEvent, Qt
from PyQt6.QtWidgets import QLabel, QWidget

from pyqt6_ela_pro._ownership import ContentSlot, ElaWidgetOwnershipType, releaseWidget


@pytest.fixture
def host(make):
    """宿主容器。

    必须走 ``make`` 登记（AGENTS.md：控件别在测试体里裸 ``QWidget()`` +
    ``deleteLater()``）—— 未登记的顶层窗口会活过用例边界，和后续 teardown 撞成
    0xC0000409。
    """
    return make(QWidget)


def _flush(obj=None):
    """冲刷 DeferredDelete。

    **必须传具体对象**，不能传 ``None`` —— ``None`` 会冲刷**所有**对象的延迟删除，
    把别的用例正在 teardown 的控件一起干掉，实测两目录合跑必 0xC0000005。
    （``processEvents()`` 不派发 DeferredDelete，所以只能走这条路。）
    """
    QCoreApplication.sendPostedEvents(obj, QEvent.Type.DeferredDelete)


class TestSetWidget:
    def test_reparents_content(self, host):
        """挂载期间必须 reparent —— 这是「内容跟着容器走」的前提。"""
        content = QLabel("x")
        slot = ContentSlot(host, "t")
        assert slot.setWidget(content) is True
        assert content.parentWidget() is host

    def test_default_ownership_is_borrowed(self, host):
        slot = ContentSlot(host, "t")
        assert slot.ownership() == ElaWidgetOwnershipType.Borrowed
        slot.setWidget(QLabel("x"))
        assert slot.ownership() == ElaWidgetOwnershipType.Borrowed

    def test_rejects_self(self, host):
        assert ContentSlot(host, "t").setWidget(host) is False

    def test_rejects_ancestor_of_host(self, qt_cleanup):
        """挂祖先会构成循环（祖先的祖先里含自己）。"""
        outer = QWidget()
        inner = QWidget()
        inner.setParent(outer)
        slot = ContentSlot(inner, "t")
        assert slot.setWidget(outer) is False

    def test_rejects_non_qwidget(self, host):
        assert ContentSlot(host, "t").setWidget(object()) is False

    def test_rejects_invalid_ownership(self, host):
        assert ContentSlot(host, "t").setWidget(QLabel("x"), 99) is False

    def test_records_original_parent_before_reparent(self, host, qt_cleanup):
        """原 parent 必须在 reparent **之前**记下，否则还原不回去。"""
        original = QWidget()
        content = QLabel("x")
        content.setParent(original)
        slot = ContentSlot(host, "t")
        slot.setWidget(content, ElaWidgetOwnershipType.Reparented)
        assert slot._originalParent is original

    def test_top_level_content_is_demoted_to_child(self, host):
        """顶层内容不能直接 setParent 当 child，会被 WM 当独立窗口弹出来。"""
        content = QLabel("x")
        content.setWindowFlags(content.windowFlags() | Qt.WindowType.Window)
        assert content.isWindow()
        slot = ContentSlot(host, "t")
        slot.setWidget(content)
        assert content.isWindow() is False
        assert content.parentWidget() is host

    def test_repeat_attach_only_updates_policy(self, host):
        """重复挂同一控件不重复 reparent，只改策略。"""
        content = QLabel("x")
        slot = ContentSlot(host, "t")
        slot.setWidget(content, ElaWidgetOwnershipType.Borrowed)
        changes = []
        slot.ownershipChanged.connect(lambda o: changes.append(o.name))
        slot.setWidget(content, ElaWidgetOwnershipType.Owned)
        assert content.parentWidget() is host
        assert slot.ownership() == ElaWidgetOwnershipType.Owned
        assert changes == ["Owned"]

    def test_same_policy_emits_nothing(self, host):
        content = QLabel("x")
        slot = ContentSlot(host, "t")
        slot.setWidget(content, ElaWidgetOwnershipType.Owned)
        changes = []
        slot.ownershipChanged.connect(lambda o: changes.append(o.name))
        slot.setWidget(content, ElaWidgetOwnershipType.Owned)
        assert changes == []

    def test_setting_none_clears(self, host):
        slot = ContentSlot(host, "t")
        slot.setWidget(QLabel("x"))
        assert slot.setWidget(None) is True
        assert slot.widget() is None
        assert slot.hasWidget() is False


class TestReleaseAndTake:
    def test_borrowed_returns_parentless(self, host):
        content = QLabel("x")
        slot = ContentSlot(host, "t")
        slot.setWidget(content, ElaWidgetOwnershipType.Borrowed)
        slot.releaseWidget()
        assert content.parentWidget() is None

    def test_reparented_restores_original_parent(self, host, qt_cleanup):
        original = QWidget()
        content = QLabel("x")
        content.setParent(original)
        slot = ContentSlot(host, "t")
        slot.setWidget(content, ElaWidgetOwnershipType.Reparented)
        slot.releaseWidget()
        assert content.parentWidget() is original

    def test_reparented_without_original_parent_still_parentless(self, host):
        """原 parent 为 None 时退化成 Borrowed，不能凭空造一个。"""
        content = QLabel("x")
        slot = ContentSlot(host, "t")
        slot.setWidget(content, ElaWidgetOwnershipType.Reparented)
        slot.releaseWidget()
        assert content.parentWidget() is None

    def test_owned_deletes(self, host, qapp):
        content = QLabel("x")
        slot = ContentSlot(host, "t")
        slot.setWidget(content, ElaWidgetOwnershipType.Owned)
        slot.releaseWidget()
        _flush(content)
        assert sip.isdeleted(content)

    def test_owned_without_delete_flag_keeps_widget(self, host, qapp):
        """析构路径要这个：Qt 的 parent-child 删除会在宿主析构**之后**处理。"""
        content = QLabel("x")
        slot = ContentSlot(host, "t")
        slot.setWidget(content, ElaWidgetOwnershipType.Owned)
        slot.releaseWidget(deleteOwned=False)
        assert sip.isdeleted(content) is False
        assert content.parentWidget() is None

    def test_take_returns_parentless_and_never_deletes(self, host, qapp):
        content = QLabel("x")
        slot = ContentSlot(host, "t")
        slot.setWidget(content, ElaWidgetOwnershipType.Owned)
        got = slot.takeWidget()
        _flush(got)
        assert got is content
        assert got.parentWidget() is None
        assert sip.isdeleted(content) is False

    def test_take_ignores_restore_parent(self, host, qt_cleanup):
        """``take`` 的语义是「交还」，必须无父，不能放回原 parent。"""
        original = QWidget()
        content = QLabel("x")
        content.setParent(original)
        slot = ContentSlot(host, "t")
        slot.setWidget(content, ElaWidgetOwnershipType.Reparented)
        got = slot.takeWidget()
        assert got.parentWidget() is None

    def test_take_resets_ownership(self, host):
        slot = ContentSlot(host, "t")
        slot.setWidget(QLabel("x"), ElaWidgetOwnershipType.Owned)
        slot.takeWidget()
        assert slot.ownership() == ElaWidgetOwnershipType.Borrowed
        assert slot.widget() is None

    def test_release_on_empty_slot_is_noop(self, host):
        slot = ContentSlot(host, "t")
        slot.releaseWidget()
        assert slot.widget() is None

    def test_take_on_empty_slot_returns_none(self, host):
        assert ContentSlot(host, "t").takeWidget() is None

    def test_release_emits_widget_changed(self, host):
        slot = ContentSlot(host, "t")
        slot.setWidget(QLabel("x"))
        seen = []
        slot.widgetChanged.connect(lambda w: seen.append(w))
        slot.releaseWidget()
        assert seen == [None]


class TestExternalDestruction:
    def test_self_heals_when_content_destroyed_externally(self, host, qapp):
        """内容被外部销毁时要清引用并发信号，不能留悬空包装器。"""
        content = QLabel("x")
        slot = ContentSlot(host, "t")
        slot.setWidget(content)
        seen = []
        slot.widgetChanged.connect(lambda w: seen.append(w))
        content.deleteLater()
        _flush(content)
        assert slot.widget() is None
        assert slot.ownership() == ElaWidgetOwnershipType.Borrowed
        assert seen[-1] is None

    def test_slot_survives_content_destruction(self, host, qapp):
        """槽本身是宿主的子对象，内容死了它不该跟着崩。"""
        slot = ContentSlot(host, "t")
        slot.setWidget(QLabel("x"))
        slot.widget().deleteLater()
        _flush(slot.widget())
        slot.setWidget(QLabel("y"))
        assert slot.widget() is not None

    def test_release_after_external_destruction_is_noop(self, host, qapp):
        slot = ContentSlot(host, "t")
        content = QLabel("x")
        slot.setWidget(content)
        content.deleteLater()
        _flush(content)
        slot.releaseWidget()  # 不得抛
        assert slot.widget() is None


class TestFreeFunction:
    def test_release_widget_tolerates_none(self):
        releaseWidget(None, ElaWidgetOwnershipType.Owned)

    def test_release_widget_tolerates_deleted(self, qapp):
        content = QLabel("x")
        content.deleteLater()
        _flush(content)
        releaseWidget(content, ElaWidgetOwnershipType.Owned)  # 不得抛

    def test_release_widget_borrowed_clears_parent(self, host):
        content = QLabel("x")
        content.setParent(host)
        releaseWidget(content, ElaWidgetOwnershipType.Borrowed)
        assert content.parentWidget() is None

    def test_release_widget_non_widget_is_tolerated(self):
        releaseWidget(object(), ElaWidgetOwnershipType.Borrowed)
