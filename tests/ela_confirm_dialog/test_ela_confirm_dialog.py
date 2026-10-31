"""``ElaConfirmDialog`` 测试：初值 / 文本属性 / 定位 / 按钮 / 键盘 / 表面。"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6ElaWidgetTools import ElaThemeType, eTheme

from pyqt6_ela_pro._styles import SHADOW_MARGIN
from pyqt6_ela_pro._theme import surfacePopup
from pyqt6_ela_pro.ela_button import ElaButton
from pyqt6_ela_pro.ela_confirm_dialog import (
    _BOX_WIDTH,
    _CONTENT_MAX_H,
    ElaConfirmDialog,
)


@pytest.fixture
def parent(make):
    return make(QWidget)


@pytest.fixture
def dlg(make, parent):
    return make(ElaConfirmDialog, parent)


class TestElaConfirmDialogInit:
    @pytest.mark.parametrize(
        ("attr", "expected"),
        [
            ("_title", "标题"),
            ("_content", ""),
            ("_border_radius", 8),
            ("_position", "bottom"),
        ],
    )
    def test_default_state(self, dlg, attr, expected):
        assert getattr(dlg, attr) == expected

    @pytest.mark.parametrize("position", ["top", "bottom"])
    def test_initialization_with_position(self, make, parent, position):
        dlg = make(ElaConfirmDialog, parent, position=position)
        assert dlg._position == position
        assert dlg.position() == position

    def test_window_width_is_fixed(self, dlg):
        # 宽度 = 内容宽 + 两侧阴影边距。``FramelessWindowHint`` 去掉了系统阴影，
        # 边距不预留出来的话阴影会被自身窗口裁掉。
        sm = dlg._shadow_margin
        assert sm == SHADOW_MARGIN
        assert dlg.minimumWidth() == _BOX_WIDTH + 2 * sm
        assert dlg.maximumWidth() == _BOX_WIDTH + 2 * sm
        assert dlg.sizeHint().width() == _BOX_WIDTH + 2 * sm

    @pytest.mark.parametrize("attr", ["_confirm_btn", "_cancel_btn"])
    def test_has_button(self, dlg, attr):
        assert isinstance(getattr(dlg, attr), ElaButton)

    def test_button_hierarchy(self, dlg):
        """确认 = 实心主色，取消 = 中性描边（与 Ela 对话框的按钮层级一致）。"""
        assert dlg._confirm_btn.text() == "确定"
        assert dlg._confirm_btn.variant() == "solid"
        assert dlg._confirm_btn.color() == "primary"
        assert dlg._cancel_btn.text() == "取消"
        assert dlg._cancel_btn.variant() == "outlined"
        assert dlg._cancel_btn.color() == "default"

    def test_confirm_is_default_button(self, dlg):
        assert dlg._confirm_btn.isDefault()
        assert dlg._confirm_btn.autoDefault()
        assert dlg._cancel_btn.autoDefault()

    def test_frameless_window_hint(self, dlg):
        assert dlg.windowFlags() & Qt.WindowType.FramelessWindowHint

    def test_translucent_background(self, dlg):
        assert dlg.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)


class TestElaConfirmDialogSignals:
    @pytest.mark.parametrize("name", ["confirmed", "cancelled"])
    def test_declares_signal(self, dlg, name):
        assert callable(getattr(dlg, name))

    @pytest.mark.parametrize(
        ("slot", "signal"), [("_onConfirm", "confirmed"), ("_onCancel", "cancelled")]
    )
    def test_slot_emits(self, dlg, slot, signal):
        received = []
        getattr(dlg, signal).connect(lambda: received.append(True))
        getattr(dlg, slot)()
        assert received == [True]


class TestElaConfirmDialogTextProps:
    """``setTitle`` / ``setContent`` / ``setBorderRadius`` / ``setPosition``
    四组 setter/getter 形状一致，参数化掉。"""

    @pytest.mark.parametrize(
        ("setter", "getter", "value"),
        [
            (ElaConfirmDialog.setTitle, ElaConfirmDialog.title, "确认删除？"),
            (ElaConfirmDialog.setTitle, ElaConfirmDialog.title, ""),
            (
                ElaConfirmDialog.setContent,
                ElaConfirmDialog.content,
                "确定要删除此项目吗？",
            ),
            (ElaConfirmDialog.setContent, ElaConfirmDialog.content, ""),
            (ElaConfirmDialog.setBorderRadius, ElaConfirmDialog.borderRadius, 16),
            (ElaConfirmDialog.setPosition, ElaConfirmDialog.position, "top"),
            (ElaConfirmDialog.setPosition, ElaConfirmDialog.position, "bottom"),
        ],
    )
    def test_setter_roundtrip(self, dlg, setter, getter, value):
        setter(dlg, value)
        assert getter(dlg) == value

    @pytest.mark.parametrize(
        ("getter", "expected"),
        [
            (ElaConfirmDialog.borderRadius, 8),
            (ElaConfirmDialog.position, "bottom"),
        ],
    )
    def test_getter_default(self, dlg, getter, expected):
        assert getter(dlg) == expected

    def test_long_title_is_elided(self, dlg):
        """无边框窗口不能靠拉伸看全标题，超宽按省略号截断（title() 仍是原文）。"""
        title = "很长的标题" * 20
        dlg.setTitle(title)
        assert dlg.title() == title
        assert dlg._title_label.text().endswith("…")

    def test_empty_title_hides_label(self, dlg):
        dlg.setTitle("")
        assert dlg._title_label.isHidden()
        dlg.setTitle("提示")
        assert not dlg._title_label.isHidden()


class TestElaConfirmDialogPlacement:
    """弹框定位：贴着锚点摆放，放不下时翻边 + 夹回屏幕工作区。

    回归：锚点贴窗口 / 屏幕底边（聊天输入区、最大化窗口里的整块聊天组件）
    时，只按「锚点底边 + 间距」摆放会把弹框整块算到屏幕外 —— 用户点击后
    什么都看不到。
    """

    @staticmethod
    def _anchor(make, qapp, window_rect):
        """在指定全局位置造一个窗口 + 内部锚点控件，返回锚点控件。"""
        parent = make(QWidget)
        parent.setWindowFlags(Qt.WindowType.Window)
        parent.setGeometry(window_rect)
        parent.show()
        anchor = make(QWidget, parent)
        anchor.setGeometry(10, 10, 120, 60)
        qapp.processEvents()
        return anchor

    @staticmethod
    def _anchor_rect(anchor):
        return QRect(anchor.mapToGlobal(QPoint(0, 0)), anchor.size())

    @staticmethod
    def _dialog(make, qapp, anchor, position):
        dialog = make(ElaConfirmDialog, anchor, position=position)
        dialog.show()
        qapp.processEvents()
        dialog._positionDialog()
        return dialog

    def test_sits_below_anchor_when_there_is_room(self, make, qapp):
        area = QApplication.primaryScreen().availableGeometry()
        anchor = self._anchor(
            make, qapp, QRect(area.left() + 80, area.top() + 80, 240, 200)
        )
        dialog = self._dialog(make, qapp, anchor, "bottom")

        assert dialog.y() == self._anchor_rect(anchor).bottom() + 6
        assert area.contains(dialog.frameGeometry())
        dialog.close()

    def test_flips_above_when_anchor_sits_on_bottom_edge(self, make, qapp):
        """不允许为了留在屏幕内把弹框压回锚点身上（必须真的翻到上方）。"""
        area = QApplication.primaryScreen().availableGeometry()
        anchor = self._anchor(
            make, qapp, QRect(area.left() + 80, area.bottom() - 140, 400, 140)
        )
        dialog = self._dialog(make, qapp, anchor, "bottom")

        assert area.contains(dialog.frameGeometry())
        assert dialog.y() + dialog.height() <= self._anchor_rect(anchor).top() + 1
        dialog.close()

    def test_flips_below_when_anchor_sits_on_top_edge(self, make, qapp):
        area = QApplication.primaryScreen().availableGeometry()
        anchor = self._anchor(make, qapp, QRect(area.left() + 80, area.top(), 400, 140))
        dialog = self._dialog(make, qapp, anchor, "top")

        assert area.contains(dialog.frameGeometry())
        assert dialog.y() >= self._anchor_rect(anchor).bottom()
        dialog.close()

    def test_horizontal_position_clamped_into_screen(self, make, qapp):
        area = QApplication.primaryScreen().availableGeometry()
        anchor = self._anchor(
            make, qapp, QRect(area.right() - 120, area.top() + 80, 120, 200)
        )
        dialog = self._dialog(make, qapp, anchor, "bottom")

        assert dialog.x() >= area.left()
        assert dialog.x() + dialog.width() <= area.right() + 1
        dialog.close()


class TestElaConfirmDialogContentSizing:
    """正文高度必须撑开窗口。

    回归：原先没有 ``sizeHint`` 覆写，类调用 ``show()`` 永远只有最小尺寸、
    正文区固定 50px —— 8 行文案实测需要 144px，一大半被裁掉（用户看不到
    自己在确认什么）。
    """

    LONG = "\n".join(f"第 {i} 行：这是一段较长的确认说明文字。" for i in range(1, 9))

    def test_construction_size_matches_hint(self, dlg):
        assert dlg.height() == dlg.sizeHint().height()

    def test_long_content_grows_dialog(self, dlg):
        before = dlg.height()
        dlg.setContent(self.LONG)
        assert dlg.sizeHint().height() > before
        # 隐藏时 setContent 自己 adjustSize，不需要等 show
        assert dlg.height() == dlg.sizeHint().height()

    def test_long_content_fits_content_area(self, dlg):
        dlg.setContent(self.LONG)
        need = dlg._content_label.heightForWidth(dlg._content_width())
        assert dlg._content_label.height() >= need
        assert dlg._content_label.height() <= _CONTENT_MAX_H

    def test_long_content_height_is_capped(self, dlg):
        """无边框弹框没有滚动条：超过上限的部分裁切，窗口不再无限长高。"""
        dlg.setContent("\n".join(["一行很长的确认说明文字"] * 200))
        assert dlg._content_label.height() == _CONTENT_MAX_H


class TestElaConfirmDialogKeyboard:
    """键盘可达性：按钮可 Tab 聚焦、Space / Enter 激活、Escape 与 reject 对称。"""

    @pytest.mark.parametrize("attr", ["_confirm_btn", "_cancel_btn"])
    def test_buttons_are_tab_focusable(self, dlg, attr):
        assert getattr(dlg, attr).focusPolicy() & Qt.FocusPolicy.TabFocus

    @pytest.mark.parametrize(
        "key", [Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter]
    )
    def test_key_activates_button(self, dlg, key):
        received = []
        dlg._confirm_btn.clicked.connect(lambda: received.append(True))
        QTest.keyClick(dlg._confirm_btn, key)
        assert received == [True]

    def test_initial_focus_is_confirm_without_focus_ring(self, dlg, qapp):
        """弹框一打开就套一圈主色焦点环会被误读成「已选中」。"""
        dlg.show()
        qapp.processEvents()
        assert dlg._confirm_btn.hasFocus()
        assert dlg._confirm_btn._focus_ring is False
        dlg.close()

    def test_enter_on_dialog_activates_confirm(self, dlg, qapp):
        received = []
        dlg.confirmed.connect(lambda: received.append(True))
        dlg.show()
        qapp.processEvents()
        QTest.keyClick(dlg, Qt.Key.Key_Return)
        qapp.processEvents()
        assert received == [True]
        assert not dlg.isVisible()

    def test_enter_on_focused_cancel_cancels(self, dlg, qapp):
        received = []
        dlg.cancelled.connect(lambda: received.append(True))
        dlg.show()
        qapp.processEvents()
        QTest.keyClick(dlg._cancel_btn, Qt.Key.Key_Return)
        qapp.processEvents()
        assert received == [True]
        assert not dlg.isVisible()

    def test_escape_emits_cancelled(self, dlg, qapp):
        """Escape 关掉弹框也算取消 —— 宿主接 ``cancelled`` 不能漏掉这条路径。"""
        received = []
        dlg.cancelled.connect(lambda: received.append(True))
        dlg.show()
        qapp.processEvents()
        QTest.keyClick(dlg, Qt.Key.Key_Escape)
        qapp.processEvents()
        assert received == [True]
        assert not dlg.isVisible()

    def test_reject_emits_cancelled(self, dlg):
        received = []
        dlg.cancelled.connect(lambda: received.append(True))
        dlg.reject()
        assert received == [True]


class TestElaConfirmDialogSurface:
    """表面走 ``PopupBase`` + 1px ``PopupBorder``（与 toast / tooltip 同一材质）。"""

    @pytest.fixture
    def themed(self):
        previous = eTheme.getThemeMode()

        def _set(mode):
            eTheme.setThemeMode(mode)

        yield _set
        eTheme.setThemeMode(previous)

    @pytest.mark.parametrize(
        "mode",
        [ElaThemeType.ThemeMode.Light, ElaThemeType.ThemeMode.Dark],
        ids=["light", "dark"],
    )
    def test_surface_uses_popup_base(self, make, parent, qapp, themed, mode):
        themed(mode)
        dlg = make(ElaConfirmDialog, parent)
        dlg.setContent("确定要清空当前对话吗？此操作不可撤销。")
        dlg.show()
        qapp.processEvents()
        image = dlg.grab().toImage()
        sm = dlg._shadow_margin
        # 左侧内边距区（文字从内容区 16px 处开始），避开边框与圆角
        color = image.pixelColor(sm + 2, dlg.height() // 2)
        assert color.name() == surfacePopup(mode).name()
        dlg.close()
