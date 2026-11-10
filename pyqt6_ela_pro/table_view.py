"""增强表格视图：``ElaDataTable`` 在 ``ElaTableView`` 上提供异步加载与样式配置。

列宽、单元格样式与代理的用法见 ``docs/core.md``。"""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any, Callable, Optional, Union

from PyQt6.QtCore import Qt, QModelIndex, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QIcon,
    QStandardItem,
    QFont,
    QColor,
    QStandardItemModel,
    QPainter,
)
from PyQt6.QtWidgets import (
    QWidget,
    QHeaderView,
    QAbstractItemView,
    QStyledItemDelegate,
    QStyleOptionViewItem,
)
from PyQt6ElaWidgetTools import ElaTableView

from ._internal import load_lazy_pinyin, safe_connect
from .tooltip_targets import install_item_view_tooltips


TABLE_MIN_SECTION_SIZE: int = 60
TABLE_ROW_MIN_HEIGHT: int = 46
# 保留常量以兼容外部引用（线程 quit 超时已由轮询清理取代）
TABLE_THREAD_QUIT_TIMEOUT: int = 1000
#: 单元格 tooltip 的自定义 role（不写 Qt.ToolTipRole，避免原生 QToolTip）
_CELL_TOOLTIP_ROLE = int(Qt.ItemDataRole.UserRole) + 101


def _safe_width(value) -> int:
    """列宽 -> 合法 int（取整；非有限值落默认 100）。

    ``QTableView.setColumnWidth`` 的 C++ 签名是 ``int``，PyQt6 **不做隐式
    转换**：传 ``120.5`` 抛 ``TypeError``，传 ``float('inf')`` 抛
    ``OverflowError``（它继承 ``ArithmeticError``，不是 ``ValueError``）。
    宿主按文档写 ``dict[int, int]`` 却在计算列宽时自然得到浮点，是很常见的
    形状 —— 库里统一取整，不把类型错误原样抛回去。
    """
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        # OverflowError 必须显式列出：``float(10 ** 400)`` 抛的是它，
        # 而它**不是** ValueError 的子类（全库守卫 tests/regression/
        # test_overflow_error_guards.py 会拦）
        return 100
    if number != number or number in (float("inf"), float("-inf")):
        return 100
    return int(max(0, min(10_000, number)))


