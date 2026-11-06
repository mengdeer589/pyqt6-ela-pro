"""chat 包结构守卫：层级依赖与方法归属。"""

from __future__ import annotations

import ast
from pathlib import Path

import pyqt6_ela_pro.chat as chat_pkg
from pyqt6_ela_pro.chat import input as input_module
from pyqt6_ela_pro.chat import (
    input_attachments,
    input_completion,
    input_history,
    input_parts,
    input_toolbar,
    widget_input_api,
    widget_queue,
    widget_steer,
    widget_turn,
)
from pyqt6_ela_pro.chat.input import ElaChatInput
from pyqt6_ela_pro.chat.widget import ElaChatWidget

CHAT_DIR = Path(chat_pkg.__file__).parent

#: 目录 / 文件前缀 → 禁止运行时 import 的 chat 子模块
FORBIDDEN_IMPORTS = {
    "blocks/": {"widget", "view", "input", "bubble"},
    "input.py": {"widget", "view", "bubble"},
    "view.py": {"widget", "input"},
    "binder.py": {"widget"},
}


def _module_name(node: ast.AST) -> str:
    if isinstance(node, ast.ImportFrom):
        return (node.module or "").split(".")[-1]
    return ""


def _iter_modules():
    for path in CHAT_DIR.rglob("*.py"):
        rel = path.relative_to(CHAT_DIR).as_posix()
        yield rel, path


def test_layering_has_no_reverse_imports():
    offenders = []
    for rel, path in _iter_modules():
        forbidden = set()
        for prefix, names in FORBIDDEN_IMPORTS.items():
            if rel == prefix or rel.startswith(prefix):
                forbidden |= names
        if not forbidden:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.level:
                name = _module_name(node)
                if name in forbidden:
                    offenders.append(f"{rel}:{node.lineno} -> {name}")
    assert not offenders, offenders


def test_method_ownership():
    assert ElaChatWidget.enqueueMessage.__module__ == widget_queue.__name__
    assert ElaChatWidget.steerMessage.__module__ == widget_steer.__name__
    assert ElaChatWidget.sendUserMessage.__module__ == widget_turn.__name__
    assert ElaChatWidget.mentions.__module__ == widget_input_api.__name__

    assert ElaChatInput.openMentionPopup.__module__ == input_completion.__name__
    assert ElaChatInput.addAttachment.__module__ == input_attachments.__name__
    assert ElaChatInput.draftState.__module__ == input_history.__name__
    assert ElaChatInput.setContextUsage.__module__ == input_toolbar.__name__
    assert input_parts._ChatPlainTextEdit.__module__ == input_parts.__name__
    assert input_module.ElaChatInput is ElaChatInput


def test_binder_does_not_load_widget_at_runtime():
    path = CHAT_DIR / "binder.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    runtime = [
        node.lineno
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
        and node.level
        and _module_name(node) == "widget"
    ]
    assert not runtime, runtime
