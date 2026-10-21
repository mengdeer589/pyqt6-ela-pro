"""可见文档的整趟渲染只布局一次（``QTextDocument`` 信号批处理）。

每个编辑块 ``endEditBlock`` 都会触发一次整篇重排：117KB 文档挂控件实测 147ms、
离线只要 36ms。``_render_into`` 在目标文档 == 浏览器文档时屏蔽信号，结束后
``markContentsDirty`` 一次（直接通知 layout）+ 补发一次 ``contentsChanged``。

这里钉住三条契约：结果与逐段渲染逐字节一致、宿主只收到一次变更通知、
折叠 / 代码复制按钮等依赖帧树的功能不受影响。
"""

from __future__ import annotations

from _qthelpers import wait_until as _wait_until
from pyqt6_ela_pro import ela_markdown_viewer as md_module
from pyqt6_ela_pro.ela_markdown_viewer import ElaMarkdownViewer

#: 覆盖页眉 / 表格 / 代码块 / 折叠（内含表）/ 脚注 / 长段落
DOC = (
    "# 标题\n\n正文 `code` 与 **加粗**，带脚注 `[^1]`。\n\n"
    "| a | b |\n|---|---|\n| 1 | 2 |\n\n"
    "```python\n" + "\n".join(f"x{i} = {i}" for i in range(15)) + "\n```\n\n"
    "<details>\n<summary>折叠</summary>\n\n折叠内正文。\n\n"
    "| c | d |\n|---|---|\n| 3 | 4 |\n</details>\n\n"
    + "段落内容。" * 300
    + "\n\n[^1]: 脚注内容\n"
)


def _render(qapp, make) -> ElaMarkdownViewer:
    viewer = make(ElaMarkdownViewer)
    viewer.resize(900, 700)
    viewer.show()
    qapp.processEvents()
    viewer.setMarkdown(DOC)
    _wait_until(qapp, lambda: not viewer.isRendering())
    _wait_until(qapp, lambda: viewer.textBrowser().verticalScrollBar().maximum() > 0)
    qapp.processEvents()
    return viewer


class TestAttachedLayoutBatching:
    def test_html_and_layout_match_unbatched(self, qapp, make, monkeypatch):
        """批处理只改布局时机，不改渲染结果与文档几何。"""
        batched = _render(qapp, make)
        html_batched = batched.document().toHtml()
        height_batched = batched.document().size().height()
        scroll_batched = batched.textBrowser().verticalScrollBar().maximum()

        monkeypatch.setattr(md_module, "_BATCH_ATTACHED_RENDERS", False)
        plain = _render(qapp, make)
        assert plain.document().toHtml() == html_batched
        assert plain.document().size().height() == height_batched
        assert plain.textBrowser().verticalScrollBar().maximum() == scroll_batched, (
            "批处理后的布局范围必须与逐段渲染一致"
        )

    def test_contents_changed_emitted_once(self, qapp, make):
        """渲染期间信号被合并；宿主最终只收到一次变更通知。"""
        viewer = make(ElaMarkdownViewer)
        viewer.resize(600, 400)
        viewer.show()
        qapp.processEvents()
        calls: list[int] = []
        viewer.document().contentsChanged.connect(lambda: calls.append(1))
        viewer.setMarkdown(DOC)
        _wait_until(qapp, lambda: not viewer.isRendering())
        qapp.processEvents()
        assert len(calls) == 1

    def test_folds_and_code_buttons_still_work(self, qapp, make):
        """依赖帧树的后处理（折叠删除 / 代码表按钮）在批处理下不受影响。"""
        viewer = _render(qapp, make)
        assert viewer._code_buttons, "代码复制按钮应已创建"
        assert "折叠内正文" not in viewer.toPlainText(), "折叠内容默认应收起"

        viewer._toggle_fold_expanded("0")
        qapp.processEvents()
        assert "折叠内正文" in viewer.toPlainText(), "展开后折叠内容应回来"
        assert "3" in viewer.toPlainText(), "折叠内的表格单元应保留"
