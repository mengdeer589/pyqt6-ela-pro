"""Measure the chat trace panel on an opencode bundle (real window).

The panel must not rebuild per-row widgets: timeline rows are painted on one
canvas, the graph page is created lazily, and replay only repaints the playhead
strip. Run with ``--effects off`` to compare the no-animation path.
"""

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

from PyQt6.QtCore import QEvent, QPointF, Qt  # noqa: E402
from PyQt6.QtGui import QMouseEvent  # noqa: E402
from PyQt6.QtWidgets import QApplication, QVBoxLayout, QWidget  # noqa: E402
from PyQt6ElaWidgetTools import eApp  # noqa: E402

from bench_common import (  # noqa: E402
    drain_until,
    load_bundle,
    process_events,
    rss_mb,
)
from pyqt6_ela_pro.chat import (  # noqa: E402
    ElaChatTraceOptions,
    ElaChatTracePanel,
    ElaChatView,
    buildTraceRows,
)

DEFAULT_BUNDLE = BASE / "data" / "ses_e734295a1ffeFEIRdCrlNDpg9f.stress.json"


def _summary(values: list) -> dict:
    if not values:
        return {"count": 0}
    ordered = sorted(values)
    p95 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]
    return {
        "count": len(values),
        "avg_ms": statistics.fmean(values),
        "p95_ms": p95,
        "max_ms": max(values),
    }


def _move_to(canvas, y: float) -> None:
    pos = QPointF(60.0, y)
    event = QMouseEvent(
        QEvent.Type.MouseMove,
        pos,
        QPointF(canvas.mapToGlobal(pos.toPoint())),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.instance().sendEvent(canvas, event)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--effects", choices=("on", "off"), default="on")
    parser.add_argument("--width", type=int, default=1000)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--steps", type=int, default=40)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--screenshot", type=Path)
    args = parser.parse_args()

    bundle = load_bundle(args.bundle, args.limit)
    app = QApplication(["bench-trace"])
    eApp.init()
    window = QWidget()
    window.resize(args.width, args.height)
    layout = QVBoxLayout(window)
    layout.setContentsMargins(0, 0, 0, 0)
    chat = ElaChatView(window)
    layout.addWidget(chat)
    window.show()
    process_events(app, 0.2)

    done = []
    chat.batchRenderFinished.connect(lambda: done.append(True))
    started = time.perf_counter()
    chat.importSession(bundle)
    import_s = time.perf_counter() - started
    drained = drain_until(app, lambda: bool(done), timeout=180.0)
    process_events(app, 0.3)
    messages = chat.messages()

    build_times = []
    result = None
    for _ in range(5):
        started = time.perf_counter()
        result = buildTraceRows(messages)
        build_times.append((time.perf_counter() - started) * 1000.0)

    before = rss_mb()
    panel = ElaChatTracePanel(chat, window)
    layout.addWidget(panel, 1)
    effects = args.effects == "on"
    panel.setOptions(ElaChatTraceOptions(effects=effects, replay=True, tracks=True))
    process_events(app, 0.3)
    refresh_times = []
    for _ in range(3):
        started = time.perf_counter()
        panel.refresh()
        app.processEvents()
        refresh_times.append((time.perf_counter() - started) * 1000.0)

    started = time.perf_counter()
    panel._canvas.repaint()
    app.processEvents()
    first_paint_ms = (time.perf_counter() - started) * 1000.0
    timeline_widgets = len(panel.findChildren(QWidget))

    bar = panel._scroll.verticalScrollBar()
    maximum = max(0, bar.maximum())
    scroll_times = []
    for index in range(args.steps + 1):
        value = int(maximum * index / max(1, args.steps))
        bar.setValue(value)
        app.processEvents()
        started = time.perf_counter()
        panel._canvas.repaint()
        scroll_times.append((time.perf_counter() - started) * 1000.0)

    hover_times = []
    visual = panel._canvas.visualRows()
    if visual:
        for item in visual[: min(40, len(visual))]:
            _move_to(panel._canvas, item.y + item.height / 2.0)
            started = time.perf_counter()
            panel._canvas.repaint()
            hover_times.append((time.perf_counter() - started) * 1000.0)
    panel._canvas.leaveEvent(QEvent(QEvent.Type.Leave))

    replay_frames = []
    if visual:
        panel.startReplay()
        deadline = time.perf_counter() + 1.6
        while time.perf_counter() < deadline:
            started = time.perf_counter()
            app.processEvents()
            replay_frames.append((time.perf_counter() - started) * 1000.0)
            time.sleep(0.01)
        panel.stopReplay()

    before_graph = time.perf_counter()
    panel.setViewMode("graph")
    app.processEvents()
    graph_switch_ms = (time.perf_counter() - before_graph) * 1000.0
    process_events(app, 0.2)
    graph_canvas = panel._graph_page._canvas
    graph_nodes = len(graph_canvas.graph.nodes()) if graph_canvas else 0
    started = time.perf_counter()
    if graph_canvas is not None:
        viewport = getattr(graph_canvas, "_viewport", graph_canvas)
        viewport.repaint()
    app.processEvents()
    graph_paint_ms = (time.perf_counter() - started) * 1000.0
    panel.setViewMode("timeline")
    process_events(app, 0.1)

    if args.screenshot is not None:
        args.screenshot.parent.mkdir(parents=True, exist_ok=True)
        process_events(app, 0.2)
        panel.grab().save(str(args.screenshot))

    payload = {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "bundle": str(args.bundle),
        "window": [args.width, args.height],
        "effects": args.effects,
        "import_s": import_s,
        "drained": drained,
        "messages": len(messages),
        "turns": len(result.rows) if result else 0,
        "tools": result.tool_count if result else 0,
        "trace_rows": len(result.flatten()) if result else 0,
        "clip_ms": result.clip_ms if result else 0,
        "clipped": result.clipped_count if result else 0,
        "build_trace": _summary(build_times),
        "panel_refresh": _summary(refresh_times),
        "first_paint_ms": first_paint_ms,
        "scroll": _summary(scroll_times),
        "hover": _summary(hover_times),
        "replay": _summary(replay_frames),
        "graph_switch_ms": graph_switch_ms,
        "graph_nodes": graph_nodes,
        "graph_paint_ms": graph_paint_ms,
        "rss_delta_mb": rss_mb() - before,
        "timeline_widgets": timeline_widgets,
        "panel_widgets": len(panel.findChildren(QWidget)),
        "visual_rows": len(visual),
    }
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    window.close()
    app.processEvents()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
