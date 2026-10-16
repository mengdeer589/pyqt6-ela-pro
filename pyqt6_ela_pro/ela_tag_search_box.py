"""
具名可搜索下拉框组件。

带有标题标签的可搜索下拉框，继承自 ElaSearchBox，
支持汉字原文、全拼与拼音首字母搜索。
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtGui import QPainter, QPaintEvent
from PyQt6.QtWidgets import QWidget

from .combo_box import ElaSearchBox
from .ela_tag_combo_base import (
    _TagBoxThemeMixin,
    _TagBoxAnimMixin,
    _paint_tag_single,
)
from ._internal import _adjust_combobox_popup, hideComboboxPopup


class ElaTagSearchBox(_TagBoxThemeMixin, _TagBoxAnimMixin, ElaSearchBox):
    """具名可搜索下拉框。

    带有标题标签的可搜索下拉框，支持汉字原文、全拼与拼音首字母搜索。
    继承自 ElaSearchBox，使用胶囊样式。

    :param title: 标题文字
    :param parent: 父控件

    Example::

        combo = ElaTagSearchBox(title="语言", parent=parent)
        combo.addItems(["Python", "C++", "JavaScript", "上海", "北京"])
    """

    def __init__(
        self,
        title: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._tag_box_init(title)
        self._indexChangedSlot = self._onCurrentIndexChanged  # 断连要同一对象（lambda / partial 必须存引用）
        self.currentIndexChanged.connect(self._indexChangedSlot)

    def showPopup(self) -> None:
        if self.count() == 0:
            return
        self._animate_popup_open()
        super().showPopup()
        _adjust_combobox_popup(self)

        if self._searchEdit:
            self._applySearchEditPalette()

    def hidePopup(self) -> None:
        self._animate_popup_close()
        if hideComboboxPopup(self):
            return
        super().hidePopup()

    def _onCurrentIndexChanged(self, _index: int) -> None:
        self.update()

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        _paint_tag_single(painter, self)

    def deleteLater(self) -> None:
        slot = getattr(self, '_indexChangedSlot', None)
        if slot is not None:
            try:
                self.currentIndexChanged.disconnect(slot)
            except (TypeError, RuntimeError):
                pass
            self._indexChangedSlot = None  # 幂等：deleteLater 可能被调用两次
        self._theme_cleanup()
        super().deleteLater()
