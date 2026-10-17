"""``ElaConfirmDialog`` 测试：初值 / 文本属性 / 定位 / 按钮 / 主题。"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PyQt6.QtGui import QEnterEvent, QFontMetrics
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6ElaWidgetTools import ElaThemeType

from pyqt6_ela_pro._styles import SHADOW_MARGIN
from pyqt6_ela_pro.ela_confirm_dialog import ElaConfirmDialog, _ElaConfirmButton


@pytest.fixture
def parent(make):
    return make(QWidget)


@pytest.fixture
def dlg(make, parent):
    return make(ElaConfirmDialog, parent)


@pytest.fixture
def confirm_btn(make):
    return make(_ElaConfirmButton, _ElaConfirmButton.TYPE_CONFIRM)


class TestElaConfirmDialogInit:
    @pytest.mark.parametrize(
        ("attr", "expected"),
        [
            ("_title", "标题"),
            ("_content", ""),
            ("_border_radius", 8),
            ("_position", "bottom"),
            ("_title_pixel_size", 15),
            ("_content_pixel_size", 13),
        ],
    )
    def test_default_state(self, dlg, attr, expected):
        assert getattr(dlg, attr) == expected

    @pytest.mark.parametrize("position", ["top", "bottom"])
    def test_initialization_with_position(self, make, parent, position):
        dlg = make(ElaConfirmDialog, parent, position=position)
        assert dlg._position == position
        assert dlg.position() == position

    def test_minimum_size(self, dlg):
        # 最小尺寸 = 内容区 + 两侧阴影边距。``FramelessWindowHint`` 去掉了系统
        # 阴影，边距不预留出来的话阴影会被自身窗口裁掉。
        assert dlg.minimumWidth() == 280 + dlg._shadow_margin * 2
        assert dlg.minimumHeight() == 150 + dlg._shadow_margin * 2
        assert dlg._shadow_margin == SHADOW_MARGIN

    @pytest.mark.parametrize("attr", ["_confirm_btn", "_cancel_btn"])
    def test_has_button(self, dlg, attr):
        assert hasattr(dlg, attr)

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


class TestElaConfirmDialogTheme:
    def test_on_theme_changed_updates_mode(self, dlg):
        dlg._onThemeChanged(ElaThemeType.ThemeMode.Dark)
        assert dlg._theme_mode == ElaThemeType.ThemeMode.Dark


class TestElaConfirmButton:
    @pytest.mark.parametrize(
        "btn_type", [_ElaConfirmButton.TYPE_CONFIRM, _ElaConfirmButton.TYPE_CANCEL]
    )
    def test_button_type(self, make, btn_type):
        btn = make(_ElaConfirmButton, btn_type)
        assert btn._type == btn_type

    def test_initial_state(self, confirm_btn):
        assert confirm_btn._is_hovered is False
        assert confirm_btn._is_pressed is False

    def test_button_has_clicked_signal(self, confirm_btn):
        assert hasattr(confirm_btn, "clicked")

    def test_button_has_hand_cursor(self, confirm_btn):
        assert confirm_btn.cursor().shape() == Qt.CursorShape.PointingHandCursor

    def test_button_fixed_height(self, confirm_btn):
        assert confirm_btn.height() == 40

    def test_button_enter_leave_events(self, confirm_btn):
        pos = QPointF(1, 1)
        confirm_btn.enterEvent(QEnterEvent(QPointF(pos), QPointF(pos), QPointF(pos)))
        assert confirm_btn._is_hovered is True
        confirm_btn.leaveEvent(QEvent(QEvent.Type.Leave))
        assert confirm_btn._is_hovered is False


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
        dialog.resize(280, 150)
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


class TestElaConfirmDialogDeleteLater:
    def test_delete_later_cleans_up(self, make, parent):
        make(ElaConfirmDialog, parent).deleteLater()


class TestElaConfirmDialogContentSizing:
    """正文高度必须撑开窗口。

    回归：原先没有 ``sizeHint`` 覆写，类调用 ``show()`` 永远只有最小尺寸
    288×158，正文区固定 50px —— 8 行文案实测需要 144px，一大半被裁掉
    （用户看不到自己在确认什么）。
    """

    LONG = "\n".join(f"第 {i} 行：这是一段较长的确认说明文字。" for i in range(1, 9))

    @staticmethod
    def _content_area_height(dlg) -> int:
        box_h = dlg.height() - 2 * dlg._shadow_margin
        return box_h - 40 - 45 - 15

    def test_empty_content_keeps_minimum_size(self, dlg):
        assert dlg.sizeHint().height() == dlg.minimumHeight()
        assert dlg.height() == dlg.minimumHeight()

    def test_long_content_grows_dialog(self, dlg):
        before = dlg.height()
        dlg.setContent(self.LONG)
        assert dlg.sizeHint().height() > before
        # 隐藏时 setContent 自己 adjustSize，不需要等 show
        assert dlg.height() == dlg.sizeHint().height()

    def test_long_content_fits_content_area(self, dlg):
        dlg.setContent(self.LONG)
        font = dlg.font()
        font.setPixelSize(dlg._content_pixel_size)
        need = QFontMetrics(font).boundingRect(
            QRect(0, 0, 280 - 30, 10000),
            Qt.TextFlag.TextWordWrap,
            self.LONG,
        )
        assert self._content_area_height(dlg) >= need.height()


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


class TestElaConfirmButtonStateLayer:
    """hover / press 状态层：**暗色叠白、亮色叠黑**，且裁在弹框圆角盒内。

    回归：原先状态层用 ``fillRect`` 铺满按钮矩形 —— ① 亮 / 暗都叠黑，深色
    主题下 hover 实测只差 2 个明度级（看不见）；② 按钮铺满整窗，方块状态层
    糊住弹框圆角、还盖到阴影边距上（hover 时窗口左下角出现 ``a=10`` 的方块）。
    """

    @pytest.mark.parametrize(
        ("mode", "expected"),
        [
            (ElaThemeType.ThemeMode.Dark, (255, 255, 255)),
            (ElaThemeType.ThemeMode.Light, (0, 0, 0)),
        ],
    )
    def test_state_layer_follows_theme(self, confirm_btn, mode, expected):
        confirm_btn._onThemeChanged(mode)
        assert confirm_btn._state_layer().getRgb()[:3] == expected

    def test_box_path_is_none_without_parent(self, confirm_btn):
        assert confirm_btn._box_path() is None

    def test_box_path_matches_parent_rounded_box(self, dlg, qapp):
        dlg.show()
        qapp.processEvents()
        btn = dlg._confirm_btn
        path = btn._box_path()
        assert path is not None
        bounds = path.boundingRect()
        # 弹框盒 280×150 映射到按钮坐标系：盒顶在按钮上方，盒底与按钮底对齐
        assert bounds.left() == 0
        assert bounds.top() == -110
        assert bounds.width() == 280
        assert bounds.height() == 150
        assert bounds.bottom() == btn.height()

    def test_hover_stays_inside_rounded_box(self, dlg, qapp):
        dlg.setContent("确定要清空当前对话吗？")
        dlg.show()
        qapp.processEvents()
        btn = dlg._confirm_btn
        idle = dlg.grab().toImage()
        btn._is_hovered = True
        btn.update()
        qapp.processEvents()
        hovered = dlg.grab().toImage()

        inside_y = dlg.height() - 20
        assert (
            hovered.pixelColor(30, inside_y).rgba()
            != idle.pixelColor(30, inside_y).rgba()
        )
        # 窗口左下角在圆角盒之外（阴影边距区）：hover 不许糊到这里
        corner_y = dlg.height() - 1
        assert (
            hovered.pixelColor(1, corner_y).rgba()
            == idle.pixelColor(1, corner_y).rgba()
        )
