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

from .._tokens import (
    T,
)
from .._utils import merged_text_style, parse_color, text_italic, text_weight
from ..axes import (
    chartFont,
)
from ._shared import _anchor_px, _opt_float

if TYPE_CHECKING:
    from .widget import ElaChartWidget


class Title:
    """标题组件（ECharts ``title``）。

    option：``text`` / ``subtext`` / ``left`` / ``top`` / ``right`` / ``bottom`` /
    ``itemGap`` / ``textStyle``（color/fontSize/fontWeight）/
    ``subtextStyle``（color/fontSize）。未设置的外观键回退顶层 ``textStyle``。

    默认占画布顶部条带；指定 ``bottom``（且未指定 ``top``）时改占底部条带，
    ``top`` / ``bottom`` / ``left`` / ``right`` 支持数值 px 或 ``"N%"``。
    """

    def __init__(self, chart: "ElaChartWidget" = None, opt: dict = None):
        self.chart = chart
        self.opt = dict(opt or {})

    def setOption(self, opt: dict) -> None:
        self.opt = dict(opt or {})

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

    def itemGap(self) -> float:
        try:
            return max(0.0, float(self.opt.get("itemGap", 2)))
        except (TypeError, ValueError, OverflowError):
            return 2.0

    def titleFont(self):
        """主标题字体（``textStyle`` 字号 / 字重，含顶层 ``textStyle`` 兜底）。"""
        style = self.textStyle()
        return chartFont(
            _opt_float(style.get("fontSize"), T("font.title.md")),
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
            _opt_float(style.get("fontSize"), T("font.sm")),
            text_weight(style.get("fontWeight", 400), 400),
            style.get("fontFamily"),
            text_italic(style.get("fontStyle")),
        )

    @property
    def atBottom(self) -> bool:
        """是否使用底部条带（指定 bottom 且未指定 top）。"""
        return "bottom" in self.opt and "top" not in self.opt

    def height(self) -> float:
        """标题区总高（无 text 时为 0）。"""
        if not self.text:
            return 0.0
        h = _opt_float(self.textStyle().get("fontSize"), T("font.title.md")) * 1.3 + 6
        if self.subtext:
            h += _opt_float(self.subtextStyle().get("fontSize"), T("font.sm")) * 1.5 + 2
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
        if not self.text or rect.height() <= 0:
            return
        p.save()
        style = self.textStyle()
        sub_style = self.subtextStyle()
        title_font = self.titleFont()
        sub_font = self.subtitleFont()
        fm_t = QFontMetricsF(title_font)
        fm_s = QFontMetricsF(sub_font)
        text_w = fm_t.horizontalAdvance(self.text)
        sub_w = fm_s.horizontalAdvance(self.subtext) if self.subtext else 0.0
        w = max(text_w, sub_w)
        x = self._anchor_x(rect, w)
        gap = self.itemGap()
        y = rect.top() + 2
        p.setFont(title_font)
        p.setPen(parse_color(style.get("color") or T("color.text.primary")))
        p.drawText(
            QRectF(x, y, text_w + 4, fm_t.height()),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self.text,
        )
        if self.subtext:
            y += fm_t.height() + gap
            p.setFont(sub_font)
            p.setPen(parse_color(sub_style.get("color") or T("color.text.secondary")))
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
