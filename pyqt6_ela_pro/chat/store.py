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
        self.dirty: set[int] = set()
        self.next_id = 1

    def count(self) -> int:
        return len(self.items)

    def message(self, message_id: int) -> Optional[ElaChatMessage]:
        return self.index.get(message_id)

    def add(self, message: ElaChatMessage) -> None:
        if message.id in self.index:
            raise ValueError(f"消息 id {message.id} 已存在")
        self.items.append(message)
        self.positions[message.id] = len(self.items) - 1
        self.index[message.id] = message
        if message.id >= self.next_id:
            self.next_id = message.id + 1

    def replace_items(self, items) -> None:
        self.items = list(items)
        self.reindex()

    def remove(self, message_id: int) -> None:
        self.replace_items(item for item in self.items if item.id != message_id)
        self.dirty.discard(message_id)

    def remove_ids(self, message_ids) -> None:
        doomed = set(message_ids)
        self.replace_items(item for item in self.items if item.id not in doomed)
        for message_id in doomed:
            self.dirty.discard(message_id)

    def clear(self) -> None:
        self.items.clear()
        self.index.clear()
        self.positions.clear()
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
        if updated.id != message_id:
            self.reindex()
            return True
        self.index[message_id] = updated
        return True

    def replace_at(self, index: int, message: ElaChatMessage) -> None:
        old_id = self.items[index].id
        self.items[index] = message
        self.index[message.id] = message
        if old_id != message.id:
            # 换 id 的替换：旧 id 必须摘掉，位置索引整体重建
            self.index.pop(old_id, None)
            self.reindex()
        else:
            self.positions[message.id] = index

    def take_dirty(self) -> set[int]:
        dirty = self.dirty
        self.dirty = set()
        return dirty
