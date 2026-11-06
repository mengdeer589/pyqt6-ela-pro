"""主题样式 / 视口 / 嵌入模式方法组。"""

from __future__ import annotations

import math
import os
import sys
from typing import Optional

from PyQt6ElaWidgetTools import eTheme, ElaThemeType
from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import (
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPalette,
    QRegion,
    QTextDocument,
)

from .._colors import parse_color
from .._internal import is_deleted, system_cjk_font_family
from .._styles import setTextBaseColor
from .code import (
    _default_code_font_family,
    _default_latin_code_font_family,
    _font_family_available,
)
from .fonts import _normalize_font_family, _warn_once, isFontFamilyAvailable
from .preprocess import _CALLOUT_CAUTION_COLORS, _CALLOUT_WARNING_COLORS
from .themes import _md_layout_spec, _md_theme_spec


_EMBED_MIN_VALID_WIDTH = 8

_EMBED_WIDTH_SLACK = 2

_DEBUG_LAYOUT = os.environ.get("ELACHAT_DEBUG_LAYOUT", "").strip().lower() not in (
    "",
    "0",
    "false",
    "no",
    "off",
)

_SERIF_CJK_FONTS = ("SimSun", "NSimSun")
_SERIF_LATIN_FONTS = ("Georgia", "Cambria", "Times New Roman")
_BODY_FONT_CACHE: dict = {}


def _resolve_body_font_family(token: str, base: str) -> str:
    """把 layout 的字体 token 解析成单个可用字体族（进程级缓存）。

    中文系统优先宋体系，避免 Latin 主字体渲染 CJK 走逐字形 fallback；
    没有 CJK 衬线字体时回退控件默认字体。
    """
    token = (token or "").strip()
    if not token or token == "sans":
        return base
    key = (token, base)
    cached = _BODY_FONT_CACHE.get(key)
    if cached is not None:
        return cached
    if token == "serif":
        candidates = list(_SERIF_CJK_FONTS)
        if system_cjk_font_family() is None:
            candidates.extend(_SERIF_LATIN_FONTS)
    else:
        candidates = [token]
    resolved = base
    for name in candidates:
        if _font_family_available(name):
            resolved = name
            break
    _BODY_FONT_CACHE[key] = resolved
    return resolved


