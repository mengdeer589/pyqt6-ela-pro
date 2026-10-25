"""markdown viewer 的「外部内容解析」契约回归（批次 3）。

覆盖四类**静默改坏内容**或**崩溃**的缺陷：

1. ``data:`` URI 图片 → ``AttributeError`` 穿出 ``QTimer`` 槽 = 进程终止；
2. 缩进围栏（列表 / 引用块里的 ```）不被识别 → 里面的代码被行内规则改坏
   （``:fire:`` 变 emoji、脚注引用被抽走、``- [ ]`` 变任务勾选）；
3. 围栏状态机只看前 3 字符 → 长围栏自我闭合、`````not-a-close`` 提前闭合；
4. 行内代码按**文本**反推位置 → 前文出现的同名字面文本「抢走」标记。
"""

from __future__ import annotations

import base64

import pytest
from PyQt6.QtCore import QBuffer, QIODevice
from PyQt6.QtGui import QColor, QImage, QPainter

from pyqt6_ela_pro.ela_markdown_viewer import (
    _INLINE_CODE_MARK,
    _INLINE_LINK_RE,
    _normalize_text,
    _strip_inline_links,
    ElaMarkdownViewer,
)


def _png_data_uri() -> str:
    image = QImage(8, 6, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    painter.fillRect(0, 0, 8, 6, QColor("#3366ff"))
    painter.end()
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(bytes(buf.data())).decode()


def _marked_runs(viewer: ElaMarkdownViewer) -> list[tuple[str, bool]]:
    """全文档逐片段 ``(文本, 是否带行内代码标记)``。"""
    runs: list[tuple[str, bool]] = []
    block = viewer.document().begin()
    while block.isValid():
        it = block.begin()
        while not it.atEnd():
            frag = it.fragment()
            if frag.isValid() and frag.text():
                runs.append(
                    (frag.text(), bool(frag.charFormat().property(_INLINE_CODE_MARK)))
                )
            it += 1
        block = block.next()
    return runs


def _code_texts(viewer: ElaMarkdownViewer) -> list[str]:
    return [text for text, marked in _marked_runs(viewer) if marked]


class TestDataUriImages:
    def test_valid_data_uri_renders_as_image(self, make):
        viewer = make(ElaMarkdownViewer)
        uri = _png_data_uri()
        viewer.setMarkdown(f"![x]({uri})")
        assert viewer.renderIssues() == [], "合法的 data: 图片不该降级"
        assert viewer.document().toPlainText() == "￼", "应是图片块而非占位符"

    def test_malformed_data_uri_degrades_not_crashes(self, make):
        # 原实现在这里抛 AttributeError 并穿出定时器槽 = 0xC0000409 零输出终止
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("![x](data:image/png;base64,!!!!not-base64!!!!)")
        issues = viewer.renderIssues()
        assert [kind for kind, _ in issues] == ["image"]
        assert "图片" in viewer.document().toPlainText()

    def test_empty_payload_degrades(self, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("![x](data:image/png;base64,)")
        assert [kind for kind, _ in viewer.renderIssues()] == ["image"]

    def test_stream_path_survives(self, make, qapp):
        # 流式路径原先在这里整个进程消失（退出码 0xC0000409）
        viewer = make(ElaMarkdownViewer)
        viewer.beginStream()
        viewer.appendMarkdown("hello ")
        viewer.appendMarkdown("![x](data:image/png;base64,!!!bad!!!)")
        viewer.endStream()
        qapp.processEvents()
        assert [kind for kind, _ in viewer.renderIssues()] == ["image"]

    def test_non_image_payload_degrades(self, make):
        viewer = make(ElaMarkdownViewer)
        payload = base64.b64encode(b"hello").decode()
        viewer.setMarkdown(f"![x](data:text/plain;base64,{payload})")
        assert [kind for kind, _ in viewer.renderIssues()] == ["image"]

    def test_oversized_payload_rejected(self):
        # 一行 Markdown 不该能分配任意内存。**在解码层钉**，而不是端到端 ——
        # 超过 64 KB 的文档必然走分块渲染路径，端到端那侧压根不经过这里。
        from PyQt6.QtCore import QUrl

        from pyqt6_ela_pro.ela_markdown_viewer import _decode_data_uri

        # 解码后约 37 MiB> 32 MiB 上限
        huge = _decode_data_uri(
            QUrl("data:image/png;base64," + "A" * (50 * 1024 * 1024))
        )
        assert len(huge) == 0
        # 上限之内仍要正常解码（守卫不能把合法图片也拒了）
        ok = _decode_data_uri(QUrl(_png_data_uri()))
        assert len(ok) > 0, "上限内的合法 data: 图片被误拒了"


class TestIndentedFences:
    def test_emoji_shortcode_not_rewritten_inside_list_fence(self, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("- 例：\n  ```python\n  print(':fire: and :100:')\n  ```\n")
        text = viewer.document().toPlainText()
        assert ":fire:" in text, "代码内容里的 emoji 短代码被行内规则替换了"
        assert "🔥" not in text

    def test_footnote_ref_not_extracted_inside_fence(self, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("- x:\n  ```\n  a = arr[^1]\n  ```\n")
        assert "[^1]" in viewer.document().toPlainText()

    def test_task_marker_not_created_inside_fence(self, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("- 例：\n  ```\n  - [ ] 这不是任务\n  ```\n")
        text = viewer.document().toPlainText()
        assert "□" not in text, "代码内容里的 - [ ] 被当成了任务列表"
        assert "- [ ] 这不是任务" in text

    def test_quote_nested_fence(self, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("> 引言：\n> ```js\n> const a = 1;\n> ```\n")
        assert "const a = 1;" in viewer.document().toPlainText()

    def test_plain_fence_still_works(self, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("```python\nx = 1\n```\n")
        text = viewer.document().toPlainText()
        assert "x = 1" in text
        assert "\n\n" not in text, "不该多出空块"


class TestFenceStateMachine:
    def test_longer_fence_is_not_closed_by_shorter(self, make):
        # CommonMark 里用 4 个反引号包裹 3 个反引号是标准写法
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("````\n```\ninner\n```\n````\n")
        assert viewer.document().toPlainText().count("```") == 2

    def test_closing_line_must_not_have_trailing_content(self, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("```py\ncode\n```not-a-close\nmore\n```\n")
        text = viewer.document().toPlainText()
        assert "not-a-close" in text
        assert "more" in text

    def test_tilde_fence(self, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("~~~python\nx = 1\n~~~\n")
        assert "x = 1" in viewer.document().toPlainText()


class TestInlineCodePositioning:
    def test_plain_text_does_not_steal_the_mark(self, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("The word `foo` here.\n\nbar foo baz `foo` end\n")
        assert _code_texts(viewer) == ["foo", "foo"], (
            "前文出现的同名字面文本抢走了标记，真正的 `foo` 反而没样式"
        )

    def test_heading_text_does_not_steal_the_mark(self, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("# foo\n\n正文 `foo` 结束\n")
        runs = _marked_runs(viewer)
        heading = [marked for text, marked in runs if text == "foo"]
        assert heading == [False, True], f"标题里的 foo 不该被标记：{runs}"

    def test_link_text_does_not_steal_the_mark(self, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("[docs](http://x) 然后 `docs` 结束\n")
        assert _code_texts(viewer) == ["docs"]

    def test_order_is_preserved(self, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("a `one` b `two` c `three` d\n")
        assert _code_texts(viewer) == ["one", "two", "three"]

    def test_fenced_code_not_double_marked(self, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("```\nfoo\n```\n\n正文 `foo` 结束\n")
        assert _code_texts(viewer).count("foo") == 1

    def test_no_token_residue_in_plain_text(self, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("a `one` b `two`\n")
        plain = viewer.document().toPlainText()
        assert plain == "a one b two"
        assert "" not in plain and "" not in plain

    def test_stream_path(self, make, qapp):
        viewer = make(ElaMarkdownViewer)
        viewer.beginStream()
        viewer.appendMarkdown("普通 foo 文本\n\n")
        viewer.appendMarkdown("再来 `foo` 一次\n")
        viewer.endStream()
        qapp.processEvents()
        assert _code_texts(viewer).count("foo") >= 1


class TestExternalLinkSchemeWhitelist:
    """不可信内容里的链接不得被原样交给系统 shell。"""

    @staticmethod
    def _click(viewer, url: str) -> None:
        from PyQt6.QtCore import QUrl

        viewer._on_anchor_clicked(QUrl(url))

    @pytest.mark.parametrize(
        "url",
        [
            "javascript:alert(1)",
            "file:///C:/Windows/System32/cmd.exe",
            "data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==",
            "ms-msdt:/id",
            "vbscript:msgbox(1)",
            "ftp://example.com/x",
        ],
    )
    def test_blocked_scheme_is_not_opened(self, make, monkeypatch, url):
        from PyQt6.QtGui import QDesktopServices

        opened: list = []
        monkeypatch.setattr(
            QDesktopServices,
            "openUrl",
            staticmethod(lambda u: opened.append(u) or True),
        )
        viewer = make(ElaMarkdownViewer)
        assert viewer.openExternalLinks() is True, "本用例要验证的是默认开启下的白名单"
        emitted: list = []
        viewer.linkActivated.connect(emitted.append)
        self._click(viewer, url)
        assert not opened, f"{url} 被交给系统 shell 了"
        # 被拒也要让宿主知道，宿主想自己处理（确认框 / 复制）还来得及
        assert emitted == [url]

    @pytest.mark.parametrize(
        "url", ["http://example.com", "https://example.com/a?b=1", "mailto:a@b.c"]
    )
    def test_allowed_scheme_is_opened(self, make, monkeypatch, url):
        from PyQt6.QtGui import QDesktopServices

        opened: list = []
        monkeypatch.setattr(
            QDesktopServices,
            "openUrl",
            staticmethod(lambda u: opened.append(u) or True),
        )
        viewer = make(ElaMarkdownViewer)
        self._click(viewer, url)
        assert [u.toString() for u in opened] == [url]

    def test_scheme_check_is_case_insensitive(self, make, monkeypatch):
        from PyQt6.QtGui import QDesktopServices

        opened: list = []
        monkeypatch.setattr(
            QDesktopServices,
            "openUrl",
            staticmethod(lambda u: opened.append(u) or True),
        )
        viewer = make(ElaMarkdownViewer)
        self._click(viewer, "HTTPS://EXAMPLE.COM")
        assert len(opened) == 1

    def test_switch_off_still_blocks(self, make, monkeypatch):
        from PyQt6.QtGui import QDesktopServices

        opened: list = []
        monkeypatch.setattr(
            QDesktopServices,
            "openUrl",
            staticmethod(lambda u: opened.append(u) or True),
        )
        viewer = make(ElaMarkdownViewer)
        viewer.setOpenExternalLinks(False)
        self._click(viewer, "https://example.com")
        assert not opened

    def test_whitelist_is_configurable(self, make, monkeypatch):
        from PyQt6.QtGui import QDesktopServices

        opened: list = []
        monkeypatch.setattr(
            QDesktopServices,
            "openUrl",
            staticmethod(lambda u: opened.append(u) or True),
        )
        viewer = make(ElaMarkdownViewer)
        assert viewer.externalLinkSchemes() == frozenset({"http", "https", "mailto"})
        viewer.setExternalLinkSchemes(["https", "ftp"])
        assert viewer.externalLinkSchemes() == frozenset({"https", "ftp"})
        self._click(viewer, "https://example.com")
        self._click(viewer, "ftp://example.com")
        self._click(viewer, "http://example.com")
        assert len(opened) == 2, "http 已被移出白名单，不该再打开"

    def test_internal_anchors_unaffected(self, make, monkeypatch):
        """内部控制锚点不走外链路径（任务勾选 / 折叠 / 锚点跳转必须照常工作）。"""
        from PyQt6.QtGui import QDesktopServices

        opened: list = []
        monkeypatch.setattr(
            QDesktopServices,
            "openUrl",
            staticmethod(lambda u: opened.append(u) or True),
        )
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("- [ ] 任务一\n")
        from PyQt6.QtCore import QUrl

        viewer._on_anchor_clicked(QUrl("#elatask-0"))
        assert not opened
        # 内部锚点翻转的是**源文本**（_toggle_task_by_ordinal），不是控件状态
        assert "- [x] 任务一" in viewer._source, f"任务勾选没被翻转：{viewer._source!r}"


class TestStripInlineLinks:
    """手写扫描替换正则后的语义等价与复杂度。"""

    @pytest.mark.parametrize(
        "text",
        [
            "[text](http://a)",
            "see [docs](http://x) end",
            "![alt](img.png)",
            "[](empty)",
            "[a](b) [c](d)",
            "[a](b(c))",
            "[a] (b)",
            "[a](b",
            "no link here",
            "][](x)",
            "![a](b) and [c](d)",
            "[[a]](b)",
            "[a](b) trailing )",
            "text ] (x) more",
            "](b) no opener",
            "[a](b)[c](d)[e](f)",
            "[]()",
            "![](x)",
            "[a[b]](c)",
            "a[b]c](d)e",
            "[中文](链接)",
        ],
    )
    def test_matches_regex_semantics(self, text):
        assert _strip_inline_links(text) == _INLINE_LINK_RE.sub(
            lambda m: m.group(1), text
        )

    def test_random_corpus_equivalence(self):
        import random

        random.seed(20261002)
        alphabet = "[]()!ab \t"
        for _ in range(5000):
            text = "".join(
                random.choice(alphabet) for _ in range(random.randint(0, 24))
            )
            assert _strip_inline_links(text) == _INLINE_LINK_RE.sub(
                lambda m: m.group(1), text
            ), text

    @staticmethod
    def _growth_ratio(text_factory, rounds: int = 3) -> float:
        """输入长度 ×2 时耗时之比（取每档 3 次的**最小值**，抗噪）。

        比值判据而不是墙钟绝对值：线性 ≈2，二次 ≈4；把门槛放到 **3.0 以外很远
        的位置**——这里要求「两档之比 < 3.2」，线性（≈2）稳过、二次（≈4）必挂。
        取 min 而不是单次采样，是因为同机其它测试负载会让单次样本翻好几倍
        （本条曾因此在 11 个目录同跑时偶发失败、单跑 3/3 全过）。
        """
        import time

        def best(n: int) -> float:
            text = text_factory(n)
            samples = []
            for _ in range(3):
                t0 = time.perf_counter()
                _normalize_text(text)
                samples.append(time.perf_counter() - t0)
            return min(samples)

        prev = best(20000)
        worst = 0.0
        for _ in range(rounds - 1):
            cur = best(20000 * 2)
            worst = max(worst, cur / max(prev, 1e-6))
            prev = cur
        return worst

    def test_unterminated_brackets_are_linear(self):
        # 原正则在这里是 O(n^2)：每个 '[' 都让 [^)]* 扫到行尾再回溯
        ratio = self._growth_ratio(lambda n: "[a](b" * n)
        assert ratio < 3.2, f"输入翻倍耗时涨 {ratio:.2f} 倍，二次增长会到≈4"

    def test_trailing_single_paren_is_linear(self):
        ratio = self._growth_ratio(lambda n: "[a](b" * n + ")")
        assert ratio < 3.2, f"输入翻倍耗时涨 {ratio:.2f} 倍，二次增长会到≈4"

    @pytest.mark.slow
    def test_quadratic_reference_would_be_caught(self):
        """守卫自身有效性：拿一个**故意二次**的实现跑同一判据，必须被抓。

        没有这条，上面的 3.2 门槛有可能因为写错（比如比值算反）而恒真。
        """
        import re

        quadratic = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")

        def text(n: int) -> str:
            return "[a](b" * n

        def best(n: int) -> float:
            import time

            t = text(n)
            samples = []
            for _ in range(3):
                t0 = time.perf_counter()
                quadratic.sub(lambda m: m.group(1), t)
                samples.append(time.perf_counter() - t0)
            return min(samples)

        prev = best(20000)
        worst = 0.0
        for _ in range(2):
            cur = best(40000)
            worst = max(worst, cur / max(prev, 1e-6))
            prev = cur
        assert worst >= 3.2, (
            f"原正则只涨 {worst:.2f} 倍，抓不到二次增长 —— 门槛需要重新标定"
        )
