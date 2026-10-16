"""
Parquet 表格视图组件，支持分页功能。

基于 ``ElaDataTable`` 扩展，数据来源为 Parquet 文件，
通过 ``polars`` 进行高效读取，按页展示数据。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union, TYPE_CHECKING

from PyQt6.QtCore import Qt, pyqtSignal, QModelIndex
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QWidget, QHBoxLayout
from PyQt6ElaWidgetTools import (
    ElaText,
    eTheme,
    ElaThemeType,
)

from . import ElaThemeWidget
from ._styles import ColorText
from .ela_pagination import ElaPagination
from .table_view import ElaDataTable


if TYPE_CHECKING:
    import polars as pl
else:
    try:
        import polars as pl
    except ImportError:
        pl = None


INFO_BAR_HEIGHT: int = 40
INFO_BAR_SPACING: int = 10
INFO_BAR_LABEL_SPACING: int = 20


def _make_info_label(parent: QWidget, text: str) -> "ColorText":
    """信息栏标签：``ColorText`` + 12px + **PlainText**。

    三个要求各自有代价，少一个都不报错只是「看着不对」：

    * ``ColorText`` 而非 ``ElaText`` —— 后者 ``paintEvent`` 会重置 palette；
    * **必须显式 ``setTextPixelSize``** —— 不设就是 ``ElaText`` 默认的
      28px（整条信息栏比例崩掉）；
    * **必须 ``PlainText``** —— 这些标签显示的列名 / 数值全部来自 parquet
      文件，是彻底不可信的外部数据，而默认 ``AutoText`` 会走
      ``mightBeRichText()``：列名叫 ``<b>x</b>`` 的文件会被真解析成加粗。
    """
    label = ColorText(parent)
    label.setText(text)
    label.setTextPixelSize(12)
    label.setTextFormat(Qt.TextFormat.PlainText)
    return label


class ElaInfoBarWidget(ElaThemeWidget):
    """列信息显示栏，显示当前选中列的统计信息。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._col_name: str = ""
        self._col_index: int = 0
        self._min_val: str = ""
        self._max_val: str = ""
        self._last_val: str = ""
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setFixedHeight(INFO_BAR_HEIGHT)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(INFO_BAR_SPACING)

        # **必须用 ``ColorText`` 而不是裸 ``ElaText``**：``ElaText.paintEvent``
        # 开头会把 palette 重置回主题 ``BasicText``，所以任何「设了但绘制时
        # 被丢掉」的上色方式都无效（实测 5 种语义色一个都不显示）。见
        # ``_apply_colors``。``setTextPixelSize`` 不能省 —— 不设就是
        # ``ElaText`` 默认字号（实测 28px），整条信息栏比例就崩了。
        self._col_label = _make_info_label(self, "列: -")
        self._col_index_label = _make_info_label(self, "第 - 列")
        self._min_label = _make_info_label(self, "最小值: -")
        self._max_label = _make_info_label(self, "最大值: -")
        self._last_label = _make_info_label(self, "最后一行: -")

        layout.addWidget(self._col_label)
        layout.addSpacing(INFO_BAR_LABEL_SPACING)
        layout.addWidget(self._col_index_label)
        layout.addSpacing(INFO_BAR_SPACING)
        layout.addWidget(self._min_label)
        layout.addSpacing(INFO_BAR_SPACING)
        layout.addWidget(self._max_label)
        layout.addSpacing(INFO_BAR_SPACING)
        layout.addWidget(self._last_label)
        layout.addStretch(1)

        self._apply_colors()

    def _apply_colors(self) -> None:
        mode = self._theme_mode

        col_color = eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.BasicDetailsText)
        self._set_label_color(self._col_label, col_color)

        col_index_color = eTheme.getThemeColor(
            mode, ElaThemeType.ThemeColor.PrimaryNormal
        )
        self._set_label_color(self._col_index_label, col_index_color)

        min_color = eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.PrimaryHover)
        self._set_label_color(self._min_label, min_color)

        max_color = eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.StatusDanger)
        self._set_label_color(self._max_label, max_color)

        last_color = eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.PrimaryPress)
        self._set_label_color(self._last_label, last_color)

    @staticmethod
    def _set_label_color(label, color):
        """给标签上色。

        **必须用 ``ColorText.setTextColor``，不能给 ``ElaText`` 硬塞 palette，
        也不能用 ``_styles.setTextColor``**（后者是给普通 ``QLabel`` 用的）。
        ``ElaText.paintEvent`` 开头会把 palette 重置回主题 ``BasicText``，
        所以 ``palette().setColor(...)`` 设的色在绘制时被整个丢掉 —— 实测
        设红与设绿渲染出的 3840 个像素**一个差异都没有**（同批次的 QLabel
        对照组差异 360 像素，证明探针有效）。五种语义色实际全都不显示。

        读回也要用 ``textColor()``（意图色）而不是 ``palette()``：``ColorText``
        是**绘制前**才把 palette 自愈回显式色，绘制之外读到的是陈旧值。
        """
        label.setTextColor(QColor(color))

    def update_info(
        self, col_name: str, col_index: int, min_val: str, max_val: str, last_val: str
    ) -> None:
        """更新列信息显示。

        四个值是**整列**统计（不是当前页），由
        :meth:`ElaParquetTable._compute_column_stats` 同步算出，所以点第一下会付
        一次整列扫描的成本 —— 实测 2,000 万行 22ms / 1 亿行 112ms / 5 亿行 586ms
        （主线程）；同一列再点 0.0ms（按列名缓存）。
        """
        self._col_name = col_name
        self._col_index = col_index
        self._min_val = min_val
        self._max_val = max_val
        self._last_val = last_val

        # **col_name / min_val / max_val / last_val 全部来自 parquet 文件**，
        # 是彻底不可信的外部数据。``ElaText`` 默认 ``AutoText`` 走
        # ``mightBeRichText()``，一个列名叫 ``<b>x</b>`` 的文件会被真解析成
        # 加粗。所以显示外部数据的标签一律显式 ``PlainText``。
        self._col_label.setText(f"列: {col_name}")
        self._col_index_label.setText(f"第 {col_index} 列")
        self._min_label.setText(f"最小值: {min_val}")
        self._max_label.setText(f"最大值: {max_val}")
        self._last_label.setText(f"最后一行: {last_val}")

    def clear_info(self) -> None:
        """清空列信息显示。"""
        self._col_label.setText("列: -")
        self._col_index_label.setText("第 - 列")
        self._min_label.setText("最小值: -")
        self._max_label.setText("最大值: -")
        self._last_label.setText("最后一行: -")

    def _update_bg_color(self, mode: ElaThemeType.ThemeMode) -> None:
        super()._update_bg_color(mode)
        if hasattr(self, "_col_label"):
            self._apply_colors()


