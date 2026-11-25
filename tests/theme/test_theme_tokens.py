"""``pyqt6_ela_pro._theme`` 的单元测试。

三条要钉住的不变量：

1. **强调色派生归 C++** —— ``setAccentColor`` 只写 ``PrimaryNormal``，hover / press
   由上游按 alpha 0.9 / 0.8 派生；Python 侧不得再维护 HSL 表。
2. **reset 还原出厂三元组** —— 换色后再 reset，normal / hover / press 必须逐值
   （含 alpha）回到导入时快照。
3. **状态色不从强调色派生** —— 语义来自色相（琥珀=警告 / 绿=成功），跟着强调色走
   语义就没了。
"""

from __future__ import annotations

import pathlib
from unittest.mock import patch

import pytest
from PyQt6.QtGui import QColor

from pyqt6_ela_pro import _theme as T
from PyQt6ElaWidgetTools import eTheme, ElaThemeType

_PKG = pathlib.Path(__file__).resolve().parents[2] / "pyqt6_ela_pro"

_L = ElaThemeType.ThemeMode.Light
_D = ElaThemeType.ThemeMode.Dark
_TC = ElaThemeType.ThemeColor

#: 上游 V3.0 出厂值（normal 不透明，hover / press 是同色 alpha 0.9 / 0.8）。
#: 改动 eTheme 上游默认值时这里要一起改。
_FACTORY = {
    _L: {
        "normal": QColor(0x00, 0x67, 0xC0, 0xFF),
        "hover": QColor(0x00, 0x67, 0xC0, 0xE6),
        "press": QColor(0x00, 0x67, 0xC0, 0xCC),
    },
    _D: {
        "normal": QColor(0x60, 0xCD, 0xFF, 0xFF),
        "hover": QColor(0x60, 0xCD, 0xFF, 0xE6),
        "press": QColor(0x60, 0xCD, 0xFF, 0xCC),
    },
}


def _slot(mode, token) -> str:
    return QColor(eTheme.getThemeColor(mode, token)).name()


def _rgba(mode, token) -> int:
    return QColor(eTheme.getThemeColor(mode, token)).rgba()


@pytest.fixture(autouse=True)
def _restore_accent():
    """每个用例后把强调色还原 —— 强调色是**进程级全局状态**，不还原会污染后续用例。"""
    yield
    T.resetAccentColor()


class TestReadingLayer:
    @pytest.mark.parametrize(
        "fn",
        [
            T.surface,
            T.surfaceRaised,
            T.surfaceControl,
            T.surfacePopup,
            T.surfaceDialog,
            T.border,
            T.borderStrong,
            T.text,
            T.textMuted,
            T.textDisabled,
            T.accent,
        ],
        ids=lambda f: f.__name__,
    )
    def test_reader_returns_opaque_qcolor(self, fn):
        for mode in (_L, _D):
            c = fn(mode)
            assert isinstance(c, QColor)
            assert c.isValid()
            assert c.alpha() == 255, "读取层必须给不透明色"

    def test_reader_returns_copy_not_shared_reference(self):
        """``getThemeColor`` 返回上游的 ``const QColor&`` —— 必须拷贝。

        直接改返回值会污染全局调色板，且不随主题信号复原。
        """
        a = T.surface(_L)
        a.setAlpha(1)
        assert T.surface(_L).alpha() == 255, "返回值必须是拷贝，不是上游引用"

    def test_readers_differ_between_modes(self):
        for fn in (T.surface, T.text, T.accent, T.border):
            assert fn(_L).name() != fn(_D).name(), f"{fn.__name__} 深浅色应不同"

    @pytest.mark.parametrize("mode", [_L, _D], ids=["light", "dark"])
    def test_surface_raised_uses_card_alpha_token(self, mode):
        expected = T._composite(
            T.surface(mode), eTheme.getThemeColor(mode, _TC.BasicBaseAlpha)
        )
        assert T.surfaceRaised(mode).rgba() == expected.rgba()

    @pytest.mark.parametrize("mode", [_L, _D], ids=["light", "dark"])
    def test_surface_control_uses_control_token(self, mode):
        expected = T._composite(
            T.surfaceRaised(mode), eTheme.getThemeColor(mode, _TC.BasicBase)
        )
        assert T.surfaceControl(mode).rgba() == expected.rgba()


