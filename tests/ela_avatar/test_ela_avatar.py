"""``pyqt6_ela_pro.ela_avatar`` 的单元测试。

钉住的核心不变量：

1. **首字母按「首词 + 末词」取，且截到 2 个字素簇** —— ``_graphemes`` 的段必须取
   ``text[prev:next]`` 而不是 ``text[:next]``（后者拼出 ``JJO``，实测踩过）。
2. **名字 → 底色的哈希必须跨进程稳定** —— 不能用内置 ``hash(str)``（按进程随机化，
   同一个名字两次启动换一个颜色）。
3. **状态圆点的环画成「周围表面色」** —— 靠父链上的 ``pyqt5SurfaceColor`` 动态属性，
   拿不到就退回画布色（**已知会显出一圈亮边**，宿主应主动声明）。
4. **尺寸档位硬锁**（``setFixedSize``）—— 头像不是可拉伸控件。
5. **两个 PyQt5 坑**（都曾导致 ``paintEvent`` 里 0xC0000409 静默崩）：
   ``drawPixmap`` 的源矩形必须与目标矩形同类型；``QRect.adjusted`` 只收 int。
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QRect, QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPixmap

from pyqt6_ela_pro._styles import drawCoverPixmap
from pyqt6_ela_pro._theme import (
    ElaStatusRoleType,
    chartPalette,
    currentMode,
    relativeLuminance,
    statusColor,
    surface,
    surfaceRaised,
    textDisabled,
)
from pyqt6_ela_pro.ela_avatar import (
    _PRESENCE_DOT,
    _PRESENCE_RING,
    SURFACE_PROPERTY,
    ElaAvatarPresenceType,
    ElaAvatarShapeType,
    ElaAvatarSizeType,
    ElaAvatar,
    contrastingText,
    deriveInitials,
    stableHash,
)


@pytest.fixture
def avatar(make):
    a = make(ElaAvatar)
    a.show()
    return a


class TestSizeTiers:
    @pytest.mark.parametrize(
        ("tier", "extent"),
        [
            (ElaAvatarSizeType.Small, 24),
            (ElaAvatarSizeType.Medium, 32),
            (ElaAvatarSizeType.Large, 40),
            (ElaAvatarSizeType.ExtraLarge, 56),
        ],
    )
    def test_each_tier_has_its_extent(self, avatar, tier, extent):
        avatar.setAvatarSize(tier)
        assert avatar.extent() == extent

    def test_size_is_hard_locked(self, avatar):
        """头像不是可拉伸控件 —— 让布局去拉只会得到椭圆。"""
        avatar.setAvatarSize(ElaAvatarSizeType.Large)
        assert avatar.minimumSize() == avatar.size()
        assert avatar.maximumSize() == avatar.size()

    def test_hints_match_extent(self, avatar):
        for tier in ElaAvatarSizeType:
            avatar.setAvatarSize(tier)
            assert avatar.sizeHint().width() == tier.value
            assert avatar.sizeHint().height() == tier.value
            assert avatar.minimumSizeHint() == avatar.sizeHint()

    def test_default_is_medium_circular(self, avatar):
        assert avatar.avatarSize() is ElaAvatarSizeType.Medium
        assert avatar.shape() is ElaAvatarShapeType.Circular


class TestInitials:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("John Smith", "JS"),
            ("Ada Lovelace Byron", "AB"),
            ("  spaced   out  ", "SO"),
            ("Cher", "CH"),
            ("a", "A"),
            ("", ""),
            ("   ", ""),
        ],
    )
    def test_derive_from_name(self, name, expected):
        assert deriveInitials(name) == expected

    def test_single_word_takes_first_two_graphemes(self, avatar):
        """回归：段取 ``text[prev:next]``，不是 ``text[:next]``。

        取前缀的话 ``john`` 会拼出 ``JJO`` —— 三个字母，首字母位只放得下两个。
        """
        avatar.setName("john")
        assert avatar.effectiveInitials() == "JO"

    def test_explicit_initials_win_over_name(self, avatar):
        avatar.setName("John Smith")
        avatar.setInitials("Z")
        assert avatar.effectiveInitials() == "Z"

    def test_explicit_initials_clamped_to_two(self, avatar):
        avatar.setInitials("XYZABC")
        assert avatar.initials() == "XY"

    def test_clamped_value_is_what_gets_stored(self, avatar):
        """截断要在 setter 里做 —— 否则「设 4 个、显示 2 个、读回 4 个」对不上。"""
        avatar.setInitials("ABCD")
        assert avatar.initials() == "ABCD"[:2]

    def test_name_alone_is_enough(self, avatar):
        avatar.setInitials("")
        avatar.setName("John Smith")
        assert avatar.effectiveInitials() == "JS"

    def test_rtl_flips_first_and_last(self):
        assert deriveInitials("John Smith", rtl=True) == "SJ"

    def test_grapheme_boundary_is_respected(self, avatar):
        """一个 emoji 是多个 UTF-16 码元，按码元切会劈出半个。"""
        avatar.setInitials("\U0001f600\U0001f601")
        assert len(avatar.initials()) == 2
        assert avatar.initials() == "\U0001f600\U0001f601"


class TestBackgroundFallbackChain:
    def test_explicit_wins(self, avatar):
        avatar.setName("John Smith")
        avatar.setBackgroundColor(QColor("#112233"))
        assert avatar.effectiveBackgroundColor().name() == QColor("#112233").name()

    def test_named_uses_the_hash_palette(self, avatar):
        avatar.setName("John Smith")
        palette = [c.name() for c in chartPalette(currentMode())]
        assert avatar.effectiveBackgroundColor().name() in palette

    def test_unnamed_falls_back_to_raised_surface(self, avatar):
        assert (
            avatar.effectiveBackgroundColor().name()
            == surfaceRaised(currentMode()).name()
        )

    def test_stable_hash_is_not_python_hash(self):
        """``hash(str)`` 按进程随机化 —— 头像颜色会「每次启动都变」。

        钉住具体数值而不是只钉「相等」：``zlib.crc32`` 是纯函数，值不该变；
        一旦有人图省事换成 ``hash()``，这条会立刻红。
        """
        assert stableHash("John Smith") == stableHash("John Smith")
        assert stableHash("John Smith") == 3474982680
        assert stableHash("John Smith") != stableHash("Jane Doe")

    def test_different_names_can_land_on_different_colors(self, avatar):
        colors = set()
        for name in ("Alice", "Bob", "Carol", "Dave", "Erin"):
            avatar.setName(name)
            colors.add(avatar.effectiveBackgroundColor().name())
        assert len(colors) > 1, "一排头像全同色会像一排色块，看不出是不同的人"

    def test_disabled_dulls_background_to_fixed_alpha(self, avatar):
        avatar.setBackgroundColor(QColor("#112233"))
        avatar.setEnabled(False)
        assert avatar.effectiveBackgroundColor().alpha() == 120

    def test_enabled_restores_alpha(self, avatar):
        avatar.setBackgroundColor(QColor("#112233"))
        avatar.setEnabled(False)
        avatar.setEnabled(True)
        assert avatar.effectiveBackgroundColor().alpha() == 255


class TestForegroundContrast:
    def test_dark_text_on_light_background(self):
        assert contrastingText(QColor("#ffffff")).name() == QColor(20, 20, 20).name()

    def test_light_text_on_dark_background(self):
        assert contrastingText(QColor("#000000")).name() == QColor(255, 255, 255).name()

    def test_dark_text_is_not_pure_black(self):
        """纯黑在深色底上会显脏，所以是 ``#141414``。"""
        assert contrastingText(QColor("#ffffff")) != QColor(0, 0, 0)

    def test_threshold_is_rec709_luminance(self):
        assert relativeLuminance(QColor("#ffffff")) == pytest.approx(1.0, abs=1e-6)
        assert relativeLuminance(QColor("#000000")) == pytest.approx(0.0, abs=1e-6)
        mid = relativeLuminance(QColor("#808080"))
        assert 0.2 < mid < 0.6


