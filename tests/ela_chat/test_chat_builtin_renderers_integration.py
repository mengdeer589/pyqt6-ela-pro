"""内置渲染器与工具卡集成（metadata → 文件变更 / diff / 统一外观）。"""

from __future__ import annotations

import json

from PyQt6.QtGui import QColor, QImage
from _qthelpers import wait_until as _wait_until

from pyqt6_ela_pro.chat import (
    ElaChatRoleType,
    ElaChatToolCall,
    ElaChatView,
    installBuiltinToolRenderers,
    uninstallBuiltinToolRenderers,
)
from pyqt6_ela_pro.chat.renderers_builtin import (
    BODY_CODE_FONT_PX,
    LIST_MAX_HEIGHT,
    MCP_MAX_HEIGHT,
    _EmptyBody,
    _ImageBody,
    _ShellBody,
)
from pyqt6_ela_pro.ela_diff_view import ElaDiffView


class TestBuiltinRendererIntegration:
    def test_edit_metadata_builds_diff(self, qapp, make):
        installBuiltinToolRenderers()
        try:
            view = make(ElaChatView)
            mid = view.beginMessage(ElaChatRoleType.Assistant)
            patch = "--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-x\n+y\n"
            call = ElaChatToolCall(
                id="t1",
                name="edit",
                arguments='{"path":"a.py"}',
                metadata={
                    "files": [
                        {
                            "file": "a.py",
                            "patch": patch,
                            "additions": 1,
                            "deletions": 1,
                        }
                    ]
                },
                status="done",
            )
            bubble = view.bubble(mid)
            call_id = bubble.addToolCall("edit", "", toolCallId="t1", tool_call=call)
            card = bubble._tool_cards[call_id]
            card.setOpened(True)
            qapp.processEvents()
            assert bubble.findChildren(ElaDiffView)
        finally:
            uninstallBuiltinToolRenderers()


class TestExtraBuiltinRenderers:
    def _build(self, make, name, arguments, result, status="done"):
        view = make(ElaChatView)
        mid = view.beginMessage(ElaChatRoleType.Assistant)
        call = ElaChatToolCall(
            id="t1",
            name=name,
            arguments=arguments,
            result=result,
            status=status,
        )
        bubble = view.bubble(mid)
        call_id = bubble.addToolCall(name, arguments, toolCallId="t1", tool_call=call)
        card = bubble._tool_cards[call_id]
        card.setOpened(True)
        return card

    def test_read_search_fetch_mcp(self, qapp, make):
        installBuiltinToolRenderers()
        try:
            card = self._build(make, "read", '{"path":"a.py"}', "line1\nline2")
            assert card._renderer_widget is not None
            card = self._build(make, "grep", '{"pattern":"x"}', "a.py:1:x")
            assert card._renderer_widget is not None
            card = self._build(make, "fetch", '{"url":"https://x"}', "hello")
            assert card._renderer_widget is not None
            card = self._build(make, "mcp", "{}", '{"a": 1}')
            assert card._renderer_widget is not None
        finally:
            uninstallBuiltinToolRenderers()

    def test_todo_uses_plan_list(self, qapp, make):
        installBuiltinToolRenderers()
        try:
            card = self._build(
                make,
                "todowrite",
                '{"todos":[{"content":"a","status":"done"},'
                '{"content":"b","status":"in_progress"}]}',
                "ok",
            )
            widget = card._renderer_widget
            assert widget is not None
            assert widget.plan().progress() == (1, 2)
        finally:
            uninstallBuiltinToolRenderers()

    def test_install_and_uninstall_includes_new_names(self, qapp):
        installed = installBuiltinToolRenderers()
        try:
            for name in ("read", "grep", "fetch", "mcp", "todowrite"):
                assert name in installed
        finally:
            removed = uninstallBuiltinToolRenderers()
        assert "read" in removed
        assert "todowrite" in removed


