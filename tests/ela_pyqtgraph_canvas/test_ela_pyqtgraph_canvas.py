from __future__ import annotations

import pytest

import pyqt6_ela_pro.ela_pyqtgraph_canvas as mod
from pyqt6_ela_pro.ela_pyqtgraph_canvas import (
    _DARK_THEME,
    _LIGHT_THEME,
    ElaPlotWidget,
    pg,
)


class TestElaPlotWidgetNoPyqtgraph:
    def test_placeholder_or_real(self):

        if pg is None:
            with pytest.raises(ImportError):
                ElaPlotWidget()
        else:
            pw = ElaPlotWidget()
            assert pw is not None
            pw.deleteLater()

    def test_light_theme_defined(self):

        assert "background" in _LIGHT_THEME
        assert "foreground" in _LIGHT_THEME
        assert "axis" in _LIGHT_THEME
        assert len(_LIGHT_THEME) == 5

    def test_dark_theme_defined(self):

        assert "background" in _DARK_THEME
        assert "foreground" in _DARK_THEME
        assert len(_DARK_THEME) == 5

    def test_light_and_dark_backgrounds_differ(self):

        assert _LIGHT_THEME["background"] != _DARK_THEME["background"]

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
