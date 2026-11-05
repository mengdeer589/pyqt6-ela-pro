"""Markdown 查看器包结构守卫：实现分块归属与公共入口兼容。"""

from __future__ import annotations

import ast
from pathlib import Path

import pyqt6_ela_pro.ela_markdown_viewer as shim
from pyqt6_ela_pro.markdown_viewer import (
    appearance,
    code,
    export,
    interaction,
    media,
    mermaid,
    paint,
    preprocess,
    render,
    selection,
    stream,
    syntax,
    text_browser,
    themes,
    tokens,
    viewer,
)

MODULES = (
    viewer,
    themes,
    tokens,
    syntax,
    code,
    paint,
    export,
    stream,
    mermaid,
    media,
    preprocess,
    render,
    interaction,
    appearance,
    selection,
    text_browser,
)


def test_public_entry_points_share_one_class():
    assert shim.ElaMarkdownViewer is viewer.ElaMarkdownViewer
    for name in (
        "defaultMarkdownTheme",
        "markdownThemes",
        "registerMarkdownTheme",
        "setDefaultMarkdownTheme",
        "unregisterMarkdownTheme",
    ):
        assert getattr(shim, name) is getattr(themes, name)


def test_implementation_blocks_live_in_their_module():
    owner = {
        "_insert_fenced_code": code,
        "_paint_code_line_numbers": paint,
        "exportPdf": export,
        "toHtml": export,
        "beginStream": stream,
        "_embed_mermaid": mermaid,
        "_apply_images": media,
        "_preprocess": preprocess,
        "_render_into_stages": render,
        "searchText": interaction,
        "_applyThemeStyle": appearance,
        "markdownSelection": selection,
        "_ElaTextBrowser": text_browser,
    }
    for name, module in owner.items():
        target = getattr(viewer.ElaMarkdownViewer, name, None) or getattr(module, name)
        assert target.__module__ == module.__name__
    assert syntax._stable_cut.__module__ == syntax.__name__
    assert themes.markdownThemes.__module__ == themes.__name__
    assert isinstance(tokens._CODE_MARKER, int)


def test_submodules_do_not_import_viewer():
    """除兼容 shim 外，各实现模块只允许单向依赖，避免循环导入。"""
    offenders = []
    for module in MODULES:
        path = Path(module.__file__)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                target = node.module or ""
                if target == "viewer" or target.endswith(".viewer"):
                    offenders.append(f"{path.name}:{node.lineno}")
    assert not offenders, offenders
