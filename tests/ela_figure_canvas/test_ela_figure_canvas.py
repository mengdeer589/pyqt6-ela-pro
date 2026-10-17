from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QApplication

from pyqt6_ela_pro.ela_figure_canvas import (
    _CJK_FONTS,
    _DARK_RC_PARAMS,
    _LIGHT_RC_PARAMS,
    ElaFigureCanvas,
    _FigureCanvas,
)


class TestElaFigureCanvas:
    def test_placeholder_or_real(self):

        if _FigureCanvas is None:
            with pytest.raises(ImportError):
                ElaFigureCanvas()
        else:
            QApplication.instance() or QApplication([])
            canvas = ElaFigureCanvas()
            assert canvas is not None
            canvas.deleteLater()

    def test_light_rcparams_defined(self):

        assert "figure.facecolor" in _LIGHT_RC_PARAMS
        assert "axes.facecolor" in _LIGHT_RC_PARAMS
        assert len(_LIGHT_RC_PARAMS) == 8

    def test_dark_rcparams_defined(self):

        assert "figure.facecolor" in _DARK_RC_PARAMS
        assert len(_DARK_RC_PARAMS) == 8

    def test_cjk_fonts_defined(self):

        assert len(_CJK_FONTS) > 0
        assert "Microsoft YaHei" in _CJK_FONTS
