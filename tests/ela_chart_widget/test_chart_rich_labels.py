"""富文本标签 / 背景框 / hideOverlap / markArea 样式回归。"""

from __future__ import annotations

from PyQt6.QtCore import QRectF
from PyQt6.QtGui import QImage, QPainter

from pyqt6_ela_pro import ElaChartWidget
from pyqt6_ela_pro.charts.labels import label_text_size, parse_rich_text


def _bar_chart(make, label=None, label_layout=None) -> ElaChartWidget:
    chart = make(ElaChartWidget)
    chart.resize(520, 420)
    series = {
        "type": "bar",
        "name": "S",
        "data": [1, 2, 3],
        "label": label or {},
    }
    option = {
        "animation": False,
        "xAxis": {"type": "category", "data": ["A", "B", "C"]},
        "yAxis": {"type": "value"},
        "series": [series],
    }
    if label_layout is not None:
        option["labelLayout"] = label_layout
    chart.setOption(option)
    chart.anim.stop()
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    return chart


def _paint(chart) -> None:
    image = QImage(chart.size(), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    painter = QPainter(image)
    try:
        chart._paint_content(painter, use_series_cache=False)
    finally:
        painter.end()


def test_parse_rich_text():
    assert parse_rich_text("plain") == [("", "plain")]
    assert parse_rich_text("{a|标题}{b| 12}") == [
        ("a", "标题"),
        ("b", " 12"),
    ]
    assert parse_rich_text("前{a|中}后") == [
        ("", "前"),
        ("a", "中"),
        ("", "后"),
    ]


def test_rich_label_box_is_painted(make):
    chart = _bar_chart(
        make,
        {
            "show": True,
            "position": "top",
            "formatter": "{a|高}{b| 12}",
            "backgroundColor": "#ffeecc",
            "borderColor": "#cc9900",
            "borderWidth": 2,
            "borderRadius": 4,
            "padding": [2, 5],
            "rich": {
                "a": {"color": "#ff0000", "fontSize": 16, "fontWeight": 700},
                "b": {"color": "#0000ff", "fontSize": 10},
            },
        },
    )
    renderer = chart.seriesRenderers[0]
    option = renderer.labelVisualOption(0)
    assert option["backgroundColor"].name() == "#ffeecc"
    assert option["rich"]["a"]["color"].name() == "#ff0000"
    _paint(chart)
    assert renderer._label_rects
    assert all(isinstance(item[1], QRectF) for item in renderer._label_rects)

    font = renderer._label_font_for(option)
    size = label_text_size("{a|高}{b| 12}", font, option)
    assert size.width() > 0
    assert size.height() >= 16


def test_hide_overlap_skips_existing_rect(make):
    chart = _bar_chart(make, {"show": True, "position": "top"})
    renderer = chart.seriesRenderers[0]
    renderer._label_rects = [(0, QRectF(0, 0, 100, 100), "old")]
    probe = QRectF(10, 10, 20, 20)
    assert renderer.labelOverlaps(probe) is False

    chart.setOption({"labelLayout": {"hideOverlap": True}})
    renderer = chart.seriesRenderers[0]
    renderer._label_rects = [(0, QRectF(0, 0, 100, 100), "old")]
    assert renderer.labelOverlaps(probe) is True

    image = QImage(200, 100, QImage.Format.Format_ARGB32_Premultiplied)
    painter = QPainter(image)
    try:
        assert renderer.paintLabelIn(painter, probe, "X").isNull()
        assert not renderer.paintLabelIn(
            painter, QRectF(200, 200, 40, 20), "X"
        ).isNull()
    finally:
        painter.end()


def test_title_link_hit(make):
    chart = make(ElaChartWidget)
    chart.resize(500, 320)
    chart.setOption(
        {
            "animation": False,
            "title": {"text": "打开文档", "link": "https://example.com"},
            "xAxis": {"type": "category", "data": ["A"]},
            "yAxis": {"type": "value"},
            "series": [{"type": "bar", "data": [1]}],
        }
    )
    chart.anim.stop()
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    _paint(chart)
    title = chart.title
    assert title._text_rect.width() > 0
    assert title.linkAt(title._text_rect.center())


def test_rich_axis_title_legend(make):
    chart = make(ElaChartWidget)
    chart.resize(560, 420)
    chart.setOption(
        {
            "animation": False,
            "title": {
                "text": "{a|标题}{b| 2026}",
                "textStyle": {
                    "rich": {
                        "a": {"color": "#c0392b", "fontSize": 18},
                        "b": {"color": "#2a9d8f", "fontSize": 12},
                    }
                },
            },
            "legend": {
                "top": 34,
                "textStyle": {"rich": {"l": {"color": "#4e79a7", "fontWeight": 700}}},
            },
            "xAxis": {
                "type": "category",
                "data": ["{a|一}", "{a|二}"],
                "axisLabel": {"rich": {"a": {"color": "#e76f51", "fontSize": 13}}},
            },
            "yAxis": {"type": "value"},
            "series": [{"type": "bar", "name": "{l|S}", "data": [1, 2]}],
        }
    )
    chart.anim.stop()
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    assert chart.primaryCoord().x_axis.labelHasRich()
    _paint(chart)


def test_pie_label_line_paints(make):
    chart = make(ElaChartWidget)
    chart.resize(520, 420)
    chart.setOption(
        {
            "animation": False,
            "series": [
                {
                    "type": "pie",
                    "data": [
                        {"name": "A", "value": 1},
                        {"name": "B", "value": 2},
                    ],
                    "label": {"show": True, "position": "outside"},
                    "labelLine": {
                        "show": True,
                        "length": 20,
                        "length2": 30,
                        "lineStyle": {"color": "#ff0000", "width": 2},
                    },
                }
            ],
        }
    )
    chart.anim.stop()
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    _paint(chart)
    assert chart.seriesRenderers[0]._label_rects


def test_mark_area_label_edit(make):
    chart = make(ElaChartWidget)
    chart.resize(520, 400)
    chart.setOption(
        {
            "animation": False,
            "xAxis": {"type": "category", "data": ["A", "B", "C"]},
            "yAxis": {"type": "value"},
            "series": [
                {
                    "type": "line",
                    "name": "S",
                    "data": [1, 3, 2],
                    "markArea": {
                        "data": [
                            [
                                {
                                    "xAxis": "A",
                                    "name": "旧标签",
                                    "label": {"show": True},
                                },
                                {"xAxis": "C"},
                            ]
                        ]
                    },
                }
            ],
        }
    )
    chart.anim.stop()
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    _paint(chart)
    comp = next(c for c in chart.components if c.optionKey == "markArea")
    assert comp._label_rects
    index, _rect = comp.labelEditHit(comp._label_rects[0][1].center())
    assert index == 0
    assert chart.setAnnotationText("S", "markArea", 0, "新标签")
    chart._layout_all(force=True)
    _paint(chart)
    comp = next(c for c in chart.components if c.optionKey == "markArea")
    assert comp.labelEditText(0) == "新标签"


def test_mark_area_polar_and_calendar(make):
    polar = make(ElaChartWidget)
    polar.resize(500, 400)
    polar.setOption(
        {
            "animation": False,
            "polar": {},
            "angleAxis": {"type": "category", "data": ["A", "B", "C"]},
            "radiusAxis": {"type": "value"},
            "series": [
                {
                    "type": "bar",
                    "coordinateSystem": "polar",
                    "data": [1, 2, 3],
                    "markArea": {
                        "data": [
                            [
                                {"coord": ["A", 0]},
                                {"coord": ["B", 2]},
                            ]
                        ]
                    },
                }
            ],
        }
    )
    polar.anim.stop()
    polar.anim.setProgress(1.0)
    polar._layout_all(force=True)
    comp = next(c for c in polar.components if c.optionKey == "markArea")
    assert comp._areas
    assert comp._area_meta[0]["path"] is not None
    _paint(polar)

    calendar = make(ElaChartWidget)
    calendar.resize(600, 400)
    calendar.setOption(
        {
            "animation": False,
            "calendar": {"range": "2026-01"},
            "series": [
                {
                    "type": "heatmap",
                    "coordinateSystem": "calendar",
                    "data": [],
                    "markArea": {
                        "data": [
                            [
                                {"coord": "2026-01-01"},
                                {"coord": "2026-01-10"},
                            ]
                        ]
                    },
                }
            ],
        }
    )
    calendar.anim.stop()
    calendar.anim.setProgress(1.0)
    calendar._layout_all(force=True)
    comp = next(c for c in calendar.components if c.optionKey == "markArea")
    assert comp._areas
    _paint(calendar)


def test_move_overlap_shifts_label(make):
    chart = _bar_chart(
        make,
        {"show": True, "position": "top"},
        {"moveOverlap": "shiftY"},
    )
    renderer = chart.seriesRenderers[0]
    renderer._label_rects = [(0, QRectF(0, 0, 500, 500), "old")]
    image = QImage(600, 500, QImage.Format.Format_ARGB32_Premultiplied)
    painter = QPainter(image)
    try:
        hit = renderer.paintLabelIn(painter, QRectF(10, 10, 60, 20), "X")
        assert not hit.isNull()
        assert not hit.intersects(QRectF(0, 0, 500, 500))
    finally:
        painter.end()


def test_mark_area_style_label_and_silent(make):
    chart = make(ElaChartWidget)
    chart.resize(500, 400)
    chart.setOption(
        {
            "animation": False,
            "xAxis": {"type": "category", "data": ["A", "B", "C", "D"]},
            "yAxis": {"type": "value"},
            "series": [
                {
                    "type": "line",
                    "name": "S",
                    "data": [1, 5, 3, 8],
                    "markArea": {
                        "data": [
                            [
                                {
                                    "xAxis": "A",
                                    "name": "窗口",
                                    "itemStyle": {
                                        "color": "#ff0000",
                                        "opacity": 0.2,
                                        "borderColor": "#990000",
                                        "borderWidth": 2,
                                    },
                                    "label": {"show": True},
                                },
                                {"xAxis": "C"},
                            ]
                        ]
                    },
                }
            ],
        }
    )
    chart.anim.stop()
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    comp = next(c for c in chart.components if c.optionKey == "markArea")
    assert comp._areas
    meta = comp._area_meta[0]
    assert meta["text"] == "窗口"
    assert meta["borderWidth"] == 2
    assert meta["fill"].alpha() == 51
    _paint(chart)

    chart.setOption(
        {"series": [{"markArea": {"silent": True}}]},
    )
    comp = next(c for c in chart.components if c.optionKey == "markArea")
    chart._layout_all(force=True)
    assert comp.hitTest(comp._areas[0].center()) is None
