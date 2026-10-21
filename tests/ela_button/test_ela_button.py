"""``ElaButton`` 测试：初值 / 变体 / 配色 / 尺寸 / 图标 / 禁用 / 主题。"""

from __future__ import annotations

import pytest
from _pixels import skip_if_no_pixels
from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QFocusEvent
from PyQt6.QtTest import QTest
from PyQt6ElaWidgetTools import eApp, eTheme, ElaIconType, ElaPushButton, ElaThemeType

from pyqt6_ela_pro._colors import _contrast_ratio
from pyqt6_ela_pro.ela_button import ElaButton

VARIANTS = ["solid", "dashed", "filled", "text", "link"]

COLORS = [
    "default",
    "primary",
    "danger",
    "blue",
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
]

# size -> (height, borderRadius)；可见面 = 高度 − 2×面内缩（20/28/36）
SIZES = {"small": (22, 4), "middle": (30, 6), "large": (38, 8)}


@pytest.fixture
def btn(make):
    return make(ElaButton)


class TestElaButtonInit:
    @pytest.mark.parametrize(
        ("attr", "expected"),
        [
            ("_variant", "outlined"),
            ("_color_name", "default"),
            ("_danger", False),
            ("_border_radius", 6),
            ("_icon_name", None),
            ("_hovered", False),
        ],
    )
    def test_initialization_with_defaults(self, btn, attr, expected):
        assert getattr(btn, attr) == expected

    def test_default_text_empty(self, btn):
        assert btn.text() == ""

    def test_initialization_with_text(self, make):
        assert make(ElaButton, text="提交").text() == "提交"

    def test_initialization_with_icon(self, make):
        b = make(ElaButton, icon=ElaIconType.IconName.House)
        assert b._icon_name == ElaIconType.IconName.House

    def test_initialization_with_all_params(self, make):
        b = make(
            ElaButton,
            text="删除",
            variant="solid",
            color="danger",
            danger=True,
            size="small",
            parent=None,
        )
        assert b._variant == "solid"
        assert b._color_name == "danger"
        assert b._danger is True
        assert b._border_radius == 4

    def test_initial_sizes_increase(self, make):
        heights = [
            make(ElaButton, size=name).height() for name in ("small", "middle", "large")
        ]
        assert heights[0] < heights[1] < heights[2]


class TestElaButtonVariant:
    @pytest.mark.parametrize("variant", VARIANTS)
    def test_set_variant_roundtrip(self, btn, variant):
        btn.setVariant(variant)
        assert btn.variant() == variant

    def test_default_variant(self, btn):
        assert btn.variant() == "outlined"


class TestElaButtonColor:
    @pytest.mark.parametrize("color", COLORS)
    def test_set_color_roundtrip(self, btn, color):
        btn.setColor(color)
        assert btn.color() == color
        assert btn._color_name == color

    def test_default_color(self, btn):
        assert btn.color() == "default"


class TestElaButtonDanger:
    def test_danger_default_false(self, btn):
        assert btn.isDanger() is False

    def test_set_danger(self, btn):
        btn.setDanger(True)
        assert btn.isDanger() is True

    @pytest.mark.parametrize(
        ("kwargs", "danger", "expected"),
        [
            ({}, True, "danger"),  # 构造参数
            ({"color": "primary"}, True, "danger"),  # danger 覆盖 color
            ({"color": "primary"}, False, "primary"),  # 未开 danger 时保留 color
        ],
        ids=["ctor-danger", "danger-overrides", "keeps-color"],
    )
    def test_effective_color(self, make, kwargs, danger, expected):
        b = make(ElaButton, **kwargs)
        b.setDanger(danger)
        assert b._effective_color() == expected


class TestElaButtonSize:
    @pytest.mark.parametrize(("name", "expected"), SIZES.items())
    def test_set_button_size(self, make, name, expected):
        b = make(ElaButton)
        b.setButtonSize(name)
        assert b.height() == expected[0]
        assert b.buttonSize() == name

    def test_size_variant_does_not_affect_set_border_radius(self, btn):
        btn.setButtonSize("small")
        btn.setBorderRadius(12)
        assert btn.borderRadius() == 12


class TestElaButtonBorderRadius:
    @pytest.mark.parametrize("radius", [0, 12, 50])
    def test_set_border_radius(self, btn, radius):
        btn.setBorderRadius(radius)
        assert btn.borderRadius() == radius

    def test_border_radius_default(self, btn):
        assert btn.borderRadius() == 6

    def test_border_radius_varies_by_size(self, make):
        radii = tuple(
            make(ElaButton, size=name).borderRadius()
            for name in ("small", "middle", "large")
        )
        assert radii == (4, 6, 8)


