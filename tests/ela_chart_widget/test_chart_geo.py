"""GeoJSON 地图注册 / 投影 / 孔洞 / 命中回归。"""

from __future__ import annotations

from pyqt6_ela_pro import ElaChartWidget
from pyqt6_ela_pro.charts import (
    mapNames,
    registerMap,
    unregisterMap,
)
from pyqt6_ela_pro.charts.geo import mapRegions

GEOJSON = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {"name": "A"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]],
                    [[2, 2], [4, 2], [4, 4], [2, 4], [2, 2]],
                ],
            },
        },
        {
            "type": "Feature",
            "properties": {"name": "B"},
            "geometry": {
                "type": "MultiPolygon",
                "coordinates": [
                    [[[12, 0], [16, 0], [16, 4], [12, 4], [12, 0]]],
                    [[[18, 0], [20, 0], [20, 2], [18, 2], [18, 0]]],
                ],
            },
        },
    ],
}


def test_map_antimeridian_ring_is_unwrapped():
    geojson = {
        "type": "Feature",
        "properties": {"name": "X"},
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[179, 0], [-179, 0], [-179, 10], [179, 10], [179, 0]]],
        },
    }
    assert registerMap("geo-anti", geojson)
    try:
        ring = mapRegions("geo-anti")["X"][0]
        xs = [point[0] for point in ring]
        assert max(xs) - min(xs) < 10.0
    finally:
        unregisterMap("geo-anti")


def test_register_and_unregister_map():
    assert registerMap("geo-test", GEOJSON)
    assert "geo-test" in mapNames()
    regions = mapRegions("geo-test")
    assert set(regions) == {"A", "B"}
    assert len(regions["A"]) == 2  # 外环 + 孔洞
    assert len(regions["B"]) == 2  # MultiPolygon 两个岛
    assert unregisterMap("geo-test")
    assert "geo-test" not in mapNames()


def test_multiple_geo_and_geo_index(make):
    assert registerMap("geo-multi-a", GEOJSON)
    assert registerMap("geo-multi-b", GEOJSON)
    try:
        chart = make(ElaChartWidget)
        chart.resize(680, 460)
        chart.setOption(
            {
                "animation": False,
                "geo": [
                    {"map": "geo-multi-a"},
                    {
                        "map": "geo-multi-b",
                        "right": "5%",
                        "width": "40%",
                    },
                ],
                "series": [
                    {
                        "type": "scatter",
                        "coordinateSystem": "geo",
                        "geoIndex": 1,
                        "data": [[5, 5]],
                    },
                    {
                        "type": "map",
                        "name": "M",
                        "geoIndex": 1,
                        "data": [{"name": "A", "value": 3}],
                    },
                ],
            }
        )
        chart.anim.stop()
        chart.anim.setProgress(1.0)
        chart._layout_all(force=True)
        assert len(chart.geoCoords()) == 2
        assert chart.geoCoord(1).rect.width() < chart.geoCoord(0).rect.width()
        renderer = chart.seriesRenderers[0]
        assert renderer._dots[0]["pt"].x() > chart.width() * 0.5
        map_renderer = chart.seriesRenderers[1]
        assert [item[0] for item in map_renderer._polys] == ["A", "B"]
    finally:
        unregisterMap("geo-multi-a")
        unregisterMap("geo-multi-b")


def test_geo_component_maps_scatter_and_lines(make):
    assert registerMap("geo-component", GEOJSON)
    try:
        chart = make(ElaChartWidget)
        chart.resize(640, 460)
        chart.setOption(
            {
                "animation": False,
                "geo": {"map": "geo-component", "label": {"show": True}},
                "series": [
                    {
                        "type": "scatter",
                        "coordinateSystem": "geo",
                        "data": [[5, 5], [15, 4]],
                        "symbolSize": 16,
                    },
                    {
                        "type": "lines",
                        "coordinateSystem": "geo",
                        "data": [{"coords": [[5, 5], [15, 4]]}],
                    },
                ],
            }
        )
        chart.anim.stop()
        chart.anim.setProgress(1.0)
        chart._layout_all(force=True)
        geo = chart.coordFor({"coordinateSystem": "geo"})
        assert type(geo).__name__ == "GeoCoord"
        point = geo.mapPoint(5, 5)
        assert point.x() > 0 and point.y() > 0
        scatter = chart.seriesRenderers[0]
        assert len(scatter._dots) == 2
        assert scatter._dots[0]["pt"] == point
        lines = chart.seriesRenderers[1]
        assert len(lines._segments) == 1
    finally:
        unregisterMap("geo-component")


def test_geo_region_hover_and_select(make):
    assert registerMap("geo-select", GEOJSON)
    try:
        chart = make(ElaChartWidget)
        chart.resize(600, 420)
        chart.setOption(
            {
                "animation": False,
                "geo": {"map": "geo-select"},
                "series": [{"type": "scatter", "coordinateSystem": "geo", "data": []}],
            }
        )
        chart.anim.stop()
        chart.anim.setProgress(1.0)
        chart._layout_all(force=True)
        geo = chart.geoCoord(0)
        point = geo.mapPoint(5, 5)
        assert geo.regionAt(point) == "A"
        geo.onMouseMove(point)
        assert geo._hover_region == "A"
        seen = []
        chart.on("geoselectchanged", seen.append)
        assert geo.onMousePress(point) is True
        assert geo.selectedRegions() == {"A"}
        assert seen and seen[0]["selected"] == {"A"}
    finally:
        unregisterMap("geo-select")


