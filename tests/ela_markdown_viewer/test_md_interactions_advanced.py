"""Tests for ElaMarkdownViewer P3 interaction enhancements.

Covers: image click signal, clickable task list items.
"""

from __future__ import annotations

from PyQt6.QtCore import QEvent, QPointF, Qt, QUrl
from PyQt6.QtGui import QColor, QImage, QMouseEvent, QTextCursor
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from pyqt6_ela_pro.ela_markdown_viewer import ElaMarkdownViewer


def _fragments(viewer: ElaMarkdownViewer) -> list:
    result = []
    block = viewer.document().begin()
    while block.isValid():
        iterator = block.begin()
        while not iterator.atEnd():
            fragment = iterator.fragment()
            if fragment.isValid():
                result.append(fragment)
            iterator += 1
        block = block.next()
    return result


def _make_image(tmp_path) -> str:
    image = QImage(80, 40, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    path = tmp_path / "click.png"
    image.save(str(path))
    return str(path)


def _send_click(viewport, x, y, release_dx=0):
    press = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(x, y),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(viewport, press)
    release = QMouseEvent(
        QEvent.Type.MouseButtonRelease,
        QPointF(x + release_dx, y),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(viewport, release)


class TestImageClick:
    def _prepare(self, qapp, tmp_path):
        _make_image(tmp_path)
        v = ElaMarkdownViewer()
        v.resize(420, 320)
        v.setBaseUrl(str(tmp_path))
        v.setMarkdown("![图](click.png)\n\n正文")
        v.show()
        qapp.processEvents()
        QTest.qWait(200)
        return v

    def _image_point(self, v):
        for fragment in _fragments(v):
            if fragment.charFormat().isImageFormat():
                cursor = QTextCursor(v.document())
                cursor.setPosition(fragment.position())
                rect = v.textBrowser().cursorRect(cursor)
                return rect.center()
        raise AssertionError("image not found")

    def test_click_emits_resolved_url(self, qapp, tmp_path):
        v = self._prepare(qapp, tmp_path)
        received = []
        v.imageClicked.connect(received.append)
        point = self._image_point(v)

        _send_click(v.textBrowser().viewport(), point.x(), point.y())
        qapp.processEvents()
        assert received
        assert received[0].startswith("file:")
        assert "click.png" in received[0]
        v.close()
        v.deleteLater()

    def test_drag_does_not_emit(self, qapp, tmp_path):
        v = self._prepare(qapp, tmp_path)
        received = []
        v.imageClicked.connect(received.append)
        point = self._image_point(v)

        _send_click(v.textBrowser().viewport(), point.x(), point.y(), release_dx=40)
        qapp.processEvents()
        assert received == []
        v.close()
        v.deleteLater()

    def test_formula_click_ignored(self, qapp):
        v = ElaMarkdownViewer()
        v.resize(420, 320)
        v.setMarkdown("公式 $x^2$ 结束")
        v.show()
        qapp.processEvents()
        QTest.qWait(150)
        received = []
        v.imageClicked.connect(received.append)
        point = self._image_point(v)

        _send_click(v.textBrowser().viewport(), point.x(), point.y())
        qapp.processEvents()
        assert received == []
        v.close()
        v.deleteLater()


class TestTaskToggle:
    SOURCE = "- [ ] 待办一\n- [x] 已完成二"

    def test_click_toggles_source_and_signal(self):
        v = ElaMarkdownViewer()
        v.setMarkdown(self.SOURCE)
        assert "☑" in v.document().toPlainText()

        received = []
        v.taskToggled.connect(lambda index, checked: received.append((index, checked)))
        v._on_anchor_clicked(QUrl("#elatask-1"))

        assert received == [(1, False)]
        assert v.markdown() == "- [ ] 待办一\n- [ ] 已完成二"
        assert "☑" not in v.document().toPlainText()
        v.deleteLater()

    def test_toggle_back(self):
        v = ElaMarkdownViewer()
        v.setMarkdown(self.SOURCE)
        v._on_anchor_clicked(QUrl("#elatask-0"))
        assert v.markdown() == "- [x] 待办一\n- [x] 已完成二"

        v._on_anchor_clicked(QUrl("#elatask-0"))
        assert v.markdown() == "- [ ] 待办一\n- [x] 已完成二"
        v.deleteLater()

    def test_marker_uses_list_color(self):
        """勾选框跟随主题 ``list`` 色（旧实现钉死正文色，不跟主题切换）。

        任务项整行是 anchor，文字会拿到链接色，所以勾选框必须单独取色区分；
        取 ``list`` 色既跟主题走，又与链接色区分得开（solarized 这类
        ``list`` 与 ``link`` 同色的主题除外，那是主题自身的设计）。
        """
        v = ElaMarkdownViewer()
        v.setMarkdown(self.SOURCE)
        markers = [f for f in _fragments(v) if f.text().strip() in ("☑", "☐")]
        assert markers
        for fragment in markers:
            assert (
                fragment.charFormat().foreground().color().name()
                == v._md_list_color.name()
            )
        v.deleteLater()

    def test_streaming_ignores_toggle(self):
        v = ElaMarkdownViewer()
        v.beginStream()
        v.appendMarkdown(self.SOURCE)
        v._stream_timer.stop()
        v._flush_stream()

        received = []
        v.taskToggled.connect(lambda index, checked: received.append((index, checked)))
        v._on_anchor_clicked(QUrl("#elatask-0"))
        assert received == []
        v.endStream()
        v.deleteLater()
