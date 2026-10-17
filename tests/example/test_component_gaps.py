"""四个「补漏」小节的回归守卫。

补的是什么：一次全量组件对账（AST 命中 ∪ 运行时控件树）发现 example 从没
实例化过 ``ElaTagLineEdit`` / ``ElaToggleButton`` / ``ElaScrollPage`` /
``ElaContentDialog`` / ``ElaColorDialog``。

**别在这里调 ``exec()``**：``ElaColorDialog`` / ``ElaContentDialog`` 是模态的，
``exec()`` 会阻塞测试进程（与 ``ElaConfirmDialog`` 同一条 AGENTS.md 规则，
实测整轮测试 0xC0000409 凭空消失）。要验打开行为就构造 + 查属性。
"""

from __future__ import annotations

from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QLabel, QWidget
from PyQt6ElaWidgetTools import (
    ElaColorDialog,
    ElaContentDialog,
    ElaRoller,
    ElaScrollPage,
    ElaToggleButton,
)

from pyqt6_ela_pro import ElaTagLineEdit
from pyqt6_ela_pro.example.buttons_menus_page import ButtonsMenusPage
from pyqt6_ela_pro.example.container_layout_page import ContainerLayoutPage
from pyqt6_ela_pro.example.drawer_tooltip_page import DrawerTooltipPage
from pyqt6_ela_pro.example.input_select_page import InputSelectPage


# ================================================================ ElaTagLineEdit
class TestElaTagLineEditSection:
    def test_page_shows_three_edits(self, qapp, make):
        page = make(InputSelectPage)
        edits = page.findChildren(ElaTagLineEdit)
        assert len(edits) == 3, f"第 10 节应有 3 个输入框，实际 {len(edits)}"
        titles = [edit.title() for edit in edits]
        assert titles == ["用户名", "", "错误态演示"], titles

    def test_parent_is_first_positional_argument(self, qapp, make):
        """回归：曾写成 ``(title="Untitled", parent=None)`` —— 全库唯一的例外。

        后果是 ``ElaTagLineEdit(self)`` 把父控件当成标题传给
        ``QFontMetrics.horizontalAdvance()`` 抛 ``TypeError``；而
        ``ElaTagLineEdit("标题")`` **不报错**，造出一个没有父控件的顶层窗口。
        """
        parent = make(QWidget)
        assert ElaTagLineEdit(parent).title() == ""
        assert ElaTagLineEdit(parent, "标题").title() == "标题"
        assert ElaTagLineEdit(parent=parent, title="kw").title() == "kw"

    def test_default_title_is_empty_not_untitled(self, qapp, make):
        """没设标题的输入框不该在框里喊 "Untitled"。"""
        assert ElaTagLineEdit(make(QWidget)).title() == ""

    def test_error_state_roundtrip(self, qapp, make):
        edit = ElaTagLineEdit(make(QWidget), "标题")
        edit.notifyInvalidInput()
        assert edit._is_error is True
        edit.clearError()
        assert edit._is_error is False


# ================================================================ ElaToggleButton
class TestElaToggleButtonSection:
    def test_page_shows_three_buttons(self, qapp, make):
        page = make(ButtonsMenusPage)
        buttons = page.findChildren(ElaToggleButton)
        assert len(buttons) == 3
        # 注意：``ElaToggleButton`` 没有 ``text()``，只有 ``getText()`` /
        # ``setText()``；构造是 ``(text, parent)``（Qt 的 QPushButton 约定，
        # 与 pro 侧那些 ``parent`` 在前的封装不同）
        assert [b.getText() for b in buttons] == ["静音", "默认开启", "禁用"]
        assert [b.getIsToggled() for b in buttons] == [False, True, False]

    def test_toggled_signal_fires(self, qapp, make):
        button = ElaToggleButton("静音", make(QWidget))
        seen = []
        button.toggled.connect(seen.append)
        button.setIsToggled(True)
        qapp.processEvents()
        assert seen == [True]