class TestAccentDerivation:
    @pytest.mark.parametrize("mode", [_L, _D], ids=["light", "dark"])
    def test_cpp_derives_hover_and_press(self, mode):
        """C++ 在写 ``PrimaryNormal`` 时自动派生同色 @0.9 / @0.8。"""
        T.setAccentColor(_FACTORY[mode]["normal"], modes=[mode])
        assert _rgba(mode, _TC.PrimaryNormal) == _FACTORY[mode]["normal"].rgba()
        assert _rgba(mode, _TC.PrimaryHover) == _FACTORY[mode]["hover"].rgba()
        assert _rgba(mode, _TC.PrimaryPress) == _FACTORY[mode]["press"].rgba()

    def test_set_accent_writes_only_primary_normal(self):
        """回归：Python 再写 hover / press 会覆盖 C++ 的派生。"""
        with patch.object(eTheme, "setThemeColor", wraps=eTheme.setThemeColor) as spy:
            T.setAccentColor(QColor("#c0392b"))
        assert [call.args[1] for call in spy.call_args_list] == [
            _TC.PrimaryNormal,
            _TC.PrimaryNormal,
        ]

    def test_set_accent_moves_hover_and_press(self):
        T.setAccentColor(QColor("#c0392b"))
        hover = QColor(eTheme.getThemeColor(_L, _TC.PrimaryHover))
        press = QColor(eTheme.getThemeColor(_L, _TC.PrimaryPress))
        assert (hover.name(), hover.alpha()) == ("#c0392b", 230)
        assert (press.name(), press.alpha()) == ("#c0392b", 204)

    @pytest.mark.parametrize(
        ("mode", "factory"),
        [(_L, 0x06000000), (_D, 0x19000000)],
        ids=["light", "dark"],
    )
    def test_set_accent_keeps_basic_alt_base(self, mode, factory):
        """``BasicAltBase`` 是交替行底色与未选中指示器的共享 alpha 叠色，换色不得覆写。"""
        T.setAccentColor(QColor("#c0392b"))
        assert eTheme.getThemeColor(mode, _TC.BasicAltBase).rgba() == factory
        T.resetAccentColor()
        assert eTheme.getThemeColor(mode, _TC.BasicAltBase).rgba() == factory

    @pytest.mark.parametrize("mode", [_L, _D], ids=["light", "dark"])
    def test_reset_restores_factory_exact(self, mode):
        """换色后 reset 必须逐值（含 alpha）回到导入时快照。"""
        T.setAccentColor(QColor("#16a085"))
        T.resetAccentColor()
        for key, token in (
            ("normal", _TC.PrimaryNormal),
            ("hover", _TC.PrimaryHover),
            ("press", _TC.PrimaryPress),
        ):
            assert _rgba(mode, token) == _FACTORY[mode][key].rgba()

    def test_reset_round_trip_is_visually_identical(self):
        """换色再换回来必须**逐值**一致（不是「差不多」）。"""
        tokens = (_TC.PrimaryNormal, _TC.PrimaryHover, _TC.PrimaryPress)
        before = {mode: tuple(_rgba(mode, t) for t in tokens) for mode in (_L, _D)}
        T.setAccentColor(QColor("#16a085"))
        T.resetAccentColor()
        after = {mode: tuple(_rgba(mode, t) for t in tokens) for mode in (_L, _D)}
        assert before == after

    def test_set_accent_covers_both_modes_by_default(self):
        T.setAccentColor(QColor("#c0392b"))
        for mode in (_L, _D):
            assert _slot(mode, _TC.PrimaryNormal) == "#c0392b"

    def test_set_accent_can_target_single_mode(self):
        T.setAccentColor(QColor("#c0392b"), modes=[_L])
        assert _slot(_L, _TC.PrimaryNormal) == "#c0392b"
        assert _slot(_D, _TC.PrimaryNormal) == _FACTORY[_D]["normal"].name()

    @pytest.mark.parametrize("bad", [None, 42, "", "not-a-color"])
    def test_set_accent_rejects_non_color(self, bad):
        before = _slot(_L, _TC.PrimaryNormal)
        T.setAccentColor(bad)
        assert _slot(_L, _TC.PrimaryNormal) == before, "非法输入必须静默忽略"

    @pytest.mark.parametrize(
        "color",
        ["#c0392b", "rgb(192, 57, 43)", "rgba(192, 57, 43, 1)"],
        ids=["hex", "rgb", "rgba"],
    )
    def test_set_accent_accepts_color_strings(self, color):
        """颜色字符串与 ``QColor`` 等价（``QColor`` 自己解析不了 ``rgb()``）。"""
        T.setAccentColor(QColor("#c0392b"))
        expected = _slot(_L, _TC.PrimaryNormal)
        T.resetAccentColor()

        T.setAccentColor(color)
        assert _slot(_L, _TC.PrimaryNormal) == expected

    def test_set_accent_rejects_invalid_color(self):
        before = _slot(_L, _TC.PrimaryNormal)
        T.setAccentColor(QColor())  # 无效 QColor
        assert _slot(_L, _TC.PrimaryNormal) == before


