"""示例页共用的脚本播放器（单 ``QTimer``，无线程）。"""

from __future__ import annotations

import traceback

from PyQt6.QtCore import QTimer


class _ScriptPlayer:
    """按脚本逐步驱动公开 API 的播放器（单个 ``QTimer``，无线程）。

    回调里必须 try/except：异常穿过 C++ 边界 = 0xC0000409 静默终止。
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
        """从头播一遍 ``steps``；``interval`` 是每步之间的默认节奏。"""
        self.stop()
        self._steps = list(steps)
        self._index = 0
        self._interval = interval
        self._on_done = on_done
        if self._steps:
            self._timer.start(0)

    def play_now(self, steps) -> None:
        """**预填**：同步跑完整个脚本，函数返回时内容已经在界面上。"""
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
