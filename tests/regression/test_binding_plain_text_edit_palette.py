"""本地重编轮守卫：``ElaPlainTextEdit`` 首次 show 后必须保留主题 palette。

上游 ``ElaPlainTextEdit`` 在构造函数里设了
``#ElaPlainTextEdit{background-color:transparent;}``，而 ``ElaWindow`` 也带 QSS。
Qt 的 ``QStyleSheetStyle`` 在**首次 polish / show** 时会把这类子控件的 widget
palette 重置成 ``QApplication::palette()``；Ela 主题从不设置
``QApplication::setPalette``（所有控件自绘），于是深色主题下 ``Text`` /
``PlaceholderText`` 拿到系统浅色默认值 —— placeholder 是「黑 50%」，连输入的
文字都是黑的。

修复在本地重编轮：``ElaPlainTextEdit::showEvent`` 调 ``applyThemePalette()``
补回主题色。**换回重编前的旧轮子时本用例会红** —— 它也是「当前装的是不是打过
补丁的轮子」的探针。
"""

from __future__ import annotations

from PyQt6.QtGui import QColor, QPalette
from PyQt6ElaWidgetTools import (
    ElaPlainTextEdit,
    ElaThemeType,
    ElaWindow,
    eTheme,
)
from pyqt6_ela_pro import ElaChatWidget


def _expected_placeholder(mode) -> QColor:
    if mode == ElaThemeType.ThemeMode.Dark:
        return QColor(0xBA, 0xBA, 0xBA)
    return QColor(0, 0, 0, 128)


def _assert_theme_palette(edit, mode) -> None:
    palette = edit.palette()
    text = palette.color(QPalette.ColorRole.Text)
    expected_text = eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.BasicText)
    assert text.name() == expected_text.name()
    placeholder = palette.color(QPalette.ColorRole.PlaceholderText)
    expected_placeholder = _expected_placeholder(mode)
    assert placeholder.name() == expected_placeholder.name()
    assert placeholder.alpha() == expected_placeholder.alpha()


def test_plain_text_edit_keeps_theme_palette_after_show(qapp, make):
    previous = eTheme.getThemeMode()
    eTheme.setThemeMode(ElaThemeType.ThemeMode.Dark)
    window = None
    try:
        window = make(ElaWindow)
        window.resize(800, 600)
        window.show()
        qapp.processEvents()

        edit = make(ElaPlainTextEdit, window)
        edit.setPlaceholderText("请输入多行文本...")
        edit.show()
        qapp.processEvents()

        _assert_theme_palette(edit, ElaThemeType.ThemeMode.Dark)
    finally:
        if window is not None:
            window.hide()
        eTheme.setThemeMode(previous)


def test_chat_input_keeps_theme_palette_after_show(qapp, make):
    """聊天输入框（内部同样是 ``ElaPlainTextEdit``）也走同一条修复。"""
    previous = eTheme.getThemeMode()
    eTheme.setThemeMode(ElaThemeType.ThemeMode.Dark)
    window = None
    try:
        window = make(ElaWindow)
        window.resize(900, 700)
        window.show()
        qapp.processEvents()

        chat = make(ElaChatWidget, window)
        chat.resize(700, 600)
        chat.show()
        qapp.processEvents()

        _assert_theme_palette(chat.chatInput().textEdit(), ElaThemeType.ThemeMode.Dark)
    finally:
        if window is not None:
            window.hide()
        eTheme.setThemeMode(previous)
