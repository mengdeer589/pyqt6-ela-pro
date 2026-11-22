"""颜色混合 / 对比度 canonical 实现的守卫。"""

from __future__ import annotations

from pyqt6_ela_pro._colors import contrastRatio, mixColor
from pyqt6_ela_pro.charts._utils import ramp_color


def test_mix_endpoints_and_clamp():
    red = mixColor("#ff0000", "#0000ff", 0.0)
    blue = mixColor("#ff0000", "#0000ff", 1.0)
    assert red.name() == "#ff0000"
    assert blue.name() == "#0000ff"
    assert mixColor("#ff0000", "#0000ff", -1.0).name() == "#ff0000"
    assert mixColor("#ff0000", "#0000ff", 2.0).name() == "#0000ff"


def test_mix_keeps_alpha():
    mid = mixColor("rgba(255, 0, 0, 0)", "rgba(0, 0, 255, 255)", 0.5)
    assert mid.alpha() == 127
    assert mid.red() == 127
    assert mid.blue() == 127


def test_ramp_color_uses_same_mix():
    colors = ["rgba(255, 0, 0, 0)", "rgba(0, 0, 255, 255)"]
    mid = ramp_color(colors, 0.5)
    assert (mid.red(), mid.green(), mid.blue(), mid.alpha()) == (127, 0, 127, 127)


def test_contrast_ratio_symmetric():
    white, black = "#ffffff", "#000000"
    assert contrastRatio(white, black) == contrastRatio(black, white)
    assert round(contrastRatio(white, black), 2) == 21.0
