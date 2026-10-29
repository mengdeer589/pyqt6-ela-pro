"""
ComboBox 组件模块。

提供以下组件：

- ``ElaSearchBox``：基于 ``ElaComboBox`` 的可搜索单选下拉框
- ``ElaSearchMultiBox``：基于 ``ElaMultiSelectComboBox`` 的可搜索多选下拉框

搜索同时匹配选项原文、全拼与拼音首字母（``"bei"`` / ``"bj"`` 均可命中“北京”），
空格分隔的多个关键词需全部命中。所有组件均支持主题适配，自动跟随应用程序的
亮/暗主题切换样式。
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QBoxLayout, QLineEdit, QVBoxLayout, QWidget
from PyQt6ElaWidgetTools import (
    ElaComboBox,
    ElaMultiSelectComboBox,
    ElaThemeType,
    eTheme,
)

from ._internal import (
    _adjust_combobox_popup,
    _prepare_combobox_popup,
    _ThemeAwareMixin,
    hideComboboxPopup,
    load_lazy_pinyin,
)

#: 弹层顶部搜索框的固定高度（与 ``_build_search_widget`` 的 ``setFixedHeight`` 同值）。
_SEARCH_WIDGET_HEIGHT = 40


def _split_keyword(keyword: str) -> list[str]:
    """把搜索关键词拆成小写 token 列表（空格分隔，全部命中才算匹配）。"""
    return keyword.lower().split()


def _pinyin_index(text: str, cache: dict[str, tuple[str, str]]) -> tuple[str, str]:
    """返回选项文本的 ``(全拼, 首字母)``（均为小写），并按需写入缓存。

    ``pypinyin`` 惰性导入（首次需要拼音匹配时才付 ~50 MiB 字典成本）；
    缺失时返回空索引，搜索退化为原文 / 紧凑串匹配。
    """
    index = cache.get(text)
    if index is None:
        impl = load_lazy_pinyin()
        if impl is None:
            index = ("", "")
        else:
            syllables = impl(text)
            full = "".join(syllables).lower()
            initials = "".join(
                syllable[0] for syllable in syllables if syllable
            ).lower()
            index = (full, initials)
        cache[text] = index
    return index


def _compact_value(value: str) -> str:
    """去掉字母数字以外的字符（``"gpt-4o"`` → ``"gpt4o"``），用于标点不敏感匹配。"""
    return "".join(ch for ch in value.lower() if ch.isalnum())


def _match_item(
    text: str, tokens: list[str], cache: dict[str, tuple[str, str]]
) -> bool:
    """判断选项文本是否命中关键词 token。

    匹配规则：原文 / 全拼 / 首字母的任意子串，以及忽略标点空白的紧凑串
    （``"gpt4o"`` 命中 ``"gpt-4o"``）；多个 token 之间为 AND。
    """
    if not tokens:
        return True
    full, initials = _pinyin_index(text, cache)
    lower = text.lower()
    compact_text = _compact_value(text)
    for token in tokens:
        if token in lower or token in full or token in initials:
            continue
        compact_token = _compact_value(token)
        if compact_token and compact_token in compact_text:
            continue
        return False
    return True


class _SearchComboMixin:
    """Mixin providing shared search widget methods for combo boxes."""

    _pinyin_cache: dict[str, tuple[str, str]]
    _popup_search_visible: bool

    def _apply_row_filter(self, keyword: str) -> None:
        """按关键词隐藏不匹配的行（原文 / 全拼 / 首字母），并滚动到首个命中项。"""
        view = self.view()
        if view is None:
            return
        tokens = _split_keyword(keyword)
        first_match = -1
        for i in range(self.count()):
            hidden = not _match_item(self.itemText(i), tokens, self._pinyin_cache)
            if view.isRowHidden(i) != hidden:
                view.setRowHidden(i, hidden)
            if not hidden and first_match < 0:
                first_match = i
        if tokens and first_match >= 0:
            model = self.model()
            if model is not None:
                view.scrollTo(model.index(first_match, 0))

    def _reset_row_filter(self) -> None:
        """取消所有行的隐藏状态（重新打开弹窗时调用）。"""
        view = self.view()
        if view is None:
            return
        for i in range(self.count()):
            if view.isRowHidden(i):
                view.setRowHidden(i, False)

    def setSearchVisible(self, on: bool = True) -> None:  # noqa: N802 (Qt 命名)
        """设置弹窗顶部搜索框显隐（关闭时清空关键词并恢复全部选项）。

        弹窗正打开时立即生效，否则在下次 ``showPopup()`` 时生效。

        :param on: ``True`` 显示搜索框，``False`` 隐藏。
        """
        self._popup_search_visible = on
        if not on:
            self._apply_row_filter("")
            search_widget = getattr(self, "_searchWidget", None)
            if search_widget is not None:
                search_widget.hide()
            return
        view = self.view()
        if view is not None and view.isVisible():
            container = self.findChild(QWidget, "ElaComboBoxContainer")
            if container is not None:
                self._setupSearchInPopup(container)
                if getattr(self, "_searchEdit", None) is not None:
                    self._searchEdit.setFocus()

    def searchVisible(self) -> bool:
        """返回弹窗顶部搜索框是否可见（默认 ``True``）。"""
        return self._popup_search_visible

    def setSearchPlaceholderText(self, text: str) -> None:  # noqa: N802
        """设置弹层搜索框占位文案（弹层已打开时立即生效）。"""
        self._search_placeholder = str(text)
        if getattr(self, "_searchEdit", None) is not None:
            self._searchEdit.setPlaceholderText(self._search_placeholder)

    def searchPlaceholderText(self) -> str:  # noqa: N802
        """返回弹层搜索框占位文案。"""
        return self._search_placeholder

    def _popup_extra_heights(self) -> tuple[int, int]:
        """返回弹层上下两端附件占用的高度 ``(top, bottom)``。"""
        return (_SEARCH_WIDGET_HEIGHT if self.searchVisible() else 0, 0)

    def _prepare_popup(self) -> None:
        """把附件高度交给 C++，并释放上一次的屏幕压缩固定高度。"""
        _prepare_combobox_popup(self, *self._popup_extra_heights())

    def _cleanupSearchWidget(self) -> None:
        if getattr(self, "_searchWidget", None):
            self._searchWidget.deleteLater()
            self._searchWidget = None
            self._searchEdit = None

    def _applySearchEditPalette(self) -> None:
        if getattr(self, "_searchEdit", None):
            _apply_search_edit_palette(self._searchEdit)

    def _onSearchTextChanged(self, text: str) -> None:
        """子类应重写此方法以响应搜索框文本变化。"""

    def _onThemeChanged(self, _mode=None) -> None:
        # 本 mixin **必须**排在 ``_ThemeAwareMixin`` 之前：后者也定义了同名钩子
        # 且是个空实现，写在它后面就会被 MRO 遮蔽成永远不被调用的死代码
        # （后果：搜索框调色板在切深浅色后不跟随）。
        self._applySearchEditPalette()
        super()._onThemeChanged(_mode)

    def _setupSearchInPopup(self, container: QWidget) -> None:
        layout = container.layout()
        if layout is None:
            return
        if self._searchWidget is None:
            self._searchWidget, self._searchEdit = _build_search_widget(
                self._onSearchTextChanged, self._search_placeholder
            )
        elif self._searchWidget.parent() is not None:
            self._searchWidget.setParent(None)
        if isinstance(layout, QBoxLayout):
            layout.insertWidget(0, self._searchWidget)
        self._searchWidget.show()
        # 列表在动画期间从上方滑下来，搜索框保持在最上层（否则会被列表短暂盖住）
        self._searchWidget.raise_()
        if self._searchEdit:
            self._applySearchEditPalette()
            self._searchEdit.blockSignals(True)
            self._searchEdit.clear()
            self._searchEdit.blockSignals(False)


def _build_search_widget(
    text_changed_callback,
    placeholder: str = "搜索...",
) -> tuple[QWidget, QLineEdit]:
    """创建弹窗内搜索框组件，返回 ``(searchWidget, searchEdit)``。"""
    search_widget = QWidget()
    search_widget.setObjectName("SearchWidget")
    search_widget.setFixedHeight(_SEARCH_WIDGET_HEIGHT)

    search_layout = QVBoxLayout(search_widget)
    search_layout.setContentsMargins(6, 6, 6, 2)
    search_layout.setSpacing(0)

    search_edit = QLineEdit()
    search_edit.setPlaceholderText(placeholder)
    search_edit.setFixedHeight(28)
    search_edit.textChanged.connect(text_changed_callback)
    _apply_search_edit_palette(search_edit)
    search_layout.addWidget(search_edit)

    return search_widget, search_edit


def _apply_search_edit_palette(search_edit: QLineEdit) -> None:
    """应用主题颜色到搜索框。"""
    theme_mode = eTheme.getThemeMode()
    palette = search_edit.palette()
    palette.setColor(
        QPalette.ColorRole.Text,
        eTheme.getThemeColor(theme_mode, ElaThemeType.ThemeColor.BasicText),
    )
    palette.setColor(
        QPalette.ColorRole.PlaceholderText,
        QColor(0, 0, 0, 128)
        if theme_mode == ElaThemeType.ThemeMode.Light
        else QColor(186, 186, 186),
    )
    search_edit.setPalette(palette)


class ElaSearchMultiBox(_SearchComboMixin, _ThemeAwareMixin, ElaMultiSelectComboBox):
    """可搜索多选下拉框。

    基于 ``ElaMultiSelectComboBox``：弹层顶部加搜索框，支持汉字原文 / 全拼 /
    首字母过滤（``"bei"`` / ``"bj"`` 都能命中「北京」），空格分隔的关键词 AND。
    搜索框可用 ``setSearchVisible(False)`` 关闭。
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._searchEdit: Optional[QLineEdit] = None
        self._searchWidget: Optional[QWidget] = None
        self._currentSelection: list[str] = []
        self._isRestoringSelection = False
        self._pinyin_cache: dict[str, tuple[str, str]] = {}
        self._popup_search_visible = True
        self._search_placeholder = "??..."

    @property
    def items(self) -> list[str]:
        """返回当前所有选项列表。"""
        return [self.itemText(i) for i in range(self.count())]

    def clear(self) -> None:
        """清空所有选项与拼音缓存。"""
        super().clear()
        self._currentSelection = []
        self._pinyin_cache.clear()

    def setCurrentSelection(self, selection) -> None:
        """设置当前选中项（接受 ``str`` 或字符串列表）。

        与兄弟类（``ElaTagMultiBox`` / ``ElaTagSearchMultiBox``）同口径：
        **传 ``str`` 归一成单元素** —— 旧实现 ``list(selection)`` 会把字符串
        拆成单个字符，匹配不到任何选项（「设了没反应、回读一堆字母」）。
        """
        if selection is None:
            selection = []
        elif isinstance(selection, str):
            selection = [selection]
        self._currentSelection = list(selection)
        super().setCurrentSelection(self._currentSelection)

    def currentSelection(self) -> list[str]:
        """??????? C++ ??????????????????"""
        return list(super().getCurrentSelection())

    def showPopup(self) -> None:
        """显示下拉弹窗，在弹窗顶部插入搜索框。"""
        if self.count() == 0:
            return
        self._reset_row_filter()
        # 必须 try/finally：这个标志一旦漏复位就永远是 True，而
        # _onSearchTextChanged 见它为 True 就直接 return —— 搜索过滤被永久
        # 短路，搜索框看起来还在但输入任何东西都没反应。中间任何一步抛异常
        # （_setupSearchInPopup 建控件、_adjust_combobox_popup 定位）都会命中。
        self._isRestoringSelection = True
        try:
            self._restoreSelection()
            self._prepare_popup()
            super().showPopup()

            container = self.findChild(QWidget, "ElaComboBoxContainer")
            if container is not None and self.searchVisible():
                self._setupSearchInPopup(container)
            _adjust_combobox_popup(self)
        finally:
            self._isRestoringSelection = False

    def _restoreSelection(self) -> None:
        """恢复之前的选中状态。"""
        if self._currentSelection:
            super().setCurrentSelection(self._currentSelection)

    def hidePopup(self) -> None:
        """关闭弹窗时保存选中状态（行隐藏状态留待下次 showPopup 复位）。"""
        self._currentSelection = super().getCurrentSelection()
        if hideComboboxPopup(self):
            return
        super().hidePopup()

    def deleteLater(self) -> None:
        self._theme_cleanup()
        self._cleanupSearchWidget()
        super().deleteLater()

    def _onSearchTextChanged(self, text: str) -> None:
        """搜索框文本变化时隐藏不匹配的行。"""
        if self._isRestoringSelection:
            return
        self._apply_row_filter(text)


