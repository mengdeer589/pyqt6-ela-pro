"""涟漪散点系列。（``pyqt6_ela_pro.charts`` 内部模块）。"""

from __future__ import annotations


from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import (
    QPainter,
    QPen,
)

from ..._motion import start_idle_loop
from .._utils import to_float as _to_float
from .._utils import with_alpha
from ..axes import GridCoord
from .scatter import ScatterSeriesRenderer


class EffectScatterSeriesRenderer(ScatterSeriesRenderer):
    """涟漪散点：散点 + QTimer 驱动的扩散圆动画。

    option 键：
    - ``rippleEffect``: {``period`` 秒（默认 3）、``scale`` 扩散倍数（默认 2.6）、
      ``brushType``（``"fill"`` 默认 / ``"stroke"``）、``number`` 同时可见环数}；
    - 其余同 scatter（symbolSize / 第三维映射）。

    动画生命周期：QTimer 以 chart 为 parent，随控件销毁；回调经 weakref
    持有渲染器，渲染器被替换（setOption 重建）后回调自动停止并
    deleteLater，不泄漏。仅系列可见时推进（隐藏后定时器暂停、重新显示时
    经 ``_on_visible_changed`` 恢复，不空转）。
    """

    _TICK_MS = 40

    def __init__(self, chart, opt):
        super().__init__(chart, opt)
        self._phase = 0.0
        ripple = self.opt.get("rippleEffect") or {}
        if not isinstance(ripple, dict):
            ripple = {}
        self._period = max(0.2, _to_float(ripple.get("period"), 3.0))
        self._scale = max(1.2, _to_float(ripple.get("scale"), 2.6))
        #: 每点同时可见的涟漪环数（ECharts rippleEffect.number，默认 3）
        self._number = max(1, min(8, int(_to_float(ripple.get("number"), 3))))
        #: 波纹绘制方式：fill（默认）/ stroke（ECharts brushType）
        brush = str(ripple.get("brushType") or "fill").lower()
        self._brush = "stroke" if brush == "stroke" else "fill"
        timer = QTimer(chart)  # parent 挂 ChartWidget，随控件销毁
        timer.setInterval(self._TICK_MS)
        # 绑定方法插槽：不用 lambda（闭包签名 / 引用存活都要自己盯，而槽内异常
        # 在 Qt 回调里就是 0xC0000409 静默终止）
        timer.timeout.connect(self._on_timer)
        # 持续动效：Reduced/Disabled 下不扩散。相位冻结在当前值 —— 点仍在、
        # 只是不扩散，所以不需要摆姿态钩子。
        start_idle_loop(timer, self._TICK_MS)
        self._timer = timer

    def _stop_timer(self) -> None:
        """停止并释放定时器（渲染器被替换 / 图表销毁 / 异常时调用）。"""
        timer = getattr(self, "_timer", None)
        self._timer = None
        if timer is not None:
            try:
                timer.stop()
                timer.deleteLater()
            except Exception:
                pass

    def _on_timer(self) -> None:
        """定时器回调（整体包裹：Qt 回调中的异常会终止进程）。"""
        timer = self._timer
        if timer is None:
            return
        try:
            alive = self in self.chart.seriesRenderers
        except RuntimeError:
            alive = False  # chart 已销毁
        if not alive:
            self._stop_timer()
            return
        if not self.visible:
            if timer.isActive():
                timer.stop()  # 隐藏不空转；重新显示经 _on_visible_changed 恢复
            return
        if not timer.isActive():
            timer.start()
        try:
            self._tick()
        except Exception:
            self._stop_timer()

    def _tick(self):
        """推进涟漪相位并请求重绘（测试可手动调用）。"""
        self._phase = (self._phase + self._TICK_MS / (self._period * 1000.0)) % 1.0
        self.requestSeriesRepaint()

    def stopAnimation(self) -> None:
        """停止涟漪定时器并释放（渲染器不再需要动画时调用，如测试收尾）。

        定时器 parent 为 chart，chart 销毁时自动释放；本方法用于 chart
        仍存活但渲染器不再需要动画的场景，避免活动 QTimer 在事件循环
        处理时对已删除对象发起重绘。
        """
        self._stop_timer()

    def _on_visible_changed(self):
        """显隐变化钩子（core 内部调用）：显示恢复时重启定时器。

        **必须走 ``start_idle_loop`` 而不是裸 ``timer.start()``**：裸 start
        绕过动效策略，于是「Reduced/Disabled 下持续动效停掉」被图例切换
        重新打开 —— 无障碍用户看到涟漪照常扩散。而 ``start_idle_loop`` 是幂等的
        （内部先查 ``isActive()``）、守策略、且无论启不启动都会写 interval。
        """
        if self.visible and self._timer is not None and not self._timer.isActive():
            start_idle_loop(self._timer, self._TICK_MS)

    def paint(self, p: QPainter, anim_t: float) -> None:
        super().paint(p, anim_t)
        if not self._dots:
            return
        p.save()
        coord = self.chart.coordFor(self.opt)
        if isinstance(coord, GridCoord):
            p.setClipRect(coord.plot)
        # 多环涟漪：相位错开（首帧即有可见扩散环），ECharts rippleEffect 语义
        for d in self._dots:
            color = self.itemColor(d["index"])
            opacity = self.itemOpacity(d["index"])
            r0 = max(d["r"], 3.0)
            for k in range(self._number):
                phase = (self._phase + k / self._number) % 1.0
                rr = r0 * (1.0 + phase * (self._scale - 1.0))
                alpha = 140 * (1.0 - phase) * opacity
                if alpha <= 2:
                    continue
                if self._brush == "stroke":
                    p.setPen(QPen(with_alpha(color, int(alpha)), 1.6))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                else:  # fill（ECharts brushType 默认）
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(with_alpha(color, int(alpha * 0.55)))
                p.drawEllipse(d["pt"], rr, rr)
        p.restore()
