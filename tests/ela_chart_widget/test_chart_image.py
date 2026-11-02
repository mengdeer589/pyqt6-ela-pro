"""矩阵图像系列（imshow 风格）：轴范围 / extent / origin / RGB / 色带 / 命中。"""

from __future__ import annotations

import pytest

from pyqt6_ela_pro.charts import (
    ElaChartWidget,
    GridCoord,
    colormapColors,
    colormapNames,
    registerColormap,
)


def _chart(make, option=None) -> ElaChartWidget:
    chart = make(ElaChartWidget)
    chart.resize(640, 420)
    chart.setOption({"animation": False, **(option or {})})
    chart.anim.stop()
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    return chart


def _image_chart(make, data, **series) -> ElaChartWidget:
    return _chart(
        make,
        {
            "xAxis": {"type": "value"},
            "yAxis": {"type": "value"},
            "series": [{"type": "image", "name": "img", "data": data, **series}],
        },
    )


class TestImageSeriesContract:
    def test_registers_renderer_and_grid(self, make):
        chart = _chart(make, {"series": [{"type": "image", "data": [[0, 1]]}]})
        assert len(chart.seriesRenderers) == 1
        assert type(chart.seriesRenderers[0]).__name__ == "ImageSeriesRenderer"
        assert any(isinstance(coord, GridCoord) for coord in chart.coords)

    def test_exact_axis_extent_matches_shape(self, make):
        chart = _image_chart(make, [[0, 1, 2], [3, 4, 5]])
        coord = chart.coords[0]
        assert coord.x_axis.vmin == -0.5
        assert coord.x_axis.vmax == 2.5
        assert coord.y_axis.vmin == -0.5
        assert coord.y_axis.vmax == 1.5

    def test_explicit_extent_wins(self, make):
        chart = _image_chart(make, [[0, 1], [2, 3]], extent=[0, 10, 0, 4])
        coord = chart.coords[0]
        assert coord.x_axis.vmin == 0
        assert coord.x_axis.vmax == 10
        assert coord.y_axis.vmin == 0
        assert coord.y_axis.vmax == 4

    def test_equal_aspect_keeps_square_data_pixels(self, make):
        chart = _image_chart(make, [[0.0] * 20 for _ in range(10)], aspect="equal")
        coord = chart.coords[0]
        data_ratio = (coord.y_axis.vmax - coord.y_axis.vmin) / (
            coord.x_axis.vmax - coord.x_axis.vmin
        )
        plot_ratio = coord.plot.height() / coord.plot.width()
        assert plot_ratio == pytest.approx(data_ratio, rel=1e-6)
        rect = chart.seriesRenderers[0]._image_rect
        assert rect.width() == pytest.approx(coord.plot.width(), rel=1e-9)
        assert rect.height() == pytest.approx(coord.plot.height(), rel=1e-9)

    def test_ragged_matrix_is_ignored(self, make):
        chart = _chart(
            make,
            {
                "series": [
                    {"type": "image", "data": [[0, 1], [2]]},
                ]
            },
        )
        renderer = chart.seriesRenderers[0]
        assert renderer._image is None
        assert renderer.hitTest(chart.rect().center().toPointF()) is None

    def test_full_window_keeps_exact_ticks(self, make):
        chart = _image_chart(make, [[0, 1, 2], [3, 4, 5]])
        axis = chart.coords[0].y_axis
        axis.setWindow(-0.5, 1.5, 0.0, 100.0)
        assert (axis.vmin, axis.vmax) == (-0.5, 1.5)
        assert all(-0.5 <= tick <= 1.5 for tick in axis.ticks())

    def test_mixed_series_uses_union_extent(self, make):
        chart = _chart(
            make,
            {
                "series": [
                    {"type": "image", "data": [[0, 1], [2, 3]]},
                    {"type": "line", "data": [[0, 10], [1, 20]]},
                ]
            },
        )
        coord = chart.coords[0]
        assert coord.y_axis.vmin <= -0.5
        assert coord.y_axis.vmax >= 20.0

    def test_numpy_matrix_uses_buffer_path(self, make):
        np = pytest.importorskip("numpy")
        data = np.zeros((300, 2), dtype=float)
        chart = _image_chart(make, data)
        renderer = chart.seriesRenderers[0]
        assert renderer._image is not None
        assert renderer._rows == 300
        assert renderer._cols == 2
        assert chart.coords[0].x_axis.vmax == 1.5

    def test_complex_matrix_is_rejected_with_hint(self, make, capsys):
        np = pytest.importorskip("numpy")
        chart = _image_chart(make, np.ones((2, 2), dtype=complex))
        renderer = chart.seriesRenderers[0]
        assert renderer._image is None
        assert "np.abs" in capsys.readouterr().err

    def test_export_contains_image(self, make):
        chart = _image_chart(make, [[0, 1], [2, 3]])
        assert chart.getDataURL().startswith("data:image/png;base64,")


