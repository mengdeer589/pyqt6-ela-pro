"""图表导出：底色分层 / 透明 PNG / JPEG 压平 / 矢量图背景 / 不碰子控件。

旧实现直接 ``grab()`` 整个控件再叠导出底色 —— 控件本身已画了不透明主题底，
``getDataURL({"backgroundColor": ...})`` 永远看不见。现在改成
``_paint_content`` 离屏重绘（工具条按钮等子控件天然不入镜），底色按
ECharts 顺序分层：导出参数在最底层、图表 ``backgroundColor`` 覆盖其上。
"""

from __future__ import annotations

import base64
import pathlib

import pytest
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QToolButton

from pyqt6_ela_pro.charts import ElaChartWidget
from pyqt6_ela_pro.charts._tokens import T

_BASE = {
    "animation": False,
    "xAxis": {"type": "category", "data": ["一", "二", "三"]},
    "yAxis": {"type": "value"},
    "series": [{"type": "line", "data": [1, 3, 2]}],
}


def _chart(make, **extra):
    chart = make(ElaChartWidget)
    chart.resize(180, 120)
    option = dict(_BASE)
    option.update(extra)
    chart.setOption(option)
    chart.anim.setProgress(1.0)
    return chart


def _image(url: str, fmt: bytes = b"PNG") -> QImage:
    assert url.startswith("data:image/")
    image = QImage()
    assert image.loadFromData(base64.b64decode(url.split(",", 1)[1]), fmt)
    return image


def _corner(image: QImage):
    return image.pixelColor(2, 2)


class TestRasterBackground:
    def test_export_background_is_visible(self, make):
        chart = _chart(make)
        image = _image(chart.getDataURL({"backgroundColor": "rgba(1, 2, 3, 1)"}))
        assert _corner(image).name() == "#010203"

    def test_export_background_can_be_transparent(self, make):
        chart = _chart(make)
        image = _image(chart.getDataURL({"backgroundColor": "transparent"}))
        assert _corner(image).alpha() == 0

    def test_default_export_keeps_theme_background(self, make):
        chart = _chart(make)
        image = _image(chart.getDataURL())
        assert _corner(image).name() == T("color.bg.base").name()

    def test_chart_background_covers_export_background(self, make):
        chart = _chart(make, backgroundColor="#ff0000")
        image = _image(chart.getDataURL({"backgroundColor": "#010203"}))
        assert _corner(image).name() == "#ff0000"

    def test_chart_transparent_background_leaves_png_transparent(self, make):
        chart = _chart(make, backgroundColor="transparent")
        image = _image(chart.getDataURL())
        assert _corner(image).alpha() == 0

    def test_jpeg_is_flattened_opaque(self, make):
        chart = _chart(make, backgroundColor="transparent")
        image = _image(chart.getDataURL({"type": "jpeg"}), b"JPEG")
        assert not image.isNull()
        assert _corner(image).alpha() == 255

    def test_pixel_ratio_scales_output(self, make):
        chart = _chart(make)
        dpr = chart.devicePixelRatioF()
        image = _image(chart.getDataURL({"pixelRatio": 2}))
        assert image.width() == round(chart.width() * dpr * 2)
        assert image.height() == round(chart.height() * dpr * 2)


class TestSavedFiles:
    def test_png_file_uses_chart_background(self, make, tmp_path):
        chart = _chart(make, backgroundColor="#ff0000")
        target = tmp_path / "chart.png"
        assert chart.saveImage(str(target)) == str(target)
        image = QImage(str(target))
        assert image.pixelColor(2, 2).name() == "#ff0000"

    def test_svg_uses_chart_background(self, make, tmp_path):
        chart = _chart(make, backgroundColor="#ff0000")
        target = tmp_path / "chart.svg"
        assert chart.saveImage(str(target)) == str(target)
        text = pathlib.Path(target).read_text(encoding="utf-8")
        assert "#ff0000" in text


class TestExportDoesNotTouchWidgets:
    def test_toolbox_buttons_stay_visible(self, make):
        """导出走离屏重绘，不需要（也不允许）临时隐藏工具条按钮。"""
        chart = _chart(
            make,
            toolbox={"feature": ["saveAsImage", "dataZoom", "restore"]},
        )
        buttons = chart.findChildren(QToolButton)
        before = [button.isVisible() for button in buttons]
        chart.getDataURL()
        assert [button.isVisible() for button in buttons] == before


@pytest.mark.parametrize("fmt", ["png", "jpeg", "svg"])
def test_all_formats_produce_payload(make, fmt):
    chart = _chart(make)
    url = chart.getDataURL({"type": fmt})
    assert url.startswith(f"data:image/{'svg+xml' if fmt == 'svg' else fmt};base64,")
    assert len(url) > 200
