"""聊天组件性能基线（桌面与 Win7 交付机共用）。

用法::

    python tools/perf/bench_chat.py
    python tools/perf/bench_chat.py --messages 300 --json out.json
    python tools/perf/bench_chat.py --offscreen      # 无桌面环境（绘制数字不代表实屏）

输出内容：

- 环境与字体：OS / Qt / PyQt6 / 宿主默认字体 / CJK 单族判定 / 查看器代码字体；
- 构造：纯文本消息、富消息（思考 + 工具）；
- 流式：分片追加与收尾；
- 历史：``importSession``（内部走批量 + 延迟物化）；
- 交互：resize（冻结 / 放开）、滚动、深浅主题切换。

Win7 上先看两件事：① 默认字体与单族判定（命中 shaping 毒化时所有文字都会慢
一个量级）；② 滚动一屏的耗时（`QTextBrowser` 的 DirectWrite 路径是主成本）。
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import time

_VIEW_SIZE = (1000, 700)


def _now() -> float:
    return time.perf_counter()


def _ms(start: float, end: float | None = None) -> float:
    return ((end if end is not None else time.perf_counter()) - start) * 1000.0


def _sample_text(repeat: int = 8) -> str:
    block = (
        "## 小节\n\n"
        "这是 **加粗** 与 `inline_code` 混排的正文，后面跟一个 [链接](https://example.com)。\n\n"
        "- 第一项\n"
        "- 第二项\n\n"
        "```python\n"
        "def compute(value):\n"
        "    return value * 2\n"
        "```\n\n"
    )
    return block * repeat


def _rich_text() -> str:
    return (
        "结论：先把渲染量降下来。\n\n"
        "- 每消息控件数\n"
        "- 同屏 viewer 数\n\n"
        "| 指标 | 值 |\n|---|---|\n| 控件 | 27 |\n| viewer | 1 |\n\n"
    ) * 30


def _make_app(offscreen: bool):
    if offscreen:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    from PyQt6ElaWidgetTools import eApp

    eApp.init()
    return app


def _new_view(app):
    from pyqt6_ela_pro.chat import ElaChatView

    view = ElaChatView()
    view.resize(*_VIEW_SIZE)
    view.show()
    app.processEvents()
    return view


def _drop(view, app) -> None:
    view.deleteLater()
    app.processEvents()


def _settle(app, view, timeout: float = 3.0, need_scroll: bool = False) -> None:
    """把布局 / 延迟渲染跑完（否则滚动与「是否在屏」都会量到假数据）。"""
    bar = view._scroll.verticalScrollBar()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if not need_scroll or bar.maximum() > 0:
            return
        time.sleep(0.01)


def _font_report() -> dict:
    from PyQt6.QtGui import QFontDatabase, QGuiApplication

    from pyqt6_ela_pro._internal import system_cjk_font_family
    from pyqt6_ela_pro.chat._theme import MONO_FONT_STACK, mono_font
    from pyqt6_ela_pro.ela_markdown_viewer import _default_code_font_family

    cjk = system_cjk_font_family()
    return {
        "app_font": QGuiApplication.font().family(),
        "cjk_single_family": cjk,
        "mono_font_families": list(mono_font(11).families()),
        "code_font_family": _default_code_font_family(),
        "families_has_yahei": "Microsoft YaHei" in QFontDatabase.families(),
        "mono_stack": list(MONO_FONT_STACK),
    }


def _env_report() -> dict:
    from PyQt6.QtCore import PYQT_VERSION_STR, QT_VERSION_STR

    return {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "qt": QT_VERSION_STR,
        "pyqt": PYQT_VERSION_STR,
        "offscreen": os.environ.get("QT_QPA_PLATFORM", ""),
    }


def bench_add(app, count: int) -> dict:
    view = _new_view(app)
    from PyQt6.QtWidgets import QWidget

    before = len(view.findChildren(QWidget))
    text = _sample_text()
    start = _now()
    for _ in range(count):
        view.addMessage("assistant", text)
    app.processEvents()
    _settle(app, view, timeout=2.0)
    elapsed = _ms(start)
    widgets = len(view.findChildren(QWidget)) - before
    _drop(view, app)
    return {
        "count": count,
        "ms": elapsed,
        "ms_per_message": elapsed / max(1, count),
        "widgets_added": widgets,
        "widgets_per_message": widgets / max(1, count),
    }


def bench_rich(app, count: int) -> dict:
    view = _new_view(app)
    from PyQt6.QtWidgets import QWidget

    before = len(view.findChildren(QWidget))
    reasoning = "先分析输入，再检查数据。" * 60
    text = _rich_text()
    start = _now()
    for index in range(count):
        mid = view.beginMessage()
        view.beginReasoning(mid)
        view.appendReasoning(mid, reasoning)
        view.endReasoning(mid)
        view.beginText(mid)
        view.appendText(mid, text)
        for tool in range(5):
            view.addToolCall(mid, "read_file", f"path=file_{index}_{tool}.py")
        for call in view.toolCalls(mid):
            view.setToolCallResult(mid, call.id, "result line\n" * 20)
        view.endMessage(mid)
    app.processEvents()
    _settle(app, view, timeout=2.0)
    elapsed = _ms(start)
    widgets = len(view.findChildren(QWidget)) - before
    _drop(view, app)
    return {
        "count": count,
        "ms": elapsed,
        "ms_per_message": elapsed / max(1, count),
        "widgets_added": widgets,
        "widgets_per_message": widgets / max(1, count),
    }


def bench_stream(app, chunks: int = 400) -> dict:
    view = _new_view(app)
    chunk = "the quick brown fox jumps over the lazy dog. " * 2
    mid = view.beginMessage()
    start = _now()
    for index in range(chunks):
        view.appendText(mid, chunk)
        if index % 10 == 9:
            app.processEvents()
    append_ms = _ms(start)
    start = _now()
    view.endMessage(mid)
    app.processEvents()
    end_ms = _ms(start)
    _drop(view, app)
    return {
        "chunks": chunks,
        "chars": len(chunk) * chunks,
        "append_ms": append_ms,
        "end_ms": end_ms,
    }


def _build_bundle(count: int) -> dict:
    from pyqt6_ela_pro.chat import ElaChatMessage

    text = _sample_text(2)
    rows = [
        ElaChatMessage(id=index + 1, role="assistant", text=text).toDict()
        for index in range(count)
    ]
    return {
        "schema": 1,
        "session": {"id": "bench", "title": "bench", "message_count": count},
        "view": {},
        "messages": rows,
        "extra": None,
    }


def bench_restore(app, count: int) -> dict:
    bundle = _build_bundle(count)
    view = _new_view(app)
    finished: list = []
    view.batchRenderFinished.connect(lambda: finished.append(True))
    start = _now()
    view.importSession(bundle)
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and not finished:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()
    elapsed = _ms(start)
    from PyQt6.QtWidgets import QWidget

    widgets = len(view.findChildren(QWidget))
    _drop(view, app)
    return {
        "count": count,
        "ms": elapsed,
        "ms_per_message": elapsed / max(1, count),
        "widgets_after": widgets,
    }


def _fill_view(app, count: int):
    view = _new_view(app)
    text = _sample_text(4)
    for _ in range(count):
        view.addMessage("assistant", text)
    app.processEvents()
    _settle(app, view, timeout=3.0, need_scroll=True)
    return view


def bench_resize(app, count: int) -> dict:
    view = _fill_view(app, count)
    width, height = view.width(), view.height()
    start = _now()
    for step in range(10):
        view.resize(width - step * 8, height)
        app.processEvents()
    frozen = _ms(start)
    view.setResizeReflowDeferred(False)
    app.processEvents()
    start = _now()
    for step in range(10):
        view.resize(width - 80 - step * 8, height)
        app.processEvents()
    live = _ms(start)
    _drop(view, app)
    return {
        "messages": count,
        "frames": 10,
        "frozen_ms": frozen,
        "frozen_ms_per_frame": frozen / 10,
        "live_ms": live,
        "live_ms_per_frame": live / 10,
    }


def bench_scroll(app, count: int) -> dict:
    view = _fill_view(app, count)
    bar = view._scroll.verticalScrollBar()
    bar.setValue(bar.maximum())
    app.processEvents()
    start = _now()
    for _ in range(20):
        bar.setValue(max(0, bar.value() - 120))
        app.processEvents()
    elapsed = _ms(start)
    _drop(view, app)
    return {"messages": count, "steps": 20, "ms": elapsed, "ms_per_step": elapsed / 20}


def bench_theme(app, count: int) -> dict:
    from PyQt6ElaWidgetTools import ElaThemeType, eTheme

    view = _fill_view(app, count)
    original = eTheme.getThemeMode()
    start = _now()
    eTheme.setThemeMode(ElaThemeType.ThemeMode.Dark)
    app.processEvents()
    dark_ms = _ms(start)
    start = _now()
    eTheme.setThemeMode(ElaThemeType.ThemeMode.Light)
    app.processEvents()
    light_ms = _ms(start)
    eTheme.setThemeMode(original)
    app.processEvents()
    _drop(view, app)
    return {"messages": count, "dark_ms": dark_ms, "light_ms": light_ms}


def _print_report(env: dict, fonts: dict, results: list[dict]) -> None:
    print("== 环境 ==")
    for key, value in env.items():
        print(f"  {key}: {value}")
    print("== 字体 ==")
    for key, value in fonts.items():
        print(f"  {key}: {value}")
    print("== 结果 ==")
    for item in results:
        name = item.pop("_name")
        parts = ", ".join(
            f"{key}={value:.2f}" if isinstance(value, float) else f"{key}={value}"
            for key, value in item.items()
        )
        print(f"  [{name}] {parts}")


def main() -> int:
    parser = argparse.ArgumentParser(description="聊天组件性能基线")
    parser.add_argument("--messages", type=int, default=100, help="构造 / 交互场景的消息数")
    parser.add_argument("--rich", type=int, default=20, help="富消息条数")
    parser.add_argument("--chunks", type=int, default=400, help="流式分片数")
    parser.add_argument("--offscreen", action="store_true", help="用 offscreen 平台（无实屏绘制）")
    parser.add_argument("--json", default="", help="把结果额外写到该 JSON 文件")
    args = parser.parse_args()

    app = _make_app(args.offscreen)
    env = _env_report()
    fonts = _font_report()
    results = [
        {"_name": "add", **bench_add(app, args.messages)},
        {"_name": "rich", **bench_rich(app, args.rich)},
        {"_name": "stream", **bench_stream(app, args.chunks)},
        {"_name": "restore", **bench_restore(app, args.messages)},
        {"_name": "resize", **bench_resize(app, args.messages)},
        {"_name": "scroll", **bench_scroll(app, args.messages)},
        {"_name": "theme", **bench_theme(app, args.messages)},
    ]
    _print_report(env, fonts, [dict(item) for item in results])
    if args.json:
        payload = {"env": env, "fonts": fonts, "results": results}
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        print(f"已写入 {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
