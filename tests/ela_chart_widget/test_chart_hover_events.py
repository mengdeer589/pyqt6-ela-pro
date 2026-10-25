"""悬停事件（mouseover / mouseout / mousemove / globalout）与 focus 访问器。"""

from __future__ import annotations

import pytest

from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QColor, QImage, QMouseEvent, QPainter

from pyqt6_ela_pro import ElaChartWidget


def _chart(make, **patch):
    chart = make(ElaChartWidget)
    chart.resize(600, 400)
    option = {
        "animation": False,
        "tooltip": {"trigger": "item"},
        "xAxis": {"type": "category", "data": ["a", "b", "c"]},
        "yAxis": {"type": "value"},
        "series": [
            {"type": "line", "name": "A", "mode": "lines+markers", "data": [1, 2, 3]}
        ],
    }
    option.update(patch)
    chart.setOption(option)
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    return chart


def _move(chart, pos):
    event = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(pos),
        QPointF(chart.mapToGlobal(QPointF(pos).toPoint())),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    chart.mouseMoveEvent(event)


class TestHoverEvents:
    def test_mouseover_and_mouseout(self, qapp, make):
        chart = _chart(make)
        renderer = chart.seriesRenderers[0]
        over, out, move = [], [], []
        chart.on("mouseover", over.append)
        chart.on("mouseout", out.append)
        chart.on("mousemove", move.append)
        _move(chart, renderer._points[1])
        assert over and over[-1]["dataIndex"] == 1
        assert move and move[-1]["type"] == "mousemove"
        _move(chart, QPointF(4, 4))
        assert out and out[-1]["dataIndex"] == 1

    def test_moving_between_points_emits_out_then_over(self, qapp, make):
        chart = _chart(make)
        renderer = chart.seriesRenderers[0]
        seen = []
        chart.on("mouseover", lambda p: seen.append(("over", p["dataIndex"])))
        chart.on("mouseout", lambda p: seen.append(("out", p["dataIndex"])))
        _move(chart, renderer._points[0])
        _move(chart, renderer._points[1])
        assert ("out", 0) in seen
        assert ("over", 1) in seen
        assert seen.index(("out", 0)) < seen.index(("over", 1))

    def test_globalout_on_leave(self, qapp, make):
        chart = _chart(make)
        seen = []
        chart.on("globalout", seen.append)
        chart.leaveEvent(QEvent(QEvent.Type.Leave))
        assert seen and seen[-1]["type"] == "globalout"

    def test_axis_trigger_emits_mouseover(self, qapp, make):
        chart = _chart(
            make,
            tooltip={"trigger": "axis"},
            xAxis={"type": "value"},
            yAxis={"type": "value"},
            series=[{"type": "line", "name": "A", "data": [[0, 1], [10, 2]]}],
        )
        seen = []
        chart.on("mouseover", seen.append)
        coord = chart.primaryCoord()
        px = coord.x_axis.map(5, coord.plot.left(), coord.plot.right())
        _move(chart, QPointF(px, coord.plot.center().y()))
        assert seen and seen[-1]["seriesName"] == "A"


class TestEmphasisFocus:
    def test_focus_and_blur_scope_accessors(self, qapp, make):
        chart = _chart(
            make,
            series=[
                {
                    "type": "line",
                    "name": "A",
                    "data": [1, 2, 3],
                    "emphasis": {"focus": "series", "blurScope": "global"},
                }
            ],
        )
        renderer = chart.seriesRenderers[0]
        assert renderer.emphasisFocus() == "series"
        assert renderer.blurScope() == "global"
        assert renderer.blursOtherItems() is False

    def test_default_focus_is_none(self, qapp, make):
        chart = _chart(make)
        renderer = chart.seriesRenderers[0]
        assert renderer.emphasisFocus() == "none"
        assert renderer.blursOtherItems() is False, (
            "focus='none' 不许淡化其它项：默认淡化不是 ECharts 语义，"
            "密集散点下每移动一次鼠标都要重画全部图元"
        )

    @pytest.mark.parametrize(
        ("focus", "expected"),
        [("none", False), ("self", True), ("series", False)],
        ids=["none", "self", "series"],
    )
    def test_blur_only_when_focus_is_self(self, qapp, make, focus, expected):
        chart = _chart(
            make,
            series=[
                {
                    "type": "line",
                    "name": "A",
                    "data": [1, 2, 3],
                    "emphasis": {"focus": focus},
                }
            ],
        )
        renderer = chart.seriesRenderers[0]
        assert renderer.blursOtherItems() is expected


