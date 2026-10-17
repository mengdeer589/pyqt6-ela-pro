"""``ElaChip`` 测试：初值 / 文本 / 圆角 / 关闭 / 选择 / 颜色 / 信号。"""

from __future__ import annotations

import pytest
from PyQt6.QtGui import QColor
from PyQt6ElaWidgetTools import ElaIconType, eTheme, ElaThemeType

from pyqt6_ela_pro._colors import _contrast_ratio, get_color_scheme
from pyqt6_ela_pro._theme import blend
from pyqt6_ela_pro.ela_chip import ElaChip


@pytest.fixture
def chip(make):
    return make(ElaChip)


class TestElaChipInit:
    @pytest.mark.parametrize(
        ("attr", "expected"),
        [
            ("_text", ""),
            ("_border_radius", 6),
            ("_is_closable", False),
            ("_is_checkable", False),
            ("_is_checked", False),
            ("_chip_color", ElaChip.ElaChipColorType.Default),
        ],
    )
    def test_initialization_with_defaults(self, chip, attr, expected):
        assert getattr(chip, attr) == expected

    def test_initialization_with_text(self, make):
        assert make(ElaChip, text="标签").text() == "标签"


class TestElaChipText:
    @pytest.mark.parametrize(
        ("initial", "new", "expected"),
        [("", "新标签", "新标签"), ("旧标签", "", "")],
        ids=["set-new", "clear"],
    )
    def test_set_text(self, make, initial, new, expected):
        chip = make(ElaChip, text=initial)
        chip.setText(new)
        assert chip.text() == expected


class TestElaChipBorderRadius:
    def test_border_radius_default(self, chip):
        assert chip.borderRadius() == 6

    @pytest.mark.parametrize("radius", [12, 0], ids=["12", "0"])
    def test_set_border_radius(self, chip, radius):
        chip.setBorderRadius(radius)
        assert chip.borderRadius() == radius

    def test_pill_roundtrip(self, chip):
        assert chip.isPill() is False
        chip.setPill(True)
        assert chip.isPill() is True
        chip.setPill(False)
        assert chip.isPill() is False


class TestElaChipClosable:
    def test_closable_default_false(self, chip):
        assert chip.isClosable() is False

    def test_set_closable(self, chip):
        chip.setClosable(True)
        assert chip.isClosable() is True

    def test_set_closable_toggle(self, chip):
        chip.setClosable(True)
        chip.setClosable(False)
        assert chip.isClosable() is False


class TestElaChipCheckable:
    def test_checkable_default_false(self, chip):
        assert chip.isCheckable() is False

    def test_set_checkable(self, chip):
        chip.setCheckable(True)
        assert chip.isCheckable() is True

    def test_checked_default_false(self, chip):
        assert chip.isChecked() is False

    def test_set_checked(self, chip):
        chip.setChecked(True)
        assert chip.isChecked() is True

    def test_set_checked_while_checkable(self, chip):
        chip.setCheckable(True)
        chip.setChecked(True)
        assert chip.isChecked() is True


class TestElaChipColor:
    def test_color_default(self, chip):
        assert chip.color() == ElaChip.ElaChipColorType.Default

    def test_set_color_primary(self, chip):
        chip.setColor(ElaChip.ElaChipColorType.Primary)
        assert chip.color() == ElaChip.ElaChipColorType.Primary

    def test_set_color_all_values(self, chip):
        for c in ElaChip.ElaChipColorType:
            chip.setColor(c)
            assert chip.color() == c


class TestElaChipSignals:
    @pytest.mark.parametrize("name", ["closed", "clicked", "checkedChanged"])
    def test_has_signal(self, chip, name):
        assert hasattr(chip, name)

    def test_closed_signal_is_callable(self, chip):
        assert callable(chip.closed)


class TestElaChipColorHelpers:
    @pytest.mark.parametrize(
        "getter",
        [ElaChip._getBackgroundColor, ElaChip._getForegroundColor],
        ids=["background", "foreground"],
    )
    def test_color_helper_returns_qcolor(self, chip, getter):
        assert isinstance(getter(chip), QColor)


class TestElaChipContrast:
    """彩字与底色对比度 ≥ 4.5（WCAG AA）。

    回归：暗色下 ``_getForegroundColor`` 借的是「亮色主题」的 accent ——
    primary / blue 拿到 #0067c0 压在暗底上只有 1.43；亮色下 yellow 1.31。
    """

    @pytest.mark.parametrize(
        "color", list(ElaChip.ElaChipColorType), ids=[c.name for c in ElaChip.ElaChipColorType]
    )
    @pytest.mark.parametrize(
        "mode",
        [ElaThemeType.ThemeMode.Light, ElaThemeType.ThemeMode.Dark],
        ids=["light", "dark"],
    )
    def test_foreground_readable_in_all_states(self, make, color, mode):
        """半透明底要合成到主题表面后再算对比度（空闲 / hover / press 都达标）。"""
        previous = eTheme.getThemeMode()
        eTheme.setThemeMode(mode)
        try:
            chip = make(ElaChip, text="标签")
            chip.setColor(color)
            surface = eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.BasicBase)
            samples = []
            for hovered, pressed in ((False, False), (True, False), (True, True)):
                bg, _border, fg = chip._resolve_colors(hovered, pressed)
                composited = blend(
                    surface, QColor(bg.red(), bg.green(), bg.blue()), bg.alphaF()
                )
                samples.append((hovered, pressed, fg, composited))
        finally:
            eTheme.setThemeMode(previous)
        for hovered, pressed, fg, composited in samples:
            assert _contrast_ratio(fg, composited) >= 4.5, (
                color.name,
                mode,
                hovered,
                pressed,
                fg.name(),
                composited.name(),
            )


class TestElaChipStates:
    def test_selected_uses_solid_fill(self, make):
        chip = make(ElaChip, text="标签")
        chip.setColor(ElaChip.ElaChipColorType.Blue)
        chip.setCheckable(True)
        chip.setChecked(True)
        scheme = get_color_scheme("blue", chip._theme_mode)
        bg, _border, fg = chip._resolve_colors(False, False)
        assert bg.name() == scheme["solid"].name()
        assert fg.name() == scheme["solidText"].name()

    def test_hover_tint_is_stronger(self, make):
        chip = make(ElaChip, text="标签")
        chip.setColor(ElaChip.ElaChipColorType.Blue)
        idle, _b, fg = chip._resolve_colors(False, False)
        hover, _b2, fg2 = chip._resolve_colors(True, False)
        press, _b3, _fg3 = chip._resolve_colors(True, True)
        assert idle.alpha() < hover.alpha() < press.alpha()
        assert fg2.name() == fg.name()

    def test_leading_icon_roundtrip_and_width(self, make):
        chip = make(ElaChip, text="标签")
        base = chip.sizeHint().width()
        chip.setLeadingIcon(ElaIconType.IconName.Tag)
        assert chip.leadingIcon() == ElaIconType.IconName.Tag
        assert chip.sizeHint().width() > base
        chip.setLeadingIcon(None)
        assert chip.sizeHint().width() == base

    def test_close_hit_area_is_wide_enough(self, make):
        chip = make(ElaChip, text="标签")
        chip.setClosable(True)
        assert chip._close_rect().width() >= 20


class TestElaChipDeleteLater:
    def test_delete_later_cleans_up(self, chip):
        chip.deleteLater()
