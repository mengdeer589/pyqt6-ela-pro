"""ChatMessageStore 的索引维护契约。"""

from __future__ import annotations

from dataclasses import replace

from pyqt6_ela_pro.chat import ElaChatMessage, ElaChatRoleType
from pyqt6_ela_pro.chat.store import ChatMessageStore


class TestReplaceAt:
    def test_changed_id_repairs_index_and_positions(self):
        store = ChatMessageStore()
        store.add(ElaChatMessage(id=1, role=ElaChatRoleType.User, text="a"))
        store.add(ElaChatMessage(id=2, role=ElaChatRoleType.Assistant, text="b"))

        store.replace_at(0, replace(store.items[0], id=9))
        assert store.positions == {9: 0, 2: 1}
        assert store.index[9].id == 9
        assert 1 not in store.index

    def test_same_id_keeps_position(self):
        store = ChatMessageStore()
        store.add(ElaChatMessage(id=1, role=ElaChatRoleType.User, text="a"))
        updated = store.items[0].withText("changed")
        store.replace_at(0, updated)
        assert store.items[0].text == "changed"
        assert store.positions[1] == 0
