"""``setStickToBottom`` 对 ``setMarkdown`` 全量渲染的滚动语义。

- 默认 True（聊天 / 流式语义）：首开内容仍贴底，追加跟随；
- False（阅读语义）：换新内容回到顶部；同内容重渲 / 切主题 / 改字号保留位置；
  内容先于控件首次显示设置时，首次显示仍从顶部开始（大 / 小文档两条路径）。

旧实现 ``_render()`` 完全忽略 ``_stick_to_bottom``，空文档 ``value == maximum == 0``
又恒判贴底 → 阅读器每次打开文件都被拉到文末。

整体替换文档会把 ``QTextBrowser`` 自己的 widget 光标推到文末；控件还没布局过时，
首次布局 ``ensureCursorVisible`` 到该光标并覆盖 ``bar.setValue(0)`` —— 隐藏预载
（宿主在窗口 ``show()`` 前设内容）曾经因此跳文末。
"""

from __future__ import annotations

from PyQt6.QtCore import Qt

from _qthelpers import wait_until
from pyqt6_ela_pro.ela_markdown_viewer import ElaMarkdownViewer


def _doc(lines: int) -> str:
    return "\n".join(f"line {index}" for index in range(lines)) + "\n"


def _big_doc() -> str:
    """超过 ``_LARGE_RENDER_CHARS``（65536）走分块渲染路径。"""
    text = _doc(9000)
    assert len(text) > 65536
    return text


def _viewer(qapp, make) -> ElaMarkdownViewer:
    viewer = make(ElaMarkdownViewer)
    viewer.resize(600, 400)
    viewer.show()
    qapp.processEvents()
    return viewer


def _hidden_viewer(qapp, make) -> ElaMarkdownViewer:
    """内容在首次布局前设置（宿主在窗口 show 前预载）。"""
    viewer = make(ElaMarkdownViewer)
    viewer.resize(600, 400)
    viewer.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    return viewer


def _bar(viewer):
    return viewer.textBrowser().verticalScrollBar()


def _load(qapp, viewer, text: str) -> None:
    viewer.setMarkdown(text)
    wait_until(qapp, lambda: _bar(viewer).maximum() > 0)


def _load_large(qapp, viewer, text: str) -> None:
    viewer.setMarkdown(text)
    wait_until(qapp, lambda: not viewer._large_render_chunks, timeout_ms=15000)
    wait_until(qapp, lambda: _bar(viewer).maximum() > 0)


def test_default_stick_keeps_bottom(qapp, make):
    viewer = _viewer(qapp, make)
    _load(qapp, viewer, _doc(300))
    wait_until(
        qapp,
        lambda: _bar(viewer).value() == _bar(viewer).maximum(),
    )


def test_reading_mode_starts_at_top(qapp, make):
    viewer = _viewer(qapp, make)
    viewer.setStickToBottom(False)
    _load(qapp, viewer, _doc(300))
    assert _bar(viewer).value() == 0


def test_reading_mode_new_content_returns_to_top(qapp, make):
    viewer = _viewer(qapp, make)
    viewer.setStickToBottom(False)
    _load(qapp, viewer, _doc(300))
    _bar(viewer).setValue(_bar(viewer).maximum())

    _load(qapp, viewer, _doc(500))
    assert _bar(viewer).value() == 0


def test_reading_mode_rerender_preserves_position(qapp, make):
    viewer = _viewer(qapp, make)
    viewer.setStickToBottom(False)
    _load(qapp, viewer, _doc(300))
    _bar(viewer).setValue(50)

    # 改代码折叠行数会触发一次全量 _render（不是 setMarkdown 的换内容路径）
    viewer.setCodeBlockCollapseLines(5)
    qapp.processEvents()
    assert _bar(viewer).value() == 50


def test_reading_mode_same_content_preserves_position(qapp, make):
    viewer = _viewer(qapp, make)
    viewer.setStickToBottom(False)
    source = _doc(300)
    _load(qapp, viewer, source)
    _bar(viewer).setValue(50)

    viewer.setMarkdown(source)
    qapp.processEvents()
    assert _bar(viewer).value() == 50


def test_reading_mode_hidden_small_starts_at_top(qapp, make):
    """首次布局前设内容（宿主 show 前预载）不能跳到文末。"""
    viewer = _hidden_viewer(qapp, make)
    viewer.setStickToBottom(False)
    viewer.setMarkdown(_doc(300))

    viewer.show()
    wait_until(qapp, lambda: _bar(viewer).maximum() > 0)
    assert _bar(viewer).value() == 0


def test_reading_mode_hidden_large_starts_at_top(qapp, make):
    viewer = _hidden_viewer(qapp, make)
    viewer.setStickToBottom(False)
    viewer.setMarkdown(_big_doc())
    wait_until(qapp, lambda: not viewer._large_render_chunks, timeout_ms=15000)

    viewer.show()
    wait_until(qapp, lambda: _bar(viewer).maximum() > 0)
    assert _bar(viewer).value() == 0


def test_reading_mode_hidden_after_stick_switch_starts_at_top(qapp, make):
    """宿主先 setMarkdown 再 setStickToBottom(False) 的顺序也要回顶部。"""
    viewer = _hidden_viewer(qapp, make)
    viewer.setMarkdown(_doc(300))
    viewer.setStickToBottom(False)

    viewer.show()
    wait_until(qapp, lambda: _bar(viewer).maximum() > 0)
    assert _bar(viewer).value() == 0


def test_stick_mode_hidden_content_lands_at_bottom(qapp, make):
    """聊天语义靠 widget 光标在文末贴底：光标复位不能波及 stick=True。"""
    viewer = _hidden_viewer(qapp, make)
    viewer.setMarkdown(_doc(400))

    viewer.show()
    wait_until(qapp, lambda: _bar(viewer).maximum() > 0)
    bar = _bar(viewer)
    assert bar.value() > 0
    assert bar.maximum() - bar.value() < bar.pageStep()


def test_reading_mode_large_new_content_returns_to_top(qapp, make):
    viewer = _viewer(qapp, make)
    viewer.setStickToBottom(False)
    text = _big_doc()
    _load_large(qapp, viewer, text)
    _bar(viewer).setValue(_bar(viewer).maximum() // 2)
    assert _bar(viewer).value() > 0

    _load_large(qapp, viewer, text + "\n## tail\n")
    assert _bar(viewer).value() == 0


def test_reading_mode_large_same_content_preserves_position(qapp, make):
    """分块路径也必须保留同内容重渲的位置（document.clear() 会把 bar 夹到 0）。"""
    viewer = _viewer(qapp, make)
    viewer.setStickToBottom(False)
    text = _big_doc()
    _load_large(qapp, viewer, text)
    bar = _bar(viewer)
    bar.setValue(bar.maximum() // 2)
    middle = bar.value()
    assert middle > 0

    _load_large(qapp, viewer, text)
    assert bar.value() == min(middle, bar.maximum())
