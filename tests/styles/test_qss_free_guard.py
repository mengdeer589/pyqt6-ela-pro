"""机器守卫：全库（库 + 示例）不允许出现 QSS 调用。

规则见 AGENTS.md「禁用 QSS / QStyle 路线」：需要非主题色文字 / 纯色底 / 透明底 /
圆角卡片时，用 ``pyqt6_ela_pro._styles`` 里的原语，不要写 ``setStyleSheet``。
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
#: 第一方源码树（第三方 / 外部副本目录不在其中）
GUARDED_TREES = ("pyqt6_ela_pro", "example", "llm_test")

#: 允许出现 ``setStyleSheet`` 字样的上下文（仅文档说明，不是调用）
_ALLOWED_MARKERS = ("``setStyleSheet``", "``setStyleSheet()``")


def _iter_sources():
    for tree in GUARDED_TREES:
        root = REPO_ROOT / tree
        if not root.exists():
            continue
        yield from sorted(root.rglob("*.py"))


def test_no_stylesheet_calls_in_repo():
    """任何 ``*.setStyleSheet(...)`` 调用都算违规（含 example / llm_test）。"""
    offenders = []
    for path in _iter_sources():
        for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            line = raw.strip()
            if ".setStyleSheet(" not in line:
                continue
            if any(marker in line for marker in _ALLOWED_MARKERS):
                continue  # 文档里提到 API 名，不是调用
            offenders.append(f"{path.relative_to(REPO_ROOT)}:{number}: {line}")
    assert offenders == [], "库内禁止 QSS：\n" + "\n".join(offenders)
