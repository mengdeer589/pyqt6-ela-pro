"""聊天输入区补全组件：候选项快照 + 无焦点补全列表（``pyqt6_ela_pro.chat``）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import QAbstractItemView, QVBoxLayout, QWidget
from PyQt6ElaWidgetTools import ElaListView, ElaScrollPageArea

from .message import _as_int

#: 列表项高度
_ITEM_HEIGHT = 30
#: 默认最大高度
_DEFAULT_MAX_HEIGHT = 220


@dataclass(frozen=True)
class ElaChatSuggestion:
    """补全候选项快照。"""

    #: 唯一标识（命令 id / 引用路径等）
    id: str
    #: 展示文本
    label: str
    #: 描述（悬停提示）
    description: str = ""
    #: 选中后插入编辑器的文本（默认使用 ``label``）
    insert_text: str = ""
    #: 类型（``file`` / ``agent`` / ``command`` / 其它宿主自定义）
    kind: str = ""


class SuggestionPopup(ElaScrollPageArea):
    """补全浮层：``ElaScrollPageArea`` 卡面 + ``ElaListView`` 列表。

    取色与字号交给 ``ElaListView`` 自带的 ``ElaListViewStyle``，本组件不设 QSS
    （``color:`` 无效，且 ``setStyleSheet`` 会整体替换它的透明底规则）。
    """

    #: 候选项被激活（参数：``ElaChatSuggestion``）
    suggestionActivated = pyqtSignal(object)

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        maxHeight: int = _DEFAULT_MAX_HEIGHT,
    ) -> None:
        super().__init__(parent)
        # ElaScrollPageArea 构造时 setFixedHeight(75)，浮层高度按候选项自适应
        self.setMinimumHeight(0)
        self.setBorderRadius(8)
        self.setMaximumHeight(maxHeight)
        self._items: list[ElaChatSuggestion] = []
        self._model = QStandardItemModel(self)
        self._view = ElaListView(self)
        self._view.setModel(self._model)
        self._view.setItemHeight(_ITEM_HEIGHT)
        self._view.setUniformItemSizes(True)
        self._view.setIsTransparent(True)
        self._view.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._view.clicked.connect(self._on_clicked)
        layout = self.layout()
        if layout is None:
            layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(0)
        layout.addWidget(self._view)
        self.hide()

    # -- 查询 --------------------------------------------------------------

    def items(self) -> list:
        """当前候选项列表。"""
        return list(self._items)

    def currentIndex(self) -> int:
        """当前高亮下标（无选中返回 -1）。"""
        indexes = self._view.selectionModel().selectedIndexes()
        return indexes[0].row() if indexes else -1

    def setCurrentIndex(self, index: int) -> None:
        """设置高亮下标（夹取到合法范围）。"""
        if not self._items:
            return
        index = max(0, min(_as_int(index), len(self._items) - 1))
        self._view.setCurrentIndex(self._model.index(index, 0))

    def moveSelection(self, delta: int) -> None:
        """循环移动高亮。"""
        if not self._items:
            return
        current = self.currentIndex()
        if current < 0:
            current = 0 if delta > 0 else len(self._items) - 1
        else:
            current = (current + _as_int(delta)) % len(self._items)
        self.setCurrentIndex(current)

    # -- 开合与激活 --------------------------------------------------------

    def open(self, items: list) -> None:
        """灌入候选项并显示。"""
        self.setItems(items)
        if not self._items:
            self.close()
            return
        self.setCurrentIndex(0)
        self.show()

    def close(self) -> None:  # noqa: A003 (Qt 命名)
        """关闭浮层。"""
        self.hide()

    def isOpen(self) -> bool:
        """浮层是否可见且有候选项。"""
        return self.isVisible() and bool(self._items)

    def setItems(self, items: list) -> None:
        """替换候选项列表。"""
        self._items = [
            item
            if isinstance(item, ElaChatSuggestion)
            else ElaChatSuggestion(id=str(item), label=str(item))
            for item in (items or [])
        ]
        self._model.clear()
        for item in self._items:
            entry = QStandardItem(item.label)
            entry.setEditable(False)
            entry.setData(item, Qt.ItemDataRole.UserRole)
            if item.description:
                entry.setToolTip(item.description)
            self._model.appendRow(entry)
        if not self._items:
            self.close()

    def activateCurrent(self) -> bool:
        """激活当前高亮项；返回是否已激活。"""
        index = self.currentIndex()
        if index < 0:
            index = 0
        return self._activate(index)

    def _activate(self, index: int) -> bool:
        if not 0 <= index < len(self._items):
            return False
        item = self._items[index]
        self.close()
        self.suggestionActivated.emit(item)
        return True

    def _on_clicked(self, index) -> None:
        self._activate(index.row())


__all__ = ["ElaChatSuggestion", "SuggestionPopup"]
