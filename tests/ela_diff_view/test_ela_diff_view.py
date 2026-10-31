"""diff 纯模型 / ElaDiffView / 文件变更卡。"""

from __future__ import annotations

from PyQt6.QtGui import QPalette

from pyqt6_ela_pro._diff import (
    DIFF_ADD,
    DIFF_CONTEXT,
    DIFF_DEL,
    diffFileFromAny,
    diffLines,
    parseUnifiedDiff,
)
from pyqt6_ela_pro.chat import (
    ElaChatFileChanges,
    ToolRenderContext,
    cleanAnsi,
    installBuiltinToolRenderers,
    toolRenderer,
    uninstallBuiltinToolRenderers,
)
from pyqt6_ela_pro.ela_diff_view import ElaDiffView

SAMPLE = """diff --git a/a.py b/a.py
index 1111111..2222222 100644
--- a/a.py
+++ b/a.py
@@ -1,4 +1,5 @@
 line1
-old
+new
+new2
 line3
 line4
diff --git a/b.py b/b.py
--- a/b.py
+++ b/b.py
@@ -1,2 +1,1 @@
 keep
-gone
"""


class TestDiffModel:
    def test_parse_multi_file(self):
        files = parseUnifiedDiff(SAMPLE)
        assert [item.path for item in files] == ["a.py", "b.py"]
        assert files[0].additions == 2
        assert files[0].deletions == 1
        assert files[1].additions == 0
        assert files[1].deletions == 1
        kinds = [line.kind for line in files[0].lines]
        assert "hunk" in kinds
        assert kinds.count(DIFF_ADD) == 2
        assert kinds.count(DIFF_DEL) == 1
        assert kinds.count(DIFF_CONTEXT) == 3

    def test_parse_invalid_returns_empty(self):
        assert parseUnifiedDiff("not a diff") == []
        assert parseUnifiedDiff("") == []

    def test_diff_lines(self):
        item = diffLines("a\nb\nc", "a\nB\nc", "x.py")
        assert (item.additions, item.deletions) == (1, 1)
        assert item.status == "modified"
        assert item.lines[1].kind == DIFF_DEL
        assert item.lines[2].kind == DIFF_ADD
        added = diffLines("", "a\nb", "new.py")
        assert added.status == "added"
        assert added.additions == 2
        deleted = diffLines("a\nb", "", "old.py")
        assert deleted.status == "deleted"
        assert deleted.deletions == 2

    def test_metadata_normalization(self):
        item = diffFileFromAny(
            {
                "file": "a.py",
                "patch": "--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-x\n+y\n",
                "additions": 9,
                "deletions": 8,
                "status": "modified",
            }
        )
        assert item is not None
        assert item.path == "a.py"
        assert item.additions == 9
        assert item.deletions == 8
        assert item.line_count == 3


class TestDiffView:
    def test_dark_theme_initializes_dark(self, qapp, make):
        from PyQt6ElaWidgetTools import ElaThemeType, eTheme

        previous = eTheme.getThemeMode()
        try:
            eTheme.setThemeMode(ElaThemeType.ThemeMode.Dark)
            view = make(ElaDiffView)
            assert view._theme_mode == ElaThemeType.ThemeMode.Dark
            assert view._gutter_bg.lightness() < 128
            assert (
                view.viewport().palette().color(QPalette.ColorRole.Base)
                == view._gutter_bg
            )
            widget = make(ElaChatFileChanges)
            widget.setDefaultOpen(False)
            widget.setFiles(parseUnifiedDiff(SAMPLE))
            assert widget._theme_mode == ElaThemeType.ThemeMode.Dark
            from pyqt6_ela_pro._theme import text as text_color

            assert (
                widget._rows[0]["path"].textColor().name()
                == text_color(ElaThemeType.ThemeMode.Dark).name()
            )
        finally:
            eTheme.setThemeMode(previous)

    def test_uses_ela_scrollbars(self, qapp, make):
        from PyQt6ElaWidgetTools import ElaScrollBar

        view = make(ElaDiffView)
        assert isinstance(view.verticalScrollBar(), ElaScrollBar)
        assert isinstance(view.horizontalScrollBar(), ElaScrollBar)

    def test_height_fits_short_diff_and_caps_long_diff(self, qapp, make):
        """短 diff 贴合内容，只有超过最大高度才出现滚动条。"""
        view = make(ElaDiffView)
        view.setMaximumHeight(320)
        view.setFiles(parseUnifiedDiff(SAMPLE))
        view.resize(600, view.sizeHint().height())
        view.show()
        qapp.processEvents()
        assert view.sizeHint().height() < 320
        assert view.verticalScrollBar().maximum() == 0

        long_text = "\n".join(f"line {i}" for i in range(80))
        view.setFiles([diffLines("", long_text, "long.py")])
        qapp.processEvents()
        assert view.sizeHint().height() == 320
        view.resize(600, 320)
        qapp.processEvents()
        assert view.verticalScrollBar().maximum() > 0

    def test_set_files_and_fold(self, qapp, make):
        view = make(ElaDiffView)
        files = parseUnifiedDiff(SAMPLE)
        view.setContextLines(0)
        view.setFiles(files)
        qapp.processEvents()
        assert view.blockCount() == len(view._rows)
        assert view.gutterWidth() > 0
        # 折叠占位行存在时，点击能展开
        folds = [row for row in view._rows if row.fold is not None]
        assert folds
        view.expandAll()
        assert not [row for row in view._rows if row.fold is not None]
        view.collapseAll()
        assert [row for row in view._rows if row.fold is not None]

    def test_large_diff_truncates(self, qapp, make):
        view = make(ElaDiffView)
        item = diffLines("", "\n".join(f"line{i}" for i in range(200)), "big.txt")
        view.setMaxLines(100)
        view.setFiles([item])
        assert view.isTruncated()
        assert view.blockCount() <= 101

    def test_syntax_highlight_toggle(self, qapp, make):
        view = make(ElaDiffView)
        view.setFiles(parseUnifiedDiff(SAMPLE))
        assert view.syntaxHighlightEnabled()
        view.setSyntaxHighlightEnabled(False)
        assert view._spans_by_block == {}
        view.setTokenColors({"keyword": "#ff0000"})
        assert view.syntaxPalette()["keyword"] == "#ff0000"


