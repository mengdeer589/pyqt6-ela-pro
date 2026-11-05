"""分块渲染期间切样式不得重复追加内容。"""

from __future__ import annotations

from _qthelpers import wait_until

from pyqt6_ela_pro.ela_markdown_viewer import (
    _LARGE_RENDER_CHARS,
    ElaMarkdownViewer,
)

_MARK = "唯一标记标题"
_CHUNK = "分块渲染取消验证段落，包含普通文本与 **加粗**。"


def _large_source() -> str:
    source = f"# {_MARK}\n\n" + "\n\n".join(
        _CHUNK * 12 for _ in range(400)
    )
    assert len(source) > _LARGE_RENDER_CHARS
    return source


def test_style_change_cancels_in_flight_chunked_render(qapp, make):
    viewer = make(ElaMarkdownViewer)
    viewer.setMarkdown(_large_source())
    assert viewer.isRendering() is True

    # 任意直接走 _render() 的样式入口都必须在开头取消分块队列。
    viewer.setTableZebra(True)
    assert viewer.isRendering() is False

    assert wait_until(
        qapp,
        lambda: viewer.document().characterCount() > 1,
        timeout_ms=5000,
    )
    text = viewer.toPlainText()
    assert text.count(_MARK) == 1