class TestStatusColor:
    def test_error_uses_upstream_native_token(self):
        native = QColor(eTheme.getThemeColor(_L, _TC.StatusDanger)).name()
        assert T.statusColor(_L, T.ElaStatusRoleType.Error).name() == native

    @pytest.mark.parametrize(
        ("role", "token"),
        [
            (T.ElaStatusRoleType.Warning, _TC.StatusWarning),
            (T.ElaStatusRoleType.Success, _TC.StatusSuccess),
        ],
        ids=["warning", "success"],
    )
    def test_warning_success_use_upstream_tokens(self, role, token):
        for mode in (_L, _D):
            assert (
                T.statusColor(mode, role).rgba()
                == eTheme.getThemeColor(mode, token).rgba()
            )

    def test_neutral_falls_back_to_muted_text(self):
        assert (
            T.statusColor(_L, T.ElaStatusRoleType.Neutral).name()
            == T.textMuted(_L).name()
        )

    def test_warning_and_success_keep_their_own_hues(self):
        """状态色的语义来自**色相**，不能跟着强调色走。

        强调色是蓝时若从它派生，Success 会变成一片深蓝 —— 语义完全消失。
        """
        warn = T.statusColor(_L, T.ElaStatusRoleType.Warning)
        succ = T.statusColor(_L, T.ElaStatusRoleType.Success)
        assert warn != succ
        # 警告偏琥珀（hue ~40°）、成功偏绿（hue ~120°）
        assert 0.03 < warn.getHslF()[0] < 0.17
        assert 0.20 < succ.getHslF()[0] < 0.45

    def test_status_unaffected_by_accent_change(self):
        before = [T.statusColor(_L, r).name() for r in T.ElaStatusRoleType]
        T.setAccentColor(QColor("#c0392b"))
        after = [T.statusColor(_L, r).name() for r in T.ElaStatusRoleType]
        assert before == after

    def test_status_differs_between_modes(self):
        for role in (T.ElaStatusRoleType.Warning, T.ElaStatusRoleType.Success):
            assert T.statusColor(_L, role).name() != T.statusColor(_D, role).name()

    def test_illegal_role_falls_back_to_neutral(self):
        assert (
            T.statusColor(_L, 99).name()
            == T.statusColor(_L, T.ElaStatusRoleType.Neutral).name()
        )

    def test_accepts_bare_int(self):
        assert (
            T.statusColor(_L, int(T.ElaStatusRoleType.Error)).name()
            == T.statusColor(_L, T.ElaStatusRoleType.Error).name()
        )


class TestSeverityColor:
    """``ElaSeverity`` 的取色：Info 走强调色，其余走状态色。"""

    def test_info_uses_accent(self):
        assert T.severityColor(_L, T.ElaSeverity.Info).name() == T.accent(_L).name()

    @pytest.mark.parametrize(
        "severity,role",
        [
            (T.ElaSeverity.Success, T.ElaStatusRoleType.Success),
            (T.ElaSeverity.Warning, T.ElaStatusRoleType.Warning),
            (T.ElaSeverity.Error, T.ElaStatusRoleType.Error),
        ],
    )
    def test_status_levels_use_status_color(self, severity, role):
        assert T.severityColor(_L, severity).name() == T.statusColor(_L, role).name()

    def test_accepts_bare_int(self):
        assert (
            T.severityColor(_L, int(T.ElaSeverity.Warning)).name()
            == T.severityColor(_L, T.ElaSeverity.Warning).name()
        )

    def test_illegal_severity_falls_back_to_info(self):
        assert (
            T.severityColor(_L, 99).name()
            == T.severityColor(_L, T.ElaSeverity.Info).name()
        )


class TestNoneMeansCurrentMode:
    """``mode=None`` 是「当前模式」，不是「浅色」（回归：暗色下取浅色档会给反答案）。"""

    @pytest.fixture
    def dark(self):
        previous = eTheme.getThemeMode()
        eTheme.setThemeMode(ElaThemeType.ThemeMode.Dark)
        yield
        eTheme.setThemeMode(previous)

    @pytest.mark.parametrize(
        "role",
        [T.ElaStatusRoleType.Warning, T.ElaStatusRoleType.Success],
        ids=["warning", "success"],
    )
    def test_status_color_follows_current_mode(self, dark, role):
        assert T.statusColor(None, role).name() == T.statusColor(_D, role).name()
        assert T.statusColor(None, role).name() != T.statusColor(_L, role).name()

    def test_text_on_accent_follows_current_mode(self, dark):
        """暗色强调色是亮青 —— 按浅色档算会给出白字，实际该给黑字。"""
        assert T.textOnAccent().name() == T.textOnAccent(T.accent(_D)).name()
        assert T.textOnAccent().name() != T.textOnAccent(T.accent(_L)).name()


