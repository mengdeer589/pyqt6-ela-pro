"""图标浏览器示例的数据模型（PyQt6 版）。

与 PyQt5 版的两处绑定差异：PyQt6 没有 ``QVariant``（``data()`` 直接返回 Python
对象，取不到就是 ``None``）；图标枚举在 ``ElaIconType.IconName`` 里（不再平铺在
``ElaIconType`` 上）。
"""

from __future__ import annotations

from PyQt6.QtCore import QAbstractListModel, QModelIndex, Qt
from PyQt6ElaWidgetTools import ElaIconType

from .._styles import iconGlyph


class T_IconModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._iconKeys = [m.name for m in ElaIconType.IconName]
        self._rowCount = len(self._iconKeys)
        self._pIsSearchMode = False
        self._searchKeyList: list = []

    def rowCount(self, parent=QModelIndex()) -> int:
        return self._rowCount

    def setSearchKeyList(self, searchKeyList: list):
        self.beginResetModel()
        self._searchKeyList = searchKeyList
        if self._pIsSearchMode:
            self._rowCount = len(self.getSearchKeyList())
        else:
            self._rowCount = len(self._iconKeys)
        self.endResetModel()

    def getSearchKeyList(self) -> list:
        return self._searchKeyList

    def setIsSearchMode(self, isSearchMode: bool):
        self._pIsSearchMode = isSearchMode

    def getIsSearchMode(self) -> bool:
        return self._pIsSearchMode

    def _icon_row(self, key: str):
        try:
            icon_enum = getattr(ElaIconType.IconName, key)
        except AttributeError:
            return None
        return [key, iconGlyph(icon_enum)]

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.UserRole:
            keys = self._searchKeyList if self._pIsSearchMode else self._iconKeys
            if index.row() >= len(keys):
                return None
            return self._icon_row(keys[index.row()])
        return None

    def getIconNameFromModelIndex(self, index: QModelIndex) -> str:
        if self._pIsSearchMode:
            if index.row() < len(self._searchKeyList):
                return f"ElaIconType.IconName.{self._searchKeyList[index.row()]}"
        else:
            if index.row() < len(self._iconKeys):
                return f"ElaIconType.IconName.{self._iconKeys[index.row()]}"
        return ""
