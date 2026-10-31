"""主题河流系列。（``pyqt6_ela_pro.charts`` 内部模块）。"""

from __future__ import annotations


from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QColor,
    QFontMetricsF,
    QPainter,
    QPainterPath,
    QPen,
)

from .._tokens import T
from .._utils import to_float as _to_float
from .._utils import with_alpha
from .._utils import parse_color
from ..axes import chartFont
from ..core import SeriesRenderer
from ._shared import _smooth_path


class ThemeRiverSeriesRenderer(SeriesRenderer):
    """主题河：时间 × 系列的流带图。

    数据：``[[时间, 值, 系列名], ...]``（时间为字符串，ISO 日期可排序）。流带
    平滑、居中基线（各时刻总宽关于绘图区中线对称），自带底部时间轴标签。
    """

    def __init__(self, chart, opt):
        super().__init__(chart, opt)
        self._streams = []  # [dict(name, top=[QPointF], bot=[QPointF], color_idx)]
        self._times = []
        self._matrix = {}  # (name, t_idx) -> value
        self._area = QRectF()

    # -- 数据 -------------------------------------------------------------
    def _parse(self):
        times = []
        names = []
        matrix = {}
        for item in self.data():
            v = item.get("value") if isinstance(item, dict) else item
            if not isinstance(v, (list, tuple)) or len(v) < 3:
                continue
            t, val, name = v[0], _to_float(v[1], None), str(v[2])
            if val is None:
                continue
            t = str(t)
            if t not in times:
                times.append(t)
            if name not in names:
                names.append(name)
            matrix[(name, t)] = matrix.get((name, t), 0.0) + val
        times.sort()
        return times, names, matrix

    # -- 布局 -------------------------------------------------------------
    def layout(self, rect: QRectF) -> None:
        self._streams = []
        self._times = []
        self._matrix = {}
        times, names, matrix = self._parse()
        if not times or not names:
            return
        self._times = times
        self._matrix = matrix
        self._area = QRectF(
            rect.left() + 24,
            rect.top() + 20,
            max(40.0, rect.width() - 48),
            max(30.0, rect.height() - 20 - 30),
        )
        n = len(times)
        xs = [self._area.left() + self._area.width() * (i + 0.5) / n for i in range(n)]
        totals = [sum(matrix.get((name, t), 0.0) for name in names) for t in times]
        max_total = max(totals) if totals else 1.0
        scale = (self._area.height() * 0.9) / max(1e-9, max_total)
        cy = self._area.center().y()
        for k, name in enumerate(names):
            top = []
            bot = []
            for i, t in enumerate(times):
                base_cum = sum(matrix.get((names[j], t), 0.0) for j in range(k))
                v = matrix.get((name, t), 0.0)
                y0 = cy - totals[i] * scale / 2 + base_cum * scale
                y1 = y0 + v * scale
                top.append(QPointF(xs[i], y0))
                bot.append(QPointF(xs[i], y1))
            self._streams.append({"name": name, "top": top, "bot": bot, "color_idx": k})

    # -- 绘制 -------------------------------------------------------------
    def paint(self, p: QPainter, anim_t: float) -> None:
        if not self._streams:
            return
        p.save()
        # 覆盖兜底 grid 轴线背景（跟随图表 backgroundColor）
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self.chart._background_color())
        p.drawRect(
            QRectF(
                self._area.left() - 24,
                self._area.top() - 20,
                self._area.width() + 48,
                self._area.height() + 50,
            )
        )
        palette = self.chart.palette()
        grow = max(0.0, min(1.0, anim_t))
        for s in self._streams:
            color = parse_color(palette[s["color_idx"] % len(palette)])
            top = []
            bot = []
            for a, b in zip(s["top"], s["bot"]):
                mid = (a.y() + b.y()) / 2
                top.append(QPointF(a.x(), mid + (a.y() - mid) * grow))
                bot.append(QPointF(b.x(), mid + (b.y() - mid) * grow))
            if len(top) >= 2:
                path = _smooth_path(top, 0.5)
                bottom_path = _smooth_path(bot, 0.5)
                # 反向拼接下缘
                rev = QPainterPath()
                elems = [
                    bottom_path.elementAt(i) for i in range(bottom_path.elementCount())
                ]
                rev.moveTo(elems[-1].x, elems[-1].y)
                i = len(elems) - 1
                while i >= 3:  # 贝塞尔段逆放（控制点交换）
                    rev.cubicTo(
                        QPointF(elems[i - 1].x, elems[i - 1].y),
                        QPointF(elems[i - 2].x, elems[i - 2].y),
                        QPointF(elems[i - 3].x, elems[i - 3].y),
                    )
                    i -= 3
                path.connectPath(rev)
                path.closeSubpath()
            else:
                path = QPainterPath()
            p.setPen(QPen(with_alpha(color, 200), 1))
            p.setBrush(with_alpha(color, 150))
            if not path.isEmpty():
                p.drawPath(path)
        # 底部时间轴标签（约 5 个均布）
        n = len(self._times)
        font = chartFont(T("font.xs"), None, self.chart.fontFamily())
        p.setFont(font)
        fm = QFontMetricsF(font)
        p.setPen(QColor(T("color.text.secondary")))
        tick_n = min(5, n)
        for k in range(tick_n):
            i = round(k * (n - 1) / max(1, tick_n - 1))
            x = self._area.left() + self._area.width() * (i + 0.5) / n
            p.drawText(
                QRectF(x - 60, self._area.bottom() + 8, 120, fm.height()),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                self._times[i],
            )
        # 流带标签（带端显示系列名）
        label_opt = dict(self.opt.get("label") or {})
        if bool(label_opt.get("show", True)) and n:
            label_font = self.labelFont()
            p.setFont(label_font)
            label_fm = QFontMetricsF(label_font)
            p.setPen(self.labelColor())
            last = n - 1
            for s in self._streams:
                y0 = s["top"][last].y()
                y1 = s["bot"][last].y()
                if y1 - y0 < label_fm.height() * 0.9:
                    continue
                text = (
                    str(label_opt.get("formatter") or "").replace("{b}", s["name"])
                    or s["name"]
                )
                p.drawText(
                    QRectF(
                        self._area.left() + self._area.width() * (last + 0.5) / n - 60,
                        (y0 + y1) / 2 - label_fm.height() / 2,
                        120,
                        label_fm.height(),
                    ),
                    Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                    text,
                )
        p.restore()

    # -- 交互 -------------------------------------------------------------
    def hitTest(self, pos: QPointF):
        if not self._streams or not self._times:
            return None
        n = len(self._times)
        # 最近时间列
        best_i = None
        best_dx = 1e9
        for i in range(n):
            x = self._area.left() + self._area.width() * (i + 0.5) / n
            if abs(pos.x() - x) < best_dx:
                best_dx = abs(pos.x() - x)
                best_i = i
        if best_i is None or best_dx > self._area.width() / n:
            return None
        for s in self._streams:
            y0 = s["top"][best_i].y()
            y1 = s["bot"][best_i].y()
            if min(y0, y1) - 2 <= pos.y() <= max(y0, y1) + 2 and y1 > y0:
                return {
                    "name": s["name"],
                    "value": self._matrix.get((s["name"], self._times[best_i]), 0.0),
                    "series": self.name,
                    "x": self._times[best_i],
                }
        return None
