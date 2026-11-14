from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QApplication

from pyqt6_ela_pro.ela_figure_canvas import (
    _CJK_FONTS,
    ElaFigureCanvas,
    _FigureCanvas,
    _rc_params,
)
from PyQt6ElaWidgetTools import ElaThemeType


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

    def test_light_rcparams_defined(self, qapp):

        params = _rc_params(ElaThemeType.ThemeMode.Light)
        assert "figure.facecolor" in params
        assert "axes.facecolor" in params
        assert len(params) == 8

    def test_dark_rcparams_defined(self, qapp):

        params = _rc_params(ElaThemeType.ThemeMode.Dark)
        assert "figure.facecolor" in params
        assert len(params) == 8

    def test_cjk_fonts_defined(self):

        assert len(_CJK_FONTS) > 0
        assert "Microsoft YaHei" in _CJK_FONTS


@pytest.mark.skipif(_FigureCanvas is None, reason="matplotlib 未安装")
class TestThemeSwitchUpdatesArtists:
    """切换主题时已在图上的标题 / 轴名 / 图例也要换色（rcParams 只影响新对象）。"""

    def test_existing_artists_follow_theme(self, qapp):
        import matplotlib.colors as mcolors

        from pyqt6_ela_pro._theme import text

        canvas = ElaFigureCanvas()
        ax = canvas.figure.add_subplot(111)
        ax.plot([0, 1], [0, 1], label="s")
        ax.set_title("t")
        ax.set_xlabel("x")
        ax.legend()

        canvas._onThemeChanged(ElaThemeType.ThemeMode.Dark)

        assert (
            mcolors.to_hex(ax.title.get_color())
            == text(ElaThemeType.ThemeMode.Dark).name()
        )
        assert (
            mcolors.to_hex(ax.xaxis.label.get_color())
            == text(ElaThemeType.ThemeMode.Dark).name()
        )
        assert (
            mcolors.to_hex(ax.get_legend().get_texts()[0].get_color())
            == text(ElaThemeType.ThemeMode.Dark).name()
        )
        canvas.deleteLater()
