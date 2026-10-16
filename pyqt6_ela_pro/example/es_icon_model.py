"""
SVG 图标数据模型。
"""

from PyQt6.QtCore import QModelIndex, QAbstractListModel, Qt


class EsIconModel(QAbstractListModel):
    """SVG 图标数据模型，用于图标浏览器。"""

    def __init__(self, icon_names: list[str] = None, parent=None):
        super().__init__(parent)
        self._icon_names = icon_names or []
        self._row_count = len(self._icon_names)
        self._p_is_search_mode = False
        self._search_key_list = []

    def rowCount(self, parent=QModelIndex()) -> int:
        return self._row_count

    def setSearchKeyList(self, search_key_list: list):
        self.beginResetModel()
        self._search_key_list = search_key_list
        if self._p_is_search_mode:
            self._row_count = len(self._search_key_list)
        else:
            self._row_count = len(self._icon_names)
        self.endResetModel()

    def getSearchKeyList(self) -> list:
        return self._search_key_list

    def setIsSearchMode(self, is_search_mode: bool):
        self._p_is_search_mode = is_search_mode

    def getIsSearchMode(self) -> bool:
        return self._p_is_search_mode

    def resetIconNames(self, icon_names: list) -> None:
        """整体换掉图标名列表（宿主加载新图标包后调用）。

        走 ``beginResetModel`` / ``endResetModel``：行数变了，必须让视图丢掉
        全部索引并重取 —— 逐行改会留下越界的 selection 与滚动位置。

        同时**清掉搜索态**：过滤列表是按旧名字算的，换包之后那些名字多半不存在，
        留着会让视图显示一个空列表且看不出是「搜索没命中」还是「包是空的」。
        """
        self.beginResetModel()
        self._icon_names = list(icon_names or [])
        self._search_key_list = []
        self._p_is_search_mode = False
        self._row_count = len(self._icon_names)
        self.endResetModel()

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole:
            if not self._p_is_search_mode:
                if index.row() >= len(self._icon_names):
                    return None
                return self._icon_names[index.row()]
            else:
                if index.row() >= len(self._search_key_list):
                    return None
                return self._search_key_list[index.row()]
        return None

    def getIconNameFromModelIndex(self, index: QModelIndex) -> str:
        if self._p_is_search_mode:
            if index.row() < len(self._search_key_list):
                return self._search_key_list[index.row()]
        else:
            if index.row() < len(self._icon_names):
                return self._icon_names[index.row()]
        return ""
