"""示例应用启动默认值（仅在 ``python -m pyqt6_ela_pro.example`` 主路径生效）。"""

from __future__ import annotations

from PyQt6ElaWidgetTools import ElaThemeType, eTheme

from pyqt6_ela_pro.example import __main__ as example_main


class TestExampleStartup:
    def test_default_theme_is_dark(self):
        assert example_main._DEFAULT_THEME_MODE == ElaThemeType.ThemeMode.Dark

    def test_default_background_is_enabled(self):
        """示例启动即打开窗口背景渐变（`ExampleWindow.__init__` 里立即应用）。"""
        assert example_main._DEFAULT_BACKGROUND_ENABLED is True

    def test_apply_default_theme_sets_dark(self, qapp):
        previous = eTheme.getThemeMode()
        try:
            eTheme.setThemeMode(ElaThemeType.ThemeMode.Light)
            example_main._apply_default_theme()
            assert eTheme.getThemeMode() == ElaThemeType.ThemeMode.Dark
        finally:
            eTheme.setThemeMode(previous)
