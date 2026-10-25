"""视觉映射组件。（``pyqt6_ela_pro.charts`` 内部模块）。"""

from __future__ import annotations


from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QColor,
    QFontMetricsF,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)

from .._tokens import T
from .._utils import clamp as _clamp
from .._utils import merged_text_style, parse_color, text_italic, text_weight
from .._utils import to_float as _to_float
from ..axes import chartFont, formatValue


class VisualMapComponent:
    """连续视觉映射：值 → 颜色，右下 / 底部渐变条 + 两端数值标签。

    option::

        "visualMap": {"min": 0, "max": 100,
                      "inRange": {"colors": ["#EBEFF5", "#3F5E8C"]},
                      "orient": "vertical"|"horizontal"}

    ``mapColor(v)`` 为公共方法：系列（map / heatmap 等）经
    ``chart.components`` 查找本组件调用。colors 缺省为
    primary.subtle → primary（T() 实时取，主题感知）。

    **绑定**：``seriesIndex``（int）或 ``seriesId``（str）把本 visualMap
    限定给某一个系列（ECharts 语义）；两者都不给就是「通用」，任何系列都能用。
    没有绑定语义时，多个 map / heatmap 系列会**全部拿到同一个** visualMap
    （原先是「谁排在前面谁赢」），于是给第二个系列配的独立色带永远不生效。
    """

    optionKey = "visualMap"
    #: 顶层数组要为每个元素各建一个实例（ECharts 的 visualMap 就是数组语义）。
    #: 不声明的话 ``visualMap: [{...}, {...}]`` 会把整个 list 塞进
    #: ``dict(opt or {})`` 抛 ``ValueError``，被 ``_spawn_component`` 吞掉 ——
    #: **一个 visualMap 都建不起来**。
    spawnPerItem = True

    def __init__(self, chart, opt):
        self.chart = chart
        self.opt = dict(opt or {})
        self.min = _to_float(self.opt.get("min"), 0.0) or 0.0
        self.max = _to_float(self.opt.get("max"), 100.0)
        if self.max is None:
            self.max = 100.0
        if self.max <= self.min:
            self.max = self.min + 1.0
        self.orient = (
            "horizontal" if str(self.opt.get("orient")) == "horizontal" else "vertical"
        )
        #: ``type="piecewise"`` 或给了 ``pieces``：分段色块而不是连续渐变
        self._piecewise = (
            str(self.opt.get("type") or "").strip().lower() == "piecewise"
            or isinstance(self.opt.get("pieces"), list)
        )
        self._piece_rects = []  # [(QRectF, label, color)]
        self._bar = QRectF()
        #: 可拖拽把手的当前目标（``None`` / ``"min"`` / ``"max"``）
        self._drag = None
        #: 色带代表的全量范围（``calculable`` 把手在这个区间内滑动；
        #: ``min`` / ``max`` 是当前生效的映射范围，可被拖动收窄）
        self._extent = (self.min, self.max)

    # -- 绑定 ---------------------------------------------------------------
    def bindsTo(self, series_index: int, series_id: str = "") -> bool:
        """本 visualMap 是否服务于给定系列。

        判定顺序（与 ECharts 一致）：显式绑定优先，其次「未绑定的通用
        visualMap」，都不匹配才算不适用。**通用件必须排在显式绑定之后** ——
        反过来的话一个都没绑定的 visualMap 会把所有系列都抢走。
        """
        idx = self.opt.get("seriesIndex")
        sid = self.opt.get("seriesId")
        if isinstance(idx, int) and not isinstance(idx, bool):
            return idx == series_index
        if sid is not None and str(sid):
            return bool(series_id) and str(sid) == str(series_id)
        return True

    @property
    def isGeneric(self) -> bool:
        """未绑定任何系列的通用 visualMap。"""
        idx = self.opt.get("seriesIndex")
        sid = self.opt.get("seriesId")
        if isinstance(idx, int) and not isinstance(idx, bool):
            return False
        return not (sid is not None and str(sid))

    # -- 公共 API ----------------------------------------------------------
    def colors(self) -> list:
        """生效色带（inRange.colors 覆盖；缺省 primary.subtle→primary）。"""
        in_range = self.opt.get("inRange") or {}
        cols = in_range.get("colors") if isinstance(in_range, dict) else None
        if isinstance(cols, list) and len(cols) >= 2:
            return [str(c) for c in cols]
        return [T("color.primary.subtle"), T("color.primary")]

    @property
    def piecewise(self) -> bool:
        """是否分段型（``type: "piecewise"`` / 给了 ``pieces``）。"""
        return bool(self._piecewise)

    def pieces(self) -> list:
        raw = self.opt.get("pieces")
        return (
            [item for item in raw if isinstance(item, dict)]
            if isinstance(raw, list)
            else []
        )

    @staticmethod
    def _piece_contains(piece: dict, value: float) -> bool:
        """分段命中：``value`` / ``min`` / ``max`` / ``gt`` / ``gte`` / ``lt`` / ``lte``。"""
        if "value" in piece:
            return _to_float(piece.get("value"), None) == value
        checks = (
            ("min", lambda bound: value >= bound),
            ("max", lambda bound: value <= bound),
            ("gt", lambda bound: value > bound),
            ("gte", lambda bound: value >= bound),
            ("lt", lambda bound: value < bound),
            ("lte", lambda bound: value <= bound),
        )
        for key, test in checks:
            raw = piece.get(key)
            if raw is None:
                continue
            bound = _to_float(raw, None)
            if bound is None:
                continue
            if not test(bound):
                return False
        return True

    @staticmethod
    def _piece_color(piece: dict) -> str:
        style = piece.get("itemStyle")
        raw = piece.get("color") or (
            style.get("color") if isinstance(style, dict) else None
        )
        return str(raw) if isinstance(raw, str) and raw else T("color.primary")

    @staticmethod
    def _piece_label(piece: dict) -> str:
        label = piece.get("label")
        if label is not None and str(label):
            return str(label)
        if "value" in piece:
            return formatValue(piece.get("value"))
        lo = piece.get("min")
        hi = piece.get("max")
        if lo is not None and hi is not None:
            return f"{formatValue(lo)}~{formatValue(hi)}"
        if lo is not None:
            return f"≥ {formatValue(lo)}"
        if hi is not None:
            return f"≤ {formatValue(hi)}"
        return ""

    def _font(self):
        style = self.textStyle()
        return chartFont(
            style.get("fontSize", T("font.xs")),
            text_weight(style.get("fontWeight")),
            style.get("fontFamily"),
            text_italic(style.get("fontStyle")),
        )

    @property
    def calculable(self) -> bool:
        """是否显示可拖拽把手（``calculable``）。"""
        return bool(self.opt.get("calculable", False))

    def textStyle(self) -> dict:
        """两端文案样式（``textStyle``；未设置的键回退顶层 ``textStyle``）。"""
        return merged_text_style(self.chart, self.opt.get("textStyle"))

    def textPair(self):
        """两端文案 ``(高, 低)``：``text: ["高", "低"]``，缺省为数值。"""
        raw = self.opt.get("text")
        if isinstance(raw, (list, tuple)) and raw:
            hi = raw[0]
            lo = raw[1] if len(raw) > 1 else None
            return (
                formatValue(self.max) if hi is None else str(hi),
                formatValue(self.min) if lo is None else str(lo),
            )
        return formatValue(self.max), formatValue(self.min)

    def _handle_points(self):
        """两个把手的像素位置 ``(min_point, max_point)``。"""
        bar = self._bar
        lo, hi = self._extent
        span = max(1e-9, hi - lo)
        f_lo = _clamp((self.min - lo) / span, 0.0, 1.0)
        f_hi = _clamp((self.max - lo) / span, 0.0, 1.0)
        if self.orient == "vertical":
            return (
                QPointF(bar.center().x(), bar.bottom() - f_lo * bar.height()),
                QPointF(bar.center().x(), bar.bottom() - f_hi * bar.height()),
            )
        return (
            QPointF(bar.left() + f_lo * bar.width(), bar.center().y()),
            QPointF(bar.left() + f_hi * bar.width(), bar.center().y()),
        )

    def _value_at(self, pos: QPointF) -> float:
        """把手位置 → 值（按色带代表的全量范围）。"""
        bar = self._bar
        lo, hi = self._extent
        if self.orient == "vertical":
            frac = (bar.bottom() - pos.y()) / max(1e-9, bar.height())
        else:
            frac = (pos.x() - bar.left()) / max(1e-9, bar.width())
        return lo + _clamp(frac, 0.0, 1.0) * (hi - lo)

    # -- 拖拽把手（calculable） -------------------------------------------
    def onMousePress(self, pos: QPointF) -> bool:
        if not self.calculable or self._bar.isNull():
            return False
        lo_pt, hi_pt = self._handle_points()
        if self.orient == "vertical":
            d_lo, d_hi = abs(pos.y() - lo_pt.y()), abs(pos.y() - hi_pt.y())
        else:
            d_lo, d_hi = abs(pos.x() - lo_pt.x()), abs(pos.x() - hi_pt.x())
        if min(d_lo, d_hi) > 10.0:
            return False
        self._drag = "min" if d_lo <= d_hi else "max"
        return True

    def onMouseMove(self, pos: QPointF) -> bool:
        if self._drag is None or self._bar.isNull():
            return False
        value = self._value_at(pos)
        span = max(1e-9, self._extent[1] - self._extent[0])
        margin = span * 0.001
        if self._drag == "min":
            self.min = min(value, self.max - margin)
        else:
            self.max = max(value, self.min + margin)
        self.chart.update()
        return True

    def onMouseRelease(self, pos: QPointF) -> bool:
        if self._drag is None:
            return False
        self._drag = None
        return True

    def _paint_handles(self, p: QPainter) -> None:
        """把手 + 「超出当前范围」的遮罩。"""
        bar = self._bar
        lo_pt, hi_pt = self._handle_points()
        mask = QColor(T("color.bg.base"))
        mask.setAlpha(150)
        if self.orient == "vertical":
            p.fillRect(
                QRectF(bar.left(), bar.top(), bar.width(), max(0.0, hi_pt.y() - bar.top())),
                mask,
            )
            p.fillRect(
                QRectF(
                    bar.left(),
                    lo_pt.y(),
                    bar.width(),
                    max(0.0, bar.bottom() - lo_pt.y()),
                ),
                mask,
            )
        else:
            p.fillRect(
                QRectF(bar.left(), bar.top(), max(0.0, lo_pt.x() - bar.left()), bar.height()),
                mask,
            )
            p.fillRect(
                QRectF(
                    hi_pt.x(),
                    bar.top(),
                    max(0.0, bar.right() - hi_pt.x()),
                    bar.height(),
                ),
                mask,
            )
        for point, value in ((lo_pt, self.min), (hi_pt, self.max)):
            p.setPen(QPen(QColor(T("color.bg.elevated")), 2))
            p.setBrush(self.mapColor(value))
            p.drawEllipse(point, 5.5, 5.5)

    def reserveRight(self) -> float:
        """右侧需预留的宽度（竖直色带 / 分段色块 + 标签）；横向为 0。"""
        if self.orient == "vertical":
            return 90.0 if self.piecewise else 50.0
        return 0.0

    def reserveBottom(self) -> float:
        """底部需预留的高度（横向色带 / 分段色块 + 标签）；竖直为 0。"""
        if self.orient == "horizontal":
            return 36.0 if self.piecewise else 30.0
        return 0.0

    def mapColor(self, v) -> QColor:
        """值 → 颜色（按 min..max 归一后在色带上分段线性插值）。"""
        fv = _to_float(v, None)
        if fv is None:
            return QColor(T("color.bg.muted"))
        if self.piecewise:
            for piece in self.pieces():
                if self._piece_contains(piece, fv):
                    return parse_color(self._piece_color(piece))
            out = self.opt.get("outOfRange")
            fallback = out.get("color") if isinstance(out, dict) else None
            return parse_color(
                fallback
                if isinstance(fallback, str) and fallback
                else T("color.bg.muted")
            )
        frac = _clamp((fv - self.min) / (self.max - self.min), 0.0, 1.0)
        cols = [parse_color(c) for c in self.colors()]
        if len(cols) == 1:
            return cols[0]
        seg = frac * (len(cols) - 1)
        i = min(int(seg), len(cols) - 2)
        t = seg - i
        a, b = cols[i], cols[i + 1]
        return QColor(
            int(a.red() + (b.red() - a.red()) * t),
            int(a.green() + (b.green() - a.green()) * t),
            int(a.blue() + (b.blue() - a.blue()) * t),
        )

    # -- 布局 / 绘制 ---------------------------------------------------------
    def _layout_pieces(self, rect: QRectF) -> None:
        pieces = self.pieces()
        self._piece_rects = []
        if not pieces:
            return
        if self.orient == "vertical":
            row_h = 18.0
            total = row_h * len(pieces)
            x = rect.right() - 82.0
            y0 = max(rect.top(), rect.bottom() - total - 8.0)
            for index, piece in enumerate(pieces):
                box = QRectF(x, y0 + index * row_h, 12.0, row_h - 3.0)
                self._piece_rects.append(
                    (box, self._piece_label(piece), self._piece_color(piece))
                )
        else:
            cell = min(72.0, max(30.0, rect.width() / len(pieces) - 4.0))
            total = cell * len(pieces)
            x0 = rect.center().x() - total / 2.0
            y = rect.bottom() - 30.0
            for index, piece in enumerate(pieces):
                box = QRectF(x0 + index * cell, y, cell - 2.0, 12.0)
                self._piece_rects.append(
                    (box, self._piece_label(piece), self._piece_color(piece))
                )

    def _paint_pieces(self, p: QPainter) -> None:
        if not self._piece_rects:
            return
        font = self._font()
        p.save()
        p.setFont(font)
        fm = QFontMetricsF(font)
        color = parse_color(self.textStyle().get("color") or T("color.text.secondary"))
        for box, label, piece_color in self._piece_rects:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(parse_color(piece_color))
            p.drawRoundedRect(box, 2, 2)
            p.setPen(color)
            if self.orient == "vertical":
                p.drawText(
                    QRectF(box.right() + 6, box.top() - 2, 64, box.height() + 4),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    label,
                )
            else:
                p.drawText(
                    QRectF(
                        box.left() - 4,
                        box.bottom() + 1,
                        box.width() + 8,
                        fm.height(),
                    ),
                    Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                    label,
                )
        p.restore()

    def layout(self, rect: QRectF) -> None:
        if self.piecewise:
            self._bar = QRectF()
            self._layout_pieces(rect)
            return
        if self.orient == "vertical":
            w, h = 12.0, min(120.0, max(40.0, rect.height() * 0.4))
            # 右侧预留 38px：色带 12 + 右侧数值标签 34（避免标签越界被裁剪）
            x = rect.right() - w - 38
            y = rect.bottom() - h - 12
        else:
            w, h = min(140.0, max(60.0, rect.width() * 0.35)), 12.0
            x = rect.center().x() - w / 2
            # 底部预留 30px：标签在色带上方，整条落在专属条带内
            y = rect.bottom() - h - 4
        self._bar = QRectF(x, y, w, h)

    def paint(self, p: QPainter, anim_t: float = 1.0) -> None:
        if self.piecewise:
            self._paint_pieces(p)
            return
        if self._bar.isNull():
            return
        p.save()
        cols = self.colors()
        if self.orient == "vertical":
            grad = QLinearGradient(self._bar.bottomLeft(), self._bar.topLeft())
        else:
            grad = QLinearGradient(self._bar.topLeft(), self._bar.topRight())
        n = len(cols)
        for i, c in enumerate(cols):
            grad.setColorAt(i / (n - 1) if n > 1 else 0.0, parse_color(c))
        path = QPainterPath()
        path.addRoundedRect(self._bar, 3, 3)
        p.setPen(QPen(QColor(T("color.border")), 1))
        p.setBrush(grad)
        p.drawPath(path)
        # 两端数值 / 自定义文案标签
        style = self.textStyle()
        font = self._font()
        p.setFont(font)
        fm = QFontMetricsF(font)
        p.setPen(parse_color(style.get("color") or T("color.text.secondary")))
        hi, lo = self.textPair()
        if self.calculable:
            self._paint_handles(p)
        if self.orient == "vertical":
            p.drawText(
                QRectF(
                    self._bar.right() + 4,
                    self._bar.top() - fm.height() / 2,
                    34,
                    fm.height(),
                ),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                hi,
            )
            p.drawText(
                QRectF(
                    self._bar.right() + 4,
                    self._bar.bottom() - fm.height() / 2,
                    34,
                    fm.height(),
                ),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                lo,
            )
        else:
            p.drawText(
                QRectF(self._bar.left() - 38, self._bar.top() - 2, 34, fm.height() + 4),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                lo,
            )
            p.drawText(
                QRectF(self._bar.right() + 4, self._bar.top() - 2, 34, fm.height() + 4),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                hi,
            )
        p.restore()

    def hitTest(self, pos: QPointF):
        return None
