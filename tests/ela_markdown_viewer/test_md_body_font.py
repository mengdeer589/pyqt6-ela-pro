"""Markdown 正文字体族指定接口：单族、主题切换保留、进程默认与缺失回退。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from PyQt6.QtGui import QFontDatabase

from pyqt6_ela_pro import (
    ElaMarkdownViewer,
    isFontFamilyAvailable,
    registerMarkdownTheme,
    setDefaultMarkdownBodyFontFamily,
    unregisterMarkdownTheme,
)

ROOT = Path(__file__).resolve().parents[2]

SOURCE = """# 标题

正文 **加粗** 与 `inline code`。

```python
print("hello")
```
"""


def _available_family(exclude=()) -> str:
    families = QFontDatabase.families()
    for name in ("Consolas", "Courier New", "Segoe UI", "Arial", "Calibri"):
        if name in families and name not in exclude:
            return name
    for name in families:
        if name not in exclude:
            return name
    return ""


@pytest.fixture(autouse=True)
def _reset_default():
    setDefaultMarkdownBodyFontFamily("")
    yield
    setDefaultMarkdownBodyFontFamily("")


def test_set_body_font_family_applies_to_document(make):
    viewer = make(ElaMarkdownViewer)
    viewer.setMarkdown(SOURCE)
    base = viewer.bodyFontFamily()
    target = _available_family(
        exclude=(
            base,
            viewer.codeFontFamily(),
            viewer.codeLatinFontFamily(),
        )
    )
    assert target

    viewer.setBodyFontFamily(target)

    assert viewer.bodyFontFamily() == target
    assert viewer.document().defaultFont().families() == [target]
    assert viewer.markdown() == SOURCE
    # 代码块仍走独立的等宽字体链，不被正文字体覆盖
    assert viewer.codeFontFamily() != target


def test_empty_family_restores_theme_default(make):
    viewer = make(ElaMarkdownViewer)
    viewer.setMarkdown(SOURCE)
    base = viewer.bodyFontFamily()
    target = _available_family(exclude=(base,))
    assert target

    viewer.setBodyFontFamily(target)
    viewer.setBodyFontFamily("")

    assert viewer.bodyFontFamily() == base


def test_multiple_families_take_first(make):
    viewer = make(ElaMarkdownViewer)
    base = viewer.bodyFontFamily()
    target = _available_family(exclude=(base,))
    assert target

    viewer.setBodyFontFamily(f"{target}, Microsoft YaHei")

    assert viewer.bodyFontFamily() == target


def test_missing_font_falls_back_to_theme(make):
    viewer = make(ElaMarkdownViewer)
    viewer.setMarkdown(SOURCE)
    base = viewer.bodyFontFamily()

    viewer.setBodyFontFamily("__NoSuchMarkdownBodyFont__")

    assert isFontFamilyAvailable("__NoSuchMarkdownBodyFont__") is False
    assert viewer.bodyFontFamily() == base


def test_missing_override_falls_back_to_process_default(make):
    base = make(ElaMarkdownViewer).bodyFontFamily()
    target = _available_family(exclude=(base,))
    assert target
    setDefaultMarkdownBodyFontFamily(target)
    viewer = make(ElaMarkdownViewer)

    viewer.setBodyFontFamily("__NoSuchMarkdownBodyFont__")

    assert viewer.bodyFontFamily() == target


def test_theme_switch_keeps_explicit_font(make):
    viewer = make(ElaMarkdownViewer)
    base = viewer.bodyFontFamily()
    target = _available_family(exclude=(base,))
    other = _available_family(exclude=(base, target))
    if not target or not other:
        pytest.skip("测试机没有足够的可用字体族")

    viewer.setBodyFontFamily(target)
    registerMarkdownTheme("font-switch", layout={"body_font_family": other})
    try:
        viewer.setMarkdownTheme("font-switch")
        assert viewer.bodyFontFamily() == target
    finally:
        unregisterMarkdownTheme("font-switch")


def test_zoom_keeps_body_font(make):
    viewer = make(ElaMarkdownViewer)
    base = viewer.bodyFontFamily()
    target = _available_family(exclude=(base,))
    assert target

    viewer.setBodyFontFamily(target)
    viewer.setZoomFactor(1.5)

    assert viewer.bodyFontFamily() == target


def test_process_default_only_affects_new_viewers(make):
    old = make(ElaMarkdownViewer)
    base = old.bodyFontFamily()
    target = _available_family(exclude=(base,))
    assert target

    setDefaultMarkdownBodyFontFamily(target)
    new = make(ElaMarkdownViewer)

    assert new.bodyFontFamily() == target
    assert old.bodyFontFamily() == base


def test_font_probe_without_qapp_does_not_crash():
    code = (
        "from pyqt6_ela_pro import isFontFamilyAvailable, "
        "setDefaultMarkdownBodyFontFamily, defaultMarkdownBodyFontFamily\n"
        "print(isFontFamilyAvailable('Microsoft YaHei'))\n"
        "setDefaultMarkdownBodyFontFamily('Microsoft YaHei')\n"
        "print(repr(defaultMarkdownBodyFontFamily()))\n"
    )
    result = subprocess.run(
        [sys.executable, "-X", "utf8", "-c", code],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["False", "'Microsoft YaHei'"]
