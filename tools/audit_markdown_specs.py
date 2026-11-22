"""CommonMark / GFM 语法覆盖审计（离线 harness，网络只读）。

用法::

    uv run python tools/audit_markdown_specs.py
    uv run python tools/audit_markdown_specs.py --strict

``--strict`` 在出现空文档或非图片降级时返回非零；文本差异只报告。
"""

from __future__ import annotations

import argparse
import html as htmlmod
import json
import os
import re
import sys
import time
import urllib.request
from collections import Counter
from html.parser import HTMLParser

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtGui import QTextTable  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from PyQt6ElaWidgetTools import eApp  # noqa: E402

from pyqt6_ela_pro.ela_markdown_viewer import ElaMarkdownViewer  # noqa: E402

COMMONMARK_URL = "https://spec.commonmark.org/0.31.2/spec.json"
GFM_URL = "https://github.github.com/gfm/"

GFM_SECTIONS = (
    "tables-extension-",
    "task-list-items-extension-",
    "strikethrough-extension-",
    "autolinks-extension-",
    "disallowed-raw-html-extension-",
)


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text: list[str] = []
        self.tags: Counter = Counter()
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        self.tags[tag] += 1
        if tag in ("script", "style"):
            self.skip += 1

    def handle_startendtag(self, tag, attrs):
        self.tags[tag] += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.text.append(data)


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[^\W_]+", text, re.UNICODE))


def _expected_text(source: str) -> tuple[str, Counter]:
    parser = _TextParser()
    parser.feed(re.sub(r"<br\s*/?>", " ", source, flags=re.IGNORECASE))
    return "".join(parser.text), parser.tags


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


def _metrics(viewer: ElaMarkdownViewer) -> dict:
    tables = _tables(viewer)
    code_tables = [
        table
        for table in tables
        if table.columns() == 1
        and table.cellAt(0, 0).format().background().color() == viewer._code_bg
    ]
    blocks = []
    block = viewer.document().begin()
    while block.isValid():
        blocks.append(block)
        block = block.next()
    return {
        "tables": len(tables) - len(code_tables),
        "lists": sum(1 for block in blocks if block.textList() is not None),
        "headings": sum(
            1 for block in blocks if block.blockFormat().headingLevel() > 0
        ),
        "code": len(code_tables),
    }


def _compare(viewer: ElaMarkdownViewer, markdown: str, expected_html: str) -> dict:
    viewer.setMarkdown(markdown)
    plain = viewer.toPlainText()
    expected, tags = _expected_text(expected_html)
    missing = sorted(_tokens(expected) - _tokens(plain))
    metrics = _metrics(viewer)
    bad = []
    if tags["table"] != metrics["tables"]:
        bad.append(f"table {tags['table']}!={metrics['tables']}")
    if tags["li"] != metrics["lists"]:
        bad.append(f"li {tags['li']}!={metrics['lists']}")
    headings = sum(tags[f"h{level}"] for level in range(1, 7))
    if headings != metrics["headings"]:
        bad.append(f"headings {headings}!={metrics['headings']}")
    if (tags["pre"] > 0) != (metrics["code"] > 0):
        bad.append(f"code {tags['pre']}!={metrics['code']}")
    issues = [issue for issue in viewer.renderIssues() if issue[0] != "image"]
    return {
        "markdown": markdown,
        "plain": plain,
        "missing": missing,
        "bad": bad,
        "issues": issues,
    }


def _fetch(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "ela-md-audit"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read().decode("utf-8", "replace")


def _commonmark(viewer: ElaMarkdownViewer, strict: bool) -> int:
    examples = json.loads(_fetch(COMMONMARK_URL))
    failures = 0
    differences = 0
    started = time.perf_counter()
    for example in examples:
        result = _compare(viewer, example["markdown"], example["html"])
        if result["missing"] or result["bad"]:
            differences += 1
        if result["issues"] or (
            result["plain"].strip() == "" and _expected_text(example["html"])[0].strip()
        ):
            failures += 1
            print(
                f"CommonMark #{example['example']} {example['section']}: "
                f"issues={result['issues']} empty={not result['plain'].strip()}"
            )
    elapsed = time.perf_counter() - started
    print(
        f"CommonMark: {len(examples)} examples, {differences} text/structure differences, "
        f"{failures} hard failures, {elapsed:.2f}s"
    )
    return 1 if strict and failures else 0


def _gfm_examples() -> list[tuple[str, int, str, str]]:
    raw = _fetch(GFM_URL)
    heads = [
        (match.start(), match.group(1))
        for match in re.finditer(r'<h[12][^>]*id="([^"]+)"', raw)
    ]

    def clean(source: str) -> str:
        source = re.sub(r'<span class="space"> </span>', " ", source)
        source = re.sub(
            r'<span class="tab">(.*?)</span>',
            lambda match: match.group(1),
            source,
            flags=re.S,
        )
        return htmlmod.unescape(source).replace("→", "\t")

    examples = []
    for section in GFM_SECTIONS:
        start = next(pos for pos, hid in heads if hid == section)
        stop = next((pos for pos, _hid in heads if pos > start), len(raw))
        for match in re.finditer(
            r'<div class="example" id="example-(\d+)">(.*?)(?=<div class="example"|$)',
            raw[start:stop],
            re.S,
        ):
            body = match.group(2)
            markdown = re.findall(
                r'<pre><code class="language-markdown">(.*?)</code></pre>',
                body,
                re.S,
            )
            output = re.findall(
                r'<pre><code class="language-html">(.*?)</code></pre>', body, re.S
            )
            if markdown and output:
                examples.append(
                    (
                        section,
                        int(match.group(1)),
                        clean(markdown[0]),
                        clean(output[0]),
                    )
                )
    return examples


def _gfm(viewer: ElaMarkdownViewer, strict: bool) -> int:
    examples = _gfm_examples()
    failures = 0
    differences = 0
    started = time.perf_counter()
    for section, number, markdown, output in examples:
        result = _compare(viewer, markdown, output)
        if result["missing"] or result["bad"]:
            differences += 1
            print(
                f"GFM #{number} {section}: missing={result['missing']} {result['bad']}"
            )
        if result["issues"]:
            failures += 1
            print(f"GFM #{number} {section}: issues={result['issues']}")
    elapsed = time.perf_counter() - started
    print(
        f"GFM extensions: {len(examples)} examples, {differences} differences, "
        f"{failures} hard failures, {elapsed:.2f}s"
    )
    return 1 if strict and failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="CommonMark / GFM Markdown audit")
    parser.add_argument("--strict", action="store_true", help="fail on hard failures")
    args = parser.parse_args()

    app = QApplication(["ela-markdown-audit"])
    eApp.init()
    viewer = ElaMarkdownViewer()
    try:
        return _commonmark(viewer, args.strict) | _gfm(viewer, args.strict)
    finally:
        viewer.deleteLater()
        app.processEvents()


if __name__ == "__main__":
    sys.exit(main())
