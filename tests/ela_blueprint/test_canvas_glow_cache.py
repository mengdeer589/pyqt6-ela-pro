"""选中发光位图缓存：同尺寸复用 / 视口裁剪 / 主题失效。"""

from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF
from PyQt6.QtGui import QPainter, QPixmap

from pyqt6_ela_pro.blueprint import (
    ElaBlueprintCanvas,
    pin,
    register_node_type,
)


def _canvas(make):
    register_node_type(
        "glow_node",
        "G",
        "测试",
        outputs=pin("o", "out", "tensor"),
    )
    canvas = make(ElaBlueprintCanvas)
    canvas.resize(800, 600)
    return canvas


def _paint_glow(canvas, rect=None):
    pixmap = QPixmap(canvas.size())
    painter = QPainter(pixmap)
    canvas._draw_selection_glow(painter, rect or QRectF(canvas.rect()))
    painter.end()
    return pixmap


def test_glow_cache_reuses_pixmap_for_same_size(make):
    canvas = _canvas(make)
    canvas.create_node("glow_node", QPointF(40, 40))
    canvas.create_node("glow_node", QPointF(240, 40))
    canvas.select_all()

    _paint_glow(canvas)
    assert len(canvas._glow_cache) == 1
    cached = next(iter(canvas._glow_cache.values()))

    _paint_glow(canvas)
    assert len(canvas._glow_cache) == 1
    assert next(iter(canvas._glow_cache.values())) is cached


def test_glow_cache_culls_offscreen_nodes(make):
    canvas = _canvas(make)
    canvas.create_node("glow_node", QPointF(5000, 5000))
    canvas.select_all()

    _paint_glow(canvas, QRectF(0.0, 0.0, 10.0, 10.0))
    assert not canvas._glow_cache


def test_glow_cache_invalidated_on_theme(make):
    canvas = _canvas(make)
    canvas.create_node("glow_node", QPointF(40, 40))
    canvas.select_all()

    _paint_glow(canvas)
    assert canvas._glow_cache

    canvas._retheme()
    assert not canvas._glow_cache
    assert canvas._glow_theme_rev == 1
