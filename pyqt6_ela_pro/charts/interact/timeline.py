"""时间轴组件。（``pyqt6_ela_pro.charts`` 内部模块）。"""

from __future__ import annotations


from PyQt6.QtCore import QObject, QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import (
    QColor,
    QFontMetricsF,
    QPainter,
    QPainterPath,
    QPen,
)

from ..._motion import start_idle_loop
from .._tokens import T
from .._utils import clamp as _clamp
from .._utils import merged_text_style, text_italic, text_weight
from .._utils import to_float as _to_float
from .._utils import parse_color
from ..axes import chartFont


class ChartTimeline(QObject):
    """图表时间轴：底部轴（节点圆点 + 标签）+ 播放 / 暂停按钮。

    option::

        "timeline": {"data": ["2024", "2025", "2026"], "currentIndex": 0,
                     "autoPlay": False, "playInterval": 1500}
        "baseOption": {基础 option}          # 顶层（可选）
        "options": [帧0 option, 帧1 option, ...]   # 顶层

    切换帧：``goto(i)`` → ``baseOption`` 深合并 ``options[i]`` 后
    ``setOption(..., notMerge=True)``（保留过渡动画与时间轴结构）。
    当前帧下标与播放状态挂在 chart 上（``_timeline_index`` /
    ``_timeline_playing``），重建组件后状态不丢；重建时旧 QTimer 会被
    停止并删除，不会累积。
    """

    optionKey = "timeline"
    #: 只支持单实例：数组写法取第一个 dict（见 ``_utils.single_option``）
    singleOption = True

    #: 底部条带高度
    BAND_H = 44.0

    def __init__(self, chart, opt):
        super().__init__()
        self.chart = chart
        self.opt = dict(opt or {})
        self.labels = [str(d) for d in (self.opt.get("data") or [])]
        if "currentIndex" in self.opt:
            current = int(_to_float(self.opt.get("currentIndex"), 0) or 0)
        else:
            current = int(getattr(chart, "_timeline_index", 0) or 0)
        self.current = _clamp(current, 0, max(0, len(self.labels) - 1))
        chart._timeline_index = self.current
        playing = getattr(chart, "_timeline_playing", None)
        if playing is None:
            playing = bool(self.opt.get("autoPlay", False))
        self._playing = bool(playing)
        chart._timeline_playing = self._playing
        # 定时器（父对象 chart；重建时清理旧实例防累积）
        prev = getattr(chart, "_timeline_timer", None)
        if prev is not None:
            try:
                prev.stop()
                prev.deleteLater()
            except Exception:
                pass
        self._timer = QTimer(chart)
        play_interval_ms = int(_to_float(self.opt.get("playInterval"), 1500) or 1500)
        self._timer.setInterval(play_interval_ms)
        self._timer.timeout.connect(self._advance)
        chart._timeline_timer = self._timer
        if self._playing:
            # 持续动效：Reduced/Disabled 下 timeline 不自动推进（当前帧照常显示，
            # 用户仍可 goto / 点播放按钮手动切帧）。
            start_idle_loop(self._timer, play_interval_ms)
        self._band = QRectF()
        self._play_rect = QRectF()
        self._node_pts = []  # [QPointF]

    def dispose(self) -> None:
        """停表并从 chart 上解挂（``core._rebuild`` 丢弃旧组件时调用）。

        必须连 ``deleteLater()`` 一起做：定时器的 parent 是 chart，光 ``stop()``
        会让它变成一个挂在 chart 上的停摆 QObject —— 每次 ``setOption`` 泄一个。
        注意 ``goto()`` 是从本组件的 ``_advance``（定时器回调）里进来的，此时
        ``_rebuild`` 会 dispose 到自己 —— ``deleteLater`` 是延迟投递，qt 派发完
        当前事件才落地，所以不会在发射过程中析构。
        """
        if getattr(self.chart, "_timeline_timer", None) is self._timer:
            self.chart._timeline_timer = None
        try:
            self._timer.stop()
            self._timer.deleteLater()
        except Exception:
            pass

    # -- 帧切换 --------------------------------------------------------------
    def goto(self, index: int) -> None:
        """切换到第 index 帧（经 chart 刷新：``baseOption`` 深合并 ``options[i]``）。"""
        n = max(1, len(self.labels))
        index = int(index) % n
        self.current = index
        self.chart._timeline_index = index
        opt = getattr(self.chart, "_option", None)
        if isinstance(opt, dict) and isinstance(opt.get("timeline"), dict):
            # 同步 currentIndex：帧合并时以 timeline.currentIndex 为准
            opt["timeline"]["currentIndex"] = index
        refresh = getattr(self.chart, "_refresh", None)
        if callable(refresh):
            refresh()
        else:
            self.chart.update()
        self.chart.timelineChanged.emit(index)

    def _advance(self) -> None:
        # Qt 定时器回调中抛出的异常会终止进程：整体包裹并停表
        try:
            if self.labels:
                self.goto(self.current + 1)
        except Exception:
            timer = getattr(self, "_timer", None)
            if timer is not None:
                try:
                    timer.stop()
                except Exception:
                    pass

    def togglePlay(self) -> None:
        """播放 / 暂停切换。"""
        self._playing = not self._playing
        self.chart._timeline_playing = self._playing
        if self._playing:
            self._timer.start()
        else:
            self._timer.stop()
        self.chart.update()

    @property
    def playing(self) -> bool:
        return self._playing

    def labelStyle(self) -> dict:
        """时间轴标签样式（``label`` 平铺键优先，``label.textStyle`` 次之，
        未设置的键回退顶层 ``textStyle``）。"""
        raw = self.opt.get("label")
        local = dict(raw) if isinstance(raw, dict) else {}
        nested = local.pop("textStyle", None)
        if isinstance(nested, dict):
            local.update(nested)
        return merged_text_style(self.chart, local)

    def _style(self, key: str, defaults: dict) -> dict:
        """组件子样式（``lineStyle`` / ``checkpointStyle`` / ``controlStyle``）。"""
        style = dict(defaults)
        raw = self.opt.get(key)
        if isinstance(raw, dict):
            style.update(raw)
        return style

    def reserveBottom(self) -> float:
        """底部时间轴条带高度（含间距；无标签时为 0）。"""
        if self.labels:
            return self.BAND_H + 4.0
        return 0.0

    # -- 布局 / 绘制 ---------------------------------------------------------
    def layout(self, rect: QRectF) -> None:
        h = self.BAND_H
        self._band = QRectF(
            rect.left() + 8, rect.bottom() - h - 2, max(60.0, rect.width() - 16), h
        )
        btn = 22.0
        self._play_rect = QRectF(
            self._band.left(), self._band.center().y() - btn / 2, btn, btn
        )
        # 节点均匀分布于按钮右侧区域
        self._node_pts = []
        n = len(self.labels)
        if n:
            x0 = self._play_rect.right() + 24
            x1 = self._band.right() - 16
            cy = self._band.center().y() - 6
            for i in range(n):
                x = x0 if n == 1 else x0 + (x1 - x0) * i / (n - 1)
                self._node_pts.append(QPointF(x, cy))

    def paint(self, p: QPainter, anim_t: float = 1.0) -> None:
        if not self.labels or not self._node_pts:
            return
        p.save()
        style = self.labelStyle()
        label_raw = self.opt.get("label")
        show_label = (
            bool(label_raw.get("show", True)) if isinstance(label_raw, dict) else True
        )
        font = chartFont(
            style.get("fontSize", T("font.xs")),
            text_weight(style.get("fontWeight")),
            style.get("fontFamily"),
            text_italic(style.get("fontStyle")),
        )
        p.setFont(font)
        fm = QFontMetricsF(font)
        line_style = self._style(
            "lineStyle", {"color": T("color.border.strong"), "width": 1.0}
        )
        checkpoint = self._style(
            "checkpointStyle",
            {"color": T("color.primary"), "borderColor": None, "symbolSize": None},
        )
        control = self._style(
            "controlStyle",
            {
                "color": T("color.bg.elevated"),
                "borderColor": T("color.border.strong"),
                "borderWidth": 1.2,
            },
        )
        primary = parse_color(checkpoint.get("color") or T("color.primary"))
        c_line = parse_color(line_style.get("color") or T("color.border.strong"))
        line_w = max(0.5, _to_float(line_style.get("width"), 1.0))
        c_text = parse_color(style.get("color") or T("color.text.secondary"))
        # 轴线
        p.setPen(QPen(c_line, line_w))
        p.drawLine(self._node_pts[0], self._node_pts[-1])
        # 节点 + 标签
        cp_size = _to_float(checkpoint.get("symbolSize"), 0.0)
        cp_border = checkpoint.get("borderColor")
        for i, (pt, label) in enumerate(zip(self._node_pts, self.labels)):
            cur = i == self.current
            p.setPen(
                QPen(
                    parse_color(cp_border)
                    if cur and cp_border
                    else (primary if cur else c_line),
                    1.6,
                )
            )
            p.setBrush(
                primary
                if cur
                else parse_color(control.get("color") or T("color.bg.elevated"))
            )
            r = cp_size / 2 if cur and cp_size else (5.0 if cur else 4.0)
            p.drawEllipse(pt, r, r)
            if show_label:
                p.setPen(primary if cur else c_text)
                p.drawText(
                    QRectF(pt.x() - 40, pt.y() + 8, 80, fm.height()),
                    Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                    label,
                )
        # 播放 / 暂停按钮
        ctrl_border = parse_color(
            control.get("borderColor") or T("color.border.strong")
        )
        p.setPen(QPen(ctrl_border, _to_float(control.get("borderWidth"), 1.2)))
        p.setBrush(parse_color(control.get("color") or T("color.bg.elevated")))
        p.drawEllipse(self._play_rect)
        c = self._play_rect.center()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(T("color.text.secondary")))
        if self._playing:
            # 暂停：双竖条
            p.drawRect(QRectF(c.x() - 5, c.y() - 5, 3.4, 10))
            p.drawRect(QRectF(c.x() + 1.6, c.y() - 5, 3.4, 10))
        else:
            # 播放：三角
            path = QPainterPath()
            path.moveTo(QPointF(c.x() - 3.5, c.y() - 5.5))
            path.lineTo(QPointF(c.x() - 3.5, c.y() + 5.5))
            path.lineTo(QPointF(c.x() + 5.5, c.y()))
            path.closeSubpath()
            p.drawPath(path)
        p.restore()

    # -- 交互 ---------------------------------------------------------------
    def onMousePress(self, pos: QPointF) -> bool:
        if self._play_rect.adjusted(-3, -3, 3, 3).contains(pos):
            self.togglePlay()
            return True
        for i, pt in enumerate(self._node_pts):
            if (pt.x() - pos.x()) ** 2 + (pt.y() - pos.y()) ** 2 <= 100:
                if i != self.current:
                    self.goto(i)
                return True
        return False

    def hitTest(self, pos: QPointF):
        return None
