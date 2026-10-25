"""中文系统图表字体单族化（bug 报告 §3）。

多族字体列表在 Win7 上是慢 shaping 路径，而图表文本（轴标签 / 图例 / 标题）
逐重绘——中文系统收成单族 ``Microsoft YaHei``（即 ``FONT_FAMILIES`` 首族）。
"""

from __future__ import annotations

import pytest

from pyqt6_ela_pro.charts.axes import _shared as charts_axes
from pyqt6_ela_pro.charts._tokens import FONT_FAMILIES

_CJK = "Microsoft YaHei"


@pytest.fixture
def cjk_system(monkeypatch):
    monkeypatch.setattr(charts_axes, "system_cjk_font_family", lambda: _CJK)
    return _CJK


@pytest.fixture
def non_cjk_system(monkeypatch):
    monkeypatch.setattr(charts_axes, "system_cjk_font_family", lambda: None)
    return None


class TestChartFont:
    def test_single_family_on_cjk(self, cjk_system):
        assert charts_axes.chartFont(12).families() == [_CJK]

    def test_tokens_families_without_cjk(self, non_cjk_system):
        assert charts_axes.chartFont(12).families() == list(FONT_FAMILIES)

    def test_size_weight_style_preserved(self, cjk_system):
        font = charts_axes.chartFont(17, 600)
        assert font.families() == [_CJK]
        assert font.pixelSize() == 17
        assert font.weight() == 600
        assert font.styleHint() == font.StyleHint.SansSerif
