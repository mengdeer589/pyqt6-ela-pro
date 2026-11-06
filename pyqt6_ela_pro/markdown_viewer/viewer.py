"""Markdown 查看器：主题自适应、流式追加、代码高亮与轻量公式。

渲染管线、支持语法与流式增量的细节见 ``docs/markdown.md``。"""

from __future__ import annotations

import logging
from typing import Optional

from PyQt6.QtCore import (
    Qt,
    QTimer,
    QUrl,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QTextDocument,
    QTextOption,
)
from PyQt6.QtWidgets import (
    QFrame,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from PyQt6ElaWidgetTools import (
    ElaScrollBar,
)

from .._internal import (
    system_cjk_font_family,
)
from ..math_lite import (
    clear_cache as clear_math_cache,
)
from ..mermaid_support import ElaMermaidRenderer
from ..widget_base import ElaThemeWidget
from .appearance import _MarkdownAppearanceMixin
from .code import (
    _HIGHLIGHT_CACHE_CAP,
    _MarkdownCodeMixin,
    _default_code_font_family,
    _default_latin_code_font_family,
)
from .export import _MarkdownExportMixin
from .interaction import _EXTERNAL_LINK_SCHEMES, _MarkdownInteractionMixin
from .media import _MarkdownMediaMixin
from .mermaid import _MERMAID_PRIORITY_INTERVAL_MS, _MarkdownMermaidMixin
from .paint import _MarkdownPaintMixin
from .preprocess import (
    _DEFAULT_REASONING_LABEL,
    _DEFAULT_REASONING_TAG,
    _MarkdownPreprocessMixin,
)
from .fonts import defaultMarkdownBodyFontFamily
from .render import _MarkdownRenderMixin
from .selection import _MarkdownSelectionMixin
from .stream import _LARGE_RENDER_CHARS, _MarkdownStreamMixin
from .text_browser import _ElaTextBrowser
from .themes import (
    _MD_LAYOUT_DEFAULTS,
    _MD_THEMES,
    _MD_THEME_SYNTAX_KEYS,
    defaultMarkdownTheme,
)

logger = logging.getLogger(__name__)


class ElaMarkdownViewer(
    _MarkdownSelectionMixin,
    _MarkdownAppearanceMixin,
    _MarkdownInteractionMixin,
    _MarkdownRenderMixin,
    _MarkdownPreprocessMixin,
    _MarkdownMediaMixin,
    _MarkdownMermaidMixin,
    _MarkdownStreamMixin,
    _MarkdownPaintMixin,
    _MarkdownCodeMixin,
    _MarkdownExportMixin,
    ElaThemeWidget,
):
    """Markdown 查看器：主题自适应、流式追加、代码高亮、公式与 Mermaid。

    渲染管线、支持语法、嵌入模式与性能开关见 ``docs/markdown.md``。

    :param parent: 父控件
    """

    #: 流式追加收尾（``endStream``）时发射
    streamFinished = pyqtSignal()
    #: 链接被点击时发射（参数为 URL 字符串，含内部 ``#anchor``）
    linkActivated = pyqtSignal(str)
    #: 代码块内容被复制时发射（参数为代码文本）
    codeCopied = pyqtSignal(str)
    #: 公式 LaTeX 源码被复制时发射
    formulaCopied = pyqtSignal(str)
    #: Mermaid 源码被复制时发射
    mermaidCopied = pyqtSignal(str)
    #: 选中内容复制为 Markdown 时发射（参数为 Markdown 源）
    selectionQuoted = pyqtSignal(str)
    #: 图片被点击时发射（参数为解析后的 URL）
    imageClicked = pyqtSignal(str)
    #: 任务列表项被点击切换时发射（参数为序号与勾选状态）
    taskToggled = pyqtSignal(int, bool)
    #: 大文档分块渲染进度（0-100）
    renderingProgress = pyqtSignal(int)
    #: 大文档分块渲染完成
    renderingFinished = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self._border_radius = 0
        #: 宿主显式设置的视口底色（None = 自动：嵌入透明，否则不透明 BasicPress）
        self._viewport_bg: Optional[QColor] = None
        #: 中文系统：主字体缺字形时给字符套单族符号字体（默认开；不改文本）
        self._missing_glyph_fallback = system_cjk_font_family() is not None
        #: 圆角 mask 缓存键 (宽, 高, 半径)；None = 当前无 mask
        self._mask_key: Optional[tuple] = None
        #: 嵌入模式（透明背景 + 隐藏滚动条 + 高度随文档自适应）
        self._embedded = False
        #: 嵌入模式高度附加余量（避免取整误差触发内部滚动）
        self._embedded_extra = 2
        #: 嵌入模式是否裁剪文末空白（最后一段落的下边距不计入高度）
        self._embedded_trim_bottom = False
        #: 原始 Markdown 文本（``markdown()`` 原样返回，避免 toMarkdown 往返丢失）
        self._source = ""
        #: 行内代码文本（解析后按顺序定位并套用代码样式）
        self._inline_codes: list[str] = []
        #: 与 ``_inline_codes`` 一一对应的占位符 token（预处理时顺手生成）
        self._inline_code_tokens: list[str] = []
        #: 围栏代码块内容（预处理时转为占位符，解析后替换）：[(lang, code, closed)]
        self._fenced_blocks: list[tuple[str, str, bool]] = []
        #: Mermaid 代码块源码（与 ``_MERMAID_TOKEN_PREFIX`` 占位符索引对应）
        self._mermaid_blocks: list[str] = []
        #: Mermaid 渲染配置（``None`` 时自动探测 mermaidx）
        self._mermaid_override = None
        self._mermaid_disabled = False
        self._mermaid_renderer: Optional[ElaMermaidRenderer] = None
        #: Mermaid 待渲染任务队列（按视口距离优先，逐个提交给渲染器）
        self._mermaid_jobs: list[dict] = []
        self._mermaid_job_keys: set = set()
        #: 在途 Mermaid 请求数（引擎串行，>0 时不再提交下一个）
        self._mermaid_active = 0
        #: 引擎预热开关（默认关闭；开启后首次渲染不必等待引擎冷启动）
        self._mermaid_prewarm = False
        #: 视口优先级刷新计时器（滚动时节流重算）
        self._mermaid_priority_timer = QTimer(self)
        self._mermaid_priority_timer.setSingleShot(True)
        self._mermaid_priority_timer.setInterval(_MERMAID_PRIORITY_INTERVAL_MS)
        self._mermaid_priority_timer.timeout.connect(self._refresh_mermaid_priorities)
        #: 任务提交计时器（延后一拍，先让文档滚动/贴底逻辑生效再选下一个任务）
        self._mermaid_pump_timer = QTimer(self)
        self._mermaid_pump_timer.setSingleShot(True)
        self._mermaid_pump_timer.setInterval(0)
        self._mermaid_pump_timer.timeout.connect(self._pump_mermaid)
        #: 行内高亮文本（``==text==``，解析后按顺序套用背景色）
        self._mark_texts: list[str] = []
        #: 脚注定义（预处理时抽取到文末）：[(id, text)]
        self._footnote_defs: list[tuple[str, str]] = []
        #: Callout 类型序列（与占位符索引对应）
        self._callout_types: list[str] = []
        #: 任务列表项（预处理时记录）：[(源行号, 是否勾选)]
        self._task_items: list[tuple[int, bool]] = []
        #: 本文档标题列表（解析后收集）：[(level, text, slug)]
        self._headings: list[tuple[int, str, str]] = []
        #: 代码字体族（CJK 安全默认）与纯 ASCII 代码字体族
        self._code_font_family = _default_code_font_family()
        self._code_latin_font_family = _default_latin_code_font_family()
        #: 超长代码折叠行数（0 表示关闭）
        self._code_collapse_lines = 0
        #: 已展开的代码块索引集合
        self._expanded_code_blocks: set[int] = set()
        #: 推理块标签（``None`` 关闭；默认 `` ... ``）
        self._reasoning_tag: Optional[str] = _DEFAULT_REASONING_TAG
        self._reasoning_label = _DEFAULT_REASONING_LABEL
        #: 可折叠块（推理 / ``<details>``）元数据与展开状态
        self._fold_blocks: list[dict] = []
        self._expanded_folds: set[int] = set()
        #: 围栏代码块的源行范围（与 ``_fenced_blocks`` 对应）：[(start, end)]
        self._fenced_source_lines: list[tuple[int, int]] = []
        #: 文档块号 → 源行范围（引用回复用；``None`` = 未构建）。
        #: **懒建**：逐块双指针匹配约 0.45s / 51KB，多数会话不触发引用回复。
        self._block_source_map: Optional[dict] = None
        #: 渲染降级记录：[(类型, 详情)]，全量渲染时重置
        self._render_issues: list[tuple[str, str]] = []
        #: 行号显示开关
        self._line_numbers_enabled = False
        #: 行号字体 metrics 缓存（按代码字体 / 字号 / 主题字体倍率）
        self._line_number_metrics_cache = None
        #: 表格斑马纹开关与列宽（百分比列表；``None`` 表示自动）
        self._table_zebra = False
        #: 宿主显式设置的斑马纹覆盖；None = 跟随主题默认
        self._table_zebra_override: Optional[bool] = None
        self._table_column_widths: Optional[list] = None
        #: markdown 主题名（``setMarkdownTheme`` 切换，按浅 / 深自动取对应变体）
        self._md_theme = defaultMarkdownTheme()
        #: token 颜色覆盖（setCodeTokenColors；对所有主题生效）
        self._token_overrides: dict = {}
        #: 当前生效的 token 调色板（_applyThemeStyle 填充：主题 + 覆盖）
        self._token_palette: dict = {}
        #: 公式占位标记模板（实例唯一，跨实例零碰撞；结尾 q 是终止符）
        self._math_mark = f"elamath{id(self):x}z{{}}q"
        #: 高亮结果缓存 {(lang, code, theme_key): [(text, QColor, bold, italic)]}
        self._highlight_cache: dict = {}
        self._highlight_cache_cap = _HIGHLIGHT_CACHE_CAP
        #: 主题 / 配色族变更时若不可见则只标记，等 showEvent 补渲染（见 _ensure_rendered）
        self._needs_render = False
        # 主题色缓存（_applyThemeStyle 填充）
        self._text_color = QColor()
        self._link_color = QColor()
        self._code_bg = QColor()
        self._code_border = QColor()
        self._code_text = QColor()
        self._is_dark_theme = False
        self._md_layout = _MD_LAYOUT_DEFAULTS
        self._table_border = QColor()
        self._table_stripe_bg = QColor()
        self._table_header_bg = QColor()
        self._base_bg = QColor()
        self._mark_bg = QColor()
        self._muted_color = QColor()
        self._placeholder_color = QColor()
        self._quote_rail_color = QColor()
        self._quote_text_color = QColor()
        self._quote_bg_color = QColor()
        self._heading_rule_color = QColor()
        self._heading_left_color = QColor()
        self._hr_color = QColor()
        self._callout_bg = QColor()
        self._callout_warning_color = QColor()
        self._callout_caution_color = QColor()
        self._search_bg = QColor()
        self._inline_code_bg = QColor()
        self._inline_code_border = QColor()
        self._code_button_hover_bg = QColor()
        self._code_button_press_bg = QColor()
        self._diff_add_bg = QColor()
        self._diff_del_bg = QColor()
        self._diff_hunk_bg = QColor()
        self.setObjectName("ElaMarkdownViewer")

        # 图片 / 占位 / 缩放 / 搜索状态
        self._base_url = QUrl()
        self._remote_images_enabled = False
        self._placeholder = ""
        self._zoom_factor = 1.0
        self._search_selections: list = []
        self._last_search = ""
        #: 内部锚点跳转前的滚动位置栈（供 backToPreviousAnchor 返回）
        self._anchor_back_stack: list[int] = []

        # 代码块悬浮复制按钮
        #: 与 ``_code_buttons_tables`` 按下标对齐；**离屏的项是 ``None``**
        #: （按需创建：几百个代码块的全量渲染不再一次建几百个控件）
        self._code_buttons: list = []
        self._code_buttons_tables: list = []
        self._code_button_rects: list = []
        #: 各代码表首位置的文档偏移（按顺序，供可见带二分；随表列表重建）
        self._code_table_positions: list = []
        #: 当前已物化按钮的下标区间（回收离屏按钮时只扫两端）
        self._code_button_range: tuple = (0, -1)
        #: 按钮控件集合（eventFilter 的归属判断 O(1)，不再对列表做线性 in）
        self._code_button_widgets: set = set()
        #: 当前显示的复制按钮下标（-1 = 无；显隐只动前后两个按钮）
        self._shown_code_button = -1
        #: 图片扫描水位：早于 ``_image_scan_watermark`` 的块已按
        #: ``_image_scan_width`` 的阅读列宽度处理过（宽度变化或整体替换后重置）。
        self._image_scan_width = -1
        self._image_scan_watermark = 0
        #: 本次渲染是否可能产出图片（Markdown 图片语法 / ``<img>`` / Mermaid）。
        #: 为 False 时布局刷新整趟跳过 :meth:`_apply_images` —— 那是一次
        #: 「块 × 片段」的 Python 遍历（235KB 文档 ≈ 16ms），无图片文档纯浪费。
        self._image_candidates = False
        #: 绘制索引（按 ``QTextDocument.revision()`` 懒建）：带装饰的块号集合
        #: （h1/h2、hr、引用）与带行内代码的块 marks。滚动帧命中后只做集合查找，
        #: 不再逐块逐片段读字符格式 —— Win7 上每次跨绑定取值都比桌面机贵一个量级。
        self._paint_index_revision = -1
        self._paint_index_decorations: set = set()
        self._paint_index_inline: dict = {}
        #: 一次绘制内复用 ``_visible_blocks`` 的命中测试（同一帧里装饰层与
        #: 行内代码层都会问一次；Win7 上 ``cursorForPosition`` 是贵操作）。
        self._visible_blocks_key = None
        self._visible_blocks_value = None

        # 流式状态
        self._stream_active = False
        self._stream_source = ""
        self._stream_committed = 0
        self._stream_tail_pos = 0
        #: ``_stable_cut`` 的增量扫描起点（已知在围栏 / 公式块之外，≤ 已提交位置）
        self._stream_cut_from = 0
        self._stream_first_flush = True
        self._stream_capture_at_bottom = True
        self._stick_to_bottom = True
        self._stream_timer = QTimer(self)
        self._stream_timer.setSingleShot(True)
        self._stream_timer.timeout.connect(self._stream_flush)

        # 流式末尾打字光标
        self._caret_visible = False
        self._caret_timer = QTimer(self)
        self._caret_timer.timeout.connect(self._toggle_stream_caret)

        # 大文档分块渲染状态
        self._large_render_chunks: list[str] = []
        self._large_render_index = 0
        # 分块路径的滚动语义（document.clear() 之后 bar 已被夹到 0，必须在
        # 清空前捕获）：与 _render 的三分支策略对齐。
        self._large_render_reset = False
        self._large_render_scroll = (0, 0)
        self._large_render_timer = QTimer(self)
        self._large_render_timer.setSingleShot(True)
        self._large_render_timer.timeout.connect(self._render_large_step)

        self._text_browser = _ElaTextBrowser(self)
        self._text_browser.setFrameShape(QFrame.Shape.NoFrame)
        self._text_browser.setReadOnly(True)
        # 必须为 False：Qt 在 openExternalLinks 为真时会先 openUrl 并直接 return，
        # 不再发 anchorClicked，任务勾选 / 折叠 / 内部锚点全部失效。外部链接自行打开。
        self._open_external_links = True
        # 只有白名单里的 scheme 才会真的交给系统 shell（见 _EXTERNAL_LINK_SCHEMES）
        self._external_link_schemes = _EXTERNAL_LINK_SCHEMES
        self._text_browser.setOpenExternalLinks(False)
        self._text_browser.setWordWrapMode(
            QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere
        )
        self._text_browser.document().setUndoRedoEnabled(False)
        # 不按键也接收 MouseMove，代码块悬停复制按钮依赖此设置
        self._text_browser.viewport().setMouseTracking(True)
        self._text_browser.setVerticalScrollBar(ElaScrollBar(self._text_browser))
        self._text_browser.setHorizontalScrollBar(
            ElaScrollBar(Qt.Orientation.Horizontal, self._text_browser)
        )
        self._text_browser.anchorClicked.connect(self._on_anchor_clicked)
        self._text_browser.imageClicked.connect(self._on_image_clicked)
        self._text_browser.installEventFilter(self)
        self._text_browser.viewport().installEventFilter(self)
        self._text_browser.verticalScrollBar().valueChanged.connect(
            self._on_view_scrolled
        )
        self._text_browser.document().documentLayout().documentSizeChanged.connect(
            self._on_document_size_changed
        )

        base_font = self._text_browser.document().defaultFont()
        self._base_font_family = base_font.family()
        self._base_font_point_size = base_font.pointSizeF()
        if self._base_font_point_size <= 0:
            pixel = base_font.pixelSize()
            self._base_font_point_size = pixel * 0.75 if pixel > 0 else 10.0
        #: 进程默认 / 实例覆盖的正文族（空 = 跟随主题 ``body_font_family``）
        self._body_font_family_default = defaultMarkdownBodyFontFamily()
        self._body_font_family_override = ""

        # 布局刷新（滚动/尺寸变化后重排代码复制按钮与图片宽度）
        self._layout_timer = QTimer(self)
        self._layout_timer.setSingleShot(True)
        self._layout_timer.timeout.connect(self._on_layout_refresh)
        # 被绘制时补齐懒掉的主题重渲染（不在 paintEvent 里改文档）
        self._pending_render_timer = QTimer(self)
        self._pending_render_timer.setSingleShot(True)
        self._pending_render_timer.timeout.connect(self._ensure_rendered)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._text_browser)

        self._applyThemeStyle()

    def setMarkdown(self, text: str) -> None:
        """设置 Markdown 内容（重置流式状态；超长文本自动分块渲染）。"""
        self._stop_stream()
        self._cancel_large_render()
        self._expanded_code_blocks.clear()
        self._expanded_folds.clear()
        text = text or ""
        # 阅读语义（stick=False）：换内容回顶部；同内容重渲保留位置。
        # 聊天语义（stick=True）走 ``_render`` 的贴底判定，不受这个标志影响。
        reset_position = (not self._stick_to_bottom) and (text != self._source)
        self._source = text
        if len(self._source) > _LARGE_RENDER_CHARS:
            self._begin_large_render(reset_position)
        else:
            self._render(reset_position=reset_position)

    def markdown(self) -> str:
        """当前 Markdown 内容（与传入的文本一致）。"""
        return self._source

    def clear(self) -> None:
        """清空内容。"""
        self.setMarkdown("")

    def document(self) -> QTextDocument:
        """返回底层 ``QTextDocument``，便于设置默认字体等高级选项。"""
        return self._text_browser.document()

    def textBrowser(self) -> QTextBrowser:
        """返回底层 ``QTextBrowser``（可访问 ``anchorClicked`` 等信号）。"""
        return self._text_browser

    def setPlaceholderText(self, text: str) -> None:
        """内容为空时的居中占位文本（如"正在生成…"），空字符串关闭。"""
        self._placeholder = text or ""
        self.update()

    def placeholderText(self) -> str:
        """获取占位文本。"""
        return self._placeholder

    def toPlainText(self) -> str:
        """导出当前渲染结果为纯文本。"""
        self._finish_pending_render()
        return self.document().toPlainText()

    def isRendering(self) -> bool:
        """是否正在分块渲染大文档。"""
        return bool(self._large_render_chunks)

    def clearCache(self) -> None:
        """清空代码高亮、公式与 Mermaid 渲染缓存。"""
        self._highlight_cache.clear()
        clear_math_cache()
        if self._mermaid_renderer is not None:
            self._mermaid_renderer.clearCache()

    def setHighlightCacheSize(self, size: int) -> None:
        """代码高亮缓存条数上限（``<= 0`` 时清空并停止缓存）。"""
        self._highlight_cache_cap = max(0, int(size))
        while (
            self._highlight_cache
            and len(self._highlight_cache) > self._highlight_cache_cap
        ):
            self._highlight_cache.pop(next(iter(self._highlight_cache)))

    def highlightCacheSize(self) -> int:
        """获取代码高亮缓存条数上限（0 表示不缓存）。"""
        return self._highlight_cache_cap

    def setCodeBlockCollapseLines(self, lines: int) -> None:
        """超长代码块折叠后的行数（``0`` 关闭折叠）。"""
        self._code_collapse_lines = max(0, int(lines))
        if self._source:
            self._render()

    def codeBlockCollapseLines(self) -> int:
        """获取代码块折叠行数。"""
        return self._code_collapse_lines

    def setLineNumbersEnabled(self, on: bool) -> None:
        """代码块行号显示（默认关闭；绘制层，不进复制 / 搜索 / 导出）。"""
        on = bool(on)
        if on == self._line_numbers_enabled:
            return
        self._line_numbers_enabled = on
        # 刷新代码表索引：首次开关可能早于布局回调，索引为空时绘制层会直接跳过。
        self._sync_code_buttons()
        self._text_browser.viewport().update()

    def lineNumbersEnabled(self) -> bool:
        """是否显示代码块行号。"""
        return self._line_numbers_enabled

    def setCodeTokenColors(self, colors: Optional[dict] = None) -> None:
        """覆盖代码高亮 token 颜色（``None`` 清除覆盖、回到主题自带配色）。
        可用键：``keyword/constant/type/function/class/decorator/builtin/
        attribute/tag/string/number/comment/operator``（未提供的键保留主题默认，
        """
        overrides = {}
        if colors:
            for key, value in colors.items():
                if key in _MD_THEME_SYNTAX_KEYS and isinstance(value, str):
                    overrides[key] = value
        self._token_overrides = overrides
        self._highlight_cache.clear()
        self._applyThemeStyle()

    def codeTokenColors(self) -> dict:
        """获取当前主题 / 模式下的 token 调色板（含覆盖；颜色为 hex 字符串）。"""
        return dict(self._token_palette)

    def setMarkdownTheme(self, name: str) -> bool:
        """切换 markdown 主题（内置 / 已注册），立即重渲染已有内容。
        切换成功（或本来就是该主题）返回 ``True``；未知名称返回 ``False`` 且
        不改动当前主题。
        """
        if name not in _MD_THEMES:
            return False
        if name == self._md_theme:
            return True
        self._md_theme = name
        self._applyThemeStyle()
        return True

    def markdownTheme(self) -> str:
        """当前 markdown 主题名（默认取 :func:`defaultMarkdownTheme`）。"""
        return self._md_theme