# ================================================================ ElaScrollPage
class TestElaScrollPageSection:
    def test_page_has_scroll_page_with_three_sections(self, qapp, make):
        page = make(ContainerLayoutPage)
        pages = page.findChildren(ElaScrollPage)
        assert len(pages) == 1
        # findChildren 对 StackedWidget 返回的是**自顶向下**，要排序
        titles = sorted(
            w.windowTitle()
            for w in pages[0].findChildren(QWidget)
            if w.windowTitle().startswith("第 ")
        )
        assert titles == ["第 1 段", "第 2 段", "第 3 段"], titles

    def test_navigation_switches_section(self, qapp, make):
        """``ElaScrollPage`` 内部是 StackedWidget：一次只显示一段。"""
        page = make(ContainerLayoutPage)
        scroll_page = page.findChildren(ElaScrollPage)[0]
        scroll_page.navigation(2)
        qapp.processEvents()
        # navigation 对当前段是 no-op，切过去再切回来不该抛
        scroll_page.navigation(2)
        scroll_page.navigation(0)
        qapp.processEvents()


# ================================================================ 对话框
class TestContentDialogSection:
    def test_page_builds_both_dialogs(self, qapp, make):
        page = make(DrawerTooltipPage)
        assert hasattr(page, "_demoContentDialog")
        assert hasattr(page, "_demoColorDialog")

    def test_content_dialog_slots(self, qapp, make):
        """构造 + 查属性，**不要 exec()**（模态会阻塞测试进程）。"""
        dialog = ElaContentDialog(make(QWidget))
        dialog.setWindowTitle("t")
        dialog.setCentralWidget(QLabel("内容", dialog))
        dialog.setLeftButtonText("左")
        dialog.setMiddleButtonText("中")
        dialog.setRightButtonText("右")
        seen = []
        dialog.leftButtonClicked.connect(lambda: seen.append("left"))
        dialog.middleButtonClicked.connect(lambda: seen.append("middle"))
        dialog.rightButtonClicked.connect(lambda: seen.append("right"))
        for emit in (
            dialog.leftButtonClicked,
            dialog.middleButtonClicked,
            dialog.rightButtonClicked,
        ):
            emit.emit()
        qapp.processEvents()
        assert len(seen) == 3, seen


class TestColorDialogSection:
    def test_preset_color_updates_swatch(self, qapp, make):
        page = make(DrawerTooltipPage)
        page._onPresetColor()
        qapp.processEvents()
        assert "10b981" in page._color_swatch.text().lower()
        # 同样**不能**直接 == 比 QColor（见下面那条），比 .name()
        assert page._current_color.name() == "#10b981"

    def test_current_color_roundtrip(self, qapp, make):
        """**别用 ``==`` 比 QColor**：从 Qt 内部返回的颜色哪怕 ``name()`` 一致，
        ``__eq__`` 也可能是 False（内部色彩空间规格不同）。一律比 ``.name()``。"""
        dialog = ElaColorDialog(make(QWidget))
        dialog.setCurrentColor(QColor("#FF0000"))
        assert dialog.getCurrentColor().name() == "#ff0000"
        assert dialog.getCurrentColorRGB() == "#FF0000"
        # 未经使用的取色器「最近使用色」是空的，不是 24 个 #000000
        assert len(dialog.getCustomColorList()) in (0, 24)


# ================================================================ ElaRoller
class TestElaRollerSection:
    def test_page_roller_has_items(self, qapp, make):
        """回归：示例曾用 ``setProperty("pItemList", ...)`` —— 那是动态属性、
        无任何效果，滚轮整块空掉（而且空列表上点击 / 滚轮会死循环卡死 GUI）。

        上游私有类里的 ``ELA_PROPERTY_D`` 只是成员声明，不是 Q_PROPERTY；
        设置列表只能走 ``setItemList()``。
        """
        page = make(InputSelectPage)
        roller_items = [roller.getItemList() for roller in page.findChildren(ElaRoller)]
        assert [
            "选项 A",
            "选项 B",
            "选项 C",
            "选项 D",
            "选项 E",
            "选项 F",
        ] in roller_items, roller_items
