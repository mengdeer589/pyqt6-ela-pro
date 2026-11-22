"""图表导出（PNG / JPEG / SVG / data URL）。

只读画布当前 option / 几何，用 ``_paint_content`` 离屏重绘（子控件不入镜）。
"""

from __future__ import annotations

import base64
import pathlib
import tempfile
from typing import TYPE_CHECKING, Optional

from PyQt6.QtCore import QBuffer, QIODevice, QRect, QSize, QSizeF, Qt
from PyQt6.QtGui import (
    QColor,
    QGuiApplication,
    QImage,
    QPageSize,
    QPainter,
    QPdfWriter,
)
from PyQt6.QtWidgets import QFileDialog

from ._tokens import T
from ._utils import resolve_color_option

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
            return self._svg_data_url(opts)
        if fmt == "pdf":
            return self._pdf_data_url(bool(opts.get("multiPage", False)), opts)
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
        if ratio > 0:
            # pixelRatio 是相对逻辑尺寸的绝对倍率；离屏图已经乘过 DPR。
            dpr = max(1.0, float(self._chart.devicePixelRatioF() or 1.0))
            scale = ratio / dpr
            if abs(scale - 1.0) > 1e-6:
                image = image.scaled(
                    max(1, int(image.width() * scale)),
                    max(1, int(image.height() * scale)),
                    Qt.AspectRatioMode.IgnoreAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        quality = -1
        if fmt == "jpeg":
            try:
                quality = max(0, min(100, int(opts.get("quality", 90))))
            except (TypeError, ValueError, OverflowError):
                quality = 90
        ok = image.save(buffer, fmt.upper(), quality)
        buffer.close()
        if not ok:
            return ""
        payload = bytes(buffer.data().toBase64()).decode("ascii")
        mime = "image/jpeg" if fmt == "jpeg" else "image/png"
        return f"data:{mime};base64,{payload}"

    def save_image(
        self,
        path: str = None,
        *,
        format: str = None,
        quality: int = None,
        scale: float = None,
        multiPage: bool = False,
    ) -> str:
        """保存当前图表；``path=None`` 时弹保存对话框。"""
        target = path
        want_svg = str(format or "").lower() == "svg" or (
            bool(target) and str(target).lower().endswith(".svg")
        )
        want_pdf = str(format or "").lower() == "pdf" or (
            bool(target) and str(target).lower().endswith(".pdf")
        )
        if not target:
            try:
                if QGuiApplication.platformName() == "offscreen":
                    return ""
                filt = (
                    "SVG 矢量图 (*.svg)"
                    if want_svg
                    else ("PDF 文档 (*.pdf)" if want_pdf else "PNG 图片 (*.png)")
                )
                default = (
                    "chart.svg"
                    if want_svg
                    else ("chart.pdf" if want_pdf else "chart.png")
                )
                target, _ = QFileDialog.getSaveFileName(
                    self._chart, "保存图表", default, filt
                )
            except Exception:
                target = None
        if not target:
            return ""
        suffix = str(target).lower()
        want_svg = want_svg or suffix.endswith(".svg")
        want_pdf = want_pdf or suffix.endswith(".pdf")
        if want_svg:
            return self._save_svg(str(target))
        if want_pdf:
            return self._save_pdf(str(target), multiPage=multiPage)
        suffix = str(target).lower()
        want_jpeg = (
            str(format or "").lower() in ("jpeg", "jpg")
            or suffix.endswith(".jpg")
            or suffix.endswith(".jpeg")
        )
        try:
            # JPEG 没有 alpha：先压到主题底，再按扩展名写对应格式。
            image = self._render_image(opaque=want_jpeg)
            if scale is not None:
                try:
                    ratio = max(0.05, float(scale))
                except (TypeError, ValueError, OverflowError):
                    ratio = 1.0
                if abs(ratio - 1.0) > 1e-6:
                    image = image.scaled(
                        max(1, int(image.width() * ratio)),
                        max(1, int(image.height() * ratio)),
                        Qt.AspectRatioMode.IgnoreAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
            jpeg_quality = -1
            if want_jpeg:
                try:
                    jpeg_quality = max(
                        0, min(100, int(quality if quality is not None else 90))
                    )
                except (TypeError, ValueError, OverflowError):
                    jpeg_quality = 90
            fmt = "JPEG" if want_jpeg else "PNG"
            if not image.isNull() and image.save(str(target), fmt, jpeg_quality):
                return str(target)
        except Exception:
            pass
        return ""

    def _save_svg(self, target: str, opts: dict = None) -> str:
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
                self._paint_backgrounds(painter, width, height, opts or {})
                chart._layout_all()
                self._paint_full(painter, use_series_cache=False)
            finally:
                painter.end()
            return target
        except Exception:
            return ""

    def _save_pdf(self, target: str, *, multiPage: bool = False, opts: dict = None) -> str:
        """导出单页 / 多页 PDF（与屏幕绘制链一致）。"""
        try:
            chart = self._chart
            width, height = max(1, chart.width()), max(1, chart.height())
            page_h_px = min(height, 1123) if multiPage else height
            writer = QPdfWriter(target)
            writer.setResolution(96)
            # 自定义页面与画布同比例（点 = 像素 × 72 / 96），避免内容被裁切。
            writer.setPageSize(
                QPageSize(
                    QSizeF(width * 0.75, page_h_px * 0.75),
                    QPageSize.Unit.Point,
                    "chart",
                )
            )
            painter = QPainter(writer)
            try:
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
                chart._layout_all()
                offsets = (
                    range(0, height, page_h_px)
                    if multiPage and height > page_h_px
                    else [0]
                )
                first = True
                for offset in offsets:
                    if not first:
                        writer.newPage()
                    first = False
                    painter.save()
                    painter.translate(0, -offset)
                    self._paint_backgrounds(painter, width, page_h_px, opts or {})
                    self._paint_full(painter, use_series_cache=False)
                    painter.restore()
            finally:
                painter.end()
            return target
        except Exception:
            return ""

    def _pdf_data_url(self, multi_page: bool = False, opts: dict = None) -> str:
        try:
            with tempfile.TemporaryDirectory() as tmp:
                target = str(pathlib.Path(tmp) / "chart.pdf")
                if not self._save_pdf(target, multiPage=multi_page, opts=opts):
                    return ""
                data = pathlib.Path(target).read_bytes()
        except Exception:
            return ""
        if not data:
            return ""
        return "data:application/pdf;base64," + base64.b64encode(data).decode("ascii")

    def _option_color(self, raw) -> Optional[QColor]:
        """option 里的颜色 → QColor；``None`` / 非法值返回 ``None``。"""
        if raw is None:
            return None
        color = resolve_color_option(raw, self._chart)
        return color if color.isValid() else None

    def _background_layers(self, opts: dict) -> tuple:
        """→ (导出底色, 图表背景)，导出参数在下、图表背景在上。

        两者都没给时导出底色回落主题底；图表显式设 ``"transparent"`` 时不铺底。
        """
        export_bg = self._option_color((opts or {}).get("backgroundColor"))
        # 只读内部 option，不调 ``getOption()``：后者会深拷贝整份数据（40 万点约 1.0s）。
        chart_bg = self._option_color(self._chart._option_ref().get("backgroundColor"))
        if export_bg is None and chart_bg is None:
            export_bg = QColor(T("color.bg.base", self._chart))
        return export_bg, chart_bg

    def _paint_full(self, painter: QPainter, **kwargs) -> None:
        """导出时关闭 ``progressive``，保证一次画完整。"""
        chart = self._chart
        previous = getattr(chart, "_progressive_disabled", False)
        previous_universal = getattr(chart, "_universal_disabled", False)
        chart._progressive_disabled = True
        chart._universal_disabled = True
        try:
            chart._paint_content(painter, **kwargs)
        finally:
            chart._progressive_disabled = previous
            chart._universal_disabled = previous_universal

    def _paint_backgrounds(self, painter: QPainter, width: int, height: int, opts):
        """按层铺底色（alpha 0 的层跳过，免得 SVG 里留一个空矩形）。"""
        for color in self._background_layers(opts):
            if color is not None and color.alpha() > 0:
                painter.fillRect(QRect(0, 0, width, height), color)

    def _render_image(self, opts: dict = None, *, opaque: bool = False) -> QImage:
        """图表内容 → 离屏 ``QImage``（不含子控件）；``opaque`` 时压到主题底。"""
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
            self._paint_full(painter)
        finally:
            painter.end()
        if opaque:
            image = self._flatten(image)
        return image

    def _flatten(self, image: QImage) -> QImage:
        """把带透明度的图压到主题底（JPEG 用）。"""
        canvas = QImage(image.size(), QImage.Format.Format_RGB32)
        canvas.setDevicePixelRatio(image.devicePixelRatio())
        canvas.fill(QColor(T("color.bg.base", self._chart)))
        painter = QPainter(canvas)
        try:
            painter.drawImage(0, 0, image)
        finally:
            painter.end()
        return canvas

    def _svg_data_url(self, opts: dict = None) -> str:
        """矢量图 → ``data:image/svg+xml;base64,...``。"""
        try:
            with tempfile.TemporaryDirectory() as tmp:
                target = str(pathlib.Path(tmp) / "chart.svg")
                if not self._save_svg(target, opts):
                    return ""
                data = pathlib.Path(target).read_bytes()
        except Exception:
            return ""
        if not data:
            return ""
        return "data:image/svg+xml;base64," + base64.b64encode(data).decode("ascii")
