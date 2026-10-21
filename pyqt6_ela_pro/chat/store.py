"""聊天消息快照存储（id 索引 / 位置索引 / 高度缓存 / 脏同步集合）。"""

from __future__ import annotations

from typing import Callable, Optional

from .message import ElaChatMessage


class ChatMessageStore:
    """``ElaChatView`` 的消息数据层：只做快照存取与索引，不碰控件。"""

    def __init__(self) -> None:
        self.items: list[ElaChatMessage] = []
        self.index: dict[int, ElaChatMessage] = {}
        self.positions: dict[int, int] = {}
        self.height_meta: dict[int, tuple] = {}
        self.dirty: set[int] = set()
        self.next_id = 1

    # -- 读 ----------------------------------------------------------------
    def count(self) -> int:
        return len(self.items)

    def message(self, message_id: int) -> Optional[ElaChatMessage]:
        return self.index.get(message_id)

    def last(self) -> Optional[ElaChatMessage]:
        return self.items[-1] if self.items else None

    def contains(self, message_id: int) -> bool:
        return message_id in self.index

    def ids(self) -> list[int]:
        return list(self.index)

    # -- 结构变更 ----------------------------------------------------------
    def add(self, message: ElaChatMessage) -> None:
        self.items.append(message)
        self.positions[message.id] = len(self.items) - 1
        self.index[message.id] = message
        self.height_meta.pop(message.id, None)

    def replace_items(self, items) -> None:
        self.items = list(items)
        self.reindex()

    def remove(self, message_id: int) -> None:
        self.replace_items(item for item in self.items if item.id != message_id)
        self.height_meta.pop(message_id, None)
        self.dirty.discard(message_id)

    def remove_ids(self, message_ids) -> None:
        doomed = set(message_ids)
        self.replace_items(item for item in self.items if item.id not in doomed)
        for message_id in doomed:
            self.height_meta.pop(message_id, None)
            self.dirty.discard(message_id)

    def clear(self) -> None:
        self.items.clear()
        self.index.clear()
        self.positions.clear()
        self.height_meta.clear()
        self.dirty.clear()

    def reindex(self) -> None:
        self.positions = {message.id: index for index, message in enumerate(self.items)}
        self.index = {message.id: message for message in self.items}

    def update(self, message_id: int, updater: Callable) -> bool:
        position = self.positions.get(message_id)
        if (
            position is None
            or position >= len(self.items)
            or self.items[position].id != message_id
        ):
            self.reindex()
            position = self.positions.get(message_id)
            if position is None:
                return False
        updated = updater(self.items[position])
        self.items[position] = updated
        self.index[message_id] = updated
        self.height_meta.pop(message_id, None)
        return True

    def replace_at(self, index: int, message: ElaChatMessage) -> None:
        self.items[index] = message
        self.index[message.id] = message
        self.height_meta.pop(message.id, None)

    # -- 派生同步 / 高度缓存 ----------------------------------------------
    def mark_dirty(self, message_id: int) -> None:
        self.dirty.add(message_id)

    def discard_dirty(self, message_id: int) -> None:
        self.dirty.discard(message_id)

    def take_dirty(self) -> set[int]:
        dirty = self.dirty
        self.dirty = set()
        return dirty

    def height_meta_for(self, message_id: int) -> Optional[tuple]:
        return self.height_meta.get(message_id)

    def set_height_meta(self, message_id: int, meta: tuple) -> None:
        self.height_meta[message_id] = meta

    def invalidate_height(self, message_id: int) -> None:
        self.height_meta.pop(message_id, None)