class ElaSearchBox(_SearchComboMixin, _ThemeAwareMixin, ElaComboBox):
    """可搜索下拉框。

    基于标准 ``ElaComboBox`` 扩展，在弹出列表顶部增加了一个搜索框，
    支持汉字原文、全拼与拼音首字母过滤（``"bei"`` / ``"bj"`` 均可命中“北京”），
    空格分隔的多个关键词需全部命中。

    选项由 ``QComboBox`` 原生模型承载，``addItem`` / ``insertItem`` /
    ``removeItem`` / ``setItemText`` 等原生增删改 API 与 ``items`` 属性、
    搜索过滤互不干扰。搜索框可用 ``setSearchVisible(False)`` 关闭。
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)  # type: ignore[arg-type]
        self._searchEdit: Optional[QLineEdit] = None
        self._searchWidget: Optional[QWidget] = None
        self._pinyin_cache: dict[str, tuple[str, str]] = {}
        self._popup_search_visible = True
        self._search_placeholder = "??..."

    @property
    def items(self) -> list[str]:
        """返回当前所有选项列表。"""
        return [self.itemText(i) for i in range(self.count())]

    def clear(self) -> None:
        """清空所有选项并重置拼音缓存。"""
        super().clear()
        self._pinyin_cache.clear()

    def showPopup(self) -> None:
        """显示下拉弹窗，在弹窗顶部插入搜索框（``setSearchVisible(False)`` 可关闭）。"""
        if self.count() == 0:
            return
        self._reset_row_filter()
        self._prepare_popup()
        super().showPopup()

        container = self.findChild(QWidget, "ElaComboBoxContainer")
        if container is not None and self.searchVisible():
            self._setupSearchInPopup(container)
            if self._searchEdit:
                self._searchEdit.setFocus()
        _adjust_combobox_popup(self)

    def _onSearchTextChanged(self, text: str) -> None:
        self._apply_row_filter(text)

    def hidePopup(self) -> None:
        """关闭弹窗（行隐藏状态留待下次 showPopup 复位）。"""
        if hideComboboxPopup(self):
            return
        super().hidePopup()

    def deleteLater(self) -> None:
        """清理搜索框，断开信号，调度自身删除。"""
        self._theme_cleanup()
        self._cleanupSearchWidget()
        super().deleteLater()
