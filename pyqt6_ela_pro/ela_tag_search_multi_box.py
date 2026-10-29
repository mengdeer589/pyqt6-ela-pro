"""
具名可搜索多选下拉框组件。

带有标题标签的可搜索多选下拉框，继承自 ElaSearchMultiBox，
支持汉字原文、全拼与拼音首字母搜索。
"""

from __future__ import annotations

from typing import Optional, Union

from PyQt6.QtCore import QAbstractAnimation
from PyQt6.QtGui import QPainter, QPaintEvent
from PyQt6.QtWidgets import QWidget

from .combo_box import ElaSearchMultiBox
from .ela_tag_combo_base import (
    _TagBoxThemeMixin,
    _TagBoxAnimMixin,
    _pre_init_popup,
    _get_target_mark_width,
    _paint_tag_multi,
)
from ._internal import single_shot_on, hideComboboxPopup


class ElaTagSearchMultiBox(_TagBoxThemeMixin, _TagBoxAnimMixin, ElaSearchMultiBox):
    """具名可搜索多选下拉框。

    带有标题标签的可搜索多选下拉框，支持汉字原文、全拼与拼音首字母搜索。
    继承自 ElaSearchMultiBox，使用胶囊样式。

    :param title: 标题文字
    :param parent: 父控件

    Example::

        combo = ElaTagSearchMultiBox(title="语言", parent=parent)
        combo.addItems(["Python", "C++", "JavaScript", "上海", "北京"])
        combo.setCurrentSelection(["Python", "上海"])
    """

    def __init__(
        self,
        title: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._tag_box_init(title)
        self.setMaxVisibleItems(10)
        single_shot_on(self, 0, lambda: _pre_init_popup(self))

    def showPopup(self) -> None:
        if self.count() == 0:
            return
        self._expand_mark_width = _get_target_mark_width(self)
        super().showPopup()
        if self._searchEdit:
            self._applySearchEditPalette()

    def hidePopup(self) -> None:
        self._expand_mark_width = 0.0
        if hideComboboxPopup(self):
            return
        super().hidePopup()

    def setCurrentSelection(self, selection: Union[str, list[str], None]) -> None:
        """设置选中项，**接受 None / 单个字符串 / 字符串列表**（与 :class:`ElaTagMultiBox` 同款）。

        ``None`` 与空列表等价；基类直接 ``list(selection)`` 时字符串会被拆成单个
        字符 —— 匹配不到任何选项，表现为「设了没反应」。
        """
        if selection is None:
            selection = []
        elif isinstance(selection, str):
            selection = [selection]
        selection = list(selection)
        if self._mark_animation.state() == QAbstractAnimation.State.Running:
            self._mark_animation.stop()
        # 先写 C++ 选中，再算底部标记宽度（反了会拿旧选中算目标宽）
        super().setCurrentSelection(selection)
        self._expand_mark_width = _get_target_mark_width(self)
        self.update()

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        _paint_tag_multi(painter, self)

    def deleteLater(self) -> None:
        self._theme_cleanup()
        super().deleteLater()