def _scatter_chart(make, focus=None):
    series = {
        "type": "scatter",
        "name": "样本",
        "symbolSize": 26,
        "data": [[2, 2], [8, 8]],
    }
    if focus is not None:
        series["emphasis"] = {"focus": focus}
    chart = make(ElaChartWidget)
    chart.resize(420, 300)
    chart.setOption(
        {
            "animation": False,
            "tooltip": {"trigger": "item"},
            "xAxis": {"type": "value", "min": 0, "max": 10},
            "yAxis": {"type": "value", "min": 0, "max": 10},
            "series": [series],
        }
    )
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    return chart


def _paint(chart):
    """离屏画一帧（强制绕过系列层缓存，确保用当前 hover 状态重绘）。"""
    image = QImage(
        chart.width(), chart.height(), QImage.Format.Format_ARGB32_Premultiplied
    )
    image.fill(QColor(255, 255, 255))
    painter = QPainter(image)
    try:
        chart.invalidateSeriesLayer()
        chart._paint_content(painter)
    finally:
        painter.end()
    return image


class TestHoverBlurContract:
    """默认 hover 只高亮命中项，**不淡化其它点**（ECharts ``focus='none'``）。

    用户反馈：300 点散点图悬浮时其余点全变暗 —— 视觉噪音大，而且每次移动鼠标
    都要按「hover 命中」重画整层图元；密集数据下纯属浪费。
    """

    @staticmethod
    def _other_point_color(chart, image):
        point = chart.seriesRenderers[0]._dots[1]["pt"]
        return image.pixelColor(round(point.x()), round(point.y()))

    def test_default_hover_keeps_other_points(self, make):
        chart = _scatter_chart(make)
        before = self._other_point_color(chart, _paint(chart))
        renderer = chart.seriesRenderers[0]
        chart._hover = (renderer, {"dataIndex": 0})
        after = self._other_point_color(chart, _paint(chart))
        assert before.name() == after.name(), "默认 focus='none' 不许淡化其它点"

    def test_focus_self_dims_other_points(self, make):
        chart = _scatter_chart(make, focus="self")
        before = self._other_point_color(chart, _paint(chart))
        renderer = chart.seriesRenderers[0]
        chart._hover = (renderer, {"dataIndex": 0})
        after = self._other_point_color(chart, _paint(chart))
        assert before.name() != after.name(), "focus='self' 应淡化其它点"


def _uniform_scatter(make, count=120):
    chart = make(ElaChartWidget)
    chart.resize(420, 300)
    chart.setOption(
        {
            "animation": False,
            "xAxis": {"type": "value", "min": 0, "max": 12},
            "yAxis": {"type": "value", "min": 0, "max": 12},
            "series": [
                {
                    "type": "scatter",
                    "symbolSize": 12,
                    "data": [[1 + i % 10, 1 + i // 10] for i in range(count)],
                }
            ],
        }
    )
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    return chart


class TestHoverFastPathStability:
    def test_hover_pixels_stay_local(self, make):
        """统一尺寸散点：hover 只改命中点附近，其余点与未 hover 帧逐像素一致。

        曾经 hover 会让「位图快路径」切到「逐点矢量绘制」，其余点出现轻微外观
        跳变（气泡 / 涟漪散点最明显）。
        """
        chart = _uniform_scatter(make)
        before = _paint(chart)
        renderer = chart.seriesRenderers[0]
        chart._hover = (renderer, {"dataIndex": 0})
        after = _paint(chart)
        changed = 0
        total = 0
        for y in range(0, before.height(), 2):
            for x in range(0, before.width(), 2):
                total += 1
                if before.pixel(x, y) != after.pixel(x, y):
                    changed += 1
        assert changed / total < 0.01, (
            f"hover 改变了 {changed}/{total} 像素（{changed / total:.2%}），"
            "其余点应保持与未 hover 帧一致"
        )