class _MarkdownAppearanceMixin:
    def setZoomFactor(self, factor: float) -> None:
        """缩放系数（相对默认字号，同时影响公式尺寸），夹在 0.25–4.0。"""
        factor = max(0.25, min(4.0, float(factor)))
        if abs(factor - self._zoom_factor) < 1e-6:
            return
        self._zoom_factor = factor
        font = self.document().defaultFont()
        font.setPointSizeF(self._base_font_point_size * factor)
        self.document().setDefaultFont(font)
        if self._source:
            self._render()

    def zoomFactor(self) -> float:
        """获取缩放系数。"""
        return self._zoom_factor

    def zoomIn(self, step: float = 0.1) -> None:
        """放大一级。"""
        self.setZoomFactor(self._zoom_factor + step)

    def zoomOut(self, step: float = 0.1) -> None:
        """缩小一级。"""
        self.setZoomFactor(self._zoom_factor - step)

    def setBodyFontFamily(self, family: str) -> None:
        """设置 Markdown 正文字体族（单族；空字符串恢复主题默认）。

        只影响正文 / 标题，代码块仍走 :meth:`setCodeFontFamily`，公式走
        ``math_lite``。字体不存在时仍保存设置，实际渲染回退到可用字体。
        """
        name = _normalize_font_family(family)
        if name and not isFontFamilyAvailable(name):
            _warn_once(
                "markdown-font:missing",
                f"Markdown 正文字体 {name!r} 未安装，实际渲染将回退到可用字体",
            )
        self._body_font_family_override = name
        self._apply_body_font()
        if self._source:
            if self._is_on_screen():
                self._render()
            else:
                # 隐藏 / 滚出视口：只标记，可见时由 showEvent / 绘制补齐。
                self._needs_render = True
        self.update()

    def bodyFontFamily(self) -> str:
        """当前正文实际使用的字体族（未安装时是回退后的族名）。"""
        return self.document().defaultFont().family()

    def setCodeFontFamily(self, family: str) -> None:
        """代码字体族；空字符串恢复默认（CJK 安全字体 + 纯 ASCII Latin 字体）。"""
        if family:
            self._code_font_family = family
            self._code_latin_font_family = family
        else:
            self._code_font_family = _default_code_font_family()
            self._code_latin_font_family = _default_latin_code_font_family()
        self._highlight_cache.clear()
        self._applyThemeStyle()

    def codeFontFamily(self) -> str:
        """获取 CJK 安全代码字体族。"""
        return self._code_font_family

    def codeLatinFontFamily(self) -> str:
        """获取纯 ASCII 代码字体族（默认 Consolas 等）。"""
        return self._code_latin_font_family

    def setMissingGlyphFallbackEnabled(self, on: bool = True) -> None:
        """主字体缺字形时给字符套单族符号字体（中文系统默认开）。
        只改 ``QTextCharFormat`` 的字体族，**不改文本**（复制 / 导出保真）；
        候选字体见 ``_internal.MISSING_GLYPH_FONT_CANDIDATES``，没有候选
        """
        on = bool(on)
        if on == self._missing_glyph_fallback:
            return
        self._missing_glyph_fallback = on
        if not self._source:
            return
        self._needs_render = True
        if self._is_on_screen():
            self._needs_render = False
            self._render()

    def missingGlyphFallbackEnabled(self) -> bool:
        """是否启用「主字体缺字形 → 单族符号字体」兜底。"""
        return self._missing_glyph_fallback

    def setTableZebra(self, on: bool) -> None:
        """表格斑马纹（数据行奇偶淡底）；显式设置后不再跟随主题默认。"""
        on = bool(on)
        self._table_zebra_override = on
        if on == self._table_zebra:
            return
        self._table_zebra = on
        if self._source:
            self._render()

    def tableZebra(self) -> bool:
        """是否启用表格斑马纹。"""
        return self._table_zebra

    def setTableColumnWidths(self, widths: Optional[list] = None) -> None:
        """按百分比设置表格列宽（``None`` 恢复自动）；数量与表格列数不一致时
        该表忽略设置。
        """
        if widths is None:
            self._table_column_widths = None
        else:
            try:
                values = [float(width) for width in widths]
            except (TypeError, ValueError, OverflowError):
                # ``float(10 ** 400)`` 抛OverflowError 而**不是** ValueError
                # —— 本方法docstring 承诺「数量与列数不一致时忽略设置」，
                # 是一条容错路径，就该把这类输入也容错掉。
                return
            if not values or any(width <= 0 for width in values):
                self._table_column_widths = None
            else:
                self._table_column_widths = values
        if self._source:
            self._render()

    def tableColumnWidths(self) -> Optional[list]:
        """获取当前表格列宽设置（``None`` 表示自动）。"""
        if self._table_column_widths is None:
            return None
        return list(self._table_column_widths)

    def setBorderRadius(self, r: int) -> None:
        self._border_radius = max(0, r)
        # 圆角形态：不透明底色 + 视口圆角 mask（四角由外层自绘背景透出，
        # 与「透明视口」外观一致，但避开 Win7 透明合成慢速路径，见 bug 报告 §4）
        self._apply_viewport_base()
        self.update()

    def borderRadius(self) -> int:
        return self._border_radius

    def setViewportBackground(self, color: Optional[QColor]) -> None:
        """设置文本视口的显式底色（``None`` = 恢复按模式自动）。

        自动策略：非嵌入时用与自绘背景一致的 ``BasicPress`` **不透明**底色
        （外观等价，避开透明视口在部分平台（Win7）上的慢速重绘路径；圆角形态
        配视口圆角 mask 裁出四角）；嵌入模式保持透明、由外层容器提供底色 ——
        宿主应传自己的背景色作不透明底色（如聊天气泡传气泡色）。显式传色时
        一律以该色作不透明视口底色；确实需要严格透出下层时传透明色
        （``QColor(0, 0, 0, 0)``）。
        """
        self._viewport_bg = parse_color(color) if color is not None else None
        self._apply_viewport_base()

    def viewportBackground(self) -> Optional[QColor]:
        """获取宿主显式设置的视口底色（``None`` = 未设置、走自动策略）。"""
        return QColor(self._viewport_bg) if self._viewport_bg is not None else None

    def _apply_viewport_base(self) -> None:
        """按「显式底色 > 嵌入透明 > 不透明 BasicPress」应用视口底色 + 圆角 mask。"""
        if is_deleted(self._text_browser):
            return
        if self._viewport_bg is not None:
            setTextBaseColor(self._text_browser, self._viewport_bg)
        elif self._embedded:
            setTextBaseColor(self._text_browser, None)
        else:
            color = getattr(self, "_base_bg", None)
            if color is None:
                color = eTheme.getThemeColor(
                    self._theme_mode, ElaThemeType.ThemeColor.BasicPress
                )
            setTextBaseColor(self._text_browser, color)
        self._sync_viewport_mask()

    def _apply_body_font(self, document: Optional[QTextDocument] = None) -> None:
        """按当前主题应用正文 / 标题字体族（保留字号与 zoom）。

        优先级：实例覆盖 > 进程默认 > 主题 ``body_font_family`` > 控件默认。
        """
        doc = document if document is not None else self.document()
        layout = getattr(self, "_md_layout", None) or {}
        family = ""
        for candidate in (
            self._body_font_family_override,
            self._body_font_family_default,
        ):
            if candidate and _font_family_available(candidate):
                family = candidate
                break
        if not family:
            family = _resolve_body_font_family(
                layout.get("body_font_family", ""), self._base_font_family
            )
        if not family:
            return
        font = doc.defaultFont()
        current = font.families()
        if font.family() == family and (not current or list(current) == [family]):
            return
        font.setFamilies([family])
        doc.setDefaultFont(font)

    def _content_text_width(self) -> int:
        """正文列有效宽度（用于图片 / Mermaid / 扫描水位）。"""
        viewport_width = self._text_browser.viewport().width()
        layout = getattr(self, "_md_layout", None) or {}
        max_width = int(layout.get("content_max_width", 0) or 0)
        if self._embedded or max_width <= 0:
            return viewport_width
        frame = self.document().rootFrame().frameFormat()
        return max(1, int(viewport_width - frame.leftMargin() - frame.rightMargin()))

    def _apply_content_width(self, document: Optional[QTextDocument] = None) -> None:
        """按 ``content_max_width`` 居中正文列；嵌入模式恢复默认边距。"""
        doc = document if document is not None else self.document()
        try:
            if doc is not self._text_browser.document():
                return
        except RuntimeError:
            return
        margin = doc.documentMargin()
        layout = getattr(self, "_md_layout", None) or {}
        max_width = int(layout.get("content_max_width", 0) or 0)
        viewport_width = self._text_browser.viewport().width()
        if self._embedded or max_width <= 0 or viewport_width <= max_width:
            left = right = margin
        else:
            left = right = max((viewport_width - max_width) / 2.0, margin)
        frame = doc.rootFrame().frameFormat()
        if (
            abs(frame.leftMargin() - left) < 0.5
            and abs(frame.rightMargin() - right) < 0.5
        ):
            return
        frame.setLeftMargin(left)
        frame.setRightMargin(right)
        doc.rootFrame().setFrameFormat(frame)

    def _sync_viewport_mask(self) -> None:
        """圆角形态给文本视口加圆角 ``QRegion`` mask（其它形态清除）。
        底色保持不透明（与自绘圆角背景同色、走快重绘路径），四角被 mask 裁掉
        后透出外层自绘圆角背景 —— 与透明视口外观一致（半径 6 以下多边形近似
        """
        if is_deleted(self._text_browser):
            return
        radius = self._border_radius
        if radius <= 0 or self._embedded:
            self._mask_key = None
            self._text_browser.clearMask()
            return
        size = self._text_browser.size()
        key = (size.width(), size.height(), radius)
        if key == self._mask_key:
            return
        self._mask_key = key
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, size.width(), size.height()), radius, radius)
        polygons = path.toSubpathPolygons()
        if not polygons:
            self._text_browser.clearMask()
            return
        self._text_browser.setMask(QRegion(polygons[0].toPolygon()))

    def setEmbeddedMode(self, on: bool) -> None:
        """嵌入模式：透明背景、隐藏内部滚动条、高度随文档自适应。

        适合把查看器嵌进聊天消息等外层滚动容器：

        - 不再自绘背景（由父容器提供底色）；
        - 两个滚动条始终隐藏，滚轮事件交给外层容器；
        - 文档高度变化（含流式追加）时自动调整控件高度（默认关闭，关闭后恢复原有行为）。
        """
        on = bool(on)
        if on == self._embedded:
            return
        self._embedded = on
        self._apply_viewport_base()
        self._apply_content_width()
        policy = (
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            if on
            else Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._text_browser.setVerticalScrollBarPolicy(policy)
        self._text_browser.setHorizontalScrollBarPolicy(policy)
        self._text_browser.forward_wheel = on
        if on:
            self._sync_embedded_height()
        else:
            self.setMinimumHeight(0)
            self.setMaximumHeight(16777215)
            self.updateGeometry()
        self.update()

    def embeddedMode(self) -> bool:
        """是否处于嵌入模式。"""
        return self._embedded

    def setEmbeddedExtra(self, extra: int) -> None:
        """嵌入模式高度余量（像素，默认 2）：追加到文档高度上，避免取整误差
        触发内部滚动。
        """
        self._embedded_extra = max(0, int(extra))
        self._sync_embedded_height()

    def embeddedExtra(self) -> int:
        """获取嵌入模式高度余量（像素）。"""
        return self._embedded_extra

    def setEmbeddedTrimBottom(self, on: bool) -> None:
        """设置嵌入模式是否裁剪文末空白（默认关闭）。

        开启后，控件高度不再包含文末段落的下边距（Qt Markdown 导入器会给
        每个段落加下边距，最后一个段落的下边距是纯空白），控件底边贴合
        正文内容 —— 聊天消息中「正文 → 工具面板 / 下一步思考」的视觉间距
        因此与其它分段间距一致。表格 / 代码块等非段落结尾按块边界取更小
        值（``min``），不会裁剪内容。
        """
        on = bool(on)
        if on == self._embedded_trim_bottom:
            return
        self._embedded_trim_bottom = on
        self._sync_embedded_height()

    def embeddedTrimBottom(self) -> bool:
        """是否裁剪嵌入模式下的文末空白。"""
        return self._embedded_trim_bottom

    def _sync_embedded_height(self) -> None:
        """嵌入模式下按文档高度更新控件高度（幂等，仅变化时应用）。
        测量值不可信时保留上一次高度：视口过窄 / textWidth 未重排 / 源非空却
        测出 0 高，套用会把控件压成细缝。
        """
        if not self._embedded:
            return
        document = self._text_browser.document()
        margins = self._text_browser.contentsMargins()
        viewport_width = self._text_browser.viewport().width()
        text_width = document.textWidth()
        content = document.size().height()
        if self._embedded_trim_bottom:
            content = min(content, self._embedded_content_bottom(document))
        reliable = (
            viewport_width > _EMBED_MIN_VALID_WIDTH
            and (
                text_width <= 0
                or abs(text_width - viewport_width) <= _EMBED_WIDTH_SLACK
            )
            and (content > 0 or not self._source)
        )
        height = (
            int(math.ceil(max(0.0, content) + margins.top() + margins.bottom()))
            + self._embedded_extra
        )
        height = max(1, height)
        if not reliable:
            self._debug_height_sync(
                "skipped(unreliable)", height, viewport_width, text_width, content
            )
            return
        if self._embedded_trim_bottom:
            # 裁剪后控件高度小于文档高度，内部出现可滚动范围：必须把滚动位置
            # 归零（否则 QTextBrowser 会贴底显示文末边距、并裁掉首行上边距）。
            bar = self._text_browser.verticalScrollBar()
            if bar.value() != 0:
                bar.setValue(0)
        if self.minimumHeight() == height and self.maximumHeight() == height:
            self._debug_height_sync(
                "unchanged", height, viewport_width, text_width, content
            )
            return
        self._debug_height_sync("applied", height, viewport_width, text_width, content)
        self.setFixedHeight(height)

    def _debug_height_sync(
        self,
        action: str,
        height: int,
        viewport_width: int,
        text_width: float,
        content: float,
    ) -> None:
        """嵌入高度同步诊断日志（``ELACHAT_DEBUG_LAYOUT=1`` 时输出到 stderr）。"""
        if not _DEBUG_LAYOUT:
            return
        sys.stderr.write(
            "[ElaMarkdownViewer] height sync %s: height=%d viewportW=%d textW=%.1f"
            " content=%.1f srcLen=%d streaming=%s\n"
            % (
                action,
                height,
                viewport_width,
                text_width,
                content,
                len(self._source),
                self._stream_active,
            )
        )

    @staticmethod
    def _embedded_content_bottom(document: QTextDocument) -> float:
        """文末内容底边（不含最后一段落的下边距与文末文档边距）。

        布局未就绪（流式首帧 / 宽度为 0）时返回文档高度，保持原行为。
        """
        total = document.size().height()
        last = document.lastBlock()
        if not last.isValid():
            return total
        rect = document.documentLayout().blockBoundingRect(last)
        if rect.height() <= 0 or rect.bottom() <= 0:
            return total
        return rect.bottom()

    def _resolve_layout_color(self, source, default: QColor) -> QColor:
        """把 layout 的颜色引用解析成 QColor（语义名 / hex / QColor）。"""
        if isinstance(source, QColor):
            return QColor(source)
        if isinstance(source, str):
            tokens = {
                "accent": self._link_color,
                "heading": self._md_heading_color,
                "text": self._text_color,
                "muted": self._muted_color,
                "border": self._table_border,
                "quote": self._md_quote_color,
                "list": self._md_list_color,
                "code": self._md_code_color,
            }
            token = tokens.get(source)
            if token is not None:
                return QColor(token)
            try:
                return parse_color(source)
            except Exception:  # noqa: BLE001 —— 非法颜色按默认处理
                pass
        return QColor(default)

    def _applyThemeStyle(self, defer_layout: bool = False) -> None:
        """应用主题色（样式表 + 调色板），并重新渲染已有内容。

        ``defer_layout=True`` 时不启动布局刷新定时器（离屏查看器的切主题路径）。
        """
        mode = self._theme_mode
        self._text_color = eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.BasicText)
        self._code_text = self._text_color
        # 表格 / 代码背景：与查看器背景预混合成不透明色
        # （QTextDocument 的 CSS 不支持 alpha 通道，且纯 BasicBaseDeep 在
        # 暗色主题下过亮，代码块与表格色块连片会显得"重"）
        background = eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.BasicPress)
        self._is_dark_theme = background.lightness() < 128
        # 语义配色 / 语法高亮走 markdown 主题注册表（10 套内置）；surface 可选
        # 覆盖页面底色，未覆盖时继续用 eTheme，保证与 Ela 整体协调
        self._md_layout = _md_layout_spec(self._md_theme)
        layout = self._md_layout
        surface = layout["surface"]["dark" if self._is_dark_theme else "light"]
        if surface:
            background = parse_color(surface)
        if self._table_zebra_override is None:
            self._table_zebra = bool(layout["table"]["zebra"])
        variant = _md_theme_spec(self._md_theme)[
            "dark" if self._is_dark_theme else "light"
        ]
        semantic = variant["semantic"]
        self._token_palette = dict(variant["syntax"])
        self._token_palette.update(self._token_overrides)
        self._link_color = parse_color(semantic["link"])
        self._md_heading_color = parse_color(semantic["heading"])
        self._md_strong_color = parse_color(semantic["strong"])
        self._md_emphasis_color = parse_color(semantic["emphasis"])
        self._md_code_color = parse_color(semantic["code"])
        self._md_quote_color = parse_color(semantic["quote"])
        self._md_list_color = parse_color(semantic["list"])
        self._md_mark_color = parse_color(semantic["mark"])
        code_layout = layout["code"]
        table_layout = layout["table"]
        quote_layout = layout["quote"]
        inline_layout = layout["inline_code"]
        self._code_bg = self._blend(
            background, self._text_color, code_layout["background_alpha"]
        )
        self._code_border = self._blend(
            background, self._text_color, code_layout["border_alpha"]
        )
        self._table_border = self._blend(
            background, self._text_color, table_layout["border_alpha"]
        )
        self._table_stripe_bg = self._blend(
            background, self._text_color, 0.05 if self._is_dark_theme else 0.03
        )
        self._table_header_bg = self._blend(
            background, self._text_color, table_layout["header_background_alpha"]
        )
        self._base_bg = parse_color(background)
        self._mark_bg = self._blend(
            background, self._md_mark_color, 0.6 if self._is_dark_theme else 0.72
        )
        self._muted_color = self._blend(background, self._text_color, 0.45)
        self._placeholder_color = self._blend(background, self._text_color, 0.38)
        self._quote_rail_color = self._resolve_layout_color(
            quote_layout["rail_color"], self._muted_color
        )
        self._quote_text_color = self._resolve_layout_color(
            quote_layout["text_color"], self._md_quote_color
        )
        self._quote_bg_color = self._blend(
            background,
            self._resolve_layout_color(
                quote_layout["background_color"], self._link_color
            ),
            quote_layout["background_alpha"],
        )
        self._heading_rule_color = self._resolve_layout_color(
            layout["heading_rule"]["color"], self._table_border
        )
        self._heading_left_color = self._resolve_layout_color(
            layout["heading_rule"]["left_color"], self._link_color
        )
        self._hr_color = self._resolve_layout_color(
            layout["hr"]["color"], self._table_border
        )
        self._callout_bg = self._blend(
            background, self._text_color, 0.06 if self._is_dark_theme else 0.035
        )
        self._callout_warning_color = parse_color(
            _CALLOUT_WARNING_COLORS["dark" if self._is_dark_theme else "light"]
        )
        self._callout_caution_color = parse_color(
            _CALLOUT_CAUTION_COLORS["dark" if self._is_dark_theme else "light"]
        )
        self._search_bg = self._blend(
            background, QColor("#ff922b"), 0.4 if self._is_dark_theme else 0.5
        )
        self._inline_code_bg = self._blend(
            background, self._text_color, inline_layout["background_alpha"]
        )
        self._inline_code_border = (
            self._blend(
                background, self._text_color, 0.12 if self._is_dark_theme else 0.08
            )
            if inline_layout["border"]
            else QColor(self._inline_code_bg)
        )
        self._code_button_hover_bg = self._blend(background, self._text_color, 0.16)
        self._code_button_press_bg = self._blend(background, self._text_color, 0.24)
        self._diff_add_bg = self._blend(
            self._code_bg, QColor("#2da44e"), 0.16 if self._is_dark_theme else 0.12
        )
        self._diff_del_bg = self._blend(
            self._code_bg, QColor("#cf222e"), 0.14 if self._is_dark_theme else 0.1
        )
        self._diff_hunk_bg = self._blend(
            self._code_bg, QColor("#0969da"), 0.12 if self._is_dark_theme else 0.08
        )
        # 刻意**不清** ``_highlight_cache``：它的 key 是 (lang, code, theme_key)，
        # 本来就按主题分键；清掉等于把上一次主题的高亮结果扔掉（反复切换会永远命中
        # 不了缓存）。改字号 / 换配色族走的是另一条会清缓存的路径（base 格式带字体）。

        document = self._text_browser.document()
        document.setDefaultStyleSheet(self._document_css())
        self._apply_body_font(document)
        self._apply_content_width(document)

        palette = self._text_browser.palette()
        palette.setColor(QPalette.ColorRole.Text, self._text_color)
        palette.setColor(QPalette.ColorRole.Link, self._link_color)
        self._text_browser.setPalette(palette)
        self._apply_viewport_base()

        on_screen = self._is_on_screen()
        if self._source:
            if on_screen:
                self._render()
            else:
                # 不在屏幕上时不重建：整篇重解析 + 重高亮在宿主规模下是秒级。
                # 文档文本不变，可见时由 showEvent / 绘制补齐（见 _schedule_pending_render）。
                self._needs_render = True
        self.update()
        if not defer_layout:
            self._layout_timer.start(0)

    def _is_on_screen(self) -> bool:
        """当前是否真的在屏幕上。

        ``isVisible()`` 只表示「自己和祖先都没被 hide」—— 聊天里滚出视口的
        消息仍然是 ``True``，按它判断等于每次切主题都重渲染整段会话（实测
        60 个 4KB 查看器 363ms，而真正在屏幕上的 3 个只要 17ms）。嵌入模式
        用外层滚动区映射出的可见带判断；非嵌入模式看不到内部滚动位置，
        维持原来的可见性判断。
        """
        if not self.isVisible():
            return False
        if not self._embedded:
            return True
        top, bottom = self._visible_band()
        return bottom >= top

    def _onThemeChanged(self, mode: ElaThemeType.ThemeMode) -> None:
        self._theme_mode = mode
        # 离屏查看器不跑布局刷新（图片扫描 / 代码按钮定位 / 嵌入高度）：
        # 切主题时几十条滚出视口的消息不该各付一趟。真正可见时随 _render 补齐。
        self._applyThemeStyle(defer_layout=not self._is_on_screen())

    def paintEvent(self, _event: Optional[QPaintEvent]) -> None:
        """绘制圆角背景（圆角半径为 0 时绘制普通矩形背景）；嵌入模式跳过。"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self._embedded:
            bg_color = getattr(self, "_base_bg", None)
            if bg_color is None:
                bg_color = eTheme.getThemeColor(
                    self._theme_mode, ElaThemeType.ThemeColor.BasicPress
                )
            if self._border_radius > 0:
                path = QPainterPath()
                path.addRoundedRect(
                    QRectF(self.rect()), self._border_radius, self._border_radius
                )
                painter.fillPath(path, bg_color)
            else:
                painter.fillRect(self.rect(), bg_color)
        if self._placeholder and not self._source:
            painter.setPen(self._placeholder_color)
            font = QFont(self.document().defaultFont())
            font.setPointSizeF(max(self._base_font_point_size, 9.0))
            painter.setFont(font)
            painter.drawText(
                self.rect().adjusted(16, 16, -16, -16),
                int(Qt.AlignmentFlag.AlignCenter) | int(Qt.TextFlag.TextWordWrap),
                self._placeholder,
            )
        self._paint_stream_caret(painter)
        painter.end()
