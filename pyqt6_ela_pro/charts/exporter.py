"""图表导出（PNG / JPEG / SVG / data URL）。

从 ``ElaChartWidget`` 拆出的纯导出逻辑：不拥有绘图状态，只读画布当前
option / 几何，用 ``_paint_content`` 离屏重绘（子控件 —— 工具条按钮 —— 天然不入镜）。
"""

from __future__ import annotations

import base64
import pathlib
import tempfile
from typing import TYPE_CHECKING, Optional

from PyQt6.QtCore import QBuffer, QIODevice, QRect, QSize, Qt
from PyQt6.QtGui import QColor, QGuiApplication, QImage, QPainter
from PyQt6.QtWidgets import QFileDialog

from ._tokens import T
from ._utils import parse_color

if TYPE_CHECKING:
    from .core import ElaChartWidget


class ChartExporter:
    """按需导出图表（``getDataURL`` / ``saveImage`` 的实现）。"""

    def __init__(self, chart: "ElaChartWidget") -> None:
        self._chart = chart

    def data_url(self, opts: dict = None) -> str:
        """导出为 data URL（ECharts ``getDataURL``）。"""
        opts = dict(opts or {})
        fmt = str(opts.get("type") or "png").lower()
        if fmt == "svg":
            return self._svg_data_url()
        fmt = "jpeg" if fmt in ("jpeg", "jpg") else "png"
        try:
            image = self._render_image(opts, opaque=fmt == "jpeg")
        except Exception:
            return ""
        if image.isNull():
            return ""
        try:
            ratio = float(opts.get("pixelRatio") or 1.0)
        except (TypeError, ValueError, OverflowError):
            ratio = 1.0
        if ratio > 0 and abs(ratio - 1.0) > 1e-6:
            image = image.scaled(
                max(1, int(image.width() * ratio)),
                max(1, int(image.height() * ratio)),
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        ok = image.save(buffer, fmt.upper())
        buffer.close()
        if not ok:
            return ""
        payload = bytes(buffer.data().toBase64()).decode("ascii")
        mime = "image/jpeg" if fmt == "jpeg" else "image/png"
        return f"data:{mime};base64,{payload}"

    def save_image(self, path: str = None, *, format: str = None) -> str:
        """保存当前图表；``path=None`` 时弹保存对话框。"""
        target = path
        want_svg = str(format or "").lower() == "svg" or (
            bool(target) and str(target).lower().endswith(".svg")
        )
        if not target:
            try:
                if QGuiApplication.platformName() == "offscreen":
                    return ""
                filt = "SVG 矢量图 (*.svg)" if want_svg else "PNG 图片 (*.png)"
                default = "chart.svg" if want_svg else "chart.png"
                target, _ = QFileDialog.getSaveFileName(
                    self._chart, "保存图表", default, filt
                )
            except Exception:
                target = None
        if not target:
            return ""
        if want_svg:
            return self._save_svg(str(target))
        try:
            image = self._render_image()
            if not image.isNull() and image.save(str(target), "PNG"):
                return str(target)
        except Exception:
            pass
        return ""

    def _save_svg(self, target: str) -> str:
        """用 ``QSvgGenerator`` 走同一条绘制链导出矢量图。"""
        try:
            from PyQt6.QtSvg import QSvgGenerator
        except ImportError:  # 可选依赖（QtSvg）
            return ""
        try:
            chart = self._chart
            width, height = max(1, chart.width()), max(1, chart.height())
            generator = QSvgGenerator()
            generator.setFileName(target)
            generator.setSize(QSize(width, height))
            generator.setViewBox(QRect(0, 0, width, height))
            generator.setTitle("ElaChartWidget")
            painter = QPainter(generator)
            try:
                self._paint_backgrounds(painter, width, height, {})
                chart._layout_all()
                chart._paint_content(painter)
            finally:
                painter.end()
            return target
        except Exception:
            return ""

    @staticmethod
    def _option_color(raw) -> Optional[QColor]:
        """option 里的颜色 → QColor；``None`` / 非法值返回 ``None``。"""
        if raw is None:
            return None
        color = parse_color(raw)
        return color if color.isValid() else None

    def _background_layers(self, opts: dict) -> tuple:
        """→ (导出底色, 图表背景)，与 ECharts 同序：导出参数在下、图表背景在上。

        两者都没给时导出底色回落主题底（与控件观感一致）；图表显式设了
        ``"transparent"`` 时不铺主题底 —— PNG 就是真正的透明背景。
        """
        export_bg = self._option_color((opts or {}).get("backgroundColor"))
        chart_bg = self._option_color(self._chart.getOption().get("backgroundColor"))
        if export_bg is None and chart_bg is None:
            export_bg = QColor(T("color.bg.base"))
        return export_bg, chart_bg

    def _paint_backgrounds(self, painter: QPainter, width: int, height: int, opts):
        """按层铺底色（alpha 0 的层跳过，免得 SVG 里留一个空矩形）。"""
        for color in self._background_layers(opts):
            if color is not None and color.alpha() > 0:
                painter.fillRect(QRect(0, 0, width, height), color)

    def _render_image(self, opts: dict = None, *, opaque: bool = False) -> QImage:
        """图表内容 → 离屏 ``QImage``（不含子控件，工具条按钮不会入镜）。

        ``opaque``（JPEG）时把透明像素压到主题底上 —— JPEG 没有 alpha 通道。
        """
        chart = self._chart
        dpr = max(1.0, float(chart.devicePixelRatioF() or 1.0))
        image = QImage(
            max(1, int(round(chart.width() * dpr))),
            max(1, int(round(chart.height() * dpr))),
            QImage.Format.Format_ARGB32_Premultiplied,
        )
        image.setDevicePixelRatio(dpr)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            self._paint_backgrounds(painter, chart.width(), chart.height(), opts or {})
            chart._layout_all()
            chart._paint_content(painter)
        finally:
            painter.end()
        if opaque:
            image = self._flatten(image)
        return image

    @staticmethod
    def _flatten(image: QImage) -> QImage:
        """把带透明度的图压到主题底（JPEG 用）。"""
        canvas = QImage(image.size(), QImage.Format.Format_RGB32)
        canvas.setDevicePixelRatio(image.devicePixelRatio())
        canvas.fill(QColor(T("color.bg.base")))
        painter = QPainter(canvas)
        try:
            painter.drawImage(0, 0, image)
        finally:
            painter.end()
        return canvas

    def _svg_data_url(self) -> str:
        """矢量图 → ``data:image/svg+xml;base64,...``。"""
        try:
            with tempfile.TemporaryDirectory() as tmp:
                target = str(pathlib.Path(tmp) / "chart.svg")
                if not self._save_svg(target):
                    return ""
                data = pathlib.Path(target).read_bytes()
        except Exception:
            return ""
        if not data:
            return ""
        return "data:image/svg+xml;base64," + base64.b64encode(data).decode("ascii")