class TestBuiltinRendererStyle:
    def _open(self, qapp, make, name, arguments, result, status="done"):
        view = make(ElaChatView)
        mid = view.beginMessage(ElaChatRoleType.Assistant)
        call = ElaChatToolCall(
            id="t1",
            name=name,
            arguments=arguments,
            result=result,
            status=status,
        )
        bubble = view.bubble(mid)
        call_id = bubble.addToolCall(name, arguments, toolCallId="t1", tool_call=call)
        card = bubble._tool_cards[call_id]
        view.resize(900, 700)
        view.show()
        qapp.processEvents()
        card.setOpened(True)
        qapp.processEvents()
        return card

    def test_text_body_is_embedded_and_starts_at_top(self, qapp, make):
        installBuiltinToolRenderers()
        try:
            text = "\n".join(f"line {i}" for i in range(120))
            card = self._open(qapp, make, "read", '{"path":"a.py"}', text)
            qapp.processEvents()
            body = card._renderer_widget
            assert isinstance(body, _ShellBody)
            assert body.embedded() is True
            assert body.fontSize() == BODY_CODE_FONT_PX
            assert body.autoScroll() is False
            for _ in range(4):
                qapp.processEvents()
            bar = body._edit.verticalScrollBar()
            assert bar.maximum() > 0
            assert bar.value() == 0
        finally:
            uninstallBuiltinToolRenderers()

    def test_late_unified_diff_updates_file_changes(self, qapp, make):
        installBuiltinToolRenderers()
        try:
            card = self._open(qapp, make, "edit", '{"path":"a.py"}', "")
            body = card._renderer_widget
            assert body.files() == []
            patch = "--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-x\n+y\n"
            card.setResult(patch, ok=True)
            assert [item.path for item in body.files()] == ["a.py"]
        finally:
            uninstallBuiltinToolRenderers()

    def test_empty_text_result_uses_empty_body(self, qapp, make):
        installBuiltinToolRenderers()
        try:
            card = self._open(qapp, make, "grep", '{"pattern":"x"}', "  \n")
            assert isinstance(card._renderer_widget, _EmptyBody)
        finally:
            uninstallBuiltinToolRenderers()

    def test_json_result_is_pretty_printed(self, qapp, make):
        installBuiltinToolRenderers()
        try:
            card = self._open(qapp, make, "mcp", "{}", '{"a":1,"b":[2,3]}')
            body = card._renderer_widget
            assert isinstance(body, _ShellBody)
            assert '  "a": 1' in body.toPlainText()
            assert body.maximumHeight() == MCP_MAX_HEIGHT
        finally:
            uninstallBuiltinToolRenderers()

    def test_glob_body_gets_more_height(self, qapp, make):
        """glob 行数多，body 上限要比普通文本高，避免一打开就内部滚动。"""
        installBuiltinToolRenderers()
        try:
            text = "\n".join(f"demo_{i}.py" for i in range(80))
            card = self._open(qapp, make, "glob", '{"pattern":"*.py"}', text)
            body = card._renderer_widget
            assert isinstance(body, _ShellBody)
            assert body.maximumHeight() == LIST_MAX_HEIGHT
        finally:
            uninstallBuiltinToolRenderers()

    def test_short_results_have_no_inner_scrollbar(self, qapp, make):
        """短结果贴合内容高度：不能差 2px 就冒出竖向滚动条。"""
        from pyqt6_ela_pro.chat.renderers_builtin import _text_body

        for result, max_height in (
            ("demo.py\nchat.py", LIST_MAX_HEIGHT),
            ('{"tools":["read_file"]}', MCP_MAX_HEIGHT),
        ):
            body = make(_text_body, result, 400, max_height=max_height)
            body.resize(600, body.sizeHint().height())
            body.show()
            assert _wait_until(
                qapp,
                lambda: body._edit.verticalScrollBar().maximum() == 0,
            )

    def test_image_preview_is_not_upscaled(self, qapp, make, tmp_path):
        path = tmp_path / "tiny.png"
        image = QImage(20, 10, QImage.Format.Format_ARGB32)
        image.fill(QColor("#ff0000"))
        assert image.save(str(path))
        installBuiltinToolRenderers()
        try:
            card = self._open(qapp, make, "read", json.dumps({"path": str(path)}), "")
            body = card._renderer_widget
            assert isinstance(body, _ImageBody)
            assert (body.width(), body.height()) == (20, 10)
        finally:
            uninstallBuiltinToolRenderers()
