"""Measure import / paint / scroll / resize / search on an opencode bundle."""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PyQt6.QtWidgets import QApplication, QVBoxLayout, QWidget  # noqa: E402
from PyQt6ElaWidgetTools import eApp  # noqa: E402

from bench_common import (  # noqa: E402
    apply_preset,
    drain_until,
    load_bundle,
    process_events,
    rss_mb,
    widget_counts,
)
from pyqt6_ela_pro.chat import ElaChatWidget  # noqa: E402
from pyqt6_ela_pro.chat.blocks import SubagentCard, ToolCallCard  # noqa: E402

DEFAULT_BUNDLE = BASE / "data" / "ses_e734295a1ffeFEIRdCrlNDpg9f.stress.json"


def _summary(values: list) -> dict:
    if not values:
        return {"count": 0}
    ordered = sorted(values)
    p95 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]
    return {
        "count": len(values),
        "avg_ms": statistics.fmean(values) * 1000.0,
        "p95_ms": p95 * 1000.0,
        "max_ms": max(values) * 1000.0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    parser.add_argument("--preset", default="default")
    parser.add_argument("--width", type=int, default=1400)
    parser.add_argument("--height", type=int, default=900)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--steps", type=int, default=100)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--screenshot", type=Path)
    parser.add_argument("--no-scroll", action="store_true")
    args = parser.parse_args()

    parse_started = time.perf_counter()
    bundle = load_bundle(args.bundle, args.limit)
    parse_seconds = time.perf_counter() - parse_started

    app = QApplication(sys.argv)
    eApp.init()
    window = QWidget()
    window.setWindowTitle("opencode chat benchmark")
    window.resize(args.width, args.height)
    layout = QVBoxLayout(window)
    layout.setContentsMargins(0, 0, 0, 0)
    chat = ElaChatWidget(window)
    layout.addWidget(chat)
    window.show()
    process_events(app, 0.2)
    view = chat.chatView()
    apply_preset(view, args.preset)

    finished = []
    view.batchRenderFinished.connect(lambda: finished.append(True))
    rss_before = rss_mb()
    import_started = time.perf_counter()
    view.importSession(bundle)
    import_seconds = time.perf_counter() - import_started
    drained = drain_until(app, lambda: bool(finished), timeout=args.timeout)
    process_events(app, 0.3)
    rss_after = rss_mb()
    counts = widget_counts(view)

    repaint_started = time.perf_counter()
    view._scroll.viewport().repaint()
    app.processEvents()
    repaint_seconds = time.perf_counter() - repaint_started

    scroll = {"count": 0}
    scroll_values = []
    if not args.no_scroll:
        bar = view.scrollBar()
        maximum = max(0, bar.maximum())
        steps = max(1, args.steps)
        samples = []
        for index in range(steps + 1):
            value = int(maximum * index / steps)
            started = time.perf_counter()
            bar.setValue(value)
            app.processEvents()
            view._scroll.viewport().repaint()
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            scroll_values.append(elapsed_ms / 1000.0)
            samples.append((index, value, elapsed_ms))
        scroll = _summary(scroll_values)
        scroll["top_ms"] = [
            {"step": index, "value": value, "ms": round(ms, 1)}
            for index, value, ms in sorted(samples, key=lambda item: item[2], reverse=True)[:5]
        ]
    counts_after_scroll = widget_counts(view)

    cards = view.findChildren(SubagentCard) or view.findChildren(ToolCallCard)
    expand_ms = None
    if cards:
        started = time.perf_counter()
        cards[-1].setOpened(True)
        app.processEvents()
        expand_ms = (time.perf_counter() - started) * 1000.0

    search_started = time.perf_counter()
    hits = view.searchText("edit")
    app.processEvents()
    search_ms = (time.perf_counter() - search_started) * 1000.0
    view.clearSearch()

    resize = []
    for width in (1200, 900, 1400):
        started = time.perf_counter()
        window.resize(width, args.height)
        app.processEvents()
        resize.append((width, (time.perf_counter() - started) * 1000.0))

    if args.screenshot is not None:
        args.screenshot.parent.mkdir(parents=True, exist_ok=True)
        process_events(app, 0.2)
        window.grab().save(str(args.screenshot))

    result = {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "bundle": str(args.bundle),
        "preset": args.preset,
        "limit": args.limit,
        "window": [args.width, args.height],
        "bundle_parse_s": parse_seconds,
        "import_s": import_seconds,
        "drained": drained,
        "viewport_repaint_s": repaint_seconds,
        "rss_before_mb": rss_before,
        "rss_after_mb": rss_after,
        "rss_delta_mb": rss_after - rss_before,
        "counts": counts,
        "counts_after_scroll": counts_after_scroll,
        "scroll": scroll,
        "expand_last_card_ms": expand_ms,
        "search_hits": hits,
        "search_ms": search_ms,
        "resize": [{"width": width, "ms": ms} for width, ms in resize],
        "bundle_extra": bundle.get("extra") or {},
    }
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    window.close()
    app.processEvents()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