class TestElaButtonIcon:
    def test_set_ela_icon(self, btn):
        btn.setElaIcon(ElaIconType.IconName.Pencil)
        assert btn._icon_name == ElaIconType.IconName.Pencil

    def test_set_icon_updates_icon_size(self, btn):
        btn.setElaIcon(ElaIconType.IconName.House, iconSize=20)
        assert btn._icon_size == 20

    def test_set_ela_icon_accepts_int(self, btn):
        """F12 回归：图标契约允许传整数值（入口归一）。

        传 int 时上游 ``getElaIcon`` 抛 ``TypeError``，而绘制路径裸调它 =
        异常穿出 ``paintEvent`` = 0xC0000409 崩进程（子进程探针实测）。
        """
        btn.setElaIcon(int(ElaIconType.IconName.Pencil.value))

        assert btn._icon_name == ElaIconType.IconName.Pencil
        btn.resize(80, 30)
        btn.grab()  # 触发 paint：归一后不得抛

    def test_ctor_icon_accepts_int(self, make):
        b = make(ElaButton, icon=int(ElaIconType.IconName.House.value))

        assert b._icon_name == ElaIconType.IconName.House
        b.grab()

    def test_invalid_icon_raises_at_setter(self, btn):
        """非数值输入在 setter 期响亮失败，而不是绘制期静默崩进程。"""
        with pytest.raises((ValueError, TypeError)):
            btn.setElaIcon("not-an-icon")

    def test_set_ela_icon_none_clears(self, btn):
        """``None`` = 清除图标（不画图标分支），不是 None_ 伪成员。"""
        btn.setElaIcon(ElaIconType.IconName.Pencil)

        btn.setElaIcon(None)

        assert btn._icon_name is None
        btn.grab()

    def test_icon_only_button_icon_centered(self, make, qapp):
        """纯图标按钮：图标绘制在按钮正中（回归：曾保留文字间距导致左偏）。"""
        b = make(
            ElaButton,
            icon=ElaIconType.IconName.ArrowUp,
            iconSize=16,
            variant="solid",
            color="primary",
        )
        b.setFixedSize(28, 28)
        b.show()
        qapp.processEvents()
        image = b.grab().toImage()

        xs, ys = [], []
        for y in range(image.height()):
            for x in range(image.width()):
                color = image.pixelColor(x, y)
                if color.red() > 200 and color.green() > 200 and color.blue() > 200:
                    xs.append(x)
                    ys.append(y)
        assert xs, "未找到图标像素"
        center_x = (min(xs) + max(xs) + 1) / 2
        center_y = (min(ys) + max(ys) + 1) / 2
        assert abs(center_x - image.width() / 2) <= 2.0
        assert abs(center_y - image.height() / 2) <= 2.0
        b.close()

    def test_icon_with_text_keeps_spacing(self, make):
        """图标 + 文字：宽度包含间距（纯图标时不加间距）。"""
        icon = make(ElaButton, icon=ElaIconType.IconName.House, size="middle")
        icon.setFixedHeight(28)
        with_text = make(
            ElaButton, text="首页", icon=ElaIconType.IconName.House, size="middle"
        )
        with_text.setFixedHeight(28)
        assert with_text.sizeHint().width() > icon.sizeHint().width()


