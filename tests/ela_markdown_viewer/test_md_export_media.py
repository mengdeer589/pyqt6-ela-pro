"""Tests for ElaMarkdownViewer media interactions and exports (P3/P4).

Covers: math CJK font fallback, formula / Mermaid click copy, image
save-as, PDF export parameters, printing and ``toHtml(embedImages=True)``.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from _qthelpers import wait_for_clipboard as _wait_for_clipboard
from _qthelpers import wait_until as _wait
from PyQt6.QtGui import QImage, QTextCursor
from PyQt6.QtPrintSupport import QPrinter

from pyqt6_ela_pro import ela_markdown_viewer as viewer_module
from pyqt6_ela_pro import math_lite
from pyqt6_ela_pro.ela_markdown_viewer import ElaMarkdownViewer


def _image_fragments(viewer: ElaMarkdownViewer) -> list:
    result = []
    block = viewer.document().begin()
    while block.isValid():
        iterator = block.begin()
        while not iterator.atEnd():
            fragment = iterator.fragment()
            if fragment.isValid() and fragment.charFormat().isImageFormat():
                result.append(fragment)
            iterator += 1
        block = block.next()
    return result


def _set_cursor_after(viewer: ElaMarkdownViewer, fragment) -> None:
    cursor = QTextCursor(viewer.document())
    cursor.setPosition(fragment.position() + 1)
    viewer.textBrowser().setTextCursor(cursor)


class TestMathFontFallback:
    def test_cjk_families_appended(self):
        font = math_lite._font(12.0)
        families = font.families()
        if math_lite._math_families():
            assert families[0] == math_lite._math_families()[0]
            assert "Microsoft YaHei UI" in families


class TestClickCopy:
    def test_formula_click_copies_latex(self, qapp, requires_clipboard):
        v = ElaMarkdownViewer()
        v.setMarkdown(r"公式 $x^2$ 结束")
        fragment = _image_fragments(v)[0]
        _set_cursor_after(v, fragment)

        received = []
        v.formulaCopied.connect(received.append)
        v._on_image_clicked(fragment.position() + 1)
        qapp.processEvents()

        assert received == ["x^2"]
        assert (
            _wait_for_clipboard(
                qapp, "x^2", lambda: v._on_image_clicked(fragment.position() + 1)
            )
            == "x^2"
        )
        v.deleteLater()

    def test_mermaid_click_copies_source(self, qapp, requires_clipboard):
        v = ElaMarkdownViewer()
        v.setMermaidRenderer(
            lambda code, theme: QImage(20, 20, QImage.Format.Format_ARGB32)
        )
        v.setMarkdown("```mermaid\ngraph TD;\nA-->B;\n```")
        assert _wait(qapp, lambda: bool(_image_fragments(v)))

        fragment = _image_fragments(v)[0]
        _set_cursor_after(v, fragment)
        received = []
        v.mermaidCopied.connect(received.append)
        v._on_image_clicked(fragment.position() + 1)
        qapp.processEvents()

        assert received == ["graph TD;\nA-->B;"]
        assert (
            _wait_for_clipboard(
                qapp,
                "graph TD;\nA-->B;",
                lambda: v._on_image_clicked(fragment.position() + 1),
            )
            == "graph TD;\nA-->B;"
        )
        v.deleteLater()

    def test_plain_image_click_still_emits_url(self, qapp, tmp_path):
        path = tmp_path / "click.png"
        QImage(8, 8, QImage.Format.Format_ARGB32).save(str(path))
        v = ElaMarkdownViewer()
        v.setMarkdown("![图片](%s)" % str(path).replace("\\", "/"))
        fragment = _image_fragments(v)[0]
        _set_cursor_after(v, fragment)

        received = []
        v.imageClicked.connect(received.append)
        v._on_image_clicked(fragment.position() + 1)
        qapp.processEvents()

        assert received and received[0].startswith("file:")
        assert "click.png" in received[0]
        v.deleteLater()


class TestImageSave:
    def _prepare(self, tmp_path):
        path = tmp_path / "src.png"
        image = QImage(6, 6, QImage.Format.Format_ARGB32)
        image.fill(0xFF336699)
        image.save(str(path))
        v = ElaMarkdownViewer()
        v.setMarkdown("![图](%s)" % str(path).replace("\\", "/"))
        return v, path

    def test_local_path_detected(self, qapp, tmp_path):
        v, path = self._prepare(tmp_path)
        fragment = _image_fragments(v)[0]
        _set_cursor_after(v, fragment)
        assert Path(v._image_local_path_at_cursor()) == path
        v.deleteLater()

    def test_math_image_has_no_local_path(self):
        v = ElaMarkdownViewer()
        v.setMarkdown(r"$\alpha$")
        fragment = _image_fragments(v)[0]
        _set_cursor_after(v, fragment)
        assert v._image_local_path_at_cursor() == ""
        v.deleteLater()

    def test_menu_action_enabled_only_on_local_image(self):
        v = ElaMarkdownViewer()
        v.setMarkdown("普通文本")
        menu = v._create_context_menu()
        actions = {action.text(): action for action in menu.actions()}
        assert "图片另存为…" in actions
        assert not actions["图片另存为…"].isEnabled()
        menu.deleteLater()
        v.deleteLater()

    def test_save_image_writes_file(self, qapp, tmp_path, monkeypatch):
        v, _path = self._prepare(tmp_path)
        fragment = _image_fragments(v)[0]
        _set_cursor_after(v, fragment)
        target = tmp_path / "out.png"
        monkeypatch.setattr(
            viewer_module,
            "QFileDialog",
            SimpleNamespace(getSaveFileName=lambda *args, **kwargs: (str(target), "")),
        )
        v._save_image_at_cursor()
        assert target.exists()
        assert not QImage(str(target)).isNull()
        v.deleteLater()


class TestExportPdf:
    SOURCE = "# 标题\n\n正文 $x^2$"

    def test_default_export(self, qapp, tmp_path):
        v = ElaMarkdownViewer()
        v.setMarkdown(self.SOURCE)
        path = tmp_path / "default.pdf"
        assert v.exportPdf(str(path))
        assert path.stat().st_size > 0
        v.deleteLater()

    def test_custom_page_size_and_margins(self, qapp, tmp_path):
        v = ElaMarkdownViewer()
        v.setMarkdown(self.SOURCE)
        path = tmp_path / "letter.pdf"
        assert v.exportPdf(str(path), pageSize="Letter", marginsMm=(10, 20, 10, 20))
        assert path.stat().st_size > 0
        v.deleteLater()

    def test_invalid_page_name_falls_back(self, qapp, tmp_path):
        v = ElaMarkdownViewer()
        v.setMarkdown(self.SOURCE)
        path = tmp_path / "fallback.pdf"
        assert v.exportPdf(str(path), pageSize="NOT-A-PAGE")
        assert path.stat().st_size > 0
        v.deleteLater()

    def test_empty_path_fails(self):
        v = ElaMarkdownViewer()
        assert not v.exportPdf("")
        v.deleteLater()


class TestPrintDocument:
    def test_print_to_pdf_printer(self, qapp, tmp_path):
        v = ElaMarkdownViewer()
        v.setMarkdown("# 打印测试\n\n正文")
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        output = tmp_path / "print.pdf"
        printer.setOutputFileName(str(output))
        assert v.printDocument(printer)
        assert output.stat().st_size > 0
        v.deleteLater()


class TestHtmlEmbedImages:
    def test_math_embedded_as_data_uri(self, qapp, tmp_path):
        v = ElaMarkdownViewer()
        v.setMarkdown(r"公式 $x^2$")
        html = v.toHtml(embedImages=True)
        assert "elamath://" not in html
        assert "data:image/png;base64," in html
        v.deleteLater()

    def test_local_image_embedded(self, qapp, tmp_path):
        path = tmp_path / "pic.png"
        QImage(5, 5, QImage.Format.Format_ARGB32).save(str(path))
        v = ElaMarkdownViewer()
        v.setMarkdown("![图](%s)" % str(path).replace("\\", "/"))
        html = v.toHtml(embedImages=True)
        assert "data:image/png;base64," in html
        assert "pic.png" not in html
        v.deleteLater()

    def test_default_html_keeps_names(self):
        v = ElaMarkdownViewer()
        v.setMarkdown(r"公式 $x^2$")
        assert "elamath://" in v.toHtml()
        v.deleteLater()
