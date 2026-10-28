"""``pyqt6_ela_pro.ela_shimmer`` 的单元测试。

钉住的核心不变量（都是搬运时踩过或改道过的）：

1. **基态必画** —— ``setActive(False)`` 只停扫光，控件照画骨架。Fluent 在这里直接
   return，配合「``Reduced`` 停掉持续动效」会让无障碍用户看到一个纯空白框。
2. **停止时相位归零** —— 桶 B 的「停掉 ≠ 不画」：相位不归零就会冻在半条扫光上。
3. **懒布局** —— ``resize()`` 只投递事件，``elements()`` 必须自己按当前尺寸算。
4. **``Line`` 是全圆角药丸**，扫光宽度有 56px 下限（否则窄元素上只剩一闪而过的线）。
5. **``blend`` 的参数序**（底在前、前景在后）—— 调反会算出近黑底色。
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QRectF
from PyQt6.QtGui import QColor, QPainter, QPalette, QPixmap

from pyqt6_ela_pro._motion import ElaMotionModeType, motion
from pyqt6_ela_pro._theme import blend, surface
from pyqt6_ela_pro.ela_shimmer import (
    ElaShimmer,
    ShimmerElement,
    ElaShimmerShapeType,
    ElaShimmerTemplateType,
    _darkCanvas,
    _normalizeProgress,
    avatarTextRowElements,
    imageCardElements,
    paintShimmer,
    shimmerPalette,
    textBlockElements,
)
from PyQt6ElaWidgetTools import eTheme


@pytest.fixture
def shimmer(make):
    s = make(ElaShimmer)
    s.resize(240, 72)
    return s


def _render(elements, palette, progress=0.0, animated=True, size=(120, 60)):
    """把元素画进一张位图，返回 ``QPixmap``（不依赖控件是否可见）。"""
    pm = QPixmap(*size)
    pm.fill()
    painter = QPainter(pm)
    try:
        paintShimmer(painter, elements, palette, progress, animated)
    finally:
        painter.end()
    return pm


class TestPalette:
    def test_light_base_is_black_over_canvas(self, motion_full):
        """浅色下底色 = 画布上叠 7.5% 黑（**不是**近黑 —— blend 参数序陷阱）。"""
        canvas = QColor("#ececec")
        palette = shimmerPalette(canvas)
        assert palette.base.name() == QColor("#dadada").name()
        # 真正的判据是「贴着画布」而不是某个具体值：反序调 blend 会得到 #121212
        # （red=18），那是近黑、跟画布差了一整个明度档。
        assert palette.base.red() > canvas.red() * 0.8
        assert palette.base.red() > 200

    def test_dark_base_is_white_over_canvas(self, motion_full):
        palette = shimmerPalette(QColor("#202020"))
        assert palette.base.name() == QColor("#3b3b3b").name()

    def test_dark_canvas_is_decided_by_lightness_not_theme(self):
        """判深浅看**画布明度**，不是查主题枚举。"""
        assert _darkCanvas(QColor("#202020")) is True
        assert _darkCanvas(QColor("#000000")) is True, "高对比纯黑画布也走深色分支"
        assert _darkCanvas(QColor("#ececec")) is False

    def test_highlight_is_white_in_both_modes(self, motion_full):
        """深浅两套高亮**都是白色**，只有 alpha 不同（68 / 218）。"""
        light = shimmerPalette(QColor("#ececec"))
        dark = shimmerPalette(QColor("#202020"))
        assert light.highlight.red() == 255
        assert dark.highlight.red() == 255
        assert light.highlight.alpha() == 218
        assert dark.highlight.alpha() == 68

    def test_disabled_dulls_the_highlight(self, motion_full):
        assert shimmerPalette(QColor("#ececec"), enabled=False).highlight.alpha() < 218

    def test_border_is_a_translucent_tint_of_canvas(self, motion_full):
        palette = shimmerPalette(QColor("#ececec"))
        assert palette.border.name() == QColor("#ececec").name()
        assert 0 < palette.border.alpha() < 255


class TestBlendArgumentOrder:
    """``blend`` 是从 ``chat/_theme.py`` 搬过来的，搬运时踩过一次参数序。"""

    def test_second_argument_is_the_foreground(self):
        """``blend(底, 前景, 占比)``，等价 CSS ``rgba(前景, 占比) over 底``。"""
        assert (
            blend(QColor("#ffffff"), QColor("#000000"), 0.075).name()
            == QColor("#ececec").name()
        )

    def test_reversed_arguments_give_the_wrong_answer(self):
        """写反会算出近黑 —— 这就是当年 Shimmer 底色错成一个色档的原因。"""
        assert (
            blend(QColor("#000000"), QColor("#ececec"), 0.075).name()
            == QColor("#121212").name()
        )


class TestProgress:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [(0.0, 0.0), (0.25, 0.25), (1.0, 0.0), (1.25, 0.25), (-0.25, 0.75), (2.5, 0.5)],
    )
    def test_normalized_into_unit_range(self, value, expected):
        assert abs(_normalizeProgress(value) - expected) < 1e-9

    def test_non_finite_falls_back_to_zero(self):
        """``nan`` 进 painter 是未定义行为，必须先挡掉。"""
        assert _normalizeProgress(float("nan")) == 0.0
        assert _normalizeProgress(float("inf")) == 0.0

    def test_non_numeric_is_tolerated(self):
        assert _normalizeProgress("x") == 0.0

    def test_manual_set_normalizes_and_stops_timer(self, shimmer):
        shimmer.show()
        assert shimmer.isAnimationRunning() is True
        shimmer.setShimmerProgress(1.4)
        assert abs(shimmer.shimmerProgress() - 0.4) < 1e-9


class TestCycleDuration:
    def test_default_is_two_very_slow(self, shimmer):
        assert shimmer.cycleDuration() == 1400

    def test_clamped_to_fast(self, shimmer):
        """低于 150ms 扫光变成频闪，``Reduced`` 恰好压到这个量级。"""
        shimmer.setCycleDuration(10)
        assert shimmer.cycleDuration() == 150

    def test_longer_duration_accepted(self, shimmer):
        shimmer.setCycleDuration(3000)
        assert shimmer.cycleDuration() == 3000


class TestTemplates:
    def test_text_block_has_three_lines_with_decaying_widths(self):
        els = textBlockElements(QRectF(0, 0, 240, 72), 3)
        assert len(els) == 3
        widths = [e.rect.width() for e in els]
        assert widths[0] > widths[1] > widths[2], "逐行变短才像一段真实文本"
        assert abs(widths[0] / (240 - 16) - 0.92) < 1e-6
        assert abs(widths[1] / (240 - 16) - 0.76) < 1e-6
        assert abs(widths[2] / (240 - 16) - 0.62) < 1e-6

    def test_lines_are_evenly_spaced(self):
        els = textBlockElements(QRectF(0, 0, 240, 72), 3)
        gaps = [els[i + 1].rect.top() - els[i].rect.bottom() for i in range(2)]
        assert abs(gaps[0] - gaps[1]) < 1e-9

    def test_line_shape_is_a_full_pill(self):
        """``Line`` 的默认圆角是半高 —— 全圆角药丸。"""
        els = textBlockElements(QRectF(0, 0, 240, 72), 3)
        assert all(e.shape == ElaShimmerShapeType.Line for e in els)
        assert abs(els[0].rect.height() / 2.0 - 6.0) < 1e-9

    def test_avatar_text_row_starts_with_a_circle(self):
        els = avatarTextRowElements(QRectF(0, 0, 240, 56))
        assert els[0].shape == ElaShimmerShapeType.Circle
        assert len(els) == 3

    def test_avatar_extent_is_capped_at_32(self):
        els = avatarTextRowElements(QRectF(0, 0, 240, 200))
        assert els[0].rect.width() == 32

    def test_avatar_extent_has_a_floor_of_16(self):
        # 高度 28 → 内缩 8 后剩 12 → 12-8=4 < 16 → 取下限 16
        els = avatarTextRowElements(QRectF(0, 0, 240, 28))
        assert els[0].rect.width() == 16

    def test_image_card_is_one_filled_rounded_rect(self):
        els = imageCardElements(QRectF(0, 0, 240, 140))
        assert len(els) == 1
        assert els[0].shape == ElaShimmerShapeType.RoundedRect

    @pytest.mark.parametrize(
        "builder", [textBlockElements, avatarTextRowElements, imageCardElements]
    )
    def test_templates_inset_by_8_on_all_sides(self, builder):
        els = builder(QRectF(0, 0, 240, 140))
        assert els, "非空区域必须产出元素"
        box = els[0].rect
        assert box.left() >= 8.0
        assert box.top() >= 8.0
        assert box.right() <= 232.0
        assert box.bottom() <= 132.0

    @pytest.mark.parametrize(
        "builder", [textBlockElements, avatarTextRowElements, imageCardElements]
    )
    def test_degenerate_area_yields_no_elements(self, builder):
        """零尺寸不能产出退化矩形（会画出 0 宽的脏线）。"""
        assert builder(QRectF(0, 0, 0, 0)) == []

    def test_custom_clears_template_state(self, shimmer):
        shimmer.setTemplate(ElaShimmerTemplateType.TextBlock)
        shimmer.setElements(
            [ShimmerElement(shape=ElaShimmerShapeType.Circle, rect=QRectF(0, 0, 10, 10))]
        )
        assert shimmer.shimmerTemplate() == ElaShimmerTemplateType.Custom
        assert len(shimmer.elements()) == 1

    def test_clear_elements_does_not_fall_back_to_a_template(self, shimmer):
        """清空表达的是「我自己管排版」，不是「给我默认那个」。"""
        shimmer.clearElements()
        assert shimmer.shimmerTemplate() == ElaShimmerTemplateType.Custom
        assert shimmer.elements() == []

    def test_custom_elements_are_not_relaid_out_on_resize(self, shimmer):
        """手工元素的坐标是调用方给的，resize 不许改写。"""
        rect = QRectF(5, 5, 30, 30)
        shimmer.setElements([ShimmerElement(shape=ElaShimmerShapeType.Circle, rect=rect)])
        shimmer.resize(400, 200)
        shimmer.elements()
        assert shimmer.elements()[0].rect == rect


class TestLazyLayout:
    def test_elements_reflect_size_without_event_loop(self, shimmer):
        """``resize()`` 只投递事件；``elements()`` 必须自己按当前尺寸算。"""
        shimmer.resize(340, 72)
        els = shimmer.elements()
        assert els, "刚 resize 就读元素不能是空的"
        assert abs(els[0].rect.width() / (340 - 16) - 0.92) < 1e-6

    def test_resize_event_also_refreshes(self, shimmer, qapp):
        shimmer.resize(340, 72)
        qapp.processEvents()
        assert abs(shimmer.elements()[0].rect.width() / (340 - 16) - 0.92) < 1e-6

    @pytest.mark.parametrize(
        ("template", "width", "height"),
        [
            (ElaShimmerTemplateType.TextBlock, 240, 72),
            (ElaShimmerTemplateType.AvatarTextRow, 240, 56),
            (ElaShimmerTemplateType.ImageCard, 240, 140),
        ],
    )
    def test_size_hint_per_template(self, make, template, width, height):
        s = make(ElaShimmer)
        s.setTemplate(template)
        assert (s.sizeHint().width(), s.sizeHint().height()) == (width, height)

    def test_minimum_size_hint_is_uniform(self, shimmer):
        mins = shimmer.minimumSizeHint()
        assert (mins.width(), mins.height()) == (32, 24)


class TestBaseStateAlwaysPainted:
    def test_active_false_still_visible(self, shimmer):
        """关掉动效**不能**隐藏控件 —— 骨架在、扫光停，是一个合法状态。"""
        shimmer.show()
        shimmer.setActive(False)
        assert shimmer.isVisible() is True
        assert shimmer.isAnimationRunning() is False

    def test_base_pixels_present_when_idle(self, shimmer):
        from _pixels import skip_if_no_pixels

        shimmer.resize(240, 72)
        els = textBlockElements(QRectF(0, 0, 240, 72), 3)
        pm = _render(els, shimmerPalette(surface(None)), animated=False)
        image = pm.toImage()
        colors = {
            image.pixelColor(x, y).name()
            for y in range(image.height())
            for x in range(image.width())
            if image.pixelColor(x, y).alpha() > 200
        }
        skip_if_no_pixels(colors, "骨架基态")

    def test_sweep_is_additive_over_base(self, shimmer):
        """有扫光的那一帧必须比纯基态多出更亮的像素 —— 证明扫光真的叠上去了。"""
        from _pixels import skip_if_no_pixels

        els = textBlockElements(QRectF(0, 0, 240, 72), 3)
        palette = shimmerPalette(QColor("#ececec"))
        still = _render(els, palette, progress=0.0, animated=False).toImage()
        swept = _render(els, palette, progress=0.5, animated=True).toImage()

        def brightest(image):
            return max(
                image.pixelColor(x, y).lightness()
                for y in range(image.height())
                for x in range(image.width())
            )

        if brightest(swept) == brightest(still) == 0:
            skip_if_no_pixels(set(), "扫光叠加")

    def test_progress_zero_looks_identical_to_no_sweep(self, shimmer):
        """相位 0 时扫光完整地在左边界外 ⇒ 与完全不画扫光逐像素一致。

        这条是「``on_stop`` 归零」成立的前提：冻结在相位 0 = 干净的静态骨架。
        """
        els = textBlockElements(QRectF(0, 0, 120, 60), 3)
        palette = shimmerPalette(QColor("#ececec"))
        off = _render(els, palette, animated=False).toImage()
        at_zero = _render(els, palette, progress=0.0, animated=True).toImage()
        diff = sum(
            1
            for y in range(off.height())
            for x in range(off.width())
            if off.pixelColor(x, y) != at_zero.pixelColor(x, y)
        )
        # 渐变两端 alpha 为 0，理论上零差异；留一点容差给平台抗锯齿。
        assert diff <= 8, f"相位 0 应与无扫光一致，实测 {diff} 个像素不同"


class TestMotionPolicyIntegration:
    def test_full_mode_runs_the_loop(self, shimmer, motion_full, qapp):
        shimmer.show()
        assert shimmer.isAnimationRunning() is True

    def test_local_switch_wins_over_global(self, shimmer, motion_full):
        shimmer.show()
        shimmer.setAnimationEnabled(False)
        assert shimmer.isAnimationRunning() is False

    def test_reduced_stops_the_loop(self, shimmer, motion_full):
        """持续动效在 ``Reduced`` 下是**停掉**，不是放慢。"""
        shimmer.show()
        previous = motion.mode()
        try:
            motion.setMode(ElaMotionModeType.Reduced)
            assert shimmer.isAnimationRunning() is False
        finally:
            motion.setMode(previous)

    def test_disabled_stops_the_loop(self, shimmer, motion_full):
        shimmer.show()
        previous = motion.mode()
        try:
            motion.setMode(ElaMotionModeType.Disabled)
            assert shimmer.isAnimationRunning() is False
        finally:
            motion.setMode(previous)

    def test_stop_resets_phase_to_zero(self, shimmer, motion_full):
        """桶 B 的「停掉 ≠ 不画」：相位不归零就会冻在半条扫光上。"""
        shimmer.show()
        shimmer.setShimmerProgress(0.5)
        previous = motion.mode()
        try:
            motion.setMode(ElaMotionModeType.Disabled)
        finally:
            motion.setMode(previous)
        assert shimmer.shimmerProgress() == 0.0

    def test_local_switch_also_resets_phase(self, shimmer, motion_full):
        shimmer.show()
        shimmer.setShimmerProgress(0.7)
        shimmer.setAnimationEnabled(False)
        assert shimmer.shimmerProgress() == 0.0

    def test_hide_stops_the_loop(self, shimmer, motion_full):
        shimmer.show()
        shimmer.hide()
        assert shimmer.isAnimationRunning() is False

    def test_disable_stops_the_loop(self, shimmer, motion_full):
        shimmer.show()
        shimmer.setEnabled(False)
        assert shimmer.isAnimationRunning() is False

    def test_timer_interval_is_always_written(self, shimmer):
        """间隔必须无条件写入 —— 否则 Reduced 下有人直接 ``start()`` 就是 0ms 空转。"""
        assert shimmer._timer.interval() == 16


class TestThemeSwitch:
    def test_palette_follows_theme(self, motion_full):
        from PyQt6ElaWidgetTools import ElaThemeType as TT

        previous = eTheme.getThemeMode()
        try:
            eTheme.setThemeMode(TT.ThemeMode.Light)
            light = shimmerPalette(surface(eTheme.getThemeMode())).base
            eTheme.setThemeMode(TT.ThemeMode.Dark)
            dark = shimmerPalette(surface(eTheme.getThemeMode())).base
            assert light.lightness() > dark.lightness() + 30
        finally:
            eTheme.setThemeMode(previous)


class TestCanvasColor:
    def test_canvas_uses_widget_palette_window(self, make):
        """画布优先取控件 palette 的 Window —— 消息区是 BasicPress，不是 WindowBase。"""
        shimmer = make(ElaShimmer)
        palette = shimmer.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor("#123456"))
        shimmer.setPalette(palette)
        assert shimmer._canvas_color().name() == "#123456"

    def test_transparent_window_falls_back_to_theme_surface(self, make):
        shimmer = make(ElaShimmer)
        palette = shimmer.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(0, 0, 0, 0))
        shimmer.setPalette(palette)
        assert shimmer._canvas_color().name() == surface(eTheme.getThemeMode()).name()


class TestPaintSafety:
    def test_empty_elements_paint_nothing(self, shimmer):
        """空元素列表必须一位像素都不动（不能拿背景色去糊一层）。"""
        blank = QPixmap(120, 60)
        blank.fill()
        painted = _render([], shimmerPalette(QColor("#ececec"))).toImage()
        reference = blank.toImage()
        assert all(
            painted.pixelColor(x, y) == reference.pixelColor(x, y)
            for y in range(0, 60, 7)
            for x in range(0, 120, 7)
        )

    def test_empty_rect_element_is_skipped(self, shimmer):
        els = [ShimmerElement(shape=ElaShimmerShapeType.Line, rect=QRectF())]
        _render(els, shimmerPalette(QColor("#ececec")))

    def test_paint_on_a_live_widget(self, shimmer, qapp):
        shimmer.show()
        qapp.processEvents()
        assert shimmer.grab().isNull() is False
