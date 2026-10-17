from __future__ import annotations

import re

import pytest
from PyQt6.QtGui import QColor
from PyQt6ElaWidgetTools import ElaThemeType

from pyqt6_ela_pro._colors import (
    _COLOR_ALIAS,
    _COLOR_PALETTE,
    _contrast_ratio,
    _resolve_color,
    get_accent_color,
    get_color_scheme,
    state_tint,
)
from pyqt6_ela_pro._colors import (
    STATE_HOVER_ALPHA as _HOVER_ALPHA,
    STATE_PRESS_ALPHA as _PRESS_ALPHA,
)


class TestColorsPalette:
    def test_palette_has_all_colors(self):
        expected = {
            "default",
            "blue",
            "danger",
            "purple",
            "cyan",
            "green",
            "magenta",
            "pink",
            "red",
            "orange",
            "yellow",
            "volcano",
            "geekblue",
            "lime",
            "gold",
        }
        assert set(_COLOR_PALETTE.keys()) == expected

    def test_each_color_has_light_and_dark(self):
        for name, schemes in _COLOR_PALETTE.items():
            assert "light" in schemes, f"{name} missing light"
            assert "dark" in schemes, f"{name} missing dark"

    def test_each_scheme_has_required_keys(self):
        required = {
            "accent",
            "accentHover",
            "accentActive",
            "accentBg",
            "accentBgHover",
            "textColor",
        }
        for cname, schemes in _COLOR_PALETTE.items():
            for mode in ("light", "dark"):
                keys = set(schemes[mode].keys())
                assert keys == required, f"{cname}/{mode} missing {required - keys}"

    def test_all_hex_colors_are_valid(self):

        for cname, schemes in _COLOR_PALETTE.items():
            for mode in ("light", "dark"):
                for key, val in schemes[mode].items():
                    assert re.match(r"^#[0-9a-fA-F]{6}$", val), (
                        f"{cname}/{mode}/{key}: {val}"
                    )

    def test_each_color_palette_value_parsable_as_qcolor(self):
        for cname, schemes in _COLOR_PALETTE.items():
            for mode in ("light", "dark"):
                for key, val in schemes[mode].items():
                    color = QColor(val)
                    assert color.isValid(), f"{cname}/{mode}/{key}: {val}"


class TestColorsAlias:
    def test_alias_has_expected_mappings(self):
        assert _COLOR_ALIAS == {"primary": "blue"}

    def test_resolve_color_returns_alias(self):
        assert _resolve_color("primary") == "blue"

    def test_default_and_pink_are_distinct(self):
        assert _resolve_color("default") == "default"
        assert _resolve_color("pink") == "pink"

    def test_resolve_color_returns_self_for_unknown(self):
        assert _resolve_color("nonexistent") == "nonexistent"

    def test_resolve_color_returns_self_for_direct_name(self):
        assert _resolve_color("blue") == "blue"
        assert _resolve_color("danger") == "danger"


class TestColorsStateTint:
    """状态层：hover ≈ 8% / press ≈ 12%（**暗叠白 / 亮叠黑**）。"""

    @pytest.mark.parametrize(
        "mode",
        [ElaThemeType.ThemeMode.Light, ElaThemeType.ThemeMode.Dark],
        ids=["light", "dark"],
    )
    def test_alphas(self, mode):
        assert state_tint(mode).alpha() == _HOVER_ALPHA
        assert state_tint(mode, pressed=True).alpha() == _PRESS_ALPHA
        assert _PRESS_ALPHA > _HOVER_ALPHA

    @pytest.mark.parametrize(
        ("mode", "expected_rgb"),
        [
            (ElaThemeType.ThemeMode.Light, (0, 0, 0)),
            (ElaThemeType.ThemeMode.Dark, (255, 255, 255)),
        ],
        ids=["light-black", "dark-white"],
    )
    def test_hue_follows_theme(self, mode, expected_rgb):
        hover = state_tint(mode)
        assert (hover.red(), hover.green(), hover.blue()) == expected_rgb


class TestColorsGetColorScheme:
    def test_get_color_scheme_returns_dict_of_qcolors(self):
        scheme = get_color_scheme("blue", ElaThemeType.ThemeMode.Light)
        assert isinstance(scheme, dict)
        for k, v in scheme.items():
            assert isinstance(v, QColor), f"{k} is not QColor"

    def test_get_color_scheme_has_required_keys(self):
        scheme = get_color_scheme("primary", ElaThemeType.ThemeMode.Light)
        required = {
            "accent",
            "accentHover",
            "accentActive",
            "accentBg",
            "accentBgHover",
            "textColor",
            "solid",
            "solidHover",
            "solidActive",
            "solidText",
        }
        assert required <= set(scheme.keys())

    def test_solid_text_meets_contrast(self):

        for name in _COLOR_PALETTE:
            for mode in (ElaThemeType.ThemeMode.Light, ElaThemeType.ThemeMode.Dark):
                scheme = get_color_scheme(name, mode)
                ratio = _contrast_ratio(scheme["solid"], scheme["solidText"])
                assert ratio >= 4.5, f"{name}/{mode} solid contrast {ratio:.2f}"

    def test_get_color_scheme_light_vs_dark_differ(self):
        light = get_color_scheme("blue", ElaThemeType.ThemeMode.Light)
        dark = get_color_scheme("blue", ElaThemeType.ThemeMode.Dark)
        assert light["accent"].name() != dark["accent"].name()

    def test_get_color_scheme_resolves_alias(self):
        direct = get_color_scheme("blue", ElaThemeType.ThemeMode.Light)
        aliased = get_color_scheme("primary", ElaThemeType.ThemeMode.Light)
        assert direct["accent"].name() == aliased["accent"].name()

    def test_get_color_scheme_unknown_falls_back_to_blue(self):
        unknown = get_color_scheme("nonexistent", ElaThemeType.ThemeMode.Light)
        blue = get_color_scheme("blue", ElaThemeType.ThemeMode.Light)
        assert unknown["accent"].name() == blue["accent"].name()


class TestColorsGetAccentColor:
    def test_get_accent_color_returns_qcolor(self):
        color = get_accent_color("blue", ElaThemeType.ThemeMode.Light)
        assert isinstance(color, QColor)

    def test_get_accent_color_light_value(self):
        color = get_accent_color("blue", ElaThemeType.ThemeMode.Light)
        assert color.name() == "#0067c0"

    def test_get_accent_color_dark_value(self):
        color = get_accent_color("blue", ElaThemeType.ThemeMode.Dark)
        assert color.name() == "#4cc2ff"

    def test_get_accent_color_resolves_alias(self):
        direct = get_accent_color("blue", ElaThemeType.ThemeMode.Light)
        aliased = get_accent_color("primary", ElaThemeType.ThemeMode.Light)
        assert direct.name() == aliased.name()

    def test_get_accent_color_unknown_falls_back_to_blue(self):
        unknown = get_accent_color("nonexistent", ElaThemeType.ThemeMode.Light)
        blue = get_accent_color("blue", ElaThemeType.ThemeMode.Light)
        assert unknown.name() == blue.name()