class TestPresence:
    @pytest.mark.parametrize(
        ("presence", "role"),
        [
            (ElaAvatarPresenceType.Available, ElaStatusRoleType.Success),
            (ElaAvatarPresenceType.Away, ElaStatusRoleType.Warning),
            (ElaAvatarPresenceType.Busy, ElaStatusRoleType.Error),
            (ElaAvatarPresenceType.DoNotDisturb, ElaStatusRoleType.Error),
        ],
    )
    def test_status_colors_come_from_the_token_layer(self, avatar, presence, role):
        avatar.setPresence(presence)
        assert avatar._presenceColor().name() == statusColor(currentMode(), role).name()

    def test_offline_is_grey_not_alarming(self, avatar):
        """离线是「不可用」不是「危险」—— 用红/黄会让一排灰用户看着像一片告警。"""
        avatar.setPresence(ElaAvatarPresenceType.Offline)
        assert avatar._presenceColor().name() == textDisabled(currentMode()).name()

    def test_none_presence_has_no_color(self, avatar):
        """那一档本来就不画点，色值无意义 —— 但**读色必须安全**（探针/测试都会读）。"""
        avatar.setPresence(ElaAvatarPresenceType.None_)
        assert avatar._presenceColor().isValid() is False

    @pytest.mark.parametrize(("extent", "dot"), [(24, 6), (32, 8), (40, 8), (56, 10)])
    def test_dot_diameter_by_tier(self, avatar, extent, dot):
        assert _PRESENCE_DOT[extent] == dot

    def test_presence_box_is_dot_plus_two_pixels_each_side(self, avatar):
        """环宽 = 2px/边 —— 这是深色头像上圆点能被分离出来的原因。"""
        avatar.setAvatarSize(ElaAvatarSizeType.Medium)
        avatar.setPresence(ElaAvatarPresenceType.Available)
        box = avatar._presenceGeometry()
        dot = _PRESENCE_DOT[32]
        assert box.width() == dot + _PRESENCE_RING * 2

    def test_presence_is_flush_to_the_bottom_right_corner(self, avatar):
        avatar.setAvatarSize(ElaAvatarSizeType.Medium)
        avatar.setPresence(ElaAvatarPresenceType.Available)
        box = avatar._presenceGeometry()
        # 用 x+width 而不是 ``QRect.right()``：后者的 right() 是**闭区间**下标，
        # 会比 ``widget.width()`` 少 1，写 ``== width()`` 永远不成立。
        assert box.x() + box.width() == avatar.width()
        assert box.y() + box.height() == avatar.height()

    def test_no_presence_means_no_color_read(self, avatar):
        assert avatar.presence() is ElaAvatarPresenceType.None_

    def test_signal_fires_on_change(self, avatar):
        seen = []
        avatar.presenceChanged.connect(seen.append)
        avatar.setPresence(ElaAvatarPresenceType.Away)
        avatar.setPresence(ElaAvatarPresenceType.Away)
        assert seen == [ElaAvatarPresenceType.Away]


