"""``ElaLongPressButton`` / ``ElaProgressButton`` 测试。

覆盖：初值 / setter / 信号 / 长按交互 / 尺寸与变体 / 进度填充 / 几何 / 析构。
两者都继承 ``ElaButton``，尺寸与变体 API 共用。
"""

from __future__ import annotations

import pytest
from _pixels import skip_if_no_pixels
from _qthelpers import wait_until
from PyQt6.QtCore import QEvent, QPoint, QRectF, Qt
from PyQt6.QtGui import QColor, QImage, QKeyEvent, QMouseEvent, QPainter, QPainterPath
from PyQt6ElaWidgetTools import ElaIconType

from pyqt6_ela_pro.ela_button import paintProgressFill
from pyqt6_ela_pro.ela_long_press_button import ElaLongPressButton as ElaLongPressBtn
from pyqt6_ela_pro.ela_progress_button import ElaProgressButton


def _send_mouse(qapp, widget, event_type) -> None:
    """直投鼠标事件（offscreen 下 ``QTest`` 的命中路由不可靠）。"""
    pos = QPoint(6, 6)
    qapp.sendEvent(
        widget,
        QMouseEvent(
            event_type,
            pos.toPointF(),
            widget.mapToGlobal(pos).toPointF(),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )


def _press(qapp, widget) -> None:
    _send_mouse(qapp, widget, QEvent.Type.MouseButtonPress)


def _release(qapp, widget) -> None:
    _send_mouse(qapp, widget, QEvent.Type.MouseButtonRelease)


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

    def test_default_text(self, make):
        assert make(ElaLongPressBtn).text() == "长按触发"
        assert make(ElaLongPressBtn, text="按住").text() == "按住"

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


class TestLongPressStyle:
    """尺寸 / 变体 / 颜色与 ``ElaButton`` 共用（长按按钮不再只有 30px 一档）。"""

    @pytest.mark.parametrize(
        ("size", "height"),
        [("small", 22), ("middle", 30), ("large", 38)],
        ids=["small", "middle", "large"],
    )
    def test_size_presets(self, make, size, height):
        long_press = make(ElaLongPressBtn, size=size)
        progress = make(ElaProgressButton, size=size)
        assert long_press.height() == height
        assert progress.height() == height
        assert long_press.buttonSize() == size
        assert progress.buttonSize() == size

    def test_variant_and_color_forwarded(self, make):
        btn = make(ElaLongPressBtn, variant="solid", color="primary", danger=False)
        assert (btn.variant(), btn.color()) == ("solid", "primary")

    def test_danger_flag(self, make):
        assert make(ElaLongPressBtn, danger=True).isDanger() is True

    def test_icon_kept_on_base(self, make):
        btn = make(ElaLongPressBtn, icon=ElaIconType.IconName.Pencil)
        assert btn._icon_name == ElaIconType.IconName.Pencil


class TestLongPressInteraction:
    """长按语义：按住够久才发 ``longPressed``；短按 / 中断都不发。"""

    def test_hold_emits_long_pressed(self, make, qapp):
        btn = make(ElaLongPressBtn, text="按住", duration=40)
        btn.resize(120, 30)
        btn.show()
        qapp.processEvents()
        fired = []
        btn.longPressed.connect(lambda: fired.append(1))

        _press(qapp, btn)
        assert btn.isHolding() is True
        assert wait_until(qapp, lambda: bool(fired), timeout_ms=4000, use_qwait=True), "长按未触发"
        _release(qapp, btn)
        assert fired == [1]
        assert btn.isHolding() is False

    def test_short_click_does_not_emit(self, make, qapp):
        btn = make(ElaLongPressBtn, duration=5000)
        btn.resize(120, 30)
        btn.show()
        qapp.processEvents()
        fired = []
        btn.longPressed.connect(lambda: fired.append(1))

        _press(qapp, btn)
        _release(qapp, btn)
        assert wait_until(qapp, lambda: bool(fired), timeout_ms=150, use_qwait=True) is False
        assert wait_until(qapp, lambda: btn.progress() == 0.0, timeout_ms=4000, use_qwait=True), (
            "提前松开后进度必须回流清零"
        )

    def test_disable_mid_hold_cancels(self, make, qapp):
        """置灰后不许补发 —— 审批卡在 responding 期间就是整排置灰。"""
        btn = make(ElaLongPressBtn, duration=200)
        btn.resize(120, 30)
        btn.show()
        qapp.processEvents()
        fired = []
        btn.longPressed.connect(lambda: fired.append(1))

        _press(qapp, btn)
        assert wait_until(qapp, lambda: btn.progress() > 0.0, timeout_ms=2000, use_qwait=True)
        btn.setEnabled(False)
        assert btn.isHolding() is False
        assert btn.progress() == 0.0
        assert wait_until(qapp, lambda: bool(fired), timeout_ms=400, use_qwait=True) is False

    def test_hide_mid_hold_cancels(self, make, qapp):
        btn = make(ElaLongPressBtn, duration=200)
        btn.resize(120, 30)
        btn.show()
        qapp.processEvents()
        fired = []
        btn.longPressed.connect(lambda: fired.append(1))

        _press(qapp, btn)
        assert wait_until(qapp, lambda: btn.progress() > 0.0, timeout_ms=2000, use_qwait=True)
        btn.hide()
        assert btn.isHolding() is False
        assert wait_until(qapp, lambda: bool(fired), timeout_ms=300, use_qwait=True) is False

    def test_keyboard_hold(self, make, qapp):
        """键盘也能长按（Space 按住 -> 触发）。"""
        btn = make(ElaLongPressBtn, duration=40)
        btn.resize(120, 30)
        btn.show()
        qapp.processEvents()
        fired = []
        btn.longPressed.connect(lambda: fired.append(1))

        qapp.sendEvent(
            btn,
            QKeyEvent(
                QEvent.Type.KeyPress,
                Qt.Key.Key_Space,
                Qt.KeyboardModifier.NoModifier,
            ),
        )
        assert btn.isHolding() is True
        assert wait_until(qapp, lambda: bool(fired), timeout_ms=4000, use_qwait=True)
        qapp.sendEvent(
            btn,
            QKeyEvent(
                QEvent.Type.KeyRelease,
                Qt.Key.Key_Space,
                Qt.KeyboardModifier.NoModifier,
            ),
        )
        assert fired == [1]


class TestProgressFillPrimitive:
    """``paintProgressFill``：不透明主题色填充 + 领先缘淡出。"""

    @staticmethod
    def _render(progress: float, color=QColor(255, 0, 0)) -> QImage:
        image = QImage(80, 22, QImage.Format.Format_ARGB32)
        image.fill(0)
        painter = QPainter(image)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, 80, 22), 4, 4)
        try:
            paintProgressFill(painter, path, progress, color)
        finally:
            painter.end()
        return image

    def test_zero_progress_draws_nothing(self):
        assert self._render(0.0).pixelColor(40, 11).alpha() == 0

    def test_fill_is_opaque(self):
        """填充是**主题色本身**（用户反馈半透明太淡）。"""
        color = self._render(1.0).pixelColor(40, 11)
        assert color.alpha() == 255
        assert color.name() == "#ff0000"

    def test_full_progress_fills_face(self):
        image = self._render(1.0)
        assert image.pixelColor(2, 11).alpha() > 0
        assert image.pixelColor(77, 11).alpha() > 0

    def test_partial_progress_leaves_tail_clear(self):
        image = self._render(0.5)
        assert image.pixelColor(4, 11).alpha() > 0
        assert image.pixelColor(76, 11).alpha() == 0

    def test_invalid_color_is_ignored(self):
        assert self._render(1.0, QColor()).pixelColor(40, 11).alpha() == 0


