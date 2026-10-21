"""宿主视角的组件构造成本表（per-instance 成本 + 是否创建原生子窗口）。

用法：``python bench_components.py [--repeat 3]``（真桌面；供 docs/performance.md 引用）
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time


def run_once() -> int:
    from PyQt6 import QtCore, QtWidgets

    from PyQt6ElaWidgetTools import eApp, ElaText

    app = QtWidgets.QApplication(sys.argv)
    eApp.init()
    import pyqt6_ela_pro as lib
    from pyqt6_ela_pro._styles import ColorText

    now = time.perf_counter
    host = QtWidgets.QWidget()

    cases = [
        ("ElaText（上游）", lambda: ElaText("x", host), 300),
        ("ElaButton", lambda: lib.ElaButton("x", parent=host), 200),
        ("ElaChip", lambda: lib.ElaChip("x", parent=host), 200),
        ("ColorText", lambda: ColorText("x", host), 200),
        ("ElaBlueprintCanvas", lambda: lib.ElaBlueprintCanvas(parent=host), 5),
        ("ElaDropDownButton", lambda: lib.ElaDropDownButton("x", parent=host), 200),
        ("ElaSplitButton", lambda: lib.ElaSplitButton("x", parent=host), 200),
        ("ElaField", lambda: lib.ElaField(parent=host), 100),
        ("ElaAvatar", lambda: lib.ElaAvatar(parent=host), 100),
        ("ElaShimmer", lambda: lib.ElaShimmer(parent=host), 100),
        ("ElaSelectorBar", lambda: lib.ElaSelectorBar(parent=host), 100),
        ("ElaMarkdownViewer", lambda: lib.ElaMarkdownViewer(parent=host), 20),
        ("ElaTerminalView", lambda: lib.ElaTerminalView(parent=host), 20),
        ("ElaChatView", lambda: lib.ElaChatView(parent=host), 10),
    ]
    rows = []
    for label, factory, n in cases:
        try:
            obj = factory()
            obj.deleteLater()
            app.processEvents()
            samples = []
            for _ in range(3):
                t = now()
                for _ in range(n):
                    obj = factory()
                    obj.deleteLater()
                samples.append((now() - t) * 1000 / n)
                app.processEvents()
            first = factory()
            children = len(first.findChildren(QtWidgets.QWidget))
            native = any(
                w.testAttribute(QtCore.Qt.WidgetAttribute.WA_NativeWindow)
                for w in [first, *first.findChildren(QtWidgets.QWidget)]
            )
            first.deleteLater()
            app.processEvents()
            rows.append(
                {
                    "label": label,
                    "ms": statistics.median(samples),
                    "children": children,
                    "native": native,
                }
            )
        except Exception as exc:  # noqa: BLE001
            rows.append({"label": label, "ms": -1.0, "note": str(exc)[:80]})
    print("JSON " + json.dumps({"rows": rows}))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if args.once:
        return run_once()
    runs = []
    for _ in range(args.repeat):
        proc = subprocess.run(
            [sys.executable, sys.argv[0], "--once"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        payload = [line for line in proc.stdout.splitlines() if line.startswith("JSON ")]
        if not payload:
            print("run FAILED: %s" % (proc.stderr or "")[-400:])
            continue
        runs.append(json.loads(payload[0][5:]))
    if not runs:
        return 1
    rows = runs[-1]["rows"]
    print("%-22s %10s %9s %7s  %s" % ("component", "ms/instance", "children", "native", "note"))
    for row in rows:
        print(
            "%-22s %10.3f %9s %7s  %s"
            % (
                row["label"],
                row["ms"],
                row.get("children", "-"),
                "yes" if row.get("native") else "no",
                row.get("note", ""),
            )
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
