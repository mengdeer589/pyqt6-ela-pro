"""``buttons_menus_page`` 的形状守卫。

起因是一个**运行时才炸、测试全绿**的真实事故：示例页调
``self._longPressBtn.setDuration(ms)``，而组件当时暴露的是 ``set_duration`` ——
``AttributeError`` 从按钮的 ``clicked`` 槽里抛出去，PyQt5 直接 0xC0000409
**静默终止**（连 pytest 报告都没有）。全量测试绿、ruff 绿，只有真的
``python -m pyqt6_ela_pro.example`` 才暴露。

所以这里逐个点名调用那些**确定无副作用**的演示回调：只改控件属性 / 发信号，
不弹模态框（``ElaConfirmDialog`` 在测试进程里会直接阻塞）、不开文件对话框。
"""

from __future__ import annotations

import pytest
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication

from pyqt6_ela_pro.example.buttons_menus_page import ButtonsMenusPage


@pytest.fixture
def page(make):
    p = make(ButtonsMenusPage)
    QApplication.processEvents()
    return p


class TestLongPressSection:
    """长按按钮那一节：``setDuration`` 曾不存在，点了就崩。"""

    def test_page_constructs(self, page):
        assert page.PAGE_TITLE

    def test_duration_callbacks_run(self, page):
        """回归：``_setLongPressDuration`` 调的 ``setDuration`` 必须存在。"""
        btn = page._longPressBtn
        for ms in (300, 500, 800, 1000):
            page._setLongPressDuration(ms)
            assert btn.duration() == ms, f"setDuration({ms}) 未生效"
            # 回调同时把文案改成「长按 N.N 秒」
            assert f"{ms / 1000:.1f}" in btn.text(), (
                f"文案未随 duration 更新: {btn.text()!r}"
            )

    def test_camel_case_api_present(self, page):
        """公开 API 是 camelCase（与 ``ela_button.setElaIcon`` 等对齐）。"""
        btn = page._longPressBtn
        for name in (
            "setDuration",
            "duration",
            "setProgressColor",
            "progressColor",
            "setElaIcon",
            "progress",
        ):
            assert callable(getattr(btn, name)), f"缺 {name}"

    def test_snake_case_aliases_are_gone(self, page):
        """不保留旧名（API 变更策略：不留兼容包装）。"""
        btn = page._longPressBtn
        for name in ("set_duration", "set_progress_color", "set_ela_icon"):
            assert not hasattr(btn, name), f"{name} 应已重命名为 camelCase"

    def test_trigger_callback_runs(self, page, capsys):
        page._onLongPressTriggered()
        assert "长按" in capsys.readouterr().out


class TestProgressSection:
    def test_progress_callbacks_run(self, page):
        pb = page._progressBtn
        pb.setProgress(40)
        assert pb.progress() == 40

        pb.setProgress(0)
        assert pb.progress() == 0

    def test_camel_case_api_present(self, page):
        pb = page._progressBtn
        for name in (
            "setProgress",
            "progress",
            "resetProgress",
            "setProgressColor",
            "progressColor",
            "setElaIcon",
            "setBorderRadius",
        ):
            assert callable(getattr(pb, name)), f"缺 {name}"

    def test_snake_case_aliases_are_gone(self, page):
        pb = page._progressBtn
        for name in ("reset_progress", "set_progress_color", "set_ela_icon"):
            assert not hasattr(pb, name), f"{name} 应已重命名为 camelCase"

    def test_reset_progress_helper(self, page):
        pb = page._progressBtn
        pb.setProgress(70)
        pb.resetProgress()
        assert pb.progress() == 0

    def test_progress_color_round_trip(self, page):
        pb = page._progressBtn
        pb.setProgressColor(QColor(1, 2, 3))
        assert pb.progressColor().name() == "#010203"

    def test_timer_tick_callback_runs(self, page):
        """``_onProgressTimerTick`` 是定时器槽，异常同样静默终止。"""
        page._progressBtn.setProgress(10)
        page._onProgressTimerTick()
        assert page._progressBtn.progress() == 20


class TestApiShapeAcrossButtons:
    """按钮族公开 API 一致性（camelCase），防止再出现第三个离群者。"""

    @pytest.mark.parametrize(
        "name,expected",
        [
            ("setDuration", True),
            ("set_duration", False),
        ],
    )
    def test_long_press_naming(self, page, name, expected):
        assert hasattr(page._longPressBtn, name) is expected

    @pytest.mark.parametrize(
        "name,expected",
        [
            ("setProgress", True),
            ("resetProgress", True),
            ("reset_progress", False),
        ],
    )
    def test_progress_naming(self, page, name, expected):
        assert hasattr(page._progressBtn, name) is expected
