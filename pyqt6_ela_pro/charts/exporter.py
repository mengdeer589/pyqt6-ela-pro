"""图表导出（PNG / JPEG / SVG / data URL）。

从 ``ElaChartWidget`` 拆出的纯导出逻辑：不拥有绘图状态，只读画布当前
option / 几何与子控件，导出前后恢复临时隐藏的工具条按钮。
"""

from __future__ import annotations

import base64
import pathlib
import tempfile
from typing import TYPE_CHECKING

from PyQt6.QtCore import QBuffer, QIODevice, QRect, QSize, Qt
from PyQt6.QtGui import QColor, QGuiApplication, QImage, QPainter
from PyQt6.QtWidgets import QFileDialog

from .._internal import is_deleted
from ._tokens import T

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
            image = self._grab_without_toolbox().toImage()
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
        background = opts.get("backgroundColor")
        if background or fmt == "jpeg":
            canvas = QImage(image.size(), QImage.Format.Format_RGB32)
            canvas.fill(
                QColor(background) if background else QColor(T("color.bg.base"))
            )
            painter = QPainter(canvas)
            painter.drawImage(0, 0, image)
            painter.end()
            image = canvas
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
            if self._grab_without_toolbox().save(target, "PNG"):
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
                painter.fillRect(QRect(0, 0, width, height), QColor(T("color.bg.base")))
                chart._paint_content(painter)
            finally:
                painter.end()
            return target
        except Exception:
            return ""

    def _toolbox_widgets(self) -> list:
        """工具条按钮子控件（导出时临时隐藏用）。"""
        result = []
        for component in self._chart._components:
            if str(getattr(component, "optionKey", "")) != "toolbox":
                continue
            widgets = getattr(component, "_widgets", None)
            if isinstance(widgets, dict):
                result.extend(
                    widget
                    for widget in list(widgets.values())
                    if not is_deleted(widget)
                )
        return result

    def _grab_without_toolbox(self):
        """``grab()`` 前隐藏工具条按钮：导出 / 截图要的是图，不是 UI。"""
        buttons = self._toolbox_widgets()
        hidden = [button for button in buttons if button.isVisible()]
        for button in hidden:
            button.setVisible(False)
        try:
            return self._chart.grab()
        finally:
            for button in hidden:
                button.setVisible(True)

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
