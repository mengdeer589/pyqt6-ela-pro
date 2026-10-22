"""``prepareWebEngine`` 的回归守卫（QtWebEngine 接入约束）。"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _run(code: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
    )


class TestPrepareWebEngine:
    def test_import_has_no_global_side_effect(self):
        """import 本库不得替宿主打开全局共享 GL 上下文。"""
        result = _run(
            """
            import pyqt6_ela_pro
            from PyQt6.QtCore import QCoreApplication, Qt
            print(
                QCoreApplication.testAttribute(
                    Qt.ApplicationAttribute.AA_ShareOpenGLContexts
                )
            )
            """
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "False"

    def test_prepare_before_app_sets_attribute(self):
        result = _run(
            """
            from pyqt6_ela_pro import prepareWebEngine
            from PyQt6.QtCore import QCoreApplication, Qt
            print(prepareWebEngine())
            print(
                QCoreApplication.testAttribute(
                    Qt.ApplicationAttribute.AA_ShareOpenGLContexts
                )
            )
            """
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.splitlines() == ["True", "True"]

    def test_prepare_after_app_is_rejected(self):
        """app 之后调用必须返回 False，且不留下「看起来设上了」的假象。"""
        result = _run(
            """
            from pyqt6_ela_pro import prepareWebEngine
            from PyQt6.QtWidgets import QApplication
            from PyQt6.QtCore import QCoreApplication, Qt
            app = QApplication(["pyqt6-ela-pro-tests"])
            print(prepareWebEngine())
            print(
                QCoreApplication.testAttribute(
                    Qt.ApplicationAttribute.AA_ShareOpenGLContexts
                )
            )
            """
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.splitlines() == ["False", "False"]

    def test_exported_from_package_root(self):
        import pyqt6_ela_pro

        assert callable(pyqt6_ela_pro.prepareWebEngine)
        assert "prepareWebEngine" in pyqt6_ela_pro.__all__