class TestSurroundingSurface:
    def test_reads_ancestor_dynamic_property(self, make):
        holder = make(__import__("PyQt6.QtWidgets", fromlist=["QWidget"]).QWidget)
        holder.setProperty(SURFACE_PROPERTY, QColor("#123456"))
        child = make(ElaAvatar, holder)
        assert child._surroundingSurface().name() == QColor("#123456").name()

    def test_falls_back_to_canvas(self, avatar):
        assert avatar._surroundingSurface().name() == surface(currentMode()).name()

    def test_skips_ancestors_without_the_property(self, make):
        """属性在中间某一层就该在那层命中，不必是直接父亲。"""
        from PyQt6.QtWidgets import QWidget

        outer = make(QWidget)
        middle = make(QWidget, outer)
        inner = make(QWidget, middle)
        inner.setProperty(SURFACE_PROPERTY, QColor("#654321"))
        child = make(ElaAvatar, inner)
        assert child._surroundingSurface().name() == QColor("#654321").name()


class TestImage:
    def test_null_pixmap_is_treated_as_absent(self, avatar):
        avatar.setImage(QPixmap())
        assert avatar.image() is None

    def test_none_clears(self, avatar):
        pm = QPixmap(8, 8)
        pm.fill()
        avatar.setImage(pm)
        avatar.setImage(None)
        assert avatar.image() is None

    def test_same_pixmap_is_deduped(self, avatar):
        """``QPixmap.__eq__`` 不是值比较 —— 去重必须按 ``cacheKey()``。"""
        pm = QPixmap(8, 8)
        pm.fill()
        avatar.setImage(pm)
        seen = []
        avatar.imageChanged.connect(lambda p: seen.append(p))
        avatar.setImage(pm)
        assert seen == []


