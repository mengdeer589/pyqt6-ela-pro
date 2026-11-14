"""终端输出示例页：单个输出框 + 场景按钮。

回归：该页此前一页摆了四个 ``ElaTerminalView``（ANSI 色彩 / 进度条 / 流式输出 /
调色板），同一个组件重复四遍，读者要来回扫。现在只留一个输出框，四种场景由
底部按钮喂进去；进度条也改回真实终端语义 —— ``\\r`` 重画同一行、结束才 ``\\n``
收口（旧示例每个 tick 追加 ``\\n``，进度条会堆成几十行）。
"""

from __future__ import annotations

from _qthelpers import wait_until as _wait_until
from PyQt6ElaWidgetTools import ElaComboBox

from pyqt6_ela_pro import ElaButton, ElaTerminalView, terminalThemes
from pyqt6_ela_pro.example.terminal_page import TerminalPage


def _buttons(page):
    return {btn.text(): btn for btn in page.findChildren(ElaButton)}


def _single_view(page):
    views = page.findChildren(ElaTerminalView)
    assert len(views) == 1, f"示例页应只有一个输出框，实际 {len(views)} 个"
    return views[0]


class TestTerminalPageLayout:
    def test_single_output_box(self, qapp, make):
        page = make(TerminalPage)
        _single_view(page)

    def test_scenario_buttons_present(self, qapp, make):
        page = make(TerminalPage)
        labels = set(_buttons(page))
        assert {"ANSI 色彩样例", "进度条", "流式输出", "停止"} <= labels

    def test_theme_combo_present(self, qapp, make):
        page = make(TerminalPage)
        combo = page.findChild(ElaComboBox)
        assert combo is not None
        assert [combo.itemText(i) for i in range(combo.count())] == terminalThemes()

    def test_theme_combo_switches_view(self, qapp, make):
        page = make(TerminalPage)
        combo = page.findChild(ElaComboBox)
        view = _single_view(page)
        combo.setCurrentText("solarized")
        qapp.processEvents()
        assert view.terminalTheme() == "solarized"


class TestTerminalPageScenarios:
    def test_ansi_button_restores_sample(self, qapp, make):
        page = make(TerminalPage)
        view = _single_view(page)
        buttons = _buttons(page)
        buttons["进度条"].click()
        buttons["停止"].click()
        buttons["ANSI 色彩样例"].click()
        qapp.processEvents()
        assert "编译 128 个文件" in view.toPlainText()

    def test_progress_redraws_one_line_then_finishes(self, qapp, make):
        """进度条只占一行：反复 ``\\r`` 重画，不是每个 tick 堆一行。"""
        page = make(TerminalPage)
        view = _single_view(page)
        _buttons(page)["进度条"].click()
        assert _wait_until(
            qapp, lambda: "下载完成" in view.toPlainText(), timeout_ms=5000
        ), view.toPlainText()
        assert view.lineCount() == 2
        assert view.toPlainText().count("下载完成") == 1

    def test_stop_stops_running_scenario(self, qapp, make):
        page = make(TerminalPage)
        _buttons(page)["流式输出"].click()
        assert any(timer.isActive() for timer in page._timers)
        _buttons(page)["停止"].click()
        assert not any(timer.isActive() for timer in page._timers)
