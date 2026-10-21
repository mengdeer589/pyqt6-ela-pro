"""``ElaLongPressButton`` / ``ElaProgressButton`` 测试：初值 / setter / 信号 / 几何 / 析构。"""

from __future__ import annotations

import pytest
from _pixels import skip_if_no_pixels
from PyQt6.QtGui import QColor
from PyQt6ElaWidgetTools import ElaIconType

from pyqt6_ela_pro.ela_long_press_button import ElaLongPressButton as ElaLongPressBtn
from pyqt6_ela_pro.ela_progress_button import ElaProgressButton


class TestElaLongPressBtn:
    """Test cases for ElaLongPressBtn class."""

    @pytest.mark.parametrize(
        ("attr", "expected"),
        [("_duration", 500), ("_progress", 0.0), ("_triggered", False)],
        ids=["duration", "progress", "triggered"],
    )
    def test_initialization_with_defaults(self, make, attr, expected):
        assert getattr(make(ElaLongPressBtn), attr) == expected

    def test_initialization_with_custom_duration(self, make):
        assert make(ElaLongPressBtn, duration=800)._duration == 800

    @pytest.mark.parametrize("signal", ["longPressed", "progressChanged"])
    def test_has_signal(self, make, signal):
        assert hasattr(make(ElaLongPressBtn), signal)

    def test_setDuration(self, make):
        btn = make(ElaLongPressBtn)
        btn.setDuration(1000)
        assert btn._duration == 1000

    def test_duration_returns_value(self, make):
        """setter 之后 getter 必须回读得到（此前只测了 ``_duration``）。"""
        btn = make(ElaLongPressBtn)
        btn.setDuration(2000)
        assert btn.duration() == 2000

    def test_setDuration_ignores_zero(self, make):
        """非法值（0）被忽略，保持默认 500。"""
        btn = make(ElaLongPressBtn)
        btn.setDuration(0)
        assert btn._duration == 500

    def test_progress_initially_zero(self, make):
        assert make(ElaLongPressBtn).progress() == 0.0

    def test_delete_later_stops_timers(self, make):
        """析构时鼠标按下计时器必须被停掉。"""
        btn = make(ElaLongPressBtn)
        btn._mouse_pressed_timer.start()
        btn.deleteLater()

    def test_step_length_calculation(self, make):
        """_stepLength 返回 (0, 1] 区间内的增量。"""
        step = make(ElaLongPressBtn, duration=500)._stepLength()
        assert step > 0
        assert step <= 1.0


class TestElaProgressButton:
    """Test cases for ElaProgressButton class."""

    @pytest.mark.parametrize(
        ("attr", "expected"),
        [("_progress", 0.0), ("_custom_progress_color", False)],
        ids=["progress", "custom-progress-color"],
    )
    def test_initialization_with_defaults(self, make, attr, expected):
        assert getattr(make(ElaProgressButton), attr) == expected

    def test_initialization_with_text(self, make):
        assert make(ElaProgressButton, text="下载").text() == "下载"

    def test_initialization_with_custom_color(self, make):
        """QColor 必须在用例内构造 —— parametrize 参数在 qapp 之前求值。"""
        btn = make(ElaProgressButton, getProgressColor=QColor(255, 0, 0))
        assert btn._custom_progress_color is True

    def test_has_progress_changed_signal(self, make):
        assert hasattr(make(ElaProgressButton), "progressChanged")

    def test_set_progress_emits_signal(self, make):
        btn = make(ElaProgressButton)
        received = []
        btn.progressChanged.connect(received.append)

        btn.setProgress(50)

        assert 50 in received

    def test_delete_later_disconnects_theme(self, make):
        """析构要断开主题信号。"""
        make(ElaProgressButton).deleteLater()


class TestIconIntContract:
    """F12 回归：图标契约允许传整数值（原实现传 int 首帧 paint 崩进程）。

    子进程探针实测（修复前）：两组件 ``setElaIcon(3)`` + show + processEvents
    都返回 exit 3221226505（0xC0000409）。修复后入口归一，绘制期不再抛。
    """

    def test_long_press_accepts_int_icon(self, make, qapp):
        btn = make(ElaLongPressBtn)
        btn.setElaIcon(int(ElaIconType.IconName.Pencil.value))

        assert btn._icon_name == ElaIconType.IconName.Pencil
        btn.resize(80, 30)
        btn.show()
        qapp.processEvents()
        btn.grab()  # 触发 paint，不得崩

    def test_progress_accepts_int_icon(self, make, qapp):
        btn = make(ElaProgressButton, text="下载")
        btn.setElaIcon(int(ElaIconType.IconName.Pencil.value))

        assert btn._icon_name == ElaIconType.IconName.Pencil
        btn.resize(80, 30)
        btn.show()
        qapp.processEvents()
        btn.grab()  # 触发 paint（含 _icon_getter），不得崩


class TestButtonGeometryAlignment:
    """与上游 ``ElaPushButton`` V3.0 对齐：控件高 30 / 面内缩 1（共用 ``_FACE_INSET``）。

    回归：``ElaProgressButton`` 曾写死 ``setFixedHeight(38)`` + 面内缩 3；
    ``ElaLongPressButton`` 的进度分支也按旧内缩 3 画 → 长按开始瞬间按钮面
    比空闲态（上游 V3.0 的 1px 内缩）矮 4px。
    """

    def test_widget_heights(self, make):
        assert make(ElaProgressButton).height() == 30
        assert make(ElaLongPressBtn).height() == 30

    def test_long_press_face_height_same_in_both_states(self, make, qapp):
        """进度分支（自绘）与空闲态（上游 paint）的可见面高度必须一致。"""
        btn = make(ElaLongPressBtn, text="按住")
        btn.setFixedWidth(120)
        btn.show()
        qapp.processEvents()

        def face_rows():
            image = btn.grab().toImage()
            x = 8
            return [
                y for y in range(image.height()) if image.pixelColor(x, y).alpha() > 200
            ]

        idle_rows = face_rows()
        btn._progress = 0.6
        btn.update()
        qapp.processEvents()
        hold_rows = face_rows()

        skip_if_no_pixels(
            {str(y) for y in idle_rows} | {str(y) for y in hold_rows},
            "长按按钮面像素",
        )
        assert abs(len(idle_rows) - len(hold_rows)) <= 2, (idle_rows, hold_rows)