class TestElaButtonMatchesPushButton:
    """与上游 ``ElaPushButton``（V3.0）对齐：控件高 / 字号 / 可见按钮面。

    上游 V3.0 重构把 ``ElaPushButton`` 改成控件高 30、面内缩
    ``rect().adjusted(1, 1, -1, -1)``（面 28）。``ElaButton`` 的 middle 档
    与它逐值一致（30/28），small / large 按 8px 档距下移（22/38 → 面 20/36）。
    回归：``ElaButton`` 曾按旧上游（控件 38、面 32、3px 阴影边距）对齐 ——
    V3.0 后混排高度与可见面都对不上。
    """

    def test_middle_widget_height_and_font_match_push_button(self, make):
        push = make(ElaPushButton, "确定")
        ela = make(ElaButton, "确定")
        assert ela.height() == push.height() == 30
        assert push.font().pixelSize() == eApp.getFontPixelSize() + 2
        assert ela.font().pixelSize() == push.font().pixelSize()

    @pytest.mark.parametrize(
        ("size", "delta"),
        [("small", 0), ("middle", 2), ("large", 4)],
        ids=["small", "middle", "large"],
    )
    def test_font_follows_app_font_size(self, make, size, delta):
        btn = make(ElaButton, size=size)
        assert btn.font().pixelSize() == eApp.getFontPixelSize() + delta

    def test_size_hint_reserves_face_inset(self, btn):
        """控件宽 = 面宽 + 2×1：面宽最小 64 → 控件最小 66。"""
        assert btn.sizeHint().width() == 66
        assert btn.minimumSizeHint().width() == 50

    def test_visible_face_height_matches_push_button(self, make, qapp):
        """抓图量可见按钮面：两种按钮都应是 28px（控件 30 − 2×1 面内缩）。

        用暗色主题：浅色下 ``ElaPushButton`` 还有 1px 边框，量出来会把边框
        算成/排除掉，让容差没有意义。
        """
        push = make(ElaPushButton, "确定")
        ela = make(ElaButton, "确定", variant="solid", color="primary")

        def face_rows(btn):
            btn.setFixedWidth(120)
            btn.show()
            qapp.processEvents()
            image = btn.grab().toImage()
            x = 8
            center = image.pixelColor(x, image.height() // 2)
            return [
                y
                for y in range(image.height())
                if image.pixelColor(x, y).alpha() > 200
                and abs(image.pixelColor(x, y).lightness() - center.lightness()) <= 2
            ]

        previous = eTheme.getThemeMode()
        eTheme.setThemeMode(ElaThemeType.ThemeMode.Dark)
        try:
            push_rows = face_rows(push)
            ela_rows = face_rows(ela)
        finally:
            eTheme.setThemeMode(previous)

        skip_if_no_pixels(
            {str(y) for y in push_rows} | {str(y) for y in ela_rows},
            "按钮面像素",
        )
        push_face = max(push_rows) - min(push_rows) + 1
        ela_face = max(ela_rows) - min(ela_rows) + 1
        assert abs(push_face - ela_face) <= 2, (push_face, ela_face)


class TestElaButtonFocusRing:
    """键盘聚焦才显示 focus ring（鼠标点击不显示）。"""

    def test_tab_focus_shows_ring(self, make, qapp):
        btn = make(ElaButton, "按钮")
        qapp.sendEvent(
            btn, QFocusEvent(QEvent.Type.FocusIn, Qt.FocusReason.TabFocusReason)
        )
        assert btn._focus_ring is True
        qapp.sendEvent(
            btn, QFocusEvent(QEvent.Type.FocusOut, Qt.FocusReason.OtherFocusReason)
        )
        assert btn._focus_ring is False

    def test_mouse_focus_does_not_show_ring(self, make, qapp):
        btn = make(ElaButton, "按钮")
        qapp.sendEvent(
            btn, QFocusEvent(QEvent.Type.FocusIn, Qt.FocusReason.MouseFocusReason)
        )
        assert btn._focus_ring is False


class TestElaButtonLoading:
    def test_loading_starts_and_stops_spinner(self, make):
        btn = make(ElaButton, "提交")
        assert btn.isLoading() is False
        btn.setLoading(True)
        assert btn.isLoading() is True
        assert btn._spin_timer.isActive() is True
        btn.setLoading(False)
        assert btn.isLoading() is False
        assert btn._spin_timer.isActive() is False

    def test_loading_ignores_clicks(self, make, qapp):
        btn = make(ElaButton, "提交")
        seen = []
        btn.clicked.connect(lambda: seen.append(True))
        btn.setLoading(True)
        QTest.mouseClick(btn, Qt.MouseButton.LeftButton)
        qapp.processEvents()
        assert seen == []


class TestElaButtonAccentText:
    """彩色变体的文字走可读档 ``accentText``（对比度 ≥ 4.5）。"""

    @pytest.mark.parametrize(
        "mode",
        [ElaThemeType.ThemeMode.Light, ElaThemeType.ThemeMode.Dark],
        ids=["light", "dark"],
    )
    def test_outlined_text_uses_readable_accent(self, make, mode):
        previous = eTheme.getThemeMode()
        eTheme.setThemeMode(mode)
        try:
            btn = make(ElaButton, "按钮", variant="outlined", color="blue")
            scheme = btn._scheme()
            _bg, _border, fg = btn._state_colors(scheme, False, False)
        finally:
            eTheme.setThemeMode(previous)
        assert fg.name() == scheme["accentText"].name()
        assert _contrast_ratio(fg, scheme["accentBg"]) >= 4.5


class TestElaButtonDisabled:
    def test_enabled_by_default(self, btn):
        assert btn.isEnabled() is True

    def test_set_disabled(self, btn):
        btn.setEnabled(False)
        assert btn.isEnabled() is False


class TestElaButtonTheme:
    def test_on_theme_changed_updates_mode(self, btn):
        btn._onThemeChanged(ElaThemeType.ThemeMode.Dark)
        assert btn._theme_mode == ElaThemeType.ThemeMode.Dark


class TestElaButtonDeleteLater:
    def test_delete_later_cleans_up(self, btn):
        btn.deleteLater()
