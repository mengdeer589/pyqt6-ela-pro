"""底层原语对照台：对象创建 / C++→Python 虚调用 / 普通方法调用 / 信号（跨绑定可跑）。

用法：``python bench_micro.py [--repeat 3]``（在 PyQt5 / PyQt6 / PySide6 环境里都能跑）
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time


def detect_stack():
    try:
        import PySide6

        from PySide6 import QtCore, QtGui, QtWidgets

        return "PySide6", QtCore, QtGui, QtWidgets, PySide6.__version__
    except ImportError:
        pass
    try:
        import PyQt6

        from PyQt6 import QtCore, QtGui, QtWidgets

        return "PyQt6", QtCore, QtGui, QtWidgets, PyQt6.QtCore.PYQT_VERSION_STR
    except ImportError:
        pass
    import PyQt5

    from PyQt5 import QtCore, QtGui, QtWidgets

    return "PyQt5", QtCore, QtGui, QtWidgets, PyQt5.QtCore.PYQT_VERSION_STR


def run_once() -> int:
    name, QtCore, QtGui, QtWidgets, version = detect_stack()
    now = time.perf_counter
    app = QtWidgets.QApplication(sys.argv)

    class Probe(QtWidgets.QWidget):
        """Python 子类：sizeHint / paintEvent / resizeEvent / showEvent 都走 Python 覆写。"""

        sig = QtCore.Signal() if hasattr(QtCore, "Signal") else QtCore.pyqtSignal()

        def sizeHint(self):
            return QtCore.QSize(120, 30)

        def minimumSizeHint(self):
            return QtCore.QSize(60, 20)

        def paintEvent(self, _event):
            # 最小 Python 覆写绘制：只创建 QPainter 并立刻 end()。
            # 不画任何图元 —— 测的是「进出一次绘制链」的固定开销。
            QtGui.QPainter(self).end()

        def resizeEvent(self, event):
            super().resizeEvent(event)

        def event(self, event):
            return super().event(event)

    out = {"stack": name, "binding_version": version, "qt": QtCore.qVersion()}

    def bench(label, fn, n):
        fn()
        t = now()
        for _ in range(n):
            fn()
        out[label] = (now() - t) * 1000 / n

    # ① 对象创建
    bench("QObject()", lambda: QtCore.QObject(), 5000)
    bench("QWidget()", lambda: QtWidgets.QWidget(), 5000)
    bench("QLabel('x')", lambda: QtWidgets.QLabel("x"), 3000)
    bench("QPushButton('x')", lambda: QtWidgets.QPushButton("x"), 2000)
    bench("PyWidget(子类)()", lambda: Probe(), 2000)

    host = QtWidgets.QWidget()
    probe = Probe()
    probe.setParent(host)
    probe.resize(120, 30)
    probe.show()
    app.processEvents()  # 先把 polish / 布局跑完，别把首帧开销算进基准

    # ② C++ → Python 虚调用（覆写在 Python 里）
    bench("sizeHint() [Py覆写]", lambda: probe.sizeHint(), 20000)
    bench("minimumSizeHint() [Py覆写]", lambda: probe.minimumSizeHint(), 20000)
    bench("resize() → resizeEvent [Py覆写]", lambda: probe.resize(100, 30), 5000)
    bench("show()/hide() [含 polish]", lambda: (probe.show(), probe.hide()), 2000)
    bench("grab() [paintEvent+render]", lambda: probe.grab(), 1000)

    # ③ 普通方法调用（对照：不跨 Python 覆写）
    bench("width()", lambda: probe.width(), 50000)
    bench("setToolTip('x')", lambda: probe.setToolTip("x"), 20000)
    bench("objectName()", lambda: probe.objectName(), 50000)
    bench("setVisible(True) x2", lambda: (probe.setVisible(True), probe.setVisible(True)), 5000)

    # ④ 信号
    slot = lambda: None  # noqa: E731
    bench("Signal.connect", lambda: probe.sig.connect(slot), 3000)
    probe.sig.connect(slot)
    bench("Signal.emit (1 槽)", lambda: probe.sig.emit(), 5000)

    print("JSON " + json.dumps(out))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeat", type=int, default=3)
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
    first = runs[0]
    print("=== %s %s | Qt %s ===" % (first["stack"], first["binding_version"], first["qt"]))
    keys = [k for k in first if k not in ("stack", "binding_version", "qt")]
    print("%-34s %12s" % ("op (ms/op)", "median"))
    for key in keys:
        vals = sorted(r[key] for r in runs)
        print("%-34s %12.5f" % (key, statistics.median(vals)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
