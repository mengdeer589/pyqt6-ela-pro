"""ElaSelectionPopup 测试：动作渲染、点击信号、紧凑模式与定位收敛。"""

from __future__ import annotations

from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QApplication
from PyQt6ElaWidgetTools import ElaIconType

from pyqt6_ela_pro import ElaMenuItem, ElaSelectionPopup

#: 测试用宿主自定义动作（组件本身不内置任何动作）
from pyqt6_ela_pro import tooltips as tt

_ACTIONS = (
    ElaMenuItem(id="copy", label="复制", icon=ElaIconType.IconName.Copy),
    ElaMenuItem(id="translate", label="翻译", icon=ElaIconType.IconName.Language),
    ElaMenuItem(id="explain", label="解释", icon=ElaIconType.IconName.CommentQuestion),
    ElaMenuItem(id="summary", label="总结", icon=ElaIconType.IconName.FileLines),
    ElaMenuItem(id="search", label="搜索", icon=ElaIconType.IconName.MagnifyingGlass),
    ElaMenuItem(id="quote", label="引用", icon=ElaIconType.IconName.QuoteLeft),
)


class TestActions:
    def test_actions_render_buttons(self, qapp):
        popup = ElaSelectionPopup()
        popup.setActions(_ACTIONS)
        assert popup.hasActions() is True
        assert set(popup._buttons) == {
            "copy",
            "translate",
            "explain",
            "summary",
            "search",
            "quote",
        }
        assert popup.button("copy") is not None
        assert popup.button("no-such-action") is None
        assert [item.id for item in popup.actions()] == [
            "copy",
            "translate",
            "explain",
            "summary",
            "search",
            "quote",
        ]
        popup.deleteLater()

    def test_disabled_action_not_rendered(self, qapp):
        popup = ElaSelectionPopup()
        popup.setActions(
            [
                ElaMenuItem(id="a", label="动作 A"),
                ElaMenuItem(id="b", label="动作 B", enabled=False),
            ]
        )
        assert set(popup._buttons) == {"a"}
        assert popup.hasActions() is True
        popup.setActions([])
        assert popup.hasActions() is False
        popup.deleteLater()

    def test_click_emits_action_and_hides(self, qapp):
        popup = ElaSelectionPopup()
        popup.setActions([ElaMenuItem(id="copy", label="复制")])
        triggered = []
        hidden = []
        popup.actionTriggered.connect(triggered.append)
        popup.hidden.connect(lambda: hidden.append(True))
        popup.popupAt(QPoint(200, 200))
        qapp.processEvents()
        assert popup.isVisible() is True
        popup.button("copy").click()
        assert triggered == ["copy"]
        assert popup.isVisible() is False
        assert hidden == [True]
        qapp.processEvents()
        popup.deleteLater()
        qapp.processEvents()

    def test_compact_mode_shrinks_popup(self, qapp):
        popup = ElaSelectionPopup()
        popup.setActions(
            [
                ElaMenuItem(id="copy", label="复制", icon=ElaIconType.IconName.Copy),
                ElaMenuItem(
                    id="search", label="搜索", icon=ElaIconType.IconName.MagnifyingGlass
                ),
            ]
        )
        popup.adjustSize()
        wide = popup.width()
        popup.setCompactMode(True)
        assert popup.compactMode() is True
        popup.adjustSize()
        assert popup.width() < wide
        assert set(popup._buttons) == {"copy", "search"}
        popup.deleteLater()

    def test_action_without_icon_falls_back_to_text_in_compact(self, qapp):
        popup = ElaSelectionPopup()
        popup.setActions([ElaMenuItem(id="x", label="自定义")])
        popup.setCompactMode(True)
        button = popup.button("x")
        assert button is not None
        assert button.text() == "自定义"
        popup.deleteLater()

    def test_buttons_use_library_tooltip_only(self, qapp):

        popup = ElaSelectionPopup()
        popup.setActions([ElaMenuItem(id="copy", label="复制")])
        button = popup.button("copy")
        # 不设置原生 setToolTip 文本，避免任何原生 QToolTip
        assert button.toolTip() == ""
        tooltip = tt._tooltip_dict.get(button)
        assert tooltip is not None
        assert tooltip._text == "复制"
        # 显示在动作条下方，避免遮挡上方选中的文字
        tooltip_filter = tt._filter_dict.get(button)
        assert tooltip_filter is not None
        assert tooltip_filter._position == tt.ElaToolTipPositionType.Bottom
        popup.deleteLater()
        qapp.processEvents()

    def test_shadow_margin_reserved_in_layout(self, qapp):
        """阴影边距必须从共享常量预留（否则阴影被自身窗口裁掉）。"""
        from pyqt6_ela_pro._styles import SHADOW_MARGIN

        popup = ElaSelectionPopup()
        margins = popup.layout().contentsMargins()
        assert margins.left() >= SHADOW_MARGIN
        assert margins.top() >= SHADOW_MARGIN
        assert margins.right() >= SHADOW_MARGIN
        assert margins.bottom() >= SHADOW_MARGIN
        popup.deleteLater()
        qapp.processEvents()


