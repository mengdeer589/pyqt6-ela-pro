"""审计语料在全部内置主题下的结构回归（像素外观仍需真实桌面确认）。"""

from __future__ import annotations

import pytest
from PyQt6.QtGui import QTextTable

from pyqt6_ela_pro.ela_markdown_viewer import ElaMarkdownViewer, markdownThemes

AUDIT_MARKDOWN = """# 标题

| L | C | R |
|:--|:-:|--:|
| a | b | c |

> [!NOTE]
> | A | B |
> |---|---|
> | 1 | 2 |

- item

  ```python
  print(1)
  ```

> quote
>
> ```python
> print(2)
> ```

==**marked**== and [www.example.com](https://target.example)

<details>
<summary>**More** `code`</summary>

body

</details>

Inline $e^{i\\pi}+1=0$.
"""


def _fragments(viewer: ElaMarkdownViewer) -> list:
    result = []
    block = viewer.document().begin()
    while block.isValid():
        iterator = block.begin()
        while not iterator.atEnd():
            fragment = iterator.fragment()
            if fragment.isValid():
                result.append(fragment)
            iterator += 1
        block = block.next()
    return result


def _tables(viewer: ElaMarkdownViewer) -> list[QTextTable]:
    result = []
    stack = [viewer.document().rootFrame()]
    while stack:
        frame = stack.pop()
        for child in frame.childFrames():
            if isinstance(child, QTextTable):
                result.append(child)
            stack.append(child)
    return result


def _code_tables(viewer: ElaMarkdownViewer) -> list[QTextTable]:
    return [
        table
        for table in _tables(viewer)
        if table.columns() == 1
        and table.cellAt(0, 0).format().background().color() == viewer._code_bg
    ]


@pytest.mark.parametrize("theme", markdownThemes())
def test_audit_document_survives_every_theme(qapp, make, theme):
    viewer = make(ElaMarkdownViewer)
    viewer.show()
    qapp.processEvents()
    viewer.setMarkdownTheme(theme)
    viewer.setMarkdown(AUDIT_MARKDOWN)
    qapp.processEvents()

    text = viewer.toPlainText()
    assert "\ue000" not in text and "\ue001" not in text
    assert "https://target.example" in [
        fragment.charFormat().anchorHref()
        for fragment in _fragments(viewer)
        if fragment.charFormat().isAnchor()
    ]
    assert len(_code_tables(viewer)) == 2

    tables = [
        table for table in _tables(viewer) if table.columns() == 2 and table.rows() == 2
    ]
    assert tables
    table = tables[0]
    for column in range(table.columns()):
        header = table.cellAt(0, column).firstCursorPosition().blockFormat()
        body = table.cellAt(1, column).firstCursorPosition().blockFormat()
        assert header.alignment() == body.alignment()

    marked = [
        fragment
        for fragment in _fragments(viewer)
        if "marked" in fragment.text() and fragment.charFormat().fontWeight() >= 600
    ]
    assert marked
    assert viewer.renderIssues() == []
