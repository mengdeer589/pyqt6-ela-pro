"""
[pyqt6_ela_pro] 终端输出展示示例页

单个 ``ElaTerminalView`` + 底部场景触发按钮。此前一页摆了四个输出框
（ANSI 色彩 / 进度条 / 流式输出 / 调色板），同一个组件重复四遍；现在四种场景
由按钮喂进同一个输出框，调色板按钮也作用于同一个实例。
"""

import random

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QHBoxLayout, QWidget
from PyQt6ElaWidgetTools import ElaIconType

from pyqt6_ela_pro import (
    ElaButton,
    ElaTerminalView,
    terminalThemes,
)
from pyqt6_ela_pro.example.base_page import ExamplePage

SAMPLE_ANSI = (
    "\x1b[32m√\x1b[0m 编译 128 个文件        \x1b[2m2.31s\x1b[0m\n"
    "\x1b[32m√\x1b[0m 链接 ela_pro.dll        \x1b[2m0.84s\x1b[0m\n"
    "\x1b[33m!\x1b[0m 3 个警告：未使用的变量\n"
    "\x1b[31m✗\x1b[0m 1 个错误：expected ';' before '}'\n"
    "\n"
    "\x1b[36m+\x1b[0m 基础色："
    "\x1b[30m黑\x1b[0m \x1b[31m红\x1b[0m \x1b[32m绿\x1b[0m \x1b[33m黄\x1b[0m "
    "\x1b[34m蓝\x1b[0m \x1b[35m品红\x1b[0m \x1b[36m青\x1b[0m \x1b[37m白\x1b[0m\n"
    "\x1b[36m+\x1b[0m 亮色："
    "\x1b[90m黑\x1b[0m \x1b[91m红\x1b[0m \x1b[92m绿\x1b[0m \x1b[93m黄\x1b[0m "
    "\x1b[94m蓝\x1b[0m \x1b[95m品红\x1b[0m \x1b[96m青\x1b[0m \x1b[97m白\x1b[0m\n"
    "\x1b[36m+\x1b[0m 256 色：\x1b[38;5;208m橙\x1b[0m "
    "\x1b[38;5;45m青绿\x1b[0m \x1b[38;5;129m紫\x1b[0m \x1b[38;5;196m玫红\x1b[0m "
    "\x1b[38;5;244m灰\x1b[0m\n"
    "\x1b[36m+\x1b[0m 真彩：\x1b[38;2;255;160;60m橙\x1b[0m "
    "\x1b[38;2;90;200;220m天蓝\x1b[0m \x1b[38;2;200;120;220m藕紫\x1b[0m\n"
    "\x1b[36m+\x1b[0m 样式：\x1b[1m加粗\x1b[0m \x1b[2m暗淡\x1b[0m \x1b[3m斜体\x1b[0m "
    "\x1b[4m下划线\x1b[0m \x1b[7m反显\x1b[0m \x1b[9m删除线\x1b[0m\n"
    "\x1b[36m+\x1b[0m 背景：\x1b[41m  红色底  \x1b[0m\x1b[42m  绿色底  \x1b[0m"
    "\x1b[44m  蓝色底  \x1b[0m\x1b[47m  白色底  \x1b[0m\n"
    "\n"
    "\x1b[2m被丢弃的序列：OSC 设标题 ESC ]0;t BEL、"
    "DCS ESC P…ESC \\、字符集选择\x1b[0m\n"
)

STREAM_SCRIPT = [
    ("info", "resolving dependencies..."),
    ("info", "collected 87 items"),
    ("test", "tests/test_core.py::test_alpha PASSED"),
    ("test", "tests/test_core.py::test_beta PASSED"),
    ("test", "tests/test_io.py::test_read PASSED"),
    ("warn", "tests/test_io.py::test_write SKIPPED (需要 Win7)"),
    ("test", "tests/test_ui.py::test_render PASSED"),
    ("fail", "tests/test_ui.py::test_theme FAILED"),
    ("", ""),
    ("fail", "assert 3 == 4"),
    ("info", "3 passed, 1 skipped, 1 failed in 4.12s"),
]

_COLORS = {
    "info": "\x1b[36m",
    "test": "\x1b[32m",
    "warn": "\x1b[33m",
    "fail": "\x1b[31m",
}