def test_map_series_uses_registered_geojson(make):
    assert registerMap("geo-series", GEOJSON)
    try:
        chart = make(ElaChartWidget)
        chart.resize(520, 420)
        chart.setOption(
            {
                "animation": False,
                "geo": {"projection": "mercator"},
                "series": [
                    {
                        "type": "map",
                        "map": "geo-series",
                        "data": [
                            {"name": "A", "value": 10},
                            {"name": "B", "value": 20},
                        ],
                        "label": {"show": True},
                    }
                ],
            }
        )
        chart.anim.stop()
        chart.anim.setProgress(1.0)
        chart._layout_all(force=True)
        renderer = chart.seriesRenderers[0]
        assert [item[0] for item in renderer._polys] == ["A", "B"]
        assert renderer._paths["A"].fillRule().name == "OddEvenFill"
        # 孔洞区域不能被命中；外环包围盒中心（非孔洞）可以。
        outer = renderer._polys[0][1]
        center = outer.boundingRect().center()
        hit = renderer.hitTest(center)
        assert hit is not None and hit["name"] == "A"
    finally:
        unregisterMap("geo-series")


def test_map_series_reuses_top_geo(make):
    assert registerMap("geo-dedup", GEOJSON)
    try:
        chart = make(ElaChartWidget)
        chart.resize(560, 420)
        chart.setOption(
            {
                "animation": False,
                "geo": {"map": "geo-dedup", "itemStyle": {"areaColor": "#00ff00"}},
                "series": [
                    {
                        "type": "map",
                        "map": "geo-dedup",
                        "roam": True,
                        "itemStyle": {"areaColor": "#ff0000", "borderWidth": 0},
                        "data": [{"name": "A", "value": 5}],
                    }
                ],
            }
        )
        chart.anim.stop()
        chart.anim.setProgress(1.0)
        chart._layout_all(force=True)
        geo = chart.geoCoord(0)
        renderer = chart.seriesRenderers[0]
        assert renderer._geo is geo
        assert renderer._paths is geo._paths
        assert [item[0] for item in renderer._polys] == ["A", "B"]
        # 标签交给顶层 geo；系列没显式 show 时不再叠一层。
        assert renderer.labelShown() is False
        # roam 也归顶层 geo，系列不再抢滚轮 / 拖拽。
        assert renderer.onMousePress(geo.rect.center()) is False

        from PyQt6.QtGui import QColor, QImage, QPainter

        image = QImage(chart.size(), QImage.Format.Format_ARGB32)
        image.fill(QColor("#ffffff"))
        painter = QPainter(image)
        try:
            chart._paint_content(painter)
        finally:
            painter.end()
        # 无数据区域保持 geo 底色，不被系列的 areaColor 覆盖。
        b_center = geo._polys["B"].boundingRect().center()
        assert image.pixelColor(b_center.toPoint()).name() == "#00ff00"
        # 有数据区域由系列着色。
        a_center = geo._polys["A"].boundingRect().center()
        assert image.pixelColor(a_center.toPoint()).name() == (
            renderer._region_colors["A"].name()
        )
        # 标签对比色使用系列实际叠加色。
        assert geo._label_fills.get("A") == renderer._region_colors["A"]
    finally:
        unregisterMap("geo-dedup")


def test_map_series_binds_explicit_geo_index(make):
    assert registerMap("geo-dedup-index", GEOJSON)
    try:
        chart = make(ElaChartWidget)
        chart.resize(560, 420)
        chart.setOption(
            {
                "animation": False,
                "geo": [{"map": "geo-dedup-index"}],
                "series": [
                    {
                        "type": "map",
                        "geoIndex": 0,
                        "data": [{"name": "B", "value": 1}],
                    }
                ],
            }
        )
        chart.anim.stop()
        chart.anim.setProgress(1.0)
        chart._layout_all(force=True)
        assert chart.seriesRenderers[0]._geo is chart.geoCoord(0)
    finally:
        unregisterMap("geo-dedup-index")


def test_geo_labels_draw_after_map_series(make):
    """map 系列在绑定 geo 时只叠数据着色，geo 标签必须最后画，否则被盖住。"""
    assert registerMap("geo-label-order", GEOJSON)
    try:
        chart = make(ElaChartWidget)
        chart.resize(520, 380)
        chart.setOption(
            {
                "animation": False,
                "geo": {"map": "geo-label-order", "label": {"show": True}},
                "series": [
                    {
                        "type": "map",
                        "map": "geo-label-order",
                        "data": [{"name": "A", "value": 5}],
                    }
                ],
            }
        )
        chart.anim.stop()
        chart.anim.setProgress(1.0)
        chart._layout_all(force=True)
        calls = []
        geo = chart.geoCoord(0)
        original_labels = geo.paintLabels

        def labels(painter):
            calls.append("labels")
            original_labels(painter)

        geo.paintLabels = labels
        renderer = chart.seriesRenderers[0]
        original_series = renderer.paint

        def series_paint(painter, t=1.0):
            calls.append("series")
            original_series(painter, t)

        renderer.paint = series_paint
        chart.invalidateSeriesLayer()

        from PyQt6.QtGui import QColor, QImage, QPainter

        image = QImage(chart.size(), QImage.Format.Format_ARGB32)
        image.fill(QColor("#ffffff"))
        painter = QPainter(image)
        try:
            chart._paint_content(painter)
        finally:
            painter.end()
        assert calls[:2] == ["series", "labels"]
    finally:
        unregisterMap("geo-label-order")
