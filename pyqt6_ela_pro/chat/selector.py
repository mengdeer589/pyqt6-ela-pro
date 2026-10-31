"""输入区下拉选择器（模型 / agent / 变体）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PyQt6.QtCore import pyqtSignal
from PyQt6ElaWidgetTools import ElaIconType, ElaMenu

from .._internal import is_deleted
from ..ela_dropdown_button import ElaDropDownButton


@dataclass(frozen=True)
class ElaChatSelectorItem:
    """选择器的一项。"""

    #: 稳定 id（回传给宿主）
    id: str
    #: 展示文本
    label: str
    #: 说明（菜单项 tooltip / 悬停）
    description: str = ""
    #: 图标（``ElaIconType`` 成员；``None`` 表示无图标）
    icon: Optional[ElaIconType.IconName] = None


class ElaChatSelector(ElaDropDownButton):
    """下拉选择器：当前值显示在按钮上，点击弹出 ElaMenu。"""

    #: 选中项变化（参数：item id）
    selectionChanged = pyqtSignal(str)

    def __init__(
        self,
        title: str = "",
        items=None,
        current: str = "",
        parent=None,
    ) -> None:
        super().__init__("", ElaIconType.IconName.None_, parent)
        self._title = str(title or "")
        self._items: list[ElaChatSelectorItem] = []
        self._current = str(current or "")
        self._actions: dict = {}
        self._menu: Optional[ElaMenu] = None
        self.setToolTip(self._title)
        self.setItems(items or [], current)

    # -- 数据 --------------------------------------------------------------

    def setItems(self, items, current: Optional[str] = None) -> None:
        """整体替换选项并重建菜单。"""
        self._items = [
            item
            if isinstance(item, ElaChatSelectorItem)
            else ElaChatSelectorItem(id=str(item), label=str(item))
            for item in (items or [])
        ]
        if current is not None:
            self._current = str(current or "")
        if not self._current and self._items:
            self._current = self._items[0].id
        self._rebuild_menu()
        self._sync_label()

    def items(self) -> list:
        """获取选项快照。"""
        return list(self._items)

    def setCurrent(self, itemId: str, emit: bool = False) -> bool:
        """设置当前项；找不到返回 ``False``。"""
        target = str(itemId or "")
        if not any(item.id == target for item in self._items):
            return False
        changed = target != self._current
        self._current = target
        self._sync_menu_checks()
        self._sync_label()
        if emit:
            self.selectionChanged.emit(target)
        return changed

    def current(self) -> str:
        """当前项 id（空 = 无）。"""
        return self._current

    def currentItem(self) -> Optional[ElaChatSelectorItem]:
        """当前项快照。"""
        for item in self._items:
            if item.id == self._current:
                return item
        return None

    def title(self) -> str:
        """选择器标题（tooltip）。"""
        return self._title

    # -- 内部 --------------------------------------------------------------

    def _rebuild_menu(self) -> None:
        old = self._menu
        if old is not None and not is_deleted(old):
            self.setMenu(None)
            old.deleteLater()
        menu = ElaMenu(self)
        self._actions = {}
        for item in self._items:
            if item.icon is not None and item.icon != ElaIconType.IconName.None_:
                action = menu.addElaIconAction(item.icon, item.label)
            else:
                action = menu.addAction(item.label)
            action.setCheckable(True)
            action.setChecked(item.id == self._current)
            if item.description:
                action.setToolTip(item.description)
            action.triggered.connect(
                lambda _checked=False, iid=item.id: self._select(iid)
            )
            self._actions[item.id] = action
        self._menu = menu
        self.setMenu(menu)

    def _sync_menu_checks(self) -> None:
        for itemId, action in self._actions.items():
            if is_deleted(action):
                continue
            action.setChecked(itemId == self._current)

    def _sync_label(self) -> None:
        item = self.currentItem()
        self.setText(item.label if item is not None else self._title)
        self.setToolTip(
            f"{self._title}: {item.label}"
            if item is not None and self._title
            else self._title
        )

    def _select(self, itemId: str) -> None:
        if itemId == self._current:
            self._sync_menu_checks()
            return
        self._current = itemId
        self._sync_menu_checks()
        self._sync_label()
        self.selectionChanged.emit(itemId)


__all__ = ["ElaChatSelector", "ElaChatSelectorItem"]
