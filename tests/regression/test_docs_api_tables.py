"""chat 文档 / 导出面守卫（README、chat_guide_page 与 __all__ 不漂移）。"""

from __future__ import annotations

from pathlib import Path

import pyqt6_ela_pro.chat as chat

_ROOT = Path(__file__).resolve().parents[2]
_GUIDE = _ROOT / "pyqt6_ela_pro" / "example" / "chat_guide_page.py"
_DOC = _ROOT / "docs" / "chat.md"


def test_chat_exports_resolve_and_are_unique():
    assert len(chat.__all__) == len(set(chat.__all__))
    for name in set(chat.__all__) | set(chat._LAZY_ATTRS):
        assert getattr(chat, name) is not None, name


def test_chat_guide_mentions_public_components():
    text = _GUIDE.read_text(encoding="utf-8")
    required = (
        "ElaChatWidget",
        "ElaChatView",
        "ElaChatInput",
        "ElaChatBubble",
        "ElaChatMessage",
        "ElaChatPart",
        "ElaChatPermission",
        "ElaChatQuestion",
        "ElaChatOption",
        "ElaChatPlan",
        "ElaChatStats",
        "ElaChatTurnJournal",
        "ElaChatStreamBinder",
        "ElaChatAsyncWorker",
        "ElaChatMockBackend",
        "ElaChatSessionInfo",
        "ElaChatSessionStats",
        "ElaChatSearchBar",
        "ElaChatSearchHit",
        "ElaChatSelector",
        "ElaChatQueueDock",
        "ElaChatPermissionDock",
        "ElaChatTracePanel",
        "ElaChatTraceOptions",
        "ElaChatFileChanges",
    )
    missing = [name for name in required if name not in text]
    assert not missing, f"chat_guide_page 缺少：{missing}"


def test_removed_api_tokens_stay_out_of_docs():
    text = _DOC.read_text(encoding="utf-8")
    for token in ("reorderRequested", "snippet", "deadline"):
        assert token not in text, f"docs/chat.md 仍提到已删除的 {token}"
