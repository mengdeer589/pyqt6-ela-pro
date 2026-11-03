"""示例页共用的脚本播放器（单 ``QTimer``，无线程）。"""

from __future__ import annotations

import traceback

from PyQt6.QtCore import QTimer


class _ScriptPlayer:
    """按脚本逐步驱动公开 API 的播放器（单个 ``QTimer``，无线程）。

    脚本是 ``[(延迟ms, 可调用对象), ...]``。``play`` 按 ``interval`` 节奏走，
    ``play_now`` 同步跑完（示例页「预填」用）。

    **回调里必须 try/except**：这些函数跑在 ``QTimer`` 回调链上，
    任何未捕获异常穿过 C++ 边界都是 0xC0000409 **静默终止**（无 traceback）。
    """

    def __init__(self, parent=None):
        self._timer = QTimer(parent)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._tick)
        self._steps: list = []
        self._index = 0
        self._interval = 40
        self._on_done = None

    @property
    def running(self) -> bool:
        return bool(self._steps)

    def play(self, steps, on_done=None, interval: int = 40) -> None:
        """从头播一遍 ``steps``。``interval`` 是**每步之间**的默认节奏。"""
        self.stop()
        self._steps = list(steps)
        self._index = 0
        self._interval = interval
        self._on_done = on_done
        if self._steps:
            self._timer.start(0)

    def play_now(self, steps) -> None:
        """**预填**：同步跑完整个脚本，函数返回时内容已经在界面上。
        刻意**同步**而不是「按 0 延迟排队」—— 预填的全部意义就是「读者打开
        页面就看到内容」。排队到事件循环里的后果是：页面刚建好、还没跑过第一帧
        """
        self.stop()
        self._interval = 0
        for _delay, fn in steps:
            try:
                fn()
            except Exception:  # noqa: BLE001 —— 见类 docstring
                traceback.print_exc()

    def stop(self) -> None:
        self._timer.stop()
        self._steps = []
        self._index = 0
        self._on_done = None

    def _tick(self) -> None:
        if self._index >= len(self._steps):
            done, self._on_done = self._on_done, None
            self._steps = []
            if done is not None:
                try:
                    done()
                except Exception:
                    traceback.print_exc()
            return
        _delay, fn = self._steps[self._index]
        self._index += 1
        try:
            fn()
        except Exception:  # noqa: BLE001 —— 见类 docstring：不能让它穿过 C++ 边界
            traceback.print_exc()
        self._timer.start(max(0, self._interval))
