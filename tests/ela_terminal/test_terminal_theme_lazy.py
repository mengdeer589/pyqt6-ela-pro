"""终端的懒重建：隐藏时换肤 / 换配色只标记，可见时立即重建；过滤仍即时重建。

换肤 / 换配色改的是**渲染期**颜色（文档文本不变），隐藏时整篇重渲染在宿主规模下是秒级
（实测 10k 行缓冲 ~1.6s/次）。过滤词变了会改**内容**，必须立即重建 —— 这条也要守着，
免得把懒化顺手扩到过滤路径上。
"""

from __future__ import annotations

import pytest
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from PyQt6ElaWidgetTools import eTheme, ElaThemeType
from pyqt6_ela_pro import ElaTerminalView
from pyqt6_ela_pro.terminal_view import terminalThemes

LINES = 500


@pytest.fixture(autouse=True)
def _restore_global_theme():
    """用例会切全局主题；不还原会污染同目录其它文件的断言。"""
    previous = eTheme.getThemeMode()
    yield
    eTheme.setThemeMode(previous)


def _other_mode(mode):
    return (
        ElaThemeType.ThemeMode.Light
        if mode == ElaThemeType.ThemeMode.Dark
        else ElaThemeType.ThemeMode.Dark
    )


def _switch(qapp, mode) -> None:
    eTheme.setThemeMode(mode)
    for _ in range(5):
        qapp.processEvents()


def _page(make, qapp):
    host = make(QWidget)
    layout = QVBoxLayout(host)
    layout.setContentsMargins(0, 0, 0, 0)
    view = make(ElaTerminalView, parent=host)
    layout.addWidget(view)
    view.append("\n".join(f"输出行 {index}" for index in range(LINES)) + "\n")
    QTest.qWait(30)
    qapp.processEvents()
    return host, view


def _spy_rebuild(view):
    calls = {"n": 0}
    real = view._rebuild_document

    def counting(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    view._rebuild_document = counting
    return calls


class TestTerminalLazyRebuild:
    def test_hidden_theme_change_defers(self, qapp, make):
        _, view = _page(make, qapp)
        calls = _spy_rebuild(view)

        _switch(qapp, _other_mode(eTheme.getThemeMode()))

        assert calls["n"] == 0
        assert view._needs_rebuild is True

    def test_show_catches_up_exactly_once(self, qapp, make):
        host, view = _page(make, qapp)
        calls = _spy_rebuild(view)
        _switch(qapp, _other_mode(eTheme.getThemeMode()))
        assert view._needs_rebuild is True

        host.show()
        for _ in range(5):
            qapp.processEvents()

        assert calls["n"] == 1
        assert view._needs_rebuild is False

    def test_visible_theme_change_rebuilds_immediately(self, qapp, make):
        host, view = _page(make, qapp)
        host.show()
        for _ in range(5):
            qapp.processEvents()
        calls = _spy_rebuild(view)

        _switch(qapp, _other_mode(eTheme.getThemeMode()))

        assert calls["n"] == 1
        assert view._needs_rebuild is False

    def test_hidden_palette_change_defers(self, qapp, make):
        _, view = _page(make, qapp)
        calls = _spy_rebuild(view)

        target = next(name for name in terminalThemes() if name != view.paletteName())
        view.setPaletteName(target)
        qapp.processEvents()

        assert calls["n"] == 0
        assert view._needs_rebuild is True
        assert view.paletteName() == target

    def test_filter_change_rebuilds_even_when_hidden(self, qapp, make, monkeypatch):
        """过滤改内容 → 必须立即重建（懒化不许扩到过滤路径）。

        过滤定时器在构造时连的是**当时捕获的绑定方法**，所以计数器要 patch 在构造之前
        （实例属性拦不住这条路径）。
        """
        calls = {"n": 0}
        real = ElaTerminalView._rebuild_document

        def counting(self, *args, **kwargs):
            calls["n"] += 1
            return real(self, *args, **kwargs)

        monkeypatch.setattr(ElaTerminalView, "_rebuild_document", counting)
        _, view = _page(make, qapp)
        calls["n"] = 0  # 造页时的首次重建不计

        view.setFilter("输出行 1")
        view.applyFilterNow()  # 跳过去抖（150ms），确定性触发重建
        qapp.processEvents()

        assert calls["n"] >= 1