class ElaRowColorDelegate(QStyledItemDelegate):
    """为指定行绘制自定义背景色的代理（未登记的行走默认绘制）。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._row_colors: dict[int, QColor] = {}

    def setRowColor(self, row: int, color: QColor) -> None:
        self._row_colors[row] = color

    def clearAllColors(self) -> None:
        self._row_colors.clear()

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex,
    ) -> None:  # ty:ignore[invalid-method-override]
        """绘制单元格，在设置了行颜色时填充背景。"""
        if index.row() in self._row_colors:
            painter.save()
            color = self._row_colors[index.row()]
            painter.fillRect(option.rect, color)
            painter.restore()
        super().paint(painter, option, index)


class _LoadThread(QThread):
    """在后台线程中加载表格数据的线程。

    加载完成发射 ``finished``（附行数据列表）；结束前调 :meth:`cancel` 可抑制发射。
    """

    finished = pyqtSignal(list)

    def __init__(self, rows: list) -> None:
        super().__init__()
        self._rows = rows
        self._isCanceled = False

    def cancel(self) -> None:
        """将线程标记为已取消。``finished`` 信号将不会被发射。"""
        self._isCanceled = True

    def run(self) -> None:
        """执行加载操作。若未取消则发射 ``finished`` 信号。"""
        rows = []
        for item in self._rows:
            if self._isCanceled:
                return
            rows.append(item)
        self.finished.emit(rows)


class ElaDataTable(ElaTableView):
    """增强型表格视图：``ElaTableView`` + ``QStandardItemModel``。
    同步 / 异步设置数据、列宽、单元格样式、行底色；表头排序默认关闭，
    需 ``setSortingEnabled(True)``。
    """

    sortChanged = pyqtSignal(int, Qt.SortOrder)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)  # type: ignore[arg-type]
        self._model = QStandardItemModel(self)
        self.setModel(self._model)
        # 单元格 tooltip 由 viewport 的 ToolTip 事件驱动（一个提示框服务整表）。
        install_item_view_tooltips(self, role=_CELL_TOOLTIP_ROLE)

        self.setAlternatingRowColors(True)
        vh = self.verticalHeader()
        if vh:
            vh.setHidden(True)
        hh = self.horizontalHeader()
        if hh:
            hh.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
            hh.setMinimumSectionSize(TABLE_MIN_SECTION_SIZE)
            hh.setDefaultAlignment(
                Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
            )
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        if vh:
            vh.setMinimumSectionSize(TABLE_ROW_MIN_HEIGHT)

        self._columnWidths: dict[int | str, int] = {}
        self._columnAlignments: dict[int, Qt.AlignmentFlag] = {}
        self._row_color_delegate = ElaRowColorDelegate(self)
        self.setItemDelegate(self._row_color_delegate)

        try:
            self._tableViewShowSlot = (
                self._apply_column_widths
            )  # 断连要同一对象（lambda / partial 必须存引用）
            self.tableViewShow.connect(self._tableViewShowSlot)
        except (TypeError, RuntimeError):
            pass

        self._load_thread: Optional[_LoadThread] = None
        self._isLoadThreadConnected: bool = False
        self._retired_threads: list[_LoadThread] = []

        self._sorting_enabled = False
        self._current_sort_column = -1
        self._current_sort_order = Qt.SortOrder.AscendingOrder
        self._headerClickedSlot = (
            self._onHeaderClicked
        )  # 断连要同一对象（lambda / partial 必须存引用）
        hh.sectionClicked.connect(self._headerClickedSlot)

    def _resolve_column(self, key: int | str) -> Optional[int]:
        """将列标识解析为列索引。

        int 原样返回；str 按表头名称匹配，找不到返回 ``None``。
        """
        if isinstance(key, int):
            return key
        for col in range(self.columnCount()):
            header_item = self._model.horizontalHeaderItem(col)
            if header_item and header_item.text() == key:
                return col
        return None

    def _apply_column_widths(self) -> None:
        """将缓存的所有列宽应用到视图中。"""
        for key, width in self._columnWidths.items():
            col = self._resolve_column(key)
            if col is not None:
                super().setColumnWidth(col, width)

    def _retire_thread(self, thread: _LoadThread) -> None:
        """取消并清理旧加载线程。
        因此不能阻塞等待其退出；线程真正结束后由轮询统一
        ``deleteLater``，避免对仍在运行的 QThread 销毁导致崩溃。
        """
        thread.cancel()
        if thread.isRunning():
            thread.quit()
        if self._isLoadThreadConnected:
            try:
                thread.finished.disconnect()
            except (TypeError, RuntimeError):
                pass
            self._isLoadThreadConnected = False
        if not thread.isRunning():
            thread.deleteLater()
        else:
            self._retired_threads.append(thread)
            self._poll_retired_threads()

    def _retire_poll_timer(self) -> None:
        """（重）起轮询定时器 —— **常驻子对象**，不用无主 ``singleShot``。
        销毁：表格销毁后定时器照样触发，去摸已释放的 ``_retired_threads``。
        而这里每次都能重发，所以必须是**一个**常驻定时器而不是每次 new 一个。
        """
        timer = self.__dict__.get("_retire_poll")
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(self._poll_retired_threads)
            self._retire_poll = timer
        timer.start(100)

    def _poll_retired_threads(self) -> None:
        """轮询已退出的旧线程并销毁。"""
        if not self._retired_threads:
            return
        remaining = []
        for t in self._retired_threads:
            if t.isRunning():
                remaining.append(t)
            else:
                t.deleteLater()
        self._retired_threads = remaining
        if remaining:
            self._retire_poll_timer()

    def _onHeaderClicked(self, logicalIndex: int) -> None:
        if not self._sorting_enabled:
            return
        if self._current_sort_column == logicalIndex:
            self._current_sort_order = (
                Qt.SortOrder.DescendingOrder
                if self._current_sort_order == Qt.SortOrder.AscendingOrder
                else Qt.SortOrder.AscendingOrder
            )
        else:
            self._current_sort_column = logicalIndex
            self._current_sort_order = Qt.SortOrder.AscendingOrder
        self._sort_by_column(logicalIndex, self._current_sort_order)
        self.horizontalHeader().setSortIndicator(logicalIndex, self._current_sort_order)
        self.sortChanged.emit(logicalIndex, self._current_sort_order)

    def _sort_by_column(self, column: int, order: Qt.SortOrder) -> None:
        """按列类型分派：数字 / 中文拼音 / 模型自带排序。"""
        col_type = self._get_column_type(column)
        if col_type == "numeric":
            self._sort_numeric(column, order)
        elif col_type == "chinese":
            self._sort_by_pinyin(column, order)
        else:
            self._model.sort(column, order)

    #: 列类型判定的非空采样上限
    _TYPE_SAMPLE = 20

    def _get_column_type(self, column: int) -> str:
        """取前 20 个**非空**样本判定列类型：``numeric`` / ``chinese`` / ``string``。
        空单元格**不占采样名额、也不参与判定**（旧实现把空值算进名额，一个
        空值就让数字列掉进 ``string`` 分支 —— 排序退化成字典序
        """
        numeric_count = 0
        chinese_count = 0
        checked = 0
        for row in range(self._model.rowCount()):
            if checked >= self._TYPE_SAMPLE:
                break
            item = self._model.item(row, column)
            text = item.text().strip() if item else ""
            if not text:
                continue
            checked += 1
            if self._is_numeric(text):
                numeric_count += 1
            elif self._contains_chinese(text):
                chinese_count += 1

        if checked > 0 and numeric_count == checked:
            return "numeric"
        if chinese_count > 0:
            return "chinese"
        return "string"

    @staticmethod
    def _is_numeric(text: str) -> bool:
        """是否为有限数字（``nan`` / ``inf`` 与空值同等看待）。"""
        try:
            # nan / inf 虽能被 float 解析，但不可比较（全序缺失），
            # 当成数字列会让排序静默变成空操作，见 _sort_numeric
            return math.isfinite(float(text.replace(",", "").replace(" ", "")))
        except ValueError:
            return False

    @staticmethod
    def _contains_chinese(text: str) -> bool:
        return any("\u4e00" <= char <= "\u9fff" for char in text)

    def _sort_by_pinyin(self, column: int, order: Qt.SortOrder) -> None:
        """按拼音排序（``pypinyin`` 缺失时退回模型自带排序）。"""
        lazy_pinyin = load_lazy_pinyin()
        if lazy_pinyin is None:
            self._model.sort(column, order)
            return

        row_count = self._model.rowCount()
        if row_count == 0:
            return

        items_with_pinyin = []
        for row in range(row_count):
            item = self._model.item(row, column)
            text = item.text() if item else ""
            pinyin = "".join(lazy_pinyin(text))
            items_with_pinyin.append((pinyin, row, text))

        reverse = order == Qt.SortOrder.DescendingOrder
        items_with_pinyin.sort(key=lambda x: x[0], reverse=reverse)

        self._reorder_rows([row for _, row, _ in items_with_pinyin])

    def _sort_numeric(self, column: int, order: Qt.SortOrder) -> None:
        row_count = self._model.rowCount()
        if row_count == 0:
            return

        # 空 / 非数值单元格排最后（升序降序一致）。``nan`` / ``inf`` 与空值同等对待：
        # 它们能通过 float() 但比较不成立，混进数值排序会拿不到全序。
        numeric: list[tuple[float, int]] = []
        blanks: list[int] = []
        for row in range(row_count):
            item = self._model.item(row, column)
            text = item.text() if item else ""
            raw = text.replace(",", "").replace(" ", "").strip()
            if not raw:
                blanks.append(row)
                continue
            try:
                value = float(raw)
            except ValueError:
                blanks.append(row)
                continue
            if not math.isfinite(value):
                blanks.append(row)
                continue
            numeric.append((value, row))

        reverse = order == Qt.SortOrder.DescendingOrder
        numeric.sort(key=lambda x: x[0], reverse=reverse)
        order_rows = [row for _, row in numeric] + blanks

        self._reorder_rows(order_rows)

    def _reorder_rows(self, row_order: list[int]) -> None:
        """按目标顺序重排行（takeRow/appendRow 就地搬，避免序列化再重建）。
        **必须从尾部取**（再 reverse 回原序）：``takeRow(0)`` 每次都要把剩下的行
        ``sectionClicked`` 槽里（整张表冻住）；从尾部取是 22 ms。
        """
        row_count = self._model.rowCount()
        if row_count <= 1:
            return

        rows = []
        self._model.blockSignals(True)
        try:
            while self._model.rowCount() > 0:
                rows.append(self._model.takeRow(self._model.rowCount() - 1))
            rows.reverse()  # 尾部取出来是倒序，转回原始下标顺序

            for original_row in row_order:
                self._model.appendRow(rows[original_row])
        finally:
            self._model.blockSignals(False)
        self._model.layoutChanged.emit()

    def setSortingEnabled(self, enabled: bool) -> None:
        self._sorting_enabled = enabled
        self.horizontalHeader().setSortIndicatorShown(enabled)
        if not enabled:
            self.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
            self._current_sort_column = -1

    def isSortingEnabled(self) -> bool:
        return self._sorting_enabled

    def setColumnAlignment(self, column: int, alignment: Qt.AlignmentFlag) -> None:
        """设置该列文本对齐（会补上垂直居中；默认全部居中）。"""
        full_alignment = alignment | Qt.AlignmentFlag.AlignVCenter
        self._columnAlignments[column] = full_alignment
        for row in range(self._model.rowCount()):
            item = self._model.item(row, column)
            if item:
                item.setTextAlignment(full_alignment)

    def setRowCount(self, rows: int) -> None:
        self._model.setRowCount(rows)

    def setColumnCount(self, cols: int) -> None:
        self._model.setColumnCount(cols)

    def setColumnWidth(self, column: int, width: int) -> None:
        """设置列宽并缓存（``setColumnWidths`` 的单列版）。"""
        self.setColumnWidths({column: width})

    def setColumnWidths(self, widths: dict[int | str, int]) -> None:
        """批量设置列宽；键可以是列索引或表头名称（字符串键搜全部列）。"""
        # **宽度必须自己取整**：`setColumnWidth` 的 C++ 签名是 int，PyQt6 不做隐式
        # 转换，宿主传浮点时期待的是取整而不是 TypeError（inf/nan 同理）
        safe = {key: _safe_width(width) for key, width in widths.items()}
        self._columnWidths.update(safe)
        for key, width in safe.items():
            col = self._resolve_column(key)
            if col is not None:
                super().setColumnWidth(col, width)

    def setTableData(
        self,
        data: list[list[Any]] | dict[str, Iterable[Any]],
        center_columns: Optional[set[int]] = None,
        show_row_index: bool = False,
        row_index_start: int = 1,
    ) -> None:
        """同步填充表格数据。
        *data* 支持两种格式：列表（首元素为表头，其余为行数据）或字典（列名 →
        该列可迭代对象，各列长度应一致）。默认全部居中对齐，用
        """
        if not data:
            return

        # **必须取消在途的 setTableDataAsync**：``on_finished`` 的守卫是
        # ``thread is self._load_thread``，同步路径从不碰它，于是旧线程回调
        # 照常执行，把刚同步填进去的数据顶掉且全程无报错
        if self._load_thread is not None:
            self._retire_thread(self._load_thread)
            self._load_thread = None

        if isinstance(data, dict):
            headers = list(data.keys())
            col_count = len(headers)
            if col_count == 0:
                return
            col_values = [list(data[h]) for h in headers]
            row_count = len(col_values[0])
            if any(len(col) != row_count for col in col_values[1:]):
                raise ValueError("setTableData: 字典格式下所有列的数据长度必须一致")
            rows = [
                [col_values[col_idx][row_idx] for col_idx in range(col_count)]
                for row_idx in range(row_count)
            ]
        else:
            headers = data[0]
            rows = data[1:]

        # 必须 try/finally：任何一步抛异常（某个 __str__ 抛错、表头不是 str…）
        # 都会把模型永久 blockSignals(True)，此后视图再也不更新。
        # setTableDataAsync 的 _on_finished 已经是这么写的。
        self._model.blockSignals(True)
        try:
            self.setHorizontalHeaderLabels(headers)
            self.setColumnCount(len(headers))

            # 先清除旧行，避免 setItem 逐个 delete 旧 item 的性能退化
            old_count = self._model.rowCount()
            if old_count > 0:
                self._model.removeRows(0, old_count)
            self._model.setRowCount(len(rows))

            vh = self.verticalHeader()
            if show_row_index:
                if vh:
                    vh.setHidden(False)
                self.setVerticalHeaderLabels(
                    [str(row_index_start + i) for i in range(len(rows))]
                )
            elif vh:
                # 若上一批数据用 show_row_index=True 填过表，行号会留在新数据旁边
                vh.setHidden(True)
                self.setVerticalHeaderLabels([])

            if show_row_index and vh:
                vh.resizeSections(QHeaderView.ResizeMode.ResizeToContents)

            for row_idx, row_data in enumerate(rows):
                for col_idx, cell_data in enumerate(row_data):
                    item = QStandardItem(str(cell_data))
                    if center_columns and col_idx in center_columns:
                        item.setTextAlignment(
                            Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
                        )
                    elif col_idx in self._columnAlignments:
                        item.setTextAlignment(self._columnAlignments[col_idx])
                    else:
                        item.setTextAlignment(
                            Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
                        )
                    self._model.setItem(row_idx, col_idx, item)
        finally:
            self._model.blockSignals(False)
        self._model.layoutChanged.emit()

    def setTableDataAsync(
        self,
        data: list[list[Any]],
        show_row_index: bool = False,
        row_index_start: int = 1,
        callback: Optional[Callable[[], None]] = None,
    ) -> None:
        """在后台线程中异步填充表格数据。
        表头立即设置，行数据在后台加载并应用；上次加载仍在跑时再次调用会取消并
        替换旧线程。``row_index_start`` 用于分页场景传全局偏移，
        """
        if not data:
            return

        if self._load_thread is not None:
            self._retire_thread(self._load_thread)
            self._load_thread = None

        headers = data[0]
        rows = data[1:]
        self.setHorizontalHeaderLabels(headers)
        self.setColumnCount(len(headers))

        thread = _LoadThread(rows)

        def on_finished(rows_data: list[list[Any]]) -> None:
            # 仅当发起本次加载的线程仍是当前线程时应用数据，
            # 排队的旧回调不会覆盖新数据。
            if thread is not self._load_thread or thread._isCanceled:
                return
            self._model.blockSignals(True)
            try:
                self.setRowCount(len(rows_data))
                for row_idx, row_data in enumerate(rows_data):
                    for col_idx, cell_data in enumerate(row_data):
                        item = QStandardItem(str(cell_data))
                        if col_idx in self._columnAlignments:
                            item.setTextAlignment(self._columnAlignments[col_idx])
                        else:
                            item.setTextAlignment(
                                Qt.AlignmentFlag.AlignCenter
                                | Qt.AlignmentFlag.AlignVCenter
                            )
                        self._model.setItem(row_idx, col_idx, item)
            finally:
                self._model.blockSignals(False)
            self._model.layoutChanged.emit()
            if show_row_index:
                vh = self.verticalHeader()
                if vh:
                    vh.setHidden(False)
                self.setVerticalHeaderLabels(
                    [str(row_index_start + i) for i in range(len(rows_data))]
                )
                vh.resizeSections(QHeaderView.ResizeMode.ResizeToContents)
            if callback is not None:
                callback()

        self._load_thread = thread
        safe_connect(
            self._load_thread,
            "finished",
            on_finished,
            "table.async_finished",
            receiver=self,
        )
        self._isLoadThreadConnected = True
        self._load_thread.start()

    def setHorizontalHeaderLabels(self, labels: list[str]) -> None:
        self._model.setHorizontalHeaderLabels(labels)

    def setVerticalHeaderLabels(self, labels: list[str]) -> None:
        self._model.setVerticalHeaderLabels(labels)

    def setItem(
        self, row: int, col: int, item: Union[QStandardItem, Any], center: bool = False
    ) -> None:
        """非 ``QStandardItem`` 的值会被 ``str()`` 包装。"""
        if not isinstance(item, QStandardItem):
            item = QStandardItem(str(item))
        if center:
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self._model.setItem(row, col, item)

    def item(self, row: int, col: int) -> Optional[QStandardItem]:
        return self._model.item(row, col)

    def setCellWidget(self, row: int, col: int, widget: QWidget) -> None:
        index = self._model.index(row, col)
        self.setIndexWidget(index, widget)

    def cellWidget(self, row: int, col: int) -> Optional[QWidget]:
        index = self._model.index(row, col)
        return self.indexWidget(index)

    def setItemText(self, row: int, col: int, text: str) -> None:
        self.setItem(row, col, QStandardItem(text))

    def setItemAlignment(self, row: int, col: int, alignment: Qt.AlignmentFlag) -> None:
        item = self.item(row, col)
        if item:
            item.setTextAlignment(alignment)

    def setItemFont(self, row: int, col: int, font: QFont) -> None:
        item = self.item(row, col)
        if item:
            item.setFont(font)

    def setItemForeground(self, row: int, col: int, color: QColor) -> None:
        item = self.item(row, col)
        if item:
            item.setForeground(color)

    def setItemBackground(self, row: int, col: int, color: QColor) -> None:
        item = self.item(row, col)
        if item:
            item.setBackground(color)

    def setItemIcon(self, row: int, col: int, icon: QIcon) -> None:
        item = self.item(row, col)
        if item:
            item.setIcon(icon)

    def setItemToolTip(self, row: int, col: int, toolTip: str) -> None:
        item = self.item(row, col)
        if item:
            item.setData(str(toolTip or ""), _CELL_TOOLTIP_ROLE)

    def setItemCheckable(self, row: int, col: int, checkable: bool) -> None:
        item = self.item(row, col)
        if item:
            item.setCheckable(checkable)

    def setItemEditable(self, row: int, col: int, editable: bool) -> None:
        item = self.item(row, col)
        if item:
            flags = item.flags()
            if editable:
                flags |= Qt.ItemFlag.ItemIsEditable
            else:
                flags &= ~Qt.ItemFlag.ItemIsEditable
            item.setFlags(flags)

    def insertRow(self, row: int, items: Optional[list[Any]] = None) -> None:
        if items is None:
            self._model.insertRow(row)
        else:
            self._model.insertRow(row, [QStandardItem(str(item)) for item in items])

    def removeRow(self, row: int) -> None:
        self._model.removeRow(row)

    def clear(self) -> None:
        self._model.clear()

    def clearContents(self) -> None:
        """移除所有数据行，保留表头。"""
        self._model.removeRows(0, self._model.rowCount())

    def rowCount(self) -> int:
        return self._model.rowCount()

    def columnCount(self) -> int:
        return self._model.columnCount()

    def model(self) -> QStandardItemModel:
        return self._model

    def setRowBackground(self, row: int, color: QColor) -> None:
        """经自定义代理给整行上底色。"""
        self._row_color_delegate.setRowColor(row, color)
        vp = self.viewport()
        if vp:
            vp.update()

    def clearRowBackgrounds(self) -> None:
        self._row_color_delegate.clearAllColors()
        vp = self.viewport()
        if vp:
            vp.update()

    def deleteLater(self) -> None:
        """清理加载线程，断开信号连接，调度自身删除。"""
        if self._load_thread is not None:
            self._retire_thread(self._load_thread)
            self._load_thread = None
        slot = getattr(self, "_tableViewShowSlot", None)
        if slot is not None:
            try:
                self.tableViewShow.disconnect(slot)
            except (TypeError, RuntimeError):
                pass
            self._tableViewShowSlot = None  # 幂等：deleteLater 可能被调用两次
        hh = self.horizontalHeader()
        if hh:
            slot = getattr(self, "_headerClickedSlot", None)
            if slot is not None:
                try:
                    hh.sectionClicked.disconnect(slot)
                except (TypeError, RuntimeError):
                    pass
                self._headerClickedSlot = None  # 幂等：deleteLater 可能被调用两次
        super().deleteLater()

    def columnName(self, column: int) -> Optional[str]:
        header_item = self._model.horizontalHeaderItem(column)
        return header_item.text() if header_item else None