class TestPositioning:
    def test_popup_near_cursor(self, qapp):
        popup = ElaSelectionPopup()
        popup.setActions(_ACTIONS[:2])
        popup.popupAt(QPoint(300, 300))
        qapp.processEvents()
        assert popup.frameGeometry().topLeft() == QPoint(300, 300) + popup.offset()
        popup.hide()
        qapp.processEvents()
        popup.deleteLater()

    def test_popup_clamped_inside_screen(self, qapp):
        popup = ElaSelectionPopup()
        popup.setActions(_ACTIONS[:2])
        screen = QApplication.primaryScreen()
        area = screen.availableGeometry()
        popup.popupAt(QPoint(area.right() - 2, area.bottom() - 2))
        qapp.processEvents()
        assert area.contains(popup.frameGeometry())
        popup.hide()
        qapp.processEvents()
        popup.deleteLater()

    def test_offset_configurable(self, qapp):
        popup = ElaSelectionPopup()
        popup.setActions(_ACTIONS[:1])
        popup.setOffset(QPoint(-8, -10))
        assert popup.offset() == QPoint(-8, -10)
        popup.popupAt(QPoint(400, 400))
        qapp.processEvents()
        assert popup.frameGeometry().topLeft() == QPoint(392, 390)
        popup.hide()
        qapp.processEvents()
        popup.deleteLater()

    def test_clearing_actions_hides_visible_popup(self, qapp):
        """弹窗显示中把动作清空 → 不能把没有按钮的空盒子留在屏幕上。"""
        popup = ElaSelectionPopup()
        popup.setActions([ElaMenuItem(id="copy", label="复制")])
        popup.popupAt(QPoint(200, 200))
        qapp.processEvents()
        assert popup.isVisible() is True
        popup.setActions([])
        qapp.processEvents()
        assert popup.hasActions() is False
        assert popup.isVisible() is False, "空动作后弹窗还留在屏幕上"
        popup.deleteLater()
        qapp.processEvents()

    def test_disabling_all_actions_hides_visible_popup(self, qapp):
        popup = ElaSelectionPopup()
        popup.setActions([ElaMenuItem(id="copy", label="复制")])
        popup.popupAt(QPoint(200, 200))
        qapp.processEvents()
        assert popup.isVisible() is True
        popup.setActions([ElaMenuItem(id="copy", label="复制", enabled=False)])
        qapp.processEvents()
        assert popup.hasActions() is False
        assert popup.isVisible() is False
        popup.deleteLater()
        qapp.processEvents()

    def test_resize_while_visible_reclamps_inside_screen(self, qapp):
        """可见期间从紧凑切回完整（变宽）后要按原锚点重新收敛，别越出屏幕。"""
        popup = ElaSelectionPopup()
        popup.setActions(_ACTIONS[:3])
        popup.setCompactMode(True)
        area = QApplication.primaryScreen().availableGeometry()
        popup.popupAt(QPoint(area.right() - 2, area.bottom() - 2))
        qapp.processEvents()
        assert area.contains(popup.frameGeometry())
        popup.setCompactMode(False)  # 变宽
        qapp.processEvents()
        assert area.contains(popup.frameGeometry()), "改尺寸后没有重新收敛到工作区"
        popup.hide()
        qapp.processEvents()
        popup.deleteLater()