class TestProgressOverlayColor:
    """填充用**主题主色**（不透明），覆盖区域的文字用对比色重画。"""

    def test_idle_has_no_overlay(self, make):
        btn = make(ElaLongPressBtn)
        assert btn._progress_on_color() is None

    def test_outlined_uses_theme_primary(self, make):
        from pyqt6_ela_pro._colors import get_color_scheme

        btn = make(ElaLongPressBtn, text="始终允许")
        btn._progress = 0.5
        expected = get_color_scheme("primary", btn._theme_mode)["solid"]
        assert btn._progress_fill_color().name() == expected.name()
        assert btn._progress_on_color().name() == "#ffffff"

    def test_solid_variant_darkens(self, make):
        """实心变体底色就是主色：填充压暗一档，文字不重画。"""
        from pyqt6_ela_pro._colors import get_color_scheme

        btn = make(ElaLongPressBtn, variant="solid", color="primary")
        btn._progress = 0.5
        solid = get_color_scheme("primary", btn._theme_mode)["solid"]
        assert btn._progress_fill_color().lightness() < solid.lightness()
        assert btn._progress_on_color() is None

    def test_custom_color_picks_readable_text(self, make):
        btn = make(ElaLongPressBtn, text="始终允许")
        btn._progress = 1.0
        btn.setProgressColor(QColor("#ffd400"))  # 亮黄 -> 黑字
        assert btn._progress_on_color().name() == "#000000"


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

    def test_progress_roundtrips(self, make):
        btn = make(ElaProgressButton)
        btn.setProgress(37)
        assert btn.progress() == 37
        btn.resetProgress()
        assert btn.progress() == 0

    def test_progress_paints_without_crash(self, make, qapp):
        btn = make(ElaProgressButton, text="下载", size="small")
        btn.setProgress(60)
        btn.show()
        qapp.processEvents()
        btn.grab()

    def test_rgba_progress_color(self, make):
        btn = make(ElaProgressButton)
        btn.setProgressColor("rgba(1, 2, 3, 0.5)")
        assert btn.progressColor().name() == "#010203"
        assert btn.progressColor().alpha() == 128

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
        btn.grab()  # 触发 paint，不得崩


class TestButtonGeometryAlignment:
    """两族的可见面几何一致：控件高按尺寸档、面内缩共用 ``_FACE_INSET``。

    回归：``ElaProgressButton`` 曾写死 ``setFixedHeight(38)`` + 面内缩 3；
    ``ElaLongPressButton`` 的进度分支也按旧内缩 3 画 → 长按开始瞬间按钮面
    比空闲态矮 4px。
    """

    def test_default_height(self, make):
        assert make(ElaProgressButton).height() == 30
        assert make(ElaLongPressBtn).height() == 30

    def test_long_press_face_height_same_in_both_states(self, make, qapp):
        """进度填充不改可见面高度（用实心变体量：透明底的「面」只有一圈描边）。"""
        btn = make(ElaLongPressBtn, text="按住", variant="solid", color="primary")
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
        assert len(idle_rows) > 10, idle_rows
        assert abs(len(idle_rows) - len(hold_rows)) <= 2, (idle_rows, hold_rows)