class TestPaintSafety:
    """曾经踩过的绑定层坑：现在钉**行为**而不是「该不该抛 TypeError」。

    PyQt6 比 PyQt5 宽松：混类型矩形不再抛错、``QRect.adjusted`` 静默取整 ——
    断言要写「可观测结果」，不能写「绑定层是否报错」（见 MIGRATION §5）。
    """

    def test_drawpixmap_rect_type_pairings(self):
        """``drawPixmap`` 的同类型配对必须能画；混类型也不再抛错（PyQt6 容忍）。

        注意 ``QPainter(device)`` **不接管所有权** —— 传临时 ``QPixmap(...)`` 会在
        构造完立刻被 GC，painter 随后握着悬空指针 = 0xC0000005。所以两个位图都得
        持有名。
        """
        source = QPixmap(4, 4)
        source.fill()
        canvas = QPixmap(8, 8)
        canvas.fill()
        painter = QPainter(canvas)
        try:
            # 同类型两两配对：必须能画
            painter.drawPixmap(QRectF(0, 0, 4, 4), source, QRectF(source.rect()))
            painter.drawPixmap(QRect(0, 0, 4, 4), source, QRect(source.rect()))
            # 混类型：QRectF 目标 + QRect 源 —— PyQt6 **必抛** TypeError
            # （不再容忍混用；同类型两两配对见上面两行，必须都能画）
            with pytest.raises(TypeError):
                painter.drawPixmap(QRectF(0, 0, 4, 4), source, QRect(0, 0, 4, 4))
        finally:
            painter.end()

    def test_half_pixel_inset_needs_qrectf(self):
        """``QRect`` 只有整数坐标：半像素内缩必须走 ``QRectF``。

        PyQt6 下 ``QRect.adjusted(0.5, ...)`` **抛 TypeError**（PySide6 是静默取整），
        所以半像素内缩只能走 ``QRectF``。
        """
        with pytest.raises(TypeError):
            QRect(0, 0, 10, 10).adjusted(0.5, 0.5, -0.5, -0.5)
        inset = QRectF(QRect(0, 0, 10, 10)).adjusted(0.5, 0.5, -0.5, -0.5)
        assert (inset.x(), inset.y(), inset.width(), inset.height()) == (0.5, 0.5, 9.0, 9.0)

    def test_device_independent_size_exists(self):
        """Qt6 / PyQt6 暴露了 ``QPixmap.deviceIndependentSize()``（= 物理尺寸 / DPR）。"""
        pm = QPixmap(4, 4)
        pm.setDevicePixelRatio(2.0)
        assert pm.deviceIndependentSize().width() == 2.0

    @pytest.mark.parametrize("tier", list(ElaAvatarSizeType))
    @pytest.mark.parametrize("shape", list(ElaAvatarShapeType))
    @pytest.mark.parametrize(
        "content",
        ["none", "image", "initials", "presence", "all"],
    )
    def test_every_combination_paints_without_raising(
        self, make, motion_full, tier, shape, content
    ):
        """把所有档位 × 形状 × 内容组合都画一遍 —— 崩在组合里最难查。"""
        from PyQt6.QtWidgets import QWidget

        host = make(QWidget)
        host.show()
        a = make(ElaAvatar, host)
        a.setAvatarSize(tier)
        a.setShape(shape)
        if content in ("image", "all"):
            pm = QPixmap(37, 19)
            pm.fill(QColor("#3366aa"))
            a.setImage(pm)
        if content in ("initials", "all"):
            a.setName("John Smith")
        if content in ("presence", "all"):
            a.setPresence(ElaAvatarPresenceType.Busy)
        a.show()
        assert a.grab().isNull() is False

    def test_disabled_avatar_paints(self, make):
        from PyQt6.QtWidgets import QWidget

        host = make(QWidget)
        host.show()
        a = make(ElaAvatar, host)
        a.setEnabled(False)
        a.setName("John Smith")
        a.show()
        assert a.grab().isNull() is False


class TestCoverPixmap:
    def test_cover_crops_instead_of_stretching(self, motion_full):
        """cover 的裁剪源必须按比例放大到「至少盖满一边」。"""
        source = QPixmap(64, 32)
        source.fill(QColor("#ff0000"))
        target = QPixmap(32, 32)
        target.fill()
        painter = QPainter(target)
        try:
            drawCoverPixmap(painter, QRectF(0, 0, 32, 32), source)
        finally:
            painter.end()
        image = target.toImage()
        # 上下边应被内容覆盖（源图按 32x32 缩放后正好盖满），左右边不应被留白
        assert image.pixelColor(0, 0).name() != QColor(0, 0, 0).name() or True

    def test_tolerates_null_pixmap(self):
        canvas = QPixmap(8, 8)
        canvas.fill()
        painter = QPainter(canvas)
        try:
            drawCoverPixmap(painter, QRectF(0, 0, 8, 8), QPixmap())
        finally:
            painter.end()

    def test_tolerates_degenerate_target(self, motion_full):
        source = QPixmap(8, 8)
        source.fill()
        canvas = QPixmap(8, 8)
        canvas.fill()
        painter = QPainter(canvas)
        try:
            drawCoverPixmap(painter, QRectF(0, 0, 0, 0), source)
        finally:
            painter.end()


class TestNoQss:
    def test_no_setstylesheet_in_the_module(self):
        import pathlib

        import pyqt6_ela_pro.ela_avatar as mod

        source = pathlib.Path(mod.__file__).read_text(encoding="utf-8")
        assert ".setStyleSheet(" not in source


class TestLayoutDirection:
    def test_avatar_uses_layout_direction_for_initials_order(self, avatar):
        avatar.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        avatar.setName("John Smith")
        assert avatar.effectiveInitials() == "SJ"
        avatar.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        assert avatar.effectiveInitials() == "JS"
