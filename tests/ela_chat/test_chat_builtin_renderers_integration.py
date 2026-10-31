"""内置渲染器与工具卡集成（metadata → 文件变更 / diff）。"""

from __future__ import annotations

from pyqt6_ela_pro.chat import (
    ElaChatRoleType,
    ElaChatToolCall,
    ElaChatView,
    installBuiltinToolRenderers,
    uninstallBuiltinToolRenderers,
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
