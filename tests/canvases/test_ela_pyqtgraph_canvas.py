from __future__ import annotations

import pytest

import pyqt6_ela_pro.ela_pyqtgraph_canvas as mod
from pyqt6_ela_pro.ela_pyqtgraph_canvas import (
    ElaPlotWidget,
    _theme_for_mode,
    pg,
)
from PyQt6ElaWidgetTools import ElaThemeType


class TestElaPlotWidgetNoPyqtgraph:
    def test_placeholder_or_real(self):

        if pg is None:
            with pytest.raises(ImportError):
                ElaPlotWidget()
        else:
            pw = ElaPlotWidget()
            assert pw is not None
            pw.deleteLater()

    def test_light_theme_defined(self, qapp):

        theme = _theme_for_mode(ElaThemeType.ThemeMode.Light)
        assert "background" in theme
        assert "foreground" in theme
        assert "axis" in theme
        assert len(theme) == 5

    def test_dark_theme_defined(self, qapp):

        theme = _theme_for_mode(ElaThemeType.ThemeMode.Dark)
        assert "background" in theme
        assert "foreground" in theme
        assert len(theme) == 5

    def test_light_and_dark_backgrounds_differ(self, qapp):

        assert (
            _theme_for_mode(ElaThemeType.ThemeMode.Light)["background"]
            != _theme_for_mode(ElaThemeType.ThemeMode.Dark)["background"]
        )

    def test_pg_import_handled(self):

        if mod.pg is None:
            # When not installed, placeholder should raise
            with pytest.raises(ImportError):
                mod.ElaPlotWidget()
            assert mod.pg is None
        else:
            # When installed, class should exist and be real
            assert hasattr(mod.ElaPlotWidget, "_apply_theme")
            assert mod.pg is not None