class TestPaletteAndForeground:
    def test_chart_palette_is_fresh_list_each_call(self):
        """必须每次新建 —— 调用方会对单个元素 ``setAlpha``，共享实例会污染全局。"""
        a = T.chartPalette()
        b = T.chartPalette()
        assert a is not b
        a[0].setAlpha(1)
        assert T.chartPalette()[0].alpha() != 1

    def test_chart_palette_reuses_charts_tokens(self):
        """不另维护一份分类色 —— 直接用 charts 的那一套，避免两套漂移。"""
        from pyqt6_ela_pro.charts._tokens import ECHARTS_PALETTE

        assert [c.name() for c in T.chartPalette()] == [
            c.lower() for c in ECHARTS_PALETTE
        ]

    @pytest.mark.parametrize(
        "bg,expect_dark_foreground",
        [
            ("#ffffff", True),  # 浅底 → 深色前景
            ("#f0f0f0", True),
            ("#000000", False),  # 深底 → 浅色前景
            ("#0067c0", False),
        ],
    )
    def test_text_on_accent_picks_readable_foreground(self, bg, expect_dark_foreground):
        fg = T.textOnAccent(QColor(bg))
        if expect_dark_foreground:
            assert fg.lightnessF() < 0.5
        else:
            assert fg.lightnessF() > 0.5

    def test_text_on_accent_defaults_to_current_accent(self):
        assert T.textOnAccent().isValid()


class TestShadowHelpers:
    def test_shadow_margin_is_shared_constant(self):
        from pyqt6_ela_pro._styles import SHADOW_MARGIN

        assert SHADOW_MARGIN == 4

    @pytest.mark.parametrize(
        "relpath",
        [
            "ela_toast.py",
            "ela_confirm_dialog.py",
            "notify_popup.py",
            "selection_assistant/popup.py",
        ],
    )
    def test_overlay_shadow_margin_comes_from_shared_constant(self, relpath):
        """三个弹层的阴影边距都必须**从 `_styles` 导入共享常量**。

        回归：``ela_toast`` 一直自己写死 4，``confirm_dialog`` / ``notify_popup``
        压根没有边距也没画阴影 —— 三个弹层「扁」得不一样。守卫它们统一取
        ``SHADOW_MARGIN``，避免以后又各写一个魔数。
        """
        import ast

        src = (_PKG / relpath).read_text(encoding="utf-8")
        imported: set[str] = set()
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.ImportFrom) and node.module == "_styles":
                imported.update(a.name for a in node.names)
        assert "SHADOW_MARGIN" in imported, (
            f"{relpath} 没从 ._styles 导入 SHADOW_MARGIN —— "
            f"阴影边距必须用共享常量，别写死数字"
        )
        assert "paintOverlayShadow" in imported, (
            f"{relpath} 没从 ._styles 导入 paintOverlayShadow —— "
            f"阴影要走统一助手，别各处直接调 eTheme.drawEffectShadow"
        )

    def test_toast_shadow_border_uses_shared_constant(self, qapp):
        from pyqt6_ela_pro._styles import SHADOW_MARGIN
        from pyqt6_ela_pro import ElaSeverity
        from pyqt6_ela_pro.ela_toast import ElaToast

        toast = ElaToast(ElaSeverity.Info, "x", 1000)
        try:
            assert toast._shadow_border == SHADOW_MARGIN
        finally:
            toast.deleteLater()
            qapp.processEvents()

    def test_confirm_dialog_window_includes_margin(self, qapp):
        from pyqt6_ela_pro.ela_confirm_dialog import _BOX_WIDTH, ElaConfirmDialog

        dlg = ElaConfirmDialog()
        try:
            sm = dlg._shadow_margin
            assert sm > 0
            assert dlg.width() == _BOX_WIDTH + sm * 2
            assert dlg.width() - 2 * sm == _BOX_WIDTH
        finally:
            dlg.deleteLater()
            qapp.processEvents()

    def test_notify_popup_window_includes_margin(self, qapp):
        from pyqt6_ela_pro.notify_popup import ElaNotifyPopup

        popup = ElaNotifyPopup()
        try:
            assert popup.width() == 300 + popup._shadow_margin * 2
        finally:
            popup.deleteLater()
            qapp.processEvents()
