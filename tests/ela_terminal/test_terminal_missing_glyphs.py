"""终端缺字形兜底（bug #20）：只改字体族、不改文本。

与查看器共用 ``_internal.applyMissingGlyphFonts``；终端是增量渲染，额外验证
尾行 ``\\r`` 重写与裁头（``maxLines``）后水位线不漏新内容。
"""

from __future__ import annotations

import pytest
from _qthelpers import wait_until as _wait_until

from pyqt6_ela_pro._internal import missingGlyphFont, system_cjk_font_family
from pyqt6_ela_pro.terminal_view import ElaTerminalView

_ARROW = "\u2194"


def _families_for(view, char: str) -> list:
    """返回文档里所有等于 ``char`` 的片段的字体族（去重后按出现顺序）。"""
    return _families_containing(view, char, exact=True)


def _families_containing(view, char: str, exact: bool = False) -> list:
    found: list = []
    document = view._edit.document()
    block = document.firstBlock()
    while block.isValid():
        iterator = block.begin()
        while not iterator.atEnd():
            fragment = iterator.fragment()
            if fragment.isValid() and (
                fragment.text() == char if exact else char in fragment.text()
            ):
                families = list(fragment.charFormat().fontFamilies() or [])
                if families not in found:
                    found.append(families)
            iterator += 1
        block = block.next()
    return found


def _pump(qapp, view, expected: str) -> None:
    assert _wait_until(qapp, lambda: expected in view.toPlainText())
    qapp.processEvents()


@pytest.fixture
def terminal(make, qapp):
    view = make(ElaTerminalView)
    view.resize(700, 360)
    view.show()
    qapp.processEvents()
    if system_cjk_font_family() is None:
        pytest.skip("非中文系统（缺字形兜底默认关闭）")
    if missingGlyphFont(_ARROW) is None:
        pytest.skip("本机没有覆盖 U+2194 的候选符号字体")
    return view


def test_missing_glyph_gets_single_symbol_font(terminal, qapp):
    terminal.append(f"a {_ARROW} b\n")
    _pump(qapp, terminal, _ARROW)

    assert terminal.missingGlyphFallbackEnabled() is True
    assert _families_for(terminal, _ARROW) == [[missingGlyphFont(_ARROW)]]
    assert _ARROW in terminal.toPlainText()


def test_tail_rewrite_keeps_guard(terminal, qapp):
    terminal.append(f"tail {_ARROW}")
    _pump(qapp, terminal, _ARROW)
    assert _families_for(terminal, _ARROW) == [[missingGlyphFont(_ARROW)]]

    terminal.append("\rtail 50%")
    _pump(qapp, terminal, "tail 50%")
    assert _ARROW not in terminal.toPlainText()


def test_trim_does_not_lose_guard_for_new_lines(terminal, qapp):
    terminal.setMaxLines(2)
    terminal.append("one\n")
    terminal.append("two\n")
    terminal.append(f"three {_ARROW}\n")
    _pump(qapp, terminal, _ARROW)
    assert _families_for(terminal, _ARROW) == [[missingGlyphFont(_ARROW)]]

    # 裁头后所有位置左移，水位线必须跟着调整，否则新行的缺字不会被处理
    terminal.append(f"four {_ARROW}\n")
    _pump(qapp, terminal, "four")
    assert _families_for(terminal, _ARROW) == [[missingGlyphFont(_ARROW)]]
    assert "one" not in terminal.toPlainText()


def test_disable_rerenders_existing_text(terminal, qapp):
    terminal.append(f"a {_ARROW} b\n")
    _pump(qapp, terminal, _ARROW)
    assert _families_for(terminal, _ARROW) == [[missingGlyphFont(_ARROW)]]

    terminal.setMissingGlyphFallbackEnabled(False)
    qapp.processEvents()
    assert _families_containing(terminal, _ARROW) == [[]]
    assert _ARROW in terminal.toPlainText()
