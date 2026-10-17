"""ElaChatToolBar 工具栏测试：扩展入口 / 插入 / 状态 / 区域 / 事件 / 移除。"""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QLabel, QWidget

from PyQt6ElaWidgetTools import ElaIconType

from pyqt6_ela_pro.chat import ElaChatToolBar, ElaChatToolButton


class TestAddButton:
    def test_add_and_query(self, qapp, make):
        bar = make(ElaChatToolBar)
        button = bar.addButton(
            icon=ElaIconType.IconName.Bolt, tooltip="执行", key="run"
        )
        assert isinstance(button, ElaChatToolButton)
        assert bar.count() == 1
        assert bar.keys() == ["run"]
        assert bar.toolButton("run") is button
        assert bar.item("run") is button
        assert button.toolTip() == "执行"

    def test_auto_key(self, qapp, make):
        bar = make(ElaChatToolBar)
        bar.addButton(text="A")
        bar.addButton(text="B")
        assert bar.keys() == ["tool-1", "tool-2"]

    def test_signal_and_callback(self, qapp, make):
        bar = make(ElaChatToolBar)
        triggered = []
        called = []
        bar.toolTriggered.connect(triggered.append)
        button = bar.addButton(text="点我", key="go", callback=lambda: called.append(1))
        button.click()
        assert triggered == ["go"]
        assert called == [1]

    def test_checkable_toggle(self, qapp, make):
        bar = make(ElaChatToolBar)
        toggles = []
        bar.toolToggled.connect(lambda key, checked: toggles.append((key, checked)))
        button = bar.addButton(text="模式", key="mode", checkable=True)
        button.click()
        assert button.isChecked()
        assert toggles == [("mode", True)]
        button.click()
        assert not button.isChecked()
        assert toggles[-1] == ("mode", False)

        icon_button = bar.addButton(
            icon=ElaIconType.IconName.Bolt, key="run", checkable=True
        )
        assert icon_button.isChecked() is False
        icon_button.click()
        assert icon_button.isChecked() is True
        assert toggles[-1] == ("run", True)

    def test_icon_only_button_is_square(self, qapp, make):
        bar = make(ElaChatToolBar)
        icon_button = bar.addButton(
            icon=ElaIconType.IconName.Bolt, tooltip="执行", key="run"
        )
        assert isinstance(icon_button, ElaChatToolButton)
        assert icon_button.isIconOnly()
        assert icon_button.width() == icon_button.height()
        assert icon_button.width() <= 32

        text_button = bar.addButton(text="模式", key="mode")
        assert not isinstance(text_button, ElaChatToolButton)
        assert text_button.sizeHint().width() > text_button.sizeHint().height()


class TestZonesAndWidgets:
    def test_leading_and_trailing(self, qapp, make):
        bar = make(ElaChatToolBar)
        bar.addButton(text="左", zone="leading")
        bar.addButton(text="右", zone="trailing")
        leading_button = bar.toolButton("tool-1")
        trailing_button = bar.toolButton("tool-2")
        assert leading_button.parentWidget() is bar
        assert trailing_button.parentWidget() is bar
        # 左段在 trailing 段之前
        assert bar._leading.indexOf(leading_button) >= 0
        assert bar._trailing.indexOf(trailing_button) >= 0

    def test_add_widget(self, qapp, make):
        bar = make(ElaChatToolBar)
        label = QLabel("自定义")
        returned = bar.addWidget(label, zone="trailing", key="custom")
        assert returned is label
        assert bar.item("custom") is label
        assert label.parentWidget() is bar

    def test_separator(self, qapp, make):
        bar = make(ElaChatToolBar)
        bar.addButton(text="A")
        line = bar.addSeparator()
        assert line is not None
        assert line.width() == 1
        assert bar.count() == 1  # 分隔线不计入项


class TestInsert:
    def test_insert_button_before_key(self, qapp, make):
        bar = make(ElaChatToolBar)
        first = bar.addButton(text="A", key="a")
        second = bar.addButton(text="B", key="b")
        inserted = bar.insertButton("b", text="X", key="x")
        assert bar._leading.indexOf(first) == 0
        assert bar._leading.indexOf(inserted) == 1
        assert bar._leading.indexOf(second) == 2
        assert bar.keys() == ["a", "b", "x"]  # 登记顺序仍是添加顺序

    def test_insert_uses_reference_zone(self, qapp, make):
        bar = make(ElaChatToolBar)
        left = bar.addButton(text="左", key="l", zone="leading")
        right = bar.addButton(text="右", key="r", zone="trailing")
        inserted = bar.insertButton("r", text="前", key="ins")
        assert bar._trailing.indexOf(inserted) == bar._trailing.indexOf(right) - 1
        assert bar._leading.indexOf(left) == 0

    def test_insert_widget_and_separator(self, qapp, make):
        bar = make(ElaChatToolBar)
        button = bar.addButton(text="A", key="a")
        line = bar.insertSeparator("a")
        label = bar.insertWidget("a", QLabel("自定义"), key="custom")
        assert bar.item("custom") is label
        index_line = bar._leading.indexOf(line)
        index_label = bar._leading.indexOf(label)
        index_button = bar._leading.indexOf(button)
        assert index_line < index_label < index_button

    def test_insert_unknown_before_raises(self, qapp, make):
        bar = make(ElaChatToolBar)
        with pytest.raises(ValueError):
            bar.insertButton("missing", text="X")
        with pytest.raises(ValueError):
            bar.insertWidget("missing", QLabel("x"))
        with pytest.raises(ValueError):
            bar.insertSeparator("missing")
        assert bar.count() == 0  # 失败不留半成品


