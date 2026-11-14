"""内容语义色（diff / Callout）跟随 Ela 状态色，并保持可读对比度。"""

from __future__ import annotations

import pytest
from PyQt6ElaWidgetTools import ElaThemeType

from pyqt6_ela_pro._colors import _contrast_ratio
from pyqt6_ela_pro._content_colors import calloutColors, diffColors
from pyqt6_ela_pro._theme import (
    ElaStatusRoleType,
    statusColor,
    surfaceRaised,
    textMuted,
)

_MODES = (ElaThemeType.ThemeMode.Light, ElaThemeType.ThemeMode.Dark)
_IDS = ("light", "dark")


@pytest.mark.parametrize("mode", _MODES, ids=_IDS)
def test_diff_colors_follow_status_roles(qapp, mode):
    colors = diffColors(mode)
    assert colors["add"].hue() == statusColor(mode, ElaStatusRoleType.Success).hue()
    assert colors["delete"].hue() == statusColor(mode, ElaStatusRoleType.Error).hue()
    assert colors["hunk"].name() == textMuted(mode).name()

    background = surfaceRaised(mode)
    for key in ("add", "delete"):
        ratio = _contrast_ratio(colors[key], background)
        assert ratio >= 4.5, f"{mode.name}/{key}: {ratio:.2f}:1"


@pytest.mark.parametrize("mode", _MODES, ids=_IDS)
def test_callout_colors_follow_status_roles(qapp, mode):
    colors = calloutColors(mode)
    assert colors["warning"].hue() == statusColor(mode, ElaStatusRoleType.Warning).hue()
    assert colors["caution"].hue() == statusColor(mode, ElaStatusRoleType.Error).hue()

    background = surfaceRaised(mode)
    for key, color in colors.items():
        ratio = _contrast_ratio(color, background)
        assert ratio >= 4.5, f"{mode.name}/{key}: {ratio:.2f}:1"
