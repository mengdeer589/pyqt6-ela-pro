"""Markdown 滚动绘制探针（Win7 字体 shaping / 查看器装饰层成本）。

背景：``bugs/未处理项.md`` #15/#20 —— Win7 上 CJK 与 Latin 混排、多族字体或缺
字形 fallback 会让文本绘制慢 20~40×，且是**进程级**的。一次进程只测一种文档，
否则先测的那份会毒化后测的那份。

用法::

    python tools/perf/bench_markdown_paint.py --doc cjk --target viewer
    python tools/perf/bench_markdown_paint.py --doc ascii --target native
    python tools/perf/bench_markdown_paint.py --doc cjk --target viewer --styled
    python tools/perf/bench_markdown_paint.py --doc mixed --target viewer --json out.json

输出每一步滚动（默认 40px）的毫秒数与 fps；比较 ``native`` 与 ``viewer``
就能把「Qt/DirectWrite 文本绘制」与「查看器自绘装饰层」分开。
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time

_DOC_CHOICES = ("cjk", "ascii", "mixed")


def _paragraph(kind: str, index: int, styled: bool) -> str:
    if kind == "cjk":
        body = f"第 {index} 行：这是中文正文，包含标点、数字 {index} 和英文 token。"
    elif kind == "ascii":
        body = f"Line {index}: the quick brown fox jumps over the lazy dog ({index})."
    else:
        body = f"第 {index} 行：mixed text with 中文 and English token_{index}."
    if not styled:
        return body + "\n"
    if index % 6 == 0:
        return f"## 小节 {index}\n\n{body}\n\n> 引用 {index}\n\n"
    if index % 4 == 0:
        return f"{body} 再来一段 `inline_code_{index}` 与 **加粗**。\n\n"
    return body + "\n"


def _make_document(kind: str, lines: int, styled: bool) -> str:
    return "".join(_paragraph(kind, index, styled) for index in range(lines))


def _make_app():
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    from PyQt6ElaWidgetTools import eApp

    eApp.init()
    return app


def _build_target(app, target: str, document: str, width: int, height: int):
    if target == "native":
        from PyQt6.QtWidgets import QTextBrowser

        widget = QTextBrowser()
        widget.resize(width, height)
        widget.setMarkdown(document)
        widget.show()
        app.processEvents()
        return widget, widget.verticalScrollBar()
    if target == "viewer":
        from pyqt6_ela_pro.ela_markdown_viewer import ElaMarkdownViewer

        viewer = ElaMarkdownViewer()
        viewer.resize(width, height)
        viewer.show()
        viewer.setMarkdown(document)
        app.processEvents()
        return viewer, viewer.textBrowser().verticalScrollBar()
    raise ValueError(target)


def run(target: str, kind: str, styled: bool, steps: int, pixels: int, size: str, repeat: int):
    width_text, _, height_text = size.partition("x")
    width, height = int(width_text), int(height_text)
    app = _make_app()
    document = _make_document(kind, 140, styled)

    runs = []
    for _ in range(max(1, repeat)):
        widget, bar = _build_target(app, target, document, width, height)
        bar.setValue(0)
        app.processEvents()
        maximum = bar.maximum()
        samples = []
        for _step in range(steps):
            value = min(maximum, bar.value() + pixels)
            if value == bar.value():
                break
            start = time.perf_counter()
            bar.setValue(value)
            app.processEvents()
            samples.append((time.perf_counter() - start) * 1000.0)
        widget.deleteLater()
        app.processEvents()
        if samples:
            runs.append(samples)

    if not runs:
        return {"target": target, "doc": kind, "steps": 0, "note": "文档不够长，未滚动"}
    merged = [value for run in runs for value in run]
    return {
        "target": target,
        "doc": kind,
        "styled": styled,
        "size": f"{width}x{height}",
        "pixels": pixels,
        "steps": len(merged),
        "ms_median": statistics.median(merged),
        "ms_min": min(merged),
        "ms_max": max(merged),
        "fps_median": 1000.0 / statistics.median(merged) if merged else 0.0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Markdown 滚动绘制探针")
    parser.add_argument("--doc", choices=_DOC_CHOICES, default="cjk")
    parser.add_argument("--target", choices=("native", "viewer"), default="viewer")
    parser.add_argument("--styled", action="store_true", help="加标题 / 引用 / 行内代码")
    parser.add_argument("--steps", type=int, default=20)
    parser.add_argument("--pixels", type=int, default=40)
    parser.add_argument("--size", default="1000x700")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--json", default="")
    args = parser.parse_args()

    result = run(
        args.target,
        args.doc,
        args.styled,
        args.steps,
        args.pixels,
        args.size,
        args.repeat,
    )
    for key, value in result.items():
        if isinstance(value, float):
            print(f"  {key}: {value:.2f}")
        else:
            print(f"  {key}: {value}")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
