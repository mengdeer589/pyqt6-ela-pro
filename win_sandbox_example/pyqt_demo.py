"""PyQt6 + pyqt6-ela-pro 的沙箱接入示例（不是 Dash）。

演示四件事：

1. ``QtApprovalHandler`` + ``ElaConfirmDialog`` 做越界审批；
2. 前台命令在 ``QThread`` 里跑，停止按钮走 ``Sandbox.cancel_foreground()``；
3. 后台任务用 ``QTimer`` 轮询 ``Sandbox.check()``；
4. 关窗口 ``Sandbox.close()`` 收掉所有进程树。

::

    python pyqt_demo.py
    python pyqt_demo.py --smoke     # 构造后 0.8 秒退出，用于冒烟
"""

from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import QApplication, QHBoxLayout, QVBoxLayout, QWidget
from PyQt6ElaWidgetTools import ElaLineEdit, ElaPlainTextEdit, ElaText, eApp

from pyqt6_ela_pro import ElaButton
from qt_approval import QtApprovalHandler
from win_sandbox import (
    ApprovalMode,
    JsonlAudit,
    PolicyDenied,
    Sandbox,
    SandboxPolicy,
)


class _RunThread(QThread):
    """把阻塞的 ``Sandbox.run`` 放到工作线程，避免卡 GUI。"""

    done = pyqtSignal(object)

    def __init__(self, box: Sandbox, command: str, parent: QWidget) -> None:
        super().__init__(parent)
        self._box = box
        self._command = command

    def run(self) -> None:
        self.done.emit(self._box.run(self._command))


class SandboxWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("win_sandbox + pyqt6-ela-pro")
        self.resize(860, 640)

        runtime = Path.cwd() / "runtime"
        self._workspace = runtime / "pyqt_workspace"
        self._audit = JsonlAudit(runtime / "pyqt_audit.jsonl")
        self._approval = QtApprovalHandler(self)
        self._box = Sandbox(
            self._workspace,
            audit=self._audit,
            approval=self._approval,
            policy=SandboxPolicy(approval_mode=ApprovalMode.ASK),
        )
        self._box.prepare()

        self._thread: _RunThread | None = None
        self._task_id: str | None = None

        self._input = ElaLineEdit(self)
        self._input.setPlaceholderText("输入命令，例如 echo hi > a.txt")
        self._input.returnPressed.connect(self._run_foreground)

        self._run_btn = ElaButton("前台运行", parent=self)
        self._run_btn.clicked.connect(self._run_foreground)
        self._bg_btn = ElaButton("后台运行", parent=self)
        self._bg_btn.clicked.connect(self._run_background)
        self._stop_btn = ElaButton("停止", parent=self)
        self._stop_btn.clicked.connect(self._stop)
        self._approve_btn = ElaButton("测试越界写", parent=self)
        self._approve_btn.clicked.connect(self._test_approval)

        self._output = ElaPlainTextEdit(self)
        self._output.setReadOnly(True)
        self._status = ElaText("", self)
        self._status.setTextPixelSize(12)

        buttons = QHBoxLayout()
        buttons.addWidget(self._run_btn)
        buttons.addWidget(self._bg_btn)
        buttons.addWidget(self._stop_btn)
        buttons.addWidget(self._approve_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(self._input)
        layout.addLayout(buttons)
        layout.addWidget(self._output, 1)
        layout.addWidget(self._status)

        self._poll = QTimer(self)
        self._poll.setInterval(500)
        self._poll.timeout.connect(self._poll_task)

        self._append(f"workspace: {self._workspace}")
        self._append(f"shell    : {self._box.shell.label}")
        self._status.setText("就绪")

    def _append(self, text: str) -> None:
        self._output.appendPlainText(text)
        bar = self._output.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _set_busy(self, busy: bool) -> None:
        self._run_btn.setEnabled(not busy)
        self._bg_btn.setEnabled(not busy)

    def _run_foreground(self) -> None:
        command = self._input.text().strip()
        if not command or self._thread is not None:
            return
        self._set_busy(True)
        self._status.setText("前台运行中…")
        self._thread = _RunThread(self._box, command, self)
        self._thread.done.connect(self._on_run_done)
        self._thread.finished.connect(self._on_thread_finished)
        self._thread.start()

    def _on_run_done(self, result: object) -> None:
        self._append(
            f"[exit={result.exit_code} cancelled={result.cancelled} "  # type: ignore[attr-defined]
            f"timeout={result.timed_out}]"
        )
        if result.stdout:  # type: ignore[attr-defined]
            self._append(result.stdout.rstrip())  # type: ignore[attr-defined]
        if result.stderr:  # type: ignore[attr-defined]
            self._append("[stderr]\n" + result.stderr.rstrip())  # type: ignore[attr-defined]
        self._status.setText("完成")

    def _on_thread_finished(self) -> None:
        if self._thread is not None:
            self._thread.deleteLater()
            self._thread = None
        self._set_busy(False)

    def _run_background(self) -> None:
        command = self._input.text().strip()
        if not command:
            return
        task = self._box.start(command)
        self._task_id = task.id
        self._append(f"[后台任务 {task.id}] {command}")
        self._status.setText(f"后台任务 {task.id} 运行中…")
        self._poll.start()

    def _poll_task(self) -> None:
        if not self._task_id:
            self._poll.stop()
            return
        info = self._box.check(self._task_id)
        self._status.setText(info.splitlines()[0])
        if "running" not in info:
            self._poll.stop()
            self._append(info)
            self._task_id = None

    def _stop(self) -> None:
        hit = self._box.cancel_foreground()
        self._status.setText(f"停止：命中 {hit} 条前台命令")

    def _test_approval(self) -> None:
        outside = Path.home() / "win_sandbox_pyqt_approval.txt"
        try:
            target = self._box.resolve(outside, tool="write_file", operation="write")
        except PolicyDenied as exc:
            self._append(exc.to_message())
            return
        target.write_text("approved", encoding="utf-8")
        self._append(f"已写入（审批通过）: {target}")
        target.unlink(missing_ok=True)

    def closeEvent(self, event) -> None:
        self._poll.stop()
        if self._thread is not None:
            self._box.cancel_foreground()
            self._thread.wait(3000)
            self._thread = None
        self._box.close()
        super().closeEvent(event)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    app = QApplication(["win-sandbox-pyqt"])
    eApp.init()
    window = SandboxWindow()
    window.show()
    if "--smoke" in argv:
        QTimer.singleShot(800, app.quit)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
