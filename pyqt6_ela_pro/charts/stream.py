"""流式数据窗口（环形缓冲）。"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence


class DataRing(Sequence):
    """只读环形数据窗口；切片 / 迭代语义与 list 一致。"""

    __slots__ = ("_buf", "_maxlen", "_version")

    def __init__(self, data=(), maxPoints: int = None):
        self._maxlen = None if maxPoints is None else max(1, int(maxPoints))
        self._buf = deque(data or (), maxlen=self._maxlen)
        #: 原地 push 不会改变 len（窗口满后），缓存必须靠它判数据变化。
        self._version = 0

    def __len__(self) -> int:
        return len(self._buf)

    def __getitem__(self, index):
        if isinstance(index, slice):
            return list(self._buf)[index]
        return self._buf[index]

    def __iter__(self):
        return iter(self._buf)

    def __reversed__(self):
        return reversed(self._buf)

    def __repr__(self) -> str:
        return f"DataRing(len={len(self)}, maxPoints={self._maxlen})"

    @property
    def maxPoints(self):
        return self._maxlen

    def push(self, points) -> None:
        changed = False
        for point in points:
            self._buf.append(point)
            changed = True
        if changed:
            self._version += 1

    def toList(self) -> list:
        return list(self._buf)

    def __deepcopy__(self, memo):
        # 流窗口由 chart 持有；option 深拷贝时按引用带走，避免每帧复制整窗。
        memo[id(self)] = self
        return self


def ring_points(points) -> list:
    """把单点 / 批量点归一为 list（不改写点内容）。"""
    if points is None:
        return []
    if isinstance(points, dict):
        return [points]
    if isinstance(points, (list, tuple)):
        if not points:
            return []
        first = points[0]
        if isinstance(first, (list, tuple, dict)):
            return list(points)
        return [points]
    return [points]
