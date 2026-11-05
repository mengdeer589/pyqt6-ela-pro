"""内置 Markdown 主题矩阵：配色 / 语法 / 排版 token 完整性。"""

from __future__ import annotations

import pytest
from PyQt6.QtGui import QFont

from pyqt6_ela_pro._colors import parse_color
from pyqt6_ela_pro.markdown_viewer.themes import (
    _BUILTIN_MD_THEMES,
    _MD_LAYOUT_DEFAULTS,
    _MD_THEMES,
    _MD_THEME_SEMANTIC_KEYS,
    _MD_THEME_SYNTAX_KEYS,
    _md_layout_spec,
)

EXPECTED_THEMES = {
    "bear",
    "lark",
    "typo",
    "vue",
    "ayu",
    "solarized",
    "indigo",
    "paper",
    "github",
    "nord",
}

LAYOUT_SECTIONS = (
    "heading",
    "quote",
    "table",
    "code",
    "inline_code",
    "hr",
    "link",
    "heading_rule",
)


def _assert_color(value: str) -> None:
    color = parse_color(value)
    assert color.isValid(), value
    assert color.alpha() == 255, value


def test_builtin_theme_set():
    assert set(_BUILTIN_MD_THEMES) == EXPECTED_THEMES


@pytest.mark.parametrize("name", sorted(EXPECTED_THEMES))
@pytest.mark.parametrize("variant", ("light", "dark"))
def test_theme_variant_complete(name: str, variant: str):
    spec = _MD_THEMES[name][variant]
    assert set(spec["semantic"]) == set(_MD_THEME_SEMANTIC_KEYS)
    assert set(spec["syntax"]) == set(_MD_THEME_SYNTAX_KEYS)
    for value in (*spec["semantic"].values(), *spec["syntax"].values()):
        _assert_color(value)


@pytest.mark.parametrize("name", sorted(EXPECTED_THEMES))
def test_layout_tokens_complete_and_in_range(name: str):
    layout = _md_layout_spec(name)
    assert set(layout) == set(_MD_LAYOUT_DEFAULTS)
    for section in LAYOUT_SECTIONS:
        assert set(layout[section]) == set(_MD_LAYOUT_DEFAULTS[section])

    assert isinstance(layout["body_font_family"], str)
    assert 0 <= layout["content_max_width"] <= 1600
    assert 120 <= layout["body_line_height"] <= 220
    assert 0 <= layout["paragraph_margin"] <= 40
    assert 0 <= layout["list_item_margin"] <= 20
    assert 0 <= layout["table_block_margin"] <= 40

    for level in range(1, 7):
        scale, top, bottom, line_height, weight = layout["heading"][level]
        assert 0.9 <= scale <= 3.0
        assert 0 <= top <= 60
        assert 0 <= bottom <= 60
        assert 100 <= line_height <= 250
        assert 100 <= int(weight) <= 900

    quote = layout["quote"]
    assert 0 <= quote["rail_width"] <= 8
    assert 0 <= quote["left_margin"] <= 60
    assert 0 <= quote["block_margin"] <= 40
    assert 0 <= quote["background_alpha"] <= 1

    table = layout["table"]
    assert 0 <= table["top_padding"] <= 30
    assert 0 <= table["bottom_padding"] <= 30
    assert 0 <= table["border_width"] <= 4

    code = layout["code"]
    assert 0 <= code["radius"] <= 12
    assert 0.8 <= code["font_scale"] <= 1.2
    assert 100 <= code["line_height"] <= 220

    rule = layout["heading_rule"]
    assert set(rule["levels"]) <= {1, 2, 3, 4, 5, 6}
    assert 0 <= rule["width"] <= 4

    surface = layout["surface"]
    assert set(surface) == {"light", "dark"}
    for value in surface.values():
        if value is not None:
            _assert_color(value)


def test_paper_tokens():
    layout = _md_layout_spec("paper")
    assert layout["body_font_family"] == "serif"
    assert layout["content_max_width"] == 820
    assert layout["surface"] == {"light": "#f7f1e3", "dark": "#1f1b17"}


def test_github_tokens():
    layout = _md_layout_spec("github")
    assert layout["content_max_width"] == 980
    assert layout["heading_rule"]["levels"] == (1, 2)
    assert layout["table"]["header_background"] is True
    assert int(layout["heading"][1][4]) == int(QFont.Weight.Bold)


def test_nord_tokens():
    layout = _md_layout_spec("nord")
    assert layout["content_max_width"] == 0
    assert layout["surface"] == {"light": None, "dark": None}
    assert _MD_THEMES["nord"]["dark"]["semantic"]["link"] == "#88c0d0"
