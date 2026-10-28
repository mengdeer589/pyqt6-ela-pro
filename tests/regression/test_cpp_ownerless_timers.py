"""扫 C++ 源码里的「无主 ``QTimer::singleShot``」。

Qt 6.8 的 ``QSingleShotTimer`` 在 context 为 ``nullptr`` 时把回调接到定时器自己
（``qsingleshottimer.cpp``：``r ? r : this``），不绑任何 QObject 生命周期。PyQt
宿主在 ``exec()`` 返回后会立刻析构 Python 子类对话框，回调再 ``emit`` 就是对已释放
sender 发信号 —— ``QMetaObject::activate`` 读 ``sender->d_ptr`` 访问违例
（Win7 上表现为 ``Qt6Core!doActivate``；见 ``AGENTS.md``「对话框基座」）。

本守卫只做形状检查；正确写法是 ``QTimer::singleShot(0, this, ...)``。
"""

from __future__ import annotations

import pathlib
import re

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CPP_ROOT = _ROOT / "PyElaWidgetTools" / "ElaWidgetTools" / "ElaWidgetTools"

#: ``QTimer::singleShot(<ms>, nullptr, ...)``（允许跨行，直到第一个分号）。
_OWNERLESS_RE = re.compile(r"QTimer\s*::\s*singleShot\s*\([^;]*?\bnullptr\b", re.S)


def _sites_in_source(text: str) -> list[int]:
    """返回源码里无主 singleShot 的行号（1 基）。"""
    return [
        text.count("\n", 0, match.start()) + 1 for match in _OWNERLESS_RE.finditer(text)
    ]


def _iter_cpp_files():
    if not _CPP_ROOT.is_dir():  # pragma: no cover - 子模块未检出
        return
    yield from sorted(_CPP_ROOT.rglob("*.cpp"))
    yield from sorted(_CPP_ROOT.rglob("*.h"))


class TestNoOwnerlessSingleShotInBindings:
    def test_every_single_shot_has_a_context(self):
        if not _CPP_ROOT.is_dir():  # pragma: no cover
            pytest.skip("PyElaWidgetTools 子模块未检出")

        offenders: list[str] = []
        for path in _iter_cpp_files():
            text = path.read_text(encoding="utf-8")
            for lineno in _sites_in_source(text):
                offenders.append(f"  {path.relative_to(_ROOT)}:{lineno}")

        assert not offenders, (
            "这些 QTimer::singleShot 没有 context 对象（无主定时器），对象销毁后"
            "回调会打到已释放 sender 上（Qt6Core!doActivate 读 sender->d_ptr = AV）：\n"
            + "\n".join(offenders)
            + "\n\n正确写法：QTimer::singleShot(0, this, [this]() { ... });"
        )

    def test_scanner_finds_planted_sites(self):
        """守卫本身要有效：坏形状必须抓到，带 context 的必须放过。"""
        bad = (
            "QTimer::singleShot(0, nullptr, [=]() {\n"
            "    Q_EMIT clicked();\n"
            "});\n"
            "QTimer::singleShot(\n"
            "    120, nullptr, [=]() { Q_EMIT done(); });\n"
        )
        good = "QTimer::singleShot(0, this, [this]() {\n    Q_EMIT clicked();\n});\n"
        assert _sites_in_source(bad) == [1, 4]
        assert _sites_in_source(good) == []
