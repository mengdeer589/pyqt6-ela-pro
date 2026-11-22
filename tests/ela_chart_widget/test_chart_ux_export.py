"""空态 / 错误态 / 键盘辅助 / PDF 与打印导出的回归。"""

from __future__ import annotations

import pathlib

from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtPrintSupport import QPrinter

from pyqt6_ela_pro import ElaChartWidget


def _chart(make) -> ElaChartWidget:
    chart = make(ElaChartWidget)
    chart.resize(480, 360)
    chart.setOption(
        {
            "animation": False,
            "xAxis": {"type": "category", "data": ["A", "B", "C"]},
            "yAxis": {"type": "value"},
            "dataZoom": [{"type": "inside", "start": 0, "end": 60}],
            "series": [{"type": "line", "name": "S", "data": [1, 3, 2]}],
        }
    )
    chart.anim.stop()
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    return chart


def test_empty_and_error_text_switch(make):
    chart = make(ElaChartWidget)
    chart.resize(320, 240)
    chart.setOption({"animation": False, "series": []})
    assert chart.emptyText() == ""
    chart.setEmptyText("暂无数据")
    assert chart.emptyText() == "暂无数据"
    assert chart._chart_has_data() is False

    chart.setOption({"series": [{"type": "line", "data": [1, 2]}]})
    assert chart._chart_has_data() is True

    chart.setErrorText("渲染失败")
    assert chart.errorText() == "渲染失败"
    chart.setHighContrast(True)
    assert chart.highContrast() is True
    # 两条状态绘制路径都必须能在绘制回调里安全执行。
    chart.grab()


def test_keyboard_shortcuts(make):
    chart = _chart(make)
    chart.setKeyboardShortcutsEnabled(False)
    assert chart.keyboardShortcutsEnabled() is False
    chart.setKeyboardShortcutsEnabled(True)

    zoom = chart._component("dataZoom")
    assert zoom is not None
    start, end = zoom.start, zoom.end
    event = QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_Minus, Qt.KeyboardModifier.NoModifier
    )
    chart.keyPressEvent(event)
    assert (zoom.start, zoom.end) != (start, end)

    event = QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_Home, Qt.KeyboardModifier.NoModifier
    )
    chart.keyPressEvent(event)
    assert zoom.start == 0.0
    assert zoom.end == 100.0

    # 未知按键交回基类，不影响控件。
    chart.keyPressEvent(
        QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_F12, Qt.KeyboardModifier.NoModifier)
    )


def test_accessibility_defaults(make):
    chart = _chart(make)
    assert chart.accessibleName()
    assert "Home" in chart.accessibleDescription()
    chart.setFocus()
    chart._refresh_accessible_description()
    assert "S" in chart.accessibleDescription()
    chart.grab()


def test_multipage_print(make, tmp_path: pathlib.Path):
    chart = _chart(make)
    chart.resize(480, 1600)
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    target = tmp_path / "multi.pdf"
    printer.setOutputFileName(str(target))
    assert chart.printChart(printer, multiPage=True) is True
    assert target.read_bytes().startswith(b"%PDF")


def test_pdf_export_and_print(make, tmp_path: pathlib.Path):
    chart = _chart(make)
    pdf = tmp_path / "chart.pdf"
    assert chart.saveImage(str(pdf)) == str(pdf)
    assert pdf.read_bytes().startswith(b"%PDF")

    url = chart.getDataURL({"type": "pdf"})
    assert url.startswith("data:application/pdf;base64,")

    chart.resize(480, 1800)
    multi = tmp_path / "multi.pdf"
    assert chart.saveImage(str(multi), multiPage=True) == str(multi)
    assert multi.read_bytes().startswith(b"%PDF")

    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    printed = tmp_path / "printed.pdf"
    printer.setOutputFileName(str(printed))
    assert chart.printChart(printer) is True
    assert printed.exists()


def test_jpeg_quality_export(make, tmp_path: pathlib.Path):
    chart = _chart(make)
    target = tmp_path / "chart.jpg"
    assert chart.saveImage(str(target)) == str(target)
    assert target.read_bytes()[:2] == b"\xff\xd8"