class ElaParquetTable(ElaThemeWidget):
    """Parquet 表格视图，支持分页。

    数据源为 Parquet 文件，经 ``polars`` 读取后按页展示；``polars`` 缺失时构造抛
    ``ImportError``。
    """

    pageChanged = pyqtSignal(int, int)
    loadingFinished = pyqtSignal(int)
    #: 读取 parquet 失败（文件被移动 / 截断 / schema 不符 / 网络盘断开）。
    #: ``str`` 是可直接展示给用户的中文说明。
    errorOccurred = pyqtSignal(str)

    #: 读文件失败的兜底文案前缀。``errorOccurred`` 带原文，这里给个统一出处。
    _ERROR_HINT = "读取 Parquet 文件失败"

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        parquet_path: Union[str, Path] = "",
        page_size: int = 50,
        show_row_index: bool = True,
    ) -> None:
        if pl is None:
            raise ImportError(
                "polars is required for ElaParquetTable. "
                "Please install it with: pip install polars"
            )

        super().__init__(parent)

        self._page_size = max(50, min(page_size, 5000))
        self._current_page = 1
        self._total_rows = 0
        self._show_row_index = show_row_index
        self._parquet_path = ""
        self._lf = None
        self._column_stats_cache: dict[str, dict] = {}

        self._setup_ui()

        if parquet_path:
            self.loadData(parquet_path)

    def _setup_ui(self) -> None:
        self._table = ElaDataTable(self)
        self._info_bar = ElaInfoBarWidget(self)

        self._pager_container = QWidget(self)
        pager_layout = QHBoxLayout(self._pager_container)
        pager_layout.setContentsMargins(15, 0, 15, 0)
        pager_layout.setSpacing(12)

        self._total_label = ElaText(self)
        self._total_label.setTextPixelSize(13)
        self._total_label.setMinimumWidth(180)

        self._pagination = ElaPagination(self)
        self._pagination.setJumperVisible(True)
        self._pagination.currentPageChanged.connect(self.goToPage)

        pager_layout.addWidget(self._total_label)
        pager_layout.addStretch(1)
        pager_layout.addWidget(self._pagination)

        self._main_lay = self.createLayout("v", self)
        self._main_lay.addWidget(self._table, 1)
        self._main_lay.addWidget(self._info_bar, 0)
        self._main_lay.addWidget(self._pager_container, 0)

        self._info_bar.setVisible(False)
        self._pager_container.setVisible(False)

        self._cellClickedSlot = self._on_cell_clicked  # 断连要同一对象（lambda / partial 必须存引用）
        self._table.clicked.connect(self._cellClickedSlot)

        self._loading = False

    def deleteLater(self) -> None:
        """断开信号并清理资源。"""
        slot = getattr(self, '_cellClickedSlot', None)
        if slot is not None:
            try:
                self._table.clicked.disconnect(slot)
            except (TypeError, RuntimeError):
                pass
            self._cellClickedSlot = None  # 幂等：deleteLater 可能被调用两次
        super().deleteLater()

    def _read_guard(self, what: str, func, default=None):
        """跑一次 polars 读操作，失败降级 + 发 ``errorOccurred``。

        **必须有这个兜底。** ``_load_data`` 与 ``_compute_column_stats`` 都是
        直接挂在 Qt 信号槽上的（``currentPageChanged`` / ``clicked``），
        而 PyQt6 里槽内未捕获异常 = 进程直接终止、**无traceback**
        （``0xC0000409``）。文件被移动 / 截断 / schema 不符 / 网络盘断开都
        只在 ``.collect()`` 时才暴露，构造时完全看不出来 ——
        实测路径：加载成功后 ``os.remove(path)`` 再 ``goToPage(2)``。

        :param what: 出错时给用户看的一句话（如「加载第 2 页」）
        :param func: 无参可调用，出错时其返回值作废
        :param default: 失败时的返回值
        """
        try:
            return func()
        except Exception as exc:
            self.errorOccurred.emit(f"{self._ERROR_HINT}（{what}）：{exc}")
            return default

    def _load_data(self) -> None:
        if self._lf is None:
            return

        def read():
            return self._lf.slice(
                (self._current_page - 1) * self._page_size, self._page_size
            ).collect()

        df = self._read_guard(f"加载第 {self._current_page} 页", read)
        if df is None:
            return
        headers = df.columns
        rows = df.rows()
        data = [headers] + [list(r) for r in rows]
        row_index_start = (self._current_page - 1) * self._page_size + 1
        self._table.setTableData(
            data, show_row_index=self._show_row_index, row_index_start=row_index_start
        )

        total_cols = len(headers)
        total_pages = max(
            1, (self._total_rows + self._page_size - 1) // self._page_size
        )
        self._total_label.setText(f"共 {self._total_rows} 行 × {total_cols} 列")
        self._pagination.setTotalPages(total_pages)
        self._pagination.setCurrentPage(self._current_page)
        self._info_bar.setVisible(True)
        self._pager_container.setVisible(total_pages > 1)

        self.loadingFinished.emit(self._total_rows)

    def _on_cell_clicked(self, index: QModelIndex) -> None:
        if self._lf is None:
            return
        header = self._table.model().horizontalHeaderItem(index.column())
        col_name = header.text() if header else ""
        if not col_name:
            self._info_bar.clear_info()
            return

        col_index = index.column() + 1

        if col_name in self._column_stats_cache:
            stats = self._column_stats_cache[col_name]
        else:
            stats = self._compute_column_stats(col_name)
            if stats:
                self._column_stats_cache[col_name] = stats

        if stats:
            self._info_bar.update_info(
                col_name, col_index, stats["min"], stats["max"], stats["last"]
            )
        else:
            self._info_bar.clear_info()

    def _compute_column_stats(self, column_name: str) -> Optional[dict]:
        schema = self._read_guard(
            f"读取 {column_name} 列的 schema", self._lf.collect_schema
        )
        if schema is None:
            return None

        if column_name not in schema:
            return None

        dtype = schema[column_name]
        numeric_types = (
            pl.Int64,
            pl.Int32,
            pl.Int16,
            pl.Int8,
            pl.UInt64,
            pl.UInt32,
            pl.UInt16,
            pl.UInt8,
            pl.Float64,
            pl.Float32,
        )
        if not isinstance(dtype, numeric_types):
            return None

        def read():
            # **这里刻意不切片**：统计口径是「整列」而 ``_load_data`` 的分页
            # 口径是「当前页」，两者共用 ``self._lf``。这是**实测过的取舍**，
            # 不是疏忽（4 列 Int64/Float64，本机 windows，2026-10）：
            #
            #   行数        文件        本列 min+max+last    loadData   翻页
            #   2,000 万    284 MiB22.6 ms     3.9 ms   1.4 ms
            #   1 亿        1.45 GiB   112 ms        4.8 ms   1.5 ms
            #   5 亿        7.71 GiB   586 ms        9.3 ms   1.6 ms
            #
            # 即成本**严格随行数线性增长**（真扫描，不是查footer），且
            # ``_on_cell_clicked`` 是 ``clicked`` 槽 —— 主线程会被占住。
            # 三条已确认的事实决定了「不改」是合理选择：
            # ① 成本全部来自 ``min`` / ``max``；``last()`` 白给
            #    （1.4ms -> 1.7ms，与规模无关，polars 把它下推了）；
            # ② polars 1.44 **没有便宜的 footer 统计路径** ——
            #    ``scan_parquet(use_statistics=...)`` 开关对 min/max 毫无差别
            #    （18~25ms），而 ``pl.read_parquet_metadata`` 只返回 Arrow
            #    schema、不暴露 row-group 的 min/max；
            # ③ 成本被 ``_column_stats_cache`` 按列名摊平，**每列只付一次**，
            #    之后点同一列是 0.0ms。
            #
            # 所以显示的值是**精确**的（抽样会让数据工具说谎），代价是一次性
            # 停顿：1 亿行 112ms 属可感知小卡顿，5 亿行 586ms 是真冻结但
            # 7.7 GiB 的 parquet 拿来看表已接近场景边缘。要彻底解决只能把统计
            # 挪到工作线程（设计级改动：线程生命周期 / sip 守卫 / 切文件取消 /
            # 缓存线程安全）。
            return self._lf.select(
                pl.col(column_name).min().alias("min"),
                pl.col(column_name).max().alias("max"),
                pl.col(column_name).last().alias("last"),
            ).collect()

        stats_df = self._read_guard(f"统计 {column_name} 列", read)
        if stats_df is None:
            return None
        return {
            "min": stats_df["min"][0],
            "max": stats_df["max"][0],
            "last": stats_df["last"][0],
        }

    def goToPage(self, page: int) -> None:
        """跳转到指定页码（从 1 起，会夹到合法范围）。"""
        if self._lf is None:
            return
        if page < 1:
            page = 1
        total_pages = max(
            1, (self._total_rows + self._page_size - 1) // self._page_size
        )
        if page > total_pages:
            page = total_pages

        self._current_page = page
        self._load_data()
        self.pageChanged.emit(page, total_pages)

    def nextPage(self) -> None:
        """翻到下一页。"""
        self.goToPage(self._current_page + 1)

    def prevPage(self) -> None:
        """翻到上一页。"""
        self.goToPage(self._current_page - 1)

    def setPageSize(self, page_size: int) -> None:
        """每页记录数（50~5000），变化时重置到第一页。"""
        page_size = max(50, min(page_size, 5000))
        if page_size == self._page_size:
            return
        self._page_size = max(50, min(page_size, 5000))
        self._current_page = 1
        self._load_data()

    def totalRows(self) -> int:
        return self._total_rows

    def currentPage(self) -> int:
        return self._current_page

    def pageSize(self) -> int:
        return self._page_size

    def totalPages(self) -> int:
        return max(1, (self._total_rows + self._page_size - 1) // self._page_size)

    def loadData(self, parquet_path: Union[str, Path]) -> None:
        """加载新的 parquet 文件。

        **先读成功再改状态**：``scan_parquet`` 本身几乎不碰磁盘，真正的
        ``collect()`` 在下一步。原实现先把 ``_lf`` / ``_parquet_path`` 赋上
        再 ``collect()``，于是失败后组件进入「总数是旧的、数据源是新的」的
        不一致态，下一次翻页再抛一次。

        :raises FileNotFoundError: 文件不存在。
        :raises Exception: polars 自身的异常（截断 / 损坏 / schema 不符 / 非 parquet
            → ``ComputeError`` / ``ArrowInvalid`` / ``OSError`` 等），**不只
            ``FileNotFoundError``** —— 宿主只 catch 前者会漏掉损坏文件。
        """
        parquet_path = str(parquet_path)
        if not Path(parquet_path).is_file():
            raise FileNotFoundError(f"Parquet file not found: {parquet_path}")
        lf = pl.scan_parquet(parquet_path)
        total_rows = lf.select(pl.len()).collect().item()  # type: ignore
        # 到这里才算读成功，此刻才替换组件状态
        self._parquet_path = parquet_path
        self._lf = lf
        self._total_rows = int(total_rows)
        self._current_page = 1
        self._column_stats_cache.clear()
        self._info_bar.clear_info()
        self._load_data()
