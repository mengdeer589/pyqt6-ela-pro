"""单例访问链的生命周期守卫（bug #19）。"""

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


def test_singleton_wrapper_is_not_python_owned():
    """``getInstance()`` 的 wrapper 不能在 GC 时把 C++ 单例一起删掉。"""
    result = _run(
        """
        import gc

        from PyQt6 import sip
        from PyQt6ElaWidgetTools import (
            ElaApplication,
            ElaTheme,
            eApp,
            eTheme,
        )

        theme = ElaTheme.getInstance()
        assert ElaTheme.getInstance() is theme
        assert sip.isdeleted(theme) is False
        del theme
        gc.collect()
        theme = ElaTheme.getInstance()
        print("theme_deleted", sip.isdeleted(theme))
        print("theme_mode", theme.getThemeMode())

        app = ElaApplication.getInstance()
        assert ElaApplication.getInstance() is app
        del app
        gc.collect()
        app = ElaApplication.getInstance()
        print("app_deleted", sip.isdeleted(app))
        print("app_font", app.getFontPixelSize())

        print("proxy_mode", eTheme.getThemeMode())
        print("proxy_font", eApp.getFontPixelSize())
        for name in dir(ElaTheme):
            getattr(eTheme, name)
        for name in dir(ElaApplication):
            getattr(eApp, name)
        """
    )
    assert result.returncode == 0, result.stderr
    assert "theme_deleted False" in result.stdout
    assert "app_deleted False" in result.stdout
    assert "proxy_mode ThemeMode.Light" in result.stdout
    assert "proxy_font 13" in result.stdout