class TestFileChanges:
    def test_lazy_bodies(self, qapp, make):
        widget = make(ElaChatFileChanges)
        widget.setDefaultOpen(False)
        widget.setFiles(parseUnifiedDiff(SAMPLE))
        qapp.processEvents()
        assert len(widget.findChildren(ElaDiffView)) == 0
        widget.expandAll()
        qapp.processEvents()
        assert len(widget.findChildren(ElaDiffView)) == 2
        widget.collapseAll()
        for body in widget.findChildren(ElaDiffView):
            assert body.isHidden()

    def test_max_visible(self, qapp, make):
        widget = make(ElaChatFileChanges)
        files = [diffLines("", "x", f"f{i}.txt") for i in range(5)]
        widget.setMaxVisible(2)
        widget.setDefaultOpen(False)
        widget.setFiles(files)
        qapp.processEvents()
        assert len(widget.findChildren(ElaDiffView)) == 0
        assert widget._more_button is not None


class TestBuiltinRenderers:
    def test_install_uninstall(self, qapp):
        installed = installBuiltinToolRenderers()
        assert "edit" in installed or toolRenderer("edit") is not None
        assert toolRenderer("shell") is not None
        removed = uninstallBuiltinToolRenderers()
        assert "shell" in removed

    def test_ansi_clean(self):
        assert cleanAnsi("\x1b[31mred\x1b[0m") == "red"
        assert cleanAnsi("10%\r20%\r30%") == "30%"

    def test_shell_body_uses_terminal_view(self, qapp, make):
        from pyqt6_ela_pro.chat import ToolRenderContext
        from pyqt6_ela_pro.chat.renderers_builtin import CONSOLE_MAX_HEIGHT
        from pyqt6_ela_pro.terminal_view import ElaTerminalView

        installBuiltinToolRenderers()
        try:
            factory = toolRenderer("shell")
            assert factory is not None
            body = factory(
                ToolRenderContext(
                    messageId=1,
                    toolCallId="t1",
                    name="shell",
                    arguments='{"command":"echo hi"}',
                    result="\x1b[32mhi\x1b[0m",
                    status="done",
                    isError=False,
                    allowOpenWhilePending=False,
                )
            )
            assert isinstance(body, ElaTerminalView)
            assert not body.toolbarVisible()
            assert not body.lineNumbersVisible()
            make.track(body)

            body.append("line1\nline2\nline3\nline4\n")
            qapp.processEvents()
            body.resize(600, body.sizeHint().height())
            body.show()
            qapp.processEvents()
            assert body.sizeHint().height() < CONSOLE_MAX_HEIGHT
            assert body._edit.verticalScrollBar().maximum() == 0
        finally:
            uninstallBuiltinToolRenderers()

    def test_context_metadata(self):
        ctx = ToolRenderContext(
            messageId=1,
            toolCallId="t1",
            name="edit",
            arguments="{}",
            result="",
            status="done",
            isError=False,
            allowOpenWhilePending=False,
            metadata={"files": [{"file": "a.py", "additions": 1}]},
        )
        assert ctx.metadata["files"][0]["file"] == "a.py"
