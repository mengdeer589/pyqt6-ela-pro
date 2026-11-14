"""Render an exported opencode bundle in a real ElaChatWidget window."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PyQt6.QtCore import QTimer  # noqa: E402
from PyQt6.QtWidgets import QApplication, QVBoxLayout, QWidget  # noqa: E402
from PyQt6ElaWidgetTools import eApp  # noqa: E402

from bench_common import (  # noqa: E402
    apply_preset,
    load_bundle,
    process_events,
    widget_counts,
)
from pyqt6_ela_pro.chat import ElaChatWidget  # noqa: E402

DEFAULT_BUNDLE = BASE / "data" / "ses_e734295a1ffeFEIRdCrlNDpg9f.stress.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    parser.add_argument("--preset", default="default")
    parser.add_argument("--width", type=int, default=1400)
    parser.add_argument("--height", type=int, default=900)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--message", type=int, default=0)
    parser.add_argument("--open-subagents", action="store_true")
    parser.add_argument("--screenshot", type=Path)
    parser.add_argument("--auto-close", type=int, default=0)
    args = parser.parse_args()

    bundle = load_bundle(args.bundle, args.limit)
    title = str((bundle.get("session") or {}).get("title") or "opencode replay")

    app = QApplication(sys.argv)
    eApp.init()
    window = QWidget()
    window.setWindowTitle(f"opencode replay · {title}")
    window.resize(args.width, args.height)
    layout = QVBoxLayout(window)
    layout.setContentsMargins(0, 0, 0, 0)
    chat = ElaChatWidget(window)
    layout.addWidget(chat)
    window.show()
    process_events(app, 0.2)

    apply_preset(chat.chatView(), args.preset)
    started = time.perf_counter()
    chat.chatView().importSession(bundle)
    process_events(app, 0.2)
    elapsed = time.perf_counter() - started
    if args.message:
        chat.chatView().scrollToMessage(args.message)
        process_events(app, 0.2)
    if args.open_subagents:
        from pyqt6_ela_pro.chat.blocks import SubagentCard

        for card in chat.chatView().findChildren(SubagentCard):
            card.setOpened(True)
        process_events(app, 0.2)
    print(f"imported: {chat.chatView().count()} messages in {elapsed:.2f}s")
    print(f"widgets: {widget_counts(chat.chatView())}")

    if args.screenshot is not None:
        args.screenshot.parent.mkdir(parents=True, exist_ok=True)

        def capture() -> None:
            process_events(app, 0.2)
            window.grab().save(str(args.screenshot))
            print(f"screenshot: {args.screenshot}")
            window.close()
            app.quit()

        QTimer.singleShot(max(0, args.auto_close or 1200), capture)

    if args.auto_close and args.screenshot is None:
        QTimer.singleShot(args.auto_close, window.close)
        QTimer.singleShot(args.auto_close + 100, app.quit)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
