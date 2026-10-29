"""
具名多选下拉框组件。

带有标题标签的多选下拉框，标题在左侧，值在右侧。
继承自 PyQt6ElaWidgetTools.ElaMultiSelectComboBox。
"""

from __future__ import annotations

from typing import Optional, Union

from PyQt6.QtCore import QAbstractAnimation
from PyQt6.QtGui import QPainter, QPaintEvent
from PyQt6.QtWidgets import QWidget

from PyQt6ElaWidgetTools import ElaMultiSelectComboBox

from .ela_tag_combo_base import (
    _TagBoxThemeMixin,
    _TagBoxAnimMixin,
    _pre_init_popup,
    _get_target_mark_width,
    _paint_tag_multi,
)
from ._internal import (
    _adjust_combobox_popup,
    _prepare_combobox_popup,
    single_shot_on,
    hideComboboxPopup,
)


class ElaTagMultiBox(_TagBoxThemeMixin, _TagBoxAnimMixin, ElaMultiSelectComboBox):
    """具名多选下拉框。

    带有标题标签的多选下拉框，标题在左侧，值在右侧。
    继承自 PyQt6ElaWidgetTools.ElaMultiSelectComboBox。

    :param title: 标题文字
    :param parent: 父控件

    Example::

        combo = ElaTagMultiBox(title="语言", parent=parent)
        combo.addItem("Python")
        combo.addItem("C++")
        combo.addItem("JavaScript")
    """

    def __init__(
        self,
        title: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._tag_box_init(title)
        self._currentSelection: list[str] = []
        self.setMaxVisibleItems(10)
        single_shot_on(self, 0, lambda: _pre_init_popup(self))

    @property
    def items(self) -> list[str]:
        """返回当前所有选项列表。"""
        return [self.itemText(i) for i in range(self.count())]

    def showPopup(self) -> None:
        if self.count() == 0:
            return
        self._expand_mark_width = _get_target_mark_width(self)
        _prepare_combobox_popup(self)
        super().showPopup()
        _adjust_combobox_popup(self)

    def hidePopup(self) -> None:
        self._expand_mark_width = 0.0
        if hideComboboxPopup(self):
            return
        super().hidePopup()

    def setCurrentSelection(self, selection: Union[str, list[str], None]) -> None:
        """???????? **None / ????? / ?????**?? ElaSearchMultiBox??

        `None` ????????????????**??**????????
        """
        if selection is None:
            selection = []
        elif isinstance(selection, str):
            selection = [selection]
        self._currentSelection = list(selection)
        if self._mark_animation.state() == QAbstractAnimation.State.Running:
            self._mark_animation.stop()
        # ?? C++ ??????????? ?? ????????????????
        super().setCurrentSelection(self._currentSelection)
        self._expand_mark_width = _get_target_mark_width(self)
        self.update()

    def currentSelection(self) -> list[str]:
        """??????? C++ ??????"""
        return list(super().getCurrentSelection())

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        _paint_tag_multi(painter, self)

    def deleteLater(self) -> None:
        self._theme_cleanup()
        super().deleteLater()
