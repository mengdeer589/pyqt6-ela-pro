from __future__ import annotations

import re

import pytest
from PyQt6.QtGui import QColor
from PyQt6ElaWidgetTools import ElaThemeType, eTheme

from pyqt6_ela_pro._colors import (
    _COLOR_ALIAS,
    _COLOR_PALETTE,
    _contrast_ratio,
    _resolve_color,
    get_accent_color,
    get_color_scheme,
    state_tint,
    text_on_color,
)
from pyqt6_ela_pro._colors import (
    STATE_HOVER_ALPHA as _HOVER_ALPHA,
    STATE_PRESS_ALPHA as _PRESS_ALPHA,
)
from pyqt6_ela_pro._theme import resetAccentColor, setAccentColor


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
        """深色档必须与 ``eTheme`` 的 ``PrimaryNormal`` 逐值一致。

        库内固定色板写的是 ``#4cc2ff``，而系统主题实际给的是 ``#4abcf7`` ——
        两边不一致正是「ElaButton 主题色和 Ela 自带的对不上」的来源。
        """
        color = get_accent_color("blue", ElaThemeType.ThemeMode.Dark)
        live = eTheme.getThemeColor(
            ElaThemeType.ThemeMode.Dark, ElaThemeType.ThemeColor.PrimaryNormal
        )
        assert color.name() == live.name()

    def test_get_accent_color_resolves_alias(self):
        direct = get_accent_color("blue", ElaThemeType.ThemeMode.Light)
        aliased = get_accent_color("primary", ElaThemeType.ThemeMode.Light)
        assert direct.name() == aliased.name()

    def test_get_accent_color_unknown_falls_back_to_blue(self):
        unknown = get_accent_color("nonexistent", ElaThemeType.ThemeMode.Light)
        blue = get_accent_color("blue", ElaThemeType.ThemeMode.Light)
        assert unknown.name() == blue.name()


class TestLiveAccent:
    """主色（primary / blue）跟着 ``eTheme`` 的实时强调色走，与 Ela 自带控件一致。"""

    @pytest.mark.parametrize(
        "mode",
        [ElaThemeType.ThemeMode.Light, ElaThemeType.ThemeMode.Dark],
        ids=["light", "dark"],
    )
    def test_primary_matches_theme_accent(self, mode):
        live = eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.PrimaryNormal)
        assert get_color_scheme("primary", mode)["accent"].name() == live.name()
        assert get_color_scheme("blue", mode)["accent"].name() == live.name()
        assert get_accent_color("primary", mode).name() == live.name()

    def test_primary_follows_set_accent_color(self):
        """``setAccentColor`` 之后按钮主色要跟着变（旧实现是写死的色板）。"""
        mode = ElaThemeType.ThemeMode.Light
        try:
            setAccentColor("#12ab56", modes=[mode])
            assert get_color_scheme("primary", mode)["accent"].name() == "#12ab56"
            assert get_accent_color("blue", mode).name() == "#12ab56"
        finally:
            resetAccentColor([mode])
        assert get_color_scheme("primary", mode)["accent"].name() == "#0067c0"

    def test_other_colors_are_not_affected_by_accent(self):
        mode = ElaThemeType.ThemeMode.Light
        try:
            setAccentColor("#12ab56", modes=[mode])
            assert get_color_scheme("danger", mode)["accent"].name() == "#ff4d4f"
        finally:
            resetAccentColor([mode])

    def test_scheme_returns_copies(self):
        """调用方就地改返回的 QColor 不能污染缓存（``setAlpha`` 曾污染全局调色板）。"""
        first = get_color_scheme("primary", ElaThemeType.ThemeMode.Light)
        first["accent"].setAlpha(0)
        second = get_color_scheme("primary", ElaThemeType.ThemeMode.Light)
        assert second["accent"].alpha() == 255

    def test_accent_bg_is_tinted_from_accent(self):
        """``accentBg`` 由强调色 tint 出来，换色后不再残留出厂蓝底。"""
        mode = ElaThemeType.ThemeMode.Light
        try:
            setAccentColor("#12ab56", modes=[mode])
            bg = get_color_scheme("primary", mode)["accentBg"]
            assert bg.green() > bg.red() and bg.green() > bg.blue()
        finally:
            resetAccentColor([mode])


class TestTextOnColor:
    """动态底色上的文字色（长按 / 进度填充盖住文字时用）。"""

    def test_dark_background_gets_white(self):
        assert text_on_color(QColor("#0067c0")).name() == "#ffffff"

    def test_light_background_gets_black(self):
        assert text_on_color(QColor("#ffd400")).name() == "#000000"

    def test_invalid_color_falls_back_to_black(self):
        assert text_on_color(QColor()).name() == "#000000"

    @pytest.mark.parametrize("name", ["primary", "danger", "green", "purple"])
    def test_solid_palette_text_matches_on_color(self, name):
        """``solidText`` 本来就是按 solid 底算的，两个入口必须一致。"""
        for mode in (ElaThemeType.ThemeMode.Light, ElaThemeType.ThemeMode.Dark):
            scheme = get_color_scheme(name, mode)
            assert (
                text_on_color(scheme["solid"]).name() == scheme["solidText"].name()
            ), f"{name}/{mode}"