class TestZoneValidation:
    def test_invalid_zone_raises(self, qapp, make):
        bar = make(ElaChatToolBar)
        with pytest.raises(ValueError):
            bar.addButton(text="X", zone="top")
        with pytest.raises(ValueError):
            bar.addWidget(QLabel("x"), zone="top")
        with pytest.raises(ValueError):
            bar.addSeparator(zone="top")
        with pytest.raises(ValueError):
            bar.addStretch(zone="top")
        with pytest.raises(ValueError):
            bar.clear(zone="top")
        assert bar.count() == 0


class TestItemState:
    def test_visible_and_enabled(self, qapp, make):
        bar = make(ElaChatToolBar)
        button = bar.addButton(icon=ElaIconType.IconName.Bolt, key="bolt")
        assert bar.itemVisible("bolt") is True
        assert bar.itemEnabled("bolt") is True

        assert bar.setItemVisible("bolt", False) is True
        assert bar.itemVisible("bolt") is False
        assert bar.itemVisible(button) is False
        assert button.isHidden() is True

        assert bar.setItemEnabled("bolt", False) is True
        assert bar.itemEnabled("bolt") is False
        assert bar.itemEnabled(button) is False

        # 隐藏 / 禁用不销毁控件
        assert bar.item("bolt") is button

        # 未知项返回 False，不抛异常
        assert bar.setItemVisible("missing", False) is False
        assert bar.setItemEnabled("missing", False) is False
        assert bar.itemVisible("missing") is False
        assert bar.itemEnabled("missing") is False

    def test_show_and_enable_again(self, qapp, make):
        bar = make(ElaChatToolBar)
        button = bar.addButton(text="A", key="a")
        bar.setItemVisible("a", False)
        bar.setItemEnabled("a", False)
        assert bar.setItemVisible("a", True) is True
        assert bar.setItemEnabled("a", True) is True
        assert bar.itemVisible("a") is True
        assert bar.itemEnabled("a") is True
        assert button.isHidden() is False


class TestRemove:
    def test_remove_by_key_and_handle(self, qapp, make):
        bar = make(ElaChatToolBar)
        first = bar.addButton(text="A", key="a")
        second = bar.addButton(text="B", key="b")
        assert bar.removeItem("a") is True
        assert bar.keys() == ["b"]
        assert bar.removeItem(first) is False
        assert bar.removeItem(second) is True
        assert bar.count() == 0

    def test_clear_zone(self, qapp, make):
        bar = make(ElaChatToolBar)
        bar.addButton(text="左", key="l", zone="leading")
        bar.addButton(text="右", key="r", zone="trailing")
        bar.clear(zone="leading")
        assert bar.keys() == ["r"]
        bar.clear()
        assert bar.keys() == []

    def test_compact(self, qapp, make):
        bar = make(ElaChatToolBar)
        assert not bar.compact()
        bar.setCompact(True)
        assert bar.compact()
        assert bar.layout().spacing() == 2


class TestDuplicateKey:
    def test_explicit_duplicate_key_raises(self, qapp, make):
        """显式重复 key 必须抛错：静默覆盖会让旧控件留在布局里却无法再管理。"""
        bar = make(ElaChatToolBar)
        bar.addButton(text="A", key="dup")
        with pytest.raises(ValueError):
            bar.addButton(text="B", key="dup")
        assert bar.keys() == ["dup"]

    def test_parent_is_first_positional(self, qapp, make):
        host = make(QWidget)
        button = make(ElaChatToolButton, host, icon=ElaIconType.IconName.Bolt)
        assert button.parent() is host


class TestSeparatorRemoval:
    def test_remove_separator_individually(self, qapp, make):
        """分隔线可单独移除（此前只能 clear 整段）。"""
        bar = make(ElaChatToolBar)
        bar.addButton(text="A", key="a")
        sep = bar.addSeparator(zone="leading")
        bar.addButton(text="B", key="b")
        assert bar._leading.count() == 3

        assert bar.removeSeparator(sep) is True
        assert bar.removeSeparator(sep) is False, "已移除的句柄再删返回 False"
        assert bar._leading.count() == 2
        assert bar.keys() == ["a", "b"], "分隔线不进 key 空间"

    def test_remove_item_accepts_separator(self, qapp, make):
        bar = make(ElaChatToolBar)
        sep = bar.addSeparator(zone="trailing")
        assert bar.removeItem(sep) is True
        assert bar._trailing.count() == 0
        assert bar.removeItem(sep) is False

    def test_inserted_separator_is_removable(self, qapp, make):
        bar = make(ElaChatToolBar)
        bar.addButton(text="A", key="a")
        sep = bar.insertSeparator("a")
        assert bar._leading.indexOf(sep) == 0
        assert bar.removeSeparator(sep) is True
        assert bar._leading.count() == 1

    def test_separator_visibility_and_enabled(self, qapp, make):
        bar = make(ElaChatToolBar)
        sep = bar.addSeparator()
        assert bar.setItemVisible(sep, False) is True
        assert bar.itemVisible(sep) is False
        assert bar.setItemVisible(sep, True) is True
        assert bar.itemVisible(sep) is True
        assert bar.setItemEnabled(sep, False) is True
        assert bar.itemEnabled(sep) is False
        assert bar.setItemVisible("missing", True) is False
