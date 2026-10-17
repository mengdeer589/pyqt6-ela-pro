"""``ElaDivider`` 测试：初值 / 文本 / 对齐方向 / 样式 / 垂直切换。"""

from __future__ import annotations

import pytest

from pyqt6_ela_pro.ela_divider import ElaDivider


@pytest.fixture
def d(make):
    return make(ElaDivider)


class TestElaDividerInit:
    @pytest.mark.parametrize(
        ("attr", "expected"),
        [
            ("_text", ""),
            ("_orientation", "center"),
            ("_variant", "solid"),
            ("_vertical", False),
        ],
    )
    def test_initialization_with_defaults(self, d, attr, expected):
        assert getattr(d, attr) == expected

    def test_initialization_with_text(self, make):
        assert make(ElaDivider, text="OR").text() == "OR"

    @pytest.mark.parametrize("orientation", ["left", "right"])
    def test_initialization_with_orientation(self, make, orientation):
        d = make(ElaDivider, orientation=orientation)
        assert d.orientation() == orientation

    def test_initialization_with_variant_dashed(self, make):
        assert make(ElaDivider, variant="dashed").variant() == "dashed"

    def test_initialization_with_vertical(self, make):
        assert make(ElaDivider, vertical=True).isVertical() is True

    def test_initialization_with_all_params(self, make):
        d = make(
            ElaDivider,
            text="分隔",
            orientation="left",
            variant="dashed",
            vertical=False,
        )
        assert d.text() == "分隔"
        assert d.orientation() == "left"
        assert d.variant() == "dashed"
        assert d.isVertical() is False


class TestElaDividerText:
    @pytest.mark.parametrize(
        ("initial", "new", "expected"),
        [("", "新文字", "新文字"), ("旧文字", "", "")],
        ids=["set-new", "clear"],
    )
    def test_set_text(self, make, initial, new, expected):
        d = make(ElaDivider, text=initial)
        d.setText(new)
        assert d.text() == expected


class TestElaDividerOrientation:
    @pytest.mark.parametrize(
        ("initial_vertical", "orientation"),
        [
            (False, "left"),
            (False, "center"),
            (False, "right"),
            (True, "top"),
            (True, "bottom"),
        ],
        ids=["left", "center", "right", "top-vertical", "bottom-vertical"],
    )
    def test_set_orientation(self, make, initial_vertical, orientation):
        d = make(ElaDivider, vertical=initial_vertical)
        d.setOrientation(orientation)
        assert d.orientation() == orientation


class TestElaDividerVariant:
    @pytest.mark.parametrize("variant", ["solid", "dashed"])
    def test_set_variant(self, d, variant):
        d.setVariant(variant)
        assert d.variant() == variant


class TestElaDividerVertical:
    @pytest.mark.parametrize(
        ("initial", "expected"),
        [(False, True), (True, False)],
        ids=["to-vertical", "to-horizontal"],
    )
    def test_set_vertical(self, make, initial, expected):
        d = make(ElaDivider, vertical=initial)
        d.setVertical(expected)
        assert d.isVertical() is expected


class TestElaDividerDeleteLater:
    def test_delete_later_cleans_up(self, d):
        d.deleteLater()