class TerminalPage(ExamplePage):
    """终端输出展示组件示例页。"""

    PAGE_TITLE = "[ela_ext] 终端输出"

    def __init__(self, parent=None):
        self._timers = []
        super().__init__(parent)

    def _addDemoContent(self, main_layout):
        self._demoTerminal(main_layout)

    # ── 单输出框 + 场景按钮 ────────────────────────────────────────
    def _demoTerminal(self, main_layout):
        """终端输出：一个 ``ElaTerminalView`` + 底部场景触发按钮。

        每个按钮把一种场景喂进同一个输出框；进度条按真实终端的方式用 ``\\r``
        反复重画**同一行**（只有结束才 ``\\n`` 收口），流式输出逐行追加，
        调色板按钮直接切换这个实例的配色。
        """
        main_layout.addLayout(
            self._createHeaderRow(
                "ElaTerminalView - 终端输出（单输出框 + 场景按钮）",
                self._demoTerminal,
            )
        )
        self._addInfoText(
            "只读展示、不执行任何命令。下面每个按钮把一种场景喂进同一个输出框："
            "ANSI 色彩样例、\\r 进度条、流式输出；输出框顶部工具栏是组件自带的"
            "搜索过滤、复制、导出、字号与跟随。调色板按钮切换实例配色"
            "（内置 one-dark / solarized / classic，应用主题切换时自动跟随）。",
            main_layout,
        )

        view = ElaTerminalView(maxLines=2000, parent=self)
        view.setMinimumHeight(380)
        view.append(SAMPLE_ANSI)
        main_layout.addWidget(view)

        # 场景按钮行
        row = QWidget(self)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)
        ansi_btn = ElaButton(
            "ANSI 色彩样例",
            icon=ElaIconType.IconName.Palette,
            variant="outlined",
            color="primary",
            parent=row,
        )
        progress_btn = ElaButton(
            "进度条",
            icon=ElaIconType.IconName.Play,
            variant="solid",
            color="primary",
            parent=row,
        )
        stream_btn = ElaButton(
            "流式输出",
            icon=ElaIconType.IconName.Code,
            variant="solid",
            color="primary",
            parent=row,
        )
        stop_btn = ElaButton(
            "停止",
            icon=ElaIconType.IconName.Stop,
            variant="outlined",
            color="danger",
            parent=row,
        )
        for btn in (ansi_btn, progress_btn, stream_btn, stop_btn):
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            row_layout.addWidget(btn)
        row_layout.addStretch(1)
        main_layout.addWidget(row)

        # 调色板按钮行（作用于同一个输出框）
        palette_row = QWidget(self)
        palette_layout = QHBoxLayout(palette_row)
        palette_layout.setContentsMargins(0, 0, 0, 0)
        palette_layout.setSpacing(8)
        for name in terminalThemes():
            btn = ElaButton(
                name,
                variant="outlined",
                color="primary",
                size="small",
                parent=palette_row,
            )
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.clicked.connect(lambda _c=False, n=name: view.setPaletteName(n))
            palette_layout.addWidget(btn)
        palette_layout.addStretch(1)
        main_layout.addWidget(palette_row)

        # ── 场景实现（闭包；</> 代码 按钮展示的就是本方法自身）────────
        progress_state = {"percent": 0}
        stream_state = {"index": 0}

        def stop_timers():
            progress_timer.stop()
            stream_timer.stop()

        def tick_progress():
            percent = min(100, progress_state["percent"] + random.randint(3, 11))
            progress_state["percent"] = percent
            filled = percent // 5
            bar = "█" * filled + "░" * (20 - filled)
            # \r 整行重绘：不追加 \n，当前行实时上屏；只有结束才收口
            view.append(f"\r\x1b[36m{bar}\x1b[0m {percent:3d}%")
            if percent >= 100:
                stop_timers()
                view.append("\n\x1b[32m√\x1b[0m 下载完成\n")

        def tick_stream():
            kind, text = STREAM_SCRIPT[stream_state["index"] % len(STREAM_SCRIPT)]
            stream_state["index"] += 1
            color = _COLORS.get(kind, "")
            view.append(f"{color}{text}\x1b[0m\n" if color else f"{text}\n")
            if stream_state["index"] > len(STREAM_SCRIPT) * 4:
                stop_timers()

        # 常驻定时器（挂在页面下，不随每次触发堆积）
        progress_timer = QTimer(self)
        progress_timer.setInterval(60)
        progress_timer.timeout.connect(tick_progress)
        stream_timer = QTimer(self)
        stream_timer.setInterval(120)
        stream_timer.timeout.connect(tick_stream)
        self._timers.extend([progress_timer, stream_timer])

        def show_ansi():
            stop_timers()
            view.clear()
            view.append(SAMPLE_ANSI)

        def start_progress():
            stop_timers()
            view.clear()
            progress_state["percent"] = 0
            progress_timer.start()

        def start_stream():
            stop_timers()
            view.clear()
            stream_state["index"] = 0
            stream_timer.start()

        ansi_btn.clicked.connect(show_ansi)
        progress_btn.clicked.connect(start_progress)
        stream_btn.clicked.connect(start_stream)
        stop_btn.clicked.connect(stop_timers)

    # ── 清理 ──────────────────────────────────────────────────────

    def closeEvent(self, event):  # noqa: N802 (Qt 命名)
        for timer in self._timers:
            timer.stop()
        super().closeEvent(event)
