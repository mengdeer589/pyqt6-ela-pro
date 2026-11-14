"""Markdown 选中色：固定跟随主题，不继承系统 ``Highlight``。

Win11 的系统 ``Highlight`` 是用户个性色、Win7 是另一套（浅底黑字），失焦后
还会切到 ``Inactive`` 组。查看器必须在 ``_applyThemeStyle`` 里把选中色固定到
Markdown 主题（见 ``_styles.setTextSelectionColors``）。
"""

from __future__ import annotations

import pytest
from PyQt6.QtGui import QColor, QPalette
from PyQt6ElaWidgetTools import ElaThemeType, eTheme

from pyqt6_ela_pro import ElaMarkdownViewer, markdownThemes
from pyqt6_ela_pro.markdown_viewer.themes import _BUILTIN_MD_THEMES

_MODES = (ElaThemeType.ThemeMode.Dark, ElaThemeType.ThemeMode.Light)

_GROUPS = (
    QPalette.ColorGroup.Active,
    QPalette.ColorGroup.Inactive,
    QPalette.ColorGroup.Disabled,
)


@pytest.fixture(autouse=True)
def _restore_global_theme():
    """用例会切全局主题；不还原会污染同目录其它文件的浅色断言。"""
    previous = eTheme.getThemeMode()
    yield
    eTheme.setThemeMode(previous)


def _contrast(a: QColor, b: QColor) -> float:
    """WCAG 相对亮度对比度。"""

    def luminance(color: QColor) -> float:
        def channel(value: int) -> float:
            value /= 255.0
            return (
                value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
            )

        return (
            0.2126 * channel(color.red())
            + 0.7152 * channel(color.green())
            + 0.0722 * channel(color.blue())
        )

    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _browser_palette(viewer: ElaMarkdownViewer) -> QPalette:
    return viewer.textBrowser().palette()


class TestSelectionPalette:
    @pytest.mark.parametrize("mode", _MODES)
    def test_pinned_to_theme_in_all_groups(self, make, mode):
        eTheme.setThemeMode(mode)
        viewer = make(ElaMarkdownViewer)
        palette = _browser_palette(viewer)
        viewport_palette = viewer.textBrowser().viewport().palette()
        for group in _GROUPS:
            assert (
                palette.color(group, QPalette.ColorRole.Highlight).name()
                == viewer._selection_bg.name()
            )
            assert (
                palette.color(group, QPalette.ColorRole.HighlightedText).name()
                == viewer._selection_text.name()
            )
            assert (
                viewport_palette.color(group, QPalette.ColorRole.Highlight).name()
                == viewer._selection_bg.name()
            )

    def test_theme_mode_switch_recomputes(self, make):
        eTheme.setThemeMode(ElaThemeType.ThemeMode.Light)
        viewer = make(ElaMarkdownViewer)
        light_bg = QColor(viewer._selection_bg)
        eTheme.setThemeMode(ElaThemeType.ThemeMode.Dark)
        assert viewer._selection_bg != light_bg
        assert (
            _browser_palette(viewer).color(QPalette.ColorRole.Highlight).name()
            == viewer._selection_bg.name()
        )

    def test_highlighted_text_is_body_text_color(self, make):
        viewer = make(ElaMarkdownViewer)
        palette = _browser_palette(viewer)
        assert (
            palette.color(QPalette.ColorRole.HighlightedText).name()
            == palette.color(QPalette.ColorRole.Text).name()
        )

    def test_switch_markdown_theme_recomputes_and_restores(self, make):
        viewer = make(ElaMarkdownViewer)
        bear_bg = QColor(viewer._selection_bg)
        assert viewer.setMarkdownTheme("paper") is True
        paper_bg = QColor(viewer._selection_bg)
        assert paper_bg != bear_bg
        assert (
            _browser_palette(viewer).color(QPalette.ColorRole.Highlight).name()
            == paper_bg.name()
        )
        viewer.setMarkdownTheme("bear")
        assert viewer._selection_bg.name() == bear_bg.name()

    @pytest.mark.parametrize("mode", _MODES)
    def test_builtin_themes_keep_readable_contrast(self, make, mode):
        eTheme.setThemeMode(mode)
        viewer = make(ElaMarkdownViewer)
        seen = set()
        for name in markdownThemes():
            if name not in _BUILTIN_MD_THEMES:
                continue
            seen.add(name)
            viewer.setMarkdownTheme(name)
            palette = _browser_palette(viewer)
            background = palette.color(QPalette.ColorRole.Highlight)
            foreground = palette.color(QPalette.ColorRole.HighlightedText)
            assert foreground.name() == palette.color(QPalette.ColorRole.Text).name()
            assert _contrast(background, foreground) >= 4.5, name
        assert seen == set(_BUILTIN_MD_THEMES)
