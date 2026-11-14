"""暗色 / 亮色主题必须选用对应的 Markdown 语义配色。

V3.0 把 ``BasicPress`` 等令牌改成了 alpha 叠色，不能再凭它的亮度判断主题；
这里钉住「模式直接决定配色族」这条契约。
"""

from __future__ import annotations

from PyQt6ElaWidgetTools import ElaThemeType

from pyqt6_ela_pro import ElaMarkdownViewer
from pyqt6_ela_pro.markdown_viewer.themes import _md_theme_spec


def _semantic(viewer: ElaMarkdownViewer, mode: str) -> dict:
    return _md_theme_spec(viewer._md_theme)[mode]["semantic"]


class TestThemeModeSelection:
    def test_dark_mode_uses_dark_palette(self, make):
        viewer = make(ElaMarkdownViewer)
        viewer._onThemeChanged(ElaThemeType.ThemeMode.Dark)

        assert viewer._is_dark_theme is True
        assert viewer._code_bg.lightness() < 128
        assert viewer._base_bg.alpha() == 255
        assert viewer._md_list_color.name() == _semantic(viewer, "dark")["list"]
        assert viewer._md_heading_color.name() == _semantic(viewer, "dark")["heading"]

    def test_light_mode_uses_light_palette(self, make):
        viewer = make(ElaMarkdownViewer)
        viewer._onThemeChanged(ElaThemeType.ThemeMode.Light)

        assert viewer._is_dark_theme is False
        assert viewer._code_bg.lightness() > 128
        assert viewer._base_bg.alpha() == 255
        assert viewer._md_list_color.name() == _semantic(viewer, "light")["list"]

    def test_switching_back_and_forth_restores_palette(self, make):
        viewer = make(ElaMarkdownViewer)
        viewer._onThemeChanged(ElaThemeType.ThemeMode.Dark)
        dark_bg = viewer._code_bg.name()
        viewer._onThemeChanged(ElaThemeType.ThemeMode.Light)
        assert viewer._code_bg.name() != dark_bg
        viewer._onThemeChanged(ElaThemeType.ThemeMode.Dark)
        assert viewer._code_bg.name() == dark_bg
