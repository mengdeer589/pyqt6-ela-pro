"""``pyqt6_ela_pro.ela_field`` 的单元测试。

钉住的核心不变量（搬运时改道 / 踩过的）：

1. **状态图标要求「有文案」且「状态非 None」两者同时成立** —— 只给状态不给文字时状态行
   整行隐藏；``None`` 状态 + 有文字时行显示但**无图标**。
2. **辅助文字永远不被校验状态改色** —— 说明与错误并存时，说明被染红会让用户以为
   说明本身是错的。
3. **``*`` 必填标记永远是错误色**，与 ``status()`` 无关。
4. **禁 QSS**：全部走 ``ColorText`` + 显式 ``setTextPixelSize``（不设就是 ElaText 的
   默认 28px —— 静默变大的坑）。
5. **编辑器槽走 ``_ownership.ContentSlot``**，且**不是 tab stop**（tab 归编辑器）。
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QCoreApplication, QEvent, Qt
from PyQt6.QtWidgets import QLineEdit, QWidget

from pyqt6_ela_pro._ownership import ElaWidgetOwnershipType
from pyqt6_ela_pro._theme import (
    ElaStatusRoleType,
    currentMode,
    statusColor,
    text,
    textMuted,
)
from pyqt6_ela_pro.ela_field import (
    _GAP,
    _ICON_HOST,
    _LABEL_PX,
    _DETAIL_PX,
    ElaField,
    ElaFieldStatusType,
)

from PyQt6ElaWidgetTools import ElaIconType
from PyQt6 import sip


@pytest.fixture
def field(make):
    """一个已挂好编辑器、并保证父链可见的字段。

    ``isVisible()`` 依赖父链可见（AGENTS.md 记过这条），所以这里必须 show 父控件。
    """
    host = make(QWidget)
    f = make(ElaField, host)
    host.show()
    f.show()
    f.setEditor(make(QLineEdit, f))
    return f


def _flush(obj):
    QCoreApplication.sendPostedEvents(obj, QEvent.Type.DeferredDelete)


class TestLayout:
    def test_field_is_not_a_tab_stop(self, field):
        """tab 序列属于编辑器；字段自己抢焦点会让 tab 遍历多停一次。"""
        assert field.focusPolicy() == Qt.FocusPolicy.NoFocus

    def test_focus_is_proxied_to_the_editor(self, field):
        editor = field.editor()
        assert editor is not None
        assert field.focusProxy() is editor

    def test_caption_is_buddy_of_the_editor(self, field):
        """``*`` / 标题的快捷键要指向编辑器。"""
        assert field._caption.buddy() is field.editor()

    def test_root_spacing_is_4(self, field):
        assert field.layout().spacing() == _GAP

    def test_caption_and_detail_font_sizes_are_explicit(self, field):
        """**每个 ColorText 都必须显式设字号** —— 不设就是 ElaText 的默认 28px。

        这是个静默的坑：不报错、不崩，只是「大」，而且只在一处冒出来，整张卡的比例就崩了。
        """
        assert field._caption.font().pixelSize() == _LABEL_PX
        assert field._required_mark.font().pixelSize() == _LABEL_PX
        assert field._helper.font().pixelSize() == _DETAIL_PX
        assert field._status_label.font().pixelSize() == _DETAIL_PX

    def test_font_size_ordering_makes_the_detail_row_smaller(self, field):
        """辅助行比标题小两号 —— 这是层级，不是随手定的。"""
        assert _DETAIL_PX < _LABEL_PX

    def test_status_icon_host_is_16(self, field):
        assert field._status_icon.width() == _ICON_HOST
        assert field._status_icon.height() == _ICON_HOST

    def test_helper_and_status_can_both_be_visible(self, field):
        field.setHelperText("2-16 chars")
        field.setStatus(ElaFieldStatusType.Error)
        field.setStatusText("taken")
        assert field._helper.isVisible() is True
        assert field._status_row.isVisible() is True


class TestLabel:
    def test_set_and_read_back(self, field):
        field.setLabel("username")
        assert field.label() == "username"
        assert field._caption.text() == "username"

    def test_empty_label_by_default(self, make):
        assert make(ElaField).label() == ""

    def test_none_becomes_empty_string(self, field):
        field.setLabel("x")
        field.setLabel(None)
        assert field.label() == ""

    def test_signal_fires_once_per_change(self, field):
        seen = []
        field.labelChanged.connect(seen.append)
        field.setLabel("a")
        field.setLabel("a")
        field.setLabel("b")
        assert seen == ["a", "b"]


class TestRequired:
    def test_mark_hidden_by_default(self, field):
        assert field.isRequired() is False
        assert field._required_mark.isVisible() is False

    def test_mark_shown_when_required(self, field):
        field.setRequired(True)
        assert field.isRequired() is True
        assert field._required_mark.isVisible() is True

    def test_mark_is_always_error_colored_regardless_of_status(self, field):
        """``*`` 表达「这栏必填」，不是「这栏当前有错」。"""
        field.setRequired(True)
        field.setStatus(ElaFieldStatusType.Success)
        assert (
            field._required_mark.textColor().name()
            == statusColor(currentMode(), ElaStatusRoleType.Error).name()
        )
        field.setStatus(ElaFieldStatusType.Error)
        assert (
            field._required_mark.textColor().name()
            == statusColor(currentMode(), ElaStatusRoleType.Error).name()
        )


class TestHelperText:
    def test_hidden_when_empty(self, field):
        assert field._helper.isVisible() is False

    def test_shown_when_set(self, field):
        field.setHelperText("2-16 chars")
        assert field.helperText() == "2-16 chars"
        assert field._helper.isVisible() is True

    def test_never_recolored_by_status(self, field):
        """说明与错误并存时，说明被染红会让用户以为说明本身是错的。"""
        field.setHelperText("2-16 chars")
        baseline = field._helper.textColor().name()
        for status in ElaFieldStatusType:
            if status is ElaFieldStatusType.None_:
                continue
            field.setStatus(status)
            field.setStatusText("bad")
            assert field._helper.textColor().name() == baseline

    def test_helper_uses_muted_text_token(self, field):
        field.setHelperText("x")
        assert field._helper.textColor().name() == textMuted(currentMode()).name()

    def test_caption_uses_primary_text_token(self, field):
        field.setLabel("x")
        assert field._caption.textColor().name() == text(currentMode()).name()


class TestStatusRow:
    def test_hidden_without_text(self, field):
        """一个没有文案的红三角没有信息量，只是个噪音像素。"""
        field.setStatus(ElaFieldStatusType.Error)
        assert field.hasStatusRow() is False
        assert field._status_row.isVisible() is False
        assert field._status_icon.isVisible() is False

    @pytest.mark.parametrize(
        "status", [ElaFieldStatusType.Error, ElaFieldStatusType.Warning, ElaFieldStatusType.Success]
    )
    def test_visible_with_text_and_named_status(self, field, status):
        field.setStatus(status)
        field.setStatusText("msg")
        assert field.hasStatusRow() is True
        assert field._status_row.isVisible() is True
        assert field._status_icon.isVisible() is True

    def test_none_status_with_text_shows_row_but_no_icon(self, field):
        """``None`` + 有文案：行要显示（那是一句说明），但不显示图标。"""
        field.setStatus(ElaFieldStatusType.None_)
        field.setStatusText("just a note")
        assert field._status_row.isVisible() is True
        assert field._status_icon.isVisible() is False

    def test_none_status_uses_muted_text(self, field):
        field.setStatus(ElaFieldStatusType.None_)
        field.setStatusText("note")
        assert field.statusColor().name() == textMuted(currentMode()).name()

    @pytest.mark.parametrize(
        ("status", "role"),
        [
            (ElaFieldStatusType.Error, ElaStatusRoleType.Error),
            (ElaFieldStatusType.Warning, ElaStatusRoleType.Warning),
            (ElaFieldStatusType.Success, ElaStatusRoleType.Success),
        ],
    )
    def test_status_color_comes_from_the_token_layer(self, field, status, role):
        """状态色走 ``_theme``，不是硬编码 —— 换主题时它自己会变。"""
        field.setStatus(status)
        assert field.statusColor().name() == statusColor(currentMode(), role).name()

    def test_status_and_text_are_independent(self, field):
        """宿主可以只改色不换文案，也可以只换文案不换色。"""
        field.setStatus(ElaFieldStatusType.Warning)
        field.setStatusText("careful")
        field.setStatus(ElaFieldStatusType.Error)
        assert field.statusText() == "careful"
        assert field.status() is ElaFieldStatusType.Error

    @pytest.mark.parametrize(
        ("status", "icon"),
        [
            (ElaFieldStatusType.Error, ElaIconType.IconName.CircleXmark),
            (ElaFieldStatusType.Warning, ElaIconType.IconName.TriangleExclamation),
            (ElaFieldStatusType.Success, ElaIconType.IconName.CircleCheck),
        ],
    )
    def test_each_status_has_a_distinct_icon(self, field, status, icon):
        """三个状态的图标必须互不相同 —— 否则「红色圆形」无法区分错误与成功。"""
        field.setStatus(status)
        field.setStatusText("m")
        assert field._status_icon._icon == icon

    def test_clearing_text_hides_the_row_again(self, field):
        field.setStatus(ElaFieldStatusType.Error)
        field.setStatusText("bad")
        field.setStatusText("")
        assert field._status_row.isVisible() is False
        assert field._status_icon.isVisible() is False

    def test_status_text_none_becomes_empty(self, field):
        field.setStatusText("x")
        field.setStatusText(None)
        assert field.statusText() == ""

    def test_signal_emits_on_change_only(self, field):
        seen = []
        field.statusTextChanged.connect(seen.append)
        field.setStatusText("a")
        field.setStatusText("a")
        assert seen == ["a"]


class TestEditorSlot:
    def test_editor_is_reparented_into_the_host(self, field):
        assert field.editor().parentWidget() is field._editor_host

    def test_default_ownership_is_borrowed(self, field):
        assert field.editorOwnership() == ElaWidgetOwnershipType.Borrowed

    def test_set_none_clears(self, field):
        field.setEditor(None)
        assert field.editor() is None
        assert field.focusProxy() is None

    def test_replacing_keeps_one_item_in_the_host_layout(self, field):
        field.setEditor(QLineEdit())
        assert field._editor_host_layout.count() == 1

    def test_take_returns_parentless(self, field, qapp):
        editor = field.editor()
        got = field.takeEditor()
        assert got is editor
        assert got.parentWidget() is None
        _flush(got)

        assert sip.isdeleted(got) is False

    def test_take_never_deletes_even_when_owned(self, field):
        """``take`` 的语义是「交还」，不套用 Owned 的删除。"""

        editor = QLineEdit()
        field.setEditor(editor, ElaWidgetOwnershipType.Owned)
        got = field.takeEditor()
        _flush(got)
        assert sip.isdeleted(got) is False

    def test_release_owned_deletes(self, field, qapp):

        editor = QLineEdit()
        field.setEditor(editor, ElaWidgetOwnershipType.Owned)
        field.releaseEditor()
        _flush(editor)
        assert sip.isdeleted(editor) is True

    def test_release_borrowed_keeps_widget(self, field, qapp):

        editor = QLineEdit()
        field.setEditor(editor, ElaWidgetOwnershipType.Borrowed)
        field.releaseEditor()
        _flush(editor)
        assert sip.isdeleted(editor) is False
        assert editor.parentWidget() is None

    def test_external_destruction_self_heals(self, field, qapp):
        """编辑器被外部销毁后 ``editor()`` 要 None、布局要摘干净。"""
        editor = field.editor()
        editor.deleteLater()
        _flush(editor)
        assert field.editor() is None
        assert field._editor_host_layout.count() == 0

    def test_rejects_self(self, field):
        assert field.setEditor(field) is False

    def test_rejects_ancestor(self, field):
        assert field.setEditor(field.parentWidget()) is False

    def test_focus_proxy_survives_content_swap(self, field):
        first = field.editor()
        field.setEditor(QLineEdit())
        assert field.focusProxy() is not first
        assert field.focusProxy() is field.editor()


class TestThemeSwitch:
    @pytest.fixture(autouse=True)
    def _make(self, make):
        self.make = make

    def test_helper_color_follows_theme_without_host_action(self, motion_full):
        """``ColorText`` 的颜色是**快照**，所以主题切换必须由组件自己重设。

        这条钉的是「钩子名写错」这类静默失效：接不上 ``themeModeChanged`` 时切完主题
        标题与说明会停在旧色，而所有 setter 都正常、**不报任何错**。
        """
        from PyQt6ElaWidgetTools import ElaThemeType as TT, eTheme

        f = self.make(ElaField)
        f.setHelperText("x")
        previous = eTheme.getThemeMode()
        try:
            eTheme.setThemeMode(TT.ThemeMode.Light)
            light = f._helper.textColor().name()
            eTheme.setThemeMode(TT.ThemeMode.Dark)
            dark = f._helper.textColor().name()
        finally:
            eTheme.setThemeMode(previous)
        assert light == textMuted(TT.ThemeMode.Light).name()
        assert dark == textMuted(TT.ThemeMode.Dark).name()
        assert light != dark

    def test_caption_color_follows_theme(self, motion_full):
        from PyQt6ElaWidgetTools import ElaThemeType as TT, eTheme

        f = self.make(ElaField)
        f.setLabel("x")
        previous = eTheme.getThemeMode()
        try:
            eTheme.setThemeMode(TT.ThemeMode.Dark)
            dark = f._caption.textColor().name()
        finally:
            eTheme.setThemeMode(previous)
        assert dark == text(TT.ThemeMode.Dark).name()

    def test_required_mark_color_follows_theme(self, motion_full):
        from PyQt6ElaWidgetTools import ElaThemeType as TT, eTheme

        f = self.make(ElaField)
        f.setRequired(True)
        previous = eTheme.getThemeMode()
        try:
            eTheme.setThemeMode(TT.ThemeMode.Dark)
            dark = f._required_mark.textColor().name()
        finally:
            eTheme.setThemeMode(previous)
        assert dark == statusColor(TT.ThemeMode.Dark, ElaStatusRoleType.Error).name()


class TestNoQss:
    def test_no_setstylesheet_anywhere_in_the_module(self):
        """机器守卫：本模块（及它依赖的 Field 组件面）不得出现 ``setStyleSheet``。"""
        import pathlib

        import pyqt6_ela_pro.ela_field as mod

        source = pathlib.Path(mod.__file__).read_text(encoding="utf-8")
        assert ".setStyleSheet(" not in source