class TestImageHitTesting:
    def test_hit_reports_actual_pixel_color(self, make):
        chart = _image_chart(make, [[0.0, 1.0]], cmap="gray")
        coord = chart.coords[0]
        renderer = chart.seriesRenderers[0]
        left = renderer.hitTest(coord.mapPoint(0.0, 0.0))
        right = renderer.hitTest(coord.mapPoint(1.0, 0.0))
        assert left["color"].name() == "#000000"
        assert right["color"].name() == "#ffffff"

    def test_origin_upper_rows_start_at_top(self, make):
        chart = _image_chart(make, [[1, 2], [3, 4]])
        coord = chart.coords[0]
        renderer = chart.seriesRenderers[0]
        assert renderer.hitTest(coord.mapPoint(0.0, 1.0))["value"] == 1.0
        assert renderer.hitTest(coord.mapPoint(1.0, 0.0))["value"] == 4.0

    def test_origin_lower_rows_start_at_bottom(self, make):
        chart = _image_chart(make, [[1, 2], [3, 4]], origin="lower")
        coord = chart.coords[0]
        renderer = chart.seriesRenderers[0]
        assert renderer.hitTest(coord.mapPoint(0.0, 0.0))["value"] == 1.0
        assert renderer.hitTest(coord.mapPoint(1.0, 1.0))["value"] == 4.0

    def test_rgb_hit_returns_hex(self, make):
        chart = _image_chart(make, [[[255, 0, 0], [0, 255, 0]]], origin="upper")
        coord = chart.coords[0]
        renderer = chart.seriesRenderers[0]
        assert renderer._mode == "rgb"
        assert renderer.hitTest(coord.mapPoint(0.0, 0.0))["value"] == "#ff0000"
        assert renderer.hitTest(coord.mapPoint(1.0, 0.0))["value"] == "#00ff00"

    def test_numpy_rgb_float_zero_to_one(self, make):
        np = pytest.importorskip("numpy")
        chart = _image_chart(make, np.ones((1, 2, 3), dtype=float))
        image = chart.seriesRenderers[0]._image
        assert image.pixelColor(1, 0).name() == "#ffffff"

    def test_nan_has_no_value(self, make):
        chart = _image_chart(make, [[float("nan"), 1.0]], cmap="gray", vmin=0, vmax=1)
        coord = chart.coords[0]
        renderer = chart.seriesRenderers[0]
        assert renderer.hitTest(coord.mapPoint(-0.5, 0.0))["value"] is None


class TestImageColors:
    def test_custom_colormap_lut(self, make):
        registerColormap("test-black-white", ["#000000", "#ffffff"])
        chart = _image_chart(
            make, [[0.0, 1.0]], cmap="test-black-white", vmin=0, vmax=1
        )
        image = chart.seriesRenderers[0]._image
        assert image.pixelColor(0, 0).name() == "#000000"
        assert image.pixelColor(1, 0).name() == "#ffffff"

    def test_theme_ramp_fallback(self, make):
        chart = _image_chart(make, [[0.0, 1.0]])
        image = chart.seriesRenderers[0]._image
        assert image.pixelColor(0, 0).alpha() == 255
        assert image.pixelColor(0, 0).name() != image.pixelColor(1, 0).name()

    def test_visualmap_wins_over_cmap(self, make):
        chart = _chart(
            make,
            {
                "visualMap": {
                    "min": 0,
                    "max": 1,
                    "inRange": {"colors": ["#ff0000", "#00ff00"]},
                },
                "series": [
                    {
                        "type": "image",
                        "data": [[0.0, 1.0]],
                        "cmap": "viridis",
                    }
                ],
            },
        )
        image = chart.seriesRenderers[0]._image
        assert image.pixelColor(0, 0).name() == "#ff0000"
        assert image.pixelColor(1, 0).name() == "#00ff00"

    def test_visualmap_without_colors_uses_image_cmap(self, make):
        chart = _chart(
            make,
            {
                "visualMap": {"min": 0, "max": 1},
                "series": [
                    {
                        "type": "image",
                        "data": [[0.0, 1.0]],
                        "cmap": "viridis",
                    }
                ],
            },
        )
        vm = chart._component("visualMap")
        assert vm is not None and vm.colors() == colormapColors("viridis")
        image = chart.seriesRenderers[0]._image
        assert image.pixelColor(0, 0).name() == "#440154"
        assert image.pixelColor(1, 0).name() == "#fde725"

    def test_nan_is_transparent(self, make):
        chart = _image_chart(make, [[float("nan"), 1.0]], cmap="gray", vmin=0, vmax=1)
        image = chart.seriesRenderers[0]._image
        assert image.pixelColor(0, 0).alpha() == 0
        assert image.pixelColor(1, 0).alpha() == 255

    def test_lower_origin_flips_image(self, make):
        chart = _image_chart(
            make, [[0.0], [1.0]], cmap="gray", vmin=0, vmax=1, origin="lower"
        )
        image = chart.seriesRenderers[0]._image
        assert image.pixelColor(0, 0).name() == "#ffffff"
        assert image.pixelColor(0, 1).name() == "#000000"

    def test_update_series_rebuilds_image(self, make):
        chart = _image_chart(
            make, [[0.0, 0.0], [0.0, 0.0]], cmap="gray", vmin=0, vmax=1
        )
        renderer = chart.seriesRenderers[0]
        assert renderer._image.pixelColor(0, 0).name() == "#000000"
        assert chart.updateSeries({"data": [[1.0, 1.0], [1.0, 1.0]]}) is True
        chart._layout_all(force=True)
        assert chart.seriesRenderers[0]._image.pixelColor(0, 0).name() == "#ffffff"


class TestColormapRegistry:
    def test_builtin_names_and_copy(self):
        assert "viridis" in colormapNames()
        colors = colormapColors("viridis")
        assert colors and colors[0] == "#440154"
        colors.append("#123456")
        assert len(colormapColors("viridis")) == 10

    def test_unknown_name_returns_none(self):
        assert colormapColors("no-such-cmap") is None

    @pytest.mark.parametrize(
        "name,colors",
        [
            ("", ["#000000", "#ffffff"]),
            ("x", ["#000000"]),
            ("x", ["#000000", "not-a-color"]),
        ],
        ids=["empty-name", "too-few", "invalid-color"],
    )
    def test_invalid_registration_raises(self, name, colors):
        with pytest.raises(ValueError):
            registerColormap(name, colors)
