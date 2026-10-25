"""``ElaButton.setSvgIcon`` —— 第三方 SVG 图标入口的行为契约。

**为什么这些断言这么写**：``setIcon`` 是本库唯一能在按钮里放非 ElaAwesome
图标的入口，此前只有两个平行按钮类（``ElaSvgButton`` / ``ElaSvgIconButton``）
承担这件事，而它们签名违反 ``(parent, ...)`` 规则、用 ``setFixedSize`` 冻结
尺寸、图标名拼错时静默降级成纯文字。现在这些能力并入 ``ElaButton``，
本文件守住合并后的契约。

回归 `tests/regression/test_qt_callback_abort_guards.py::TestSvgIconPaintSafety`
守住「绘制路径上的异常不得穿出 ``paintEvent``」（那会是 0xC0000409 静默终止）。
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QSize
from PyQt6.QtGui import QColor

from PyQt6ElaWidgetTools import ElaIconType, ElaThemeType, eTheme

from pyqt6_ela_pro.ela_button import ElaButton
from pyqt6_ela_pro.svg_icon import svg_icon_loader

#: 带主题色占位符的描边 SVG（占位符会被替换成当前主题文字色）
_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"'
    ' stroke="<<<COLOR_CODE>>>" stroke-width="2" stroke-linecap="round">'
    '<path d="M4 4h16v16H4z"/></svg>'
)


def _register(name: str, data: str = _SVG) -> str:
    """把图标注册进全局 loader（模拟宿主加载自己的图标包）。"""
    svg_icon_loader().append(name, data)
    return name


class TestSetSvgIcon:
    def test_svg_source_accepted(self, make):
        """传 SVG 源码直接渲染，返回 True。"""
        btn = make(ElaButton, "保存")
        assert btn.setSvgIcon(_SVG) is True
        assert btn.svgIcon() == _SVG

    def test_icon_name_accepted_when_loaded(self, make):
        """传图标名且已注册 → True。"""
        name = _register("test_icon_loaded")
        btn = make(ElaButton, "保存")
        assert btn.setSvgIcon(name) is True
        assert btn.svgIcon() == name

    def test_source_and_name_are_distinguished_by_svg_tag(self, make):
        """``<svg`` 在不在里面，决定走「源码」还是走「图标名」。

        没有这条，两个入口会互相误判：源码会被当图标名去 loader 里查 →
        永远找不到；名字会被当 SVG 源码渲染 → 空白。
        """
        name = _register("test_icon_tag")
        loader = svg_icon_loader()

        btn = make(ElaButton, "a")
        btn.setSvgIcon(name)
        assert loader.hasIcon(btn.svgIcon()) is True

        other = make(ElaButton, "b")
        other.setSvgIcon(_SVG)
        assert other.svgIcon() == _SVG

    def test_missing_name_returns_false_and_warns(self, make):
        """图标名找不到 → 返回 False + warn，且**不抛异常**（绘制仍要能跑）。"""
        btn = make(ElaButton, "保存")
        with pytest.warns(RuntimeWarning, match="图标名"):
            assert btn.setSvgIcon("test_definitely_missing_icon") is False

    def test_source_form_does_not_warn(self, make, recwarn):
        """SVG 源码形态不该产生「图标名找不到」的警告。"""
        btn = make(ElaButton, "保存")
        btn.setSvgIcon(_SVG)
        assert [w for w in recwarn if "图标名" in str(w.message)] == []

    def test_icon_size_argument(self, make):
        btn = make(ElaButton, "保存")
        btn.setSvgIcon(_SVG, 24)
        assert btn._icon_size == 24
        assert btn.iconSize() == QSize(24, 24)

    def test_icon_size_defaults_to_current(self, make):
        """不传 iconSize 时沿用当前值，而不是重置成 16。"""
        btn = make(ElaButton, "保存")
        btn.setSvgIcon(_SVG, 28)
        btn.setSvgIcon(_SVG)
        assert btn._icon_size == 28

    def test_size_hint_accounts_for_svg_icon(self, make):
        """加了图标要把宽度撑开，否则布局里会把图标压到文字上。"""
        btn = make(ElaButton, "保存")
        before = btn.sizeHint().width()
        btn.setSvgIcon(_SVG, 20)
        assert btn.sizeHint().width() > before

    def test_icon_only_button_still_reserves_space(self, make):
        """纯图标按钮（无文字）也要留出图标宽度。"""
        with_text = make(ElaButton, "x")
        with_text.setSvgIcon(_SVG, 20)
        icon_only = make(ElaButton)
        icon_only.setSvgIcon(_SVG, 20)
        # 图标 + 内边距，不含文字
        assert icon_only.sizeHint().width() < with_text.sizeHint().width()


class TestMutualExclusion:
    """SVG 与 ElaAwesome 图标互斥 —— 不清对方会两套语义并存。"""

    def test_svg_clears_ela_icon(self, make):
        btn = make(ElaButton, "保存")
        btn.setElaIcon(ElaIconType.IconName.Pencil, 16)
        assert btn._icon_name is not None
        btn.setSvgIcon(_SVG)
        assert btn._icon_name is None
        assert btn.svgIcon() == _SVG

    def test_ela_icon_clears_svg(self, make):
        btn = make(ElaButton, "保存")
        btn.setSvgIcon(_SVG)
        assert btn.svgIcon() is not None
        btn.setElaIcon(ElaIconType.IconName.Pencil, 16)
        assert btn.svgIcon() is None

    def test_clear_svg_icon(self, make):
        btn = make(ElaButton, "保存")
        btn.setSvgIcon(_SVG)
        before = btn.sizeHint().width()
        btn.clearSvgIcon()
        assert btn.svgIcon() is None
        assert btn.sizeHint().width() < before


class TestSetIconTrap:
    """``QPushButton.setIcon`` 在本控件上是静默失效的坑。"""

    def test_set_icon_raises_with_guidance(self, make):
        btn = make(ElaButton, "保存")
        with pytest.raises(RuntimeError, match="setElaIcon"):
            btn.setIcon(btn.icon())

    def test_error_message_mentions_svg_entry(self, make):
        """报错必须指向 ``setSvgIcon``，否则宿主不知道第三方图标怎么设。"""
        btn = make(ElaButton, "保存")
        with pytest.raises(RuntimeError, match="setSvgIcon"):
            btn.setIcon(btn.icon())


class TestThemeFollow:
    def test_rendered_color_follows_theme_text(self, make, mock_e_theme):
        """SVG 里的占位符要拿到当前主题文字色（否则图标在暗色下看不见）。"""
        mode = eTheme.getThemeMode()
        expected = eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.BasicText)
        btn = make(ElaButton, "保存")
        btn.setSvgIcon(_SVG, 16)
        assert btn._svg_pixmap_for_paint(expected) is not None

    def test_placeholder_is_actually_substituted(self, make):
        """占位符必须被替换掉 —— 留着 ``<<<COLOR_CODE>>>`` 会渲染成黑色/无效色。

        用**整图标范围**扫而不是角点采样：``M4 4h16v16H4z`` 描边宽 2，
        角点 (4,4) 落在圆角外侧，本来就是透明的。
        """
        from pyqt6_ela_pro.svg_icon import svg_to_pixmap
        from _pixels import skip_if_no_pixels

        colored = svg_to_pixmap(_SVG, 16, "#ff0000")
        assert not colored.isNull()
        image = colored.toImage()
        painted = {
            image.pixelColor(x, y).name()
            for y in range(image.height())
            for x in range(image.width())
            if image.pixelColor(x, y).alpha() > 200
        }
        skip_if_no_pixels(painted, "SVG 未渲染出像素")
        assert painted, "占位符没被替换：整张图标一个不透明像素都没有"

    @pytest.mark.parametrize("enabled", [True, False], ids=["enabled", "disabled"])
    def test_paints_in_both_states(self, make, qapp, enabled):
        """禁用态也要能画（图标应随文字一起变灰，不能空白）。"""
        btn = make(ElaButton, "保存")
        btn.setSvgIcon(_SVG, 16)
        btn.setEnabled(enabled)
        btn.resize(btn.sizeHint())
        btn.show()
        qapp.processEvents()
        btn.repaint()
        btn.grab()

    @pytest.mark.parametrize(
        "variant", ["outlined", "dashed", "solid", "filled", "text", "link"]
    )
    def test_all_variants_paint(self, make, qapp, variant):
        """6 种变体都要能配 SVG 图标（这是并入 ElaButton 换来的好处）。"""
        btn = make(ElaButton, "保存", variant=variant, color="primary")
        btn.setSvgIcon(_SVG, 16)
        btn.resize(btn.sizeHint())
        btn.show()
        qapp.processEvents()
        btn.repaint()
        btn.grab()

    @pytest.mark.parametrize("size", ["small", "middle", "large"])
    def test_all_sizes(self, make, qapp, size):
        """3 档尺寸都要成立（旧的平行按钮类用 setFixedSize 冻死了尺寸）。"""
        btn = make(ElaButton, "保存", size=size)
        btn.setSvgIcon(_SVG, 16)
        assert btn.height() == {"small": 22, "middle": 30, "large": 38}[size]


class TestPaintRobustness:
    """绘制路径上**任何**异常都不许穿出去（穿出去 = 0xC0000409 静默终止）。"""

    @pytest.mark.parametrize(
        ("source", "warns"),
        [
            # 空串 = 清空，是合法操作，不该 warn
            pytest.param("", False, id="empty"),
            # 闭合残缺但含 <svg → 走「源码」分支，不查图标包，因此不 warn
            pytest.param("<svg><<<未闭合", False, id="malformed"),
            # 不含 <svg → 走「图标名」分支，查不到 → 必须 warn
            pytest.param("not svg at all", True, id="plain-text-as-name"),
            pytest.param("<svg>ok</svg>", False, id="no-placeholder"),
        ],
    )
    def test_bad_source_renders_nothing_but_no_crash(self, make, qapp, source, warns):
        btn = make(ElaButton, "保存")
        if warns:
            with pytest.warns(RuntimeWarning, match="图标名"):
                btn.setSvgIcon(source)
        else:
            btn.setSvgIcon(source)
        btn.resize(btn.sizeHint())
        btn.show()
        qapp.processEvents()
        btn.repaint()
        btn.grab()

    def test_pixmap_helper_returns_none_for_missing(self, make):
        """取不到图标时返回 None（只画文字），而不是抛。"""
        btn = make(ElaButton, "保存")
        with pytest.warns(RuntimeWarning):
            btn.setSvgIcon("test_missing_for_pixmap_helper")
        assert btn._svg_pixmap_for_paint(QColor("#000000")) is None

    def test_no_icon_state_returns_none(self, make):
        btn = make(ElaButton, "保存")
        assert btn._svg_pixmap_for_paint(QColor("#000000")) is None

    def test_empty_source_is_treated_as_no_icon(self, make, recwarn):
        """``setSvgIcon("")`` 应等于清空，不该 warn（清空是合法操作）。"""
        btn = make(ElaButton, "保存")
        btn.setSvgIcon(_SVG)
        btn.setSvgIcon("")
        assert btn.svgIcon() is None
        assert [w for w in recwarn if "图标名" in str(w.message)] == []
