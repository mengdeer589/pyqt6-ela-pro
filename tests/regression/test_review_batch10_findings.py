"""回归测试（第十批）：选择器鼠标键、步骤缩容、上传清空、diff token 缓存。"""

from __future__ import annotations

from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication

from pyqt6_ela_pro._diff import parseUnifiedDiff
from pyqt6_ela_pro.ela_diff_view import ElaDiffView
from pyqt6_ela_pro.ela_selector_bar import ElaSelectorBar
from pyqt6_ela_pro.ela_steps import ElaSteps
from pyqt6_ela_pro.ela_upload_area import ElaUploadArea


def _mouse(kind: QEvent.Type, x: float, y: float, button: Qt.MouseButton):
    pos = QPointF(x, y)
    return QMouseEvent(
        kind,
        pos,
        pos,
        button,
        button,
        Qt.KeyboardModifier.NoModifier,
    )


class TestSelectorMouseButtons:
    def test_right_click_does_not_activate(self, qapp):
        bar = ElaSelectorBar()
        bar.addItems(["a", "b"])
        bar.resize(200, 40)
        bar.show()
        qapp.processEvents()
        seen = []
        bar.itemActivated.connect(lambda index, _item: seen.append(index))
        QApplication.sendEvent(
            bar,
            _mouse(QEvent.Type.MouseButtonPress, 20, 20, Qt.MouseButton.RightButton),
        )
        QApplication.sendEvent(
            bar,
            _mouse(QEvent.Type.MouseButtonRelease, 20, 20, Qt.MouseButton.RightButton),
        )
        assert seen == []
        bar.deleteLater()
        qapp.processEvents()


class TestStepsShrink:
    def test_clamping_emits_current_step_changed(self, qapp):
        steps = ElaSteps()
        steps.step_titles = ["a", "b", "c"]
        steps.setCurrentStep(2)
        seen = []
        steps.currentStepChanged.connect(seen.append)
        steps.step_titles = ["a"]
        assert seen == [0]
        assert steps.currentStep() == 0
        steps.deleteLater()
        qapp.processEvents()


class TestUploadClearSignals:
    def test_clear_emits_removed_and_empty_selection(self, qapp):
        area = ElaUploadArea()
        area._file_paths = ["a.txt", "b.py"]
        removed = []
        selected = []
        area.fileRemoved.connect(removed.append)
        area.filesSelected.connect(selected.append)
        area.clearFiles()
        assert removed == ["a.txt", "b.py"]
        assert selected == [[]]
        area.deleteLater()
        qapp.processEvents()


class TestDiffTokenCache:
    def test_expand_does_not_retokenize(self, qapp, monkeypatch):
        from pyqt6_ela_pro import ela_diff_view as module

        calls = []
        original = module._tokenize_lines

        def counted(lines, path):
            calls.append(path)
            return original(lines, path)

        monkeypatch.setattr(module, "_tokenize_lines", counted)
        diff = """diff --git a/a.py b/a.py
--- a/a.py
+++ b/a.py
@@ -1,2 +1,2 @@
-old = 1
+new = 1
 same = 2
"""
        view = ElaDiffView()
        view.setFiles(parseUnifiedDiff(diff))
        first = len(calls)
        assert first > 0
        view.expandAll()
        assert len(calls) == first
        view.deleteLater()
        qapp.processEvents()
