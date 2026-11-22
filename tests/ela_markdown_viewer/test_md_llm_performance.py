"""大文档审计语料：URL / mark / details / 代码混合分块渲染不退化。"""

from __future__ import annotations

import time

import pytest
from _qthelpers import wait_until

from pyqt6_ela_pro.ela_markdown_viewer import ElaMarkdownViewer


def _large_document() -> str:
    unit = """## 小节

这是 ==**重点**== 和 [www.example.com/path_(x)](https://target.example/a(b))
以及裸 URL https://example.com/a*b*c?q=1。

- item

  ```python
  print("hello")
  ```

<details>
<summary>**More** `code`</summary>

hidden body

</details>

| L | C | R |
|:--|:-:|--:|
| a | b | c |

"""
    return unit * 800 + "\nEND-AUDIT\n"


@pytest.mark.slow
def test_large_mixed_document_renders_without_losing_content(qapp, make):
    source = _large_document()
    assert len(source) > 200_000

    viewer = make(ElaMarkdownViewer)
    started = time.perf_counter()
    viewer.setMarkdown(source)
    assert wait_until(qapp, lambda: not viewer.isRendering(), timeout_ms=15000)
    elapsed = time.perf_counter() - started

    text = viewer.toPlainText()
    assert "END-AUDIT" in text
    assert "\ue000" not in text and "\ue001" not in text
    assert viewer.renderIssues() == []
    assert viewer.document().blockCount() > 1000
    assert elapsed < 15.0
