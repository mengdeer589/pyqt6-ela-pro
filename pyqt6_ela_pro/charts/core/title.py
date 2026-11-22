"""标题组件。（``pyqt6_ela_pro.charts`` 内部模块）。"""

from __future__ import annotations

from typing import TYPE_CHECKING


from PyQt6.QtCore import (
    QRectF,
    Qt,
)
from PyQt6.QtGui import (
    QFontMetricsF,
    QPainter,
)

from .._style import TITLE_ITEM_GAP, TITLE_SIZE, TITLE_SUBTITLE_SIZE
from .._tokens import (
    T,
)
from .._utils import (
    merged_text_style,
    resolve_color_option,
    text_italic,
    text_weight,
)
from ..labels import label_text_size, paint_label, resolve_label_option
from ..axes import chartFont
from ..models import OptionModel
from ._shared import _anchor_px, _opt_float

if TYPE_CHECKING:
    from .widget import ElaChartWidget


class Title:
    """标题组件（ECharts ``title``）。
    默认占画布顶部条带；指定 ``bottom``（且未指定 ``top``）时改占底部条带。
    ``top`` / ``bottom`` / ``left`` / ``right`` 支持数值 px 或 ``"N%"``；未设置
    """

    def __init__(self, chart: "ElaChartWidget" = None, opt: dict = None):
        self.chart = chart
        self.opt = opt if isinstance(opt, OptionModel) else dict(opt or {})
        self._text_rect = QRectF()

    def setOption(self, opt: dict) -> None:
        self.opt = opt if isinstance(opt, OptionModel) else dict(opt or {})

    @property
    def text(self) -> str:
        return str(self.opt.get("text") or "")

    @property
    def subtext(self) -> str:
        return str(self.opt.get("subtext") or "")

    def textStyle(self) -> dict:
        """主标题文字样式（组件级优先，未设置的键回退顶层 ``textStyle``）。"""
        return merged_text_style(self.chart, self.opt.get("textStyle"))

    def subtextStyle(self) -> dict:
        """副标题文字样式（组件级优先，未设置的键回退顶层 ``textStyle``）。"""
        return merged_text_style(self.chart, self.opt.get("subtextStyle"))

    def linkAt(self, pos) -> bool:
        """标题文字命中且配置了 ``link``。"""
        return bool(self.opt.get("link")) and self._text_rect.contains(pos)

    def onMousePress(self, pos) -> bool:
        if not self.linkAt(pos):
            return False
        try:
            from PyQt6.QtCore import QUrl
            from PyQt6.QtGui import QDesktopServices

            QDesktopServices.openUrl(QUrl(str(self.opt.get("link"))))
        except Exception:
            pass
        return True

    def itemGap(self) -> float:
        try:
            return max(0.0, float(self.opt.get("itemGap", TITLE_ITEM_GAP)))
        except (TypeError, ValueError, OverflowError):
            return TITLE_ITEM_GAP

    def titleFont(self):
        """主标题字体（``textStyle`` 字号 / 字重，含顶层 ``textStyle`` 兜底）。"""
        style = self.textStyle()
        return chartFont(
            _opt_float(style.get("fontSize"), TITLE_SIZE),
            text_weight(
                style.get("fontWeight", T("font.weight.semibold")),
                T("font.weight.semibold"),
            ),
            style.get("fontFamily"),
            text_italic(style.get("fontStyle")),
        )

    def subtitleFont(self):
        """副标题字体（``subtextStyle``，未设置的键回退顶层 ``textStyle``）。"""
        style = self.subtextStyle()
        return chartFont(
            _opt_float(style.get("fontSize"), TITLE_SUBTITLE_SIZE),
            text_weight(style.get("fontWeight", 400), 400),
            style.get("fontFamily"),
            text_italic(style.get("fontStyle")),
        )

    @property
    def atBottom(self) -> bool:
        """是否使用底部条带（指定 bottom 且未指定 top）。"""
        return "bottom" in self.opt and "top" not in self.opt

    def height(self) -> float:
        """标题区总高（无 text / show:false 时为 0）。"""
        if self.opt.get("show", True) is False or not self.text:
            return 0.0
        h = _opt_float(self.textStyle().get("fontSize"), TITLE_SIZE) * 1.3 + 6
        if self.subtext:
            h += (
                _opt_float(self.subtextStyle().get("fontSize"), TITLE_SUBTITLE_SIZE)
                * 1.5
                + 2
            )
        return h + 4

    def bandRect(self, width: float, height: float) -> QRectF:
        """标题条带（画布坐标）；无标题返回空矩形。"""
        h = self.height()
        if h <= 0:
            return QRectF()
        w = max(0.0, float(width))
        if self.atBottom:
            offset = _anchor_px(self.opt.get("bottom"), float(height), 0.0)
            return QRectF(0, float(height) - offset - h, w, h)
        offset = _anchor_px(self.opt.get("top"), float(height), 0.0)
        return QRectF(0, offset, w, h)

    def paint(self, p: QPainter, rect: QRectF) -> None:
        """在标题条带 rect 内绘制。"""
        if self.opt.get("show", True) is False or not self.text or rect.height() <= 0:
            return
        p.save()
        style = self.textStyle()
        sub_style = self.subtextStyle()
        raw_style = self.opt.get("textStyle")
        raw_style = raw_style if isinstance(raw_style, dict) else {}
        raw_sub_style = self.opt.get("subtextStyle")
        raw_sub_style = raw_sub_style if isinstance(raw_sub_style, dict) else {}
        title_font = self.titleFont()
        sub_font = self.subtitleFont()
        fm_t = QFontMetricsF(title_font)
        fm_s = QFontMetricsF(sub_font)
        text_w = fm_t.horizontalAdvance(self.text)
        sub_w = fm_s.horizontalAdvance(self.subtext) if self.subtext else 0.0
        title_option = resolve_label_option(raw_style, self.chart)
        title_size = label_text_size(self.text, title_font, title_option)
        text_w = max(text_w, title_size.width())
        w = max(text_w, sub_w)
        x = self._anchor_x(rect, w)
        gap = self.itemGap()
        y = rect.top() + 2
        p.setFont(title_font)
        p.setPen(
            resolve_color_option(
                style.get("color"), self.chart, T("color.text.primary", self.chart)
            )
        )
        self._text_rect = QRectF(x, y, text_w + 4, fm_t.height())
        if title_option.get("rich"):
            paint_label(
                p,
                QRectF(x, y, text_w + 4, fm_t.height()),
                self.text,
                font=title_font,
                color=resolve_color_option(
                    style.get("color"),
                    self.chart,
                    T("color.text.primary", self.chart),
                ),
                option=title_option,
                align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            )
        else:
            p.drawText(
                QRectF(x, y, text_w + 4, fm_t.height()),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                self.text,
            )
        if self.subtext:
            y += fm_t.height() + gap
            p.setFont(sub_font)
            p.setPen(
                resolve_color_option(
                    sub_style.get("color"),
                    self.chart,
                    T("color.text.secondary", self.chart),
                )
            )
            sub_option = resolve_label_option(raw_sub_style, self.chart)
            sub_size = label_text_size(self.subtext, sub_font, sub_option)
            sub_w = max(sub_w, sub_size.width())
            if sub_option.get("rich"):
                paint_label(
                    p,
                    QRectF(x, y, sub_w + 4, fm_s.height()),
                    self.subtext,
                    font=sub_font,
                    color=resolve_color_option(
                        sub_style.get("color"),
                        self.chart,
                        T("color.text.secondary", self.chart),
                    ),
                    option=sub_option,
                    align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                )
            else:
                p.drawText(
                    QRectF(x, y, sub_w + 4, fm_s.height()),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    self.subtext,
                )
        p.restore()

    def _anchor_x(self, rect: QRectF, text_w: float) -> float:
        """水平锚点：``left`` / ``right``（数值 px、"N%" 或 center/right 对齐）。"""
        left = self.opt.get("left")
        right = self.opt.get("right")
        if left is not None:
            if str(left).strip().lower() == "center":
                return rect.center().x() - text_w / 2
            if str(left).strip().lower() == "right":
                return rect.right() - text_w - 8
            return rect.left() + _anchor_px(left, rect.width(), 8.0)
        if right is not None:
            if str(right).strip().lower() == "center":
                return rect.center().x() - text_w / 2
            return rect.right() - _anchor_px(right, rect.width(), 8.0) - text_w
        return rect.left() + 8.0
