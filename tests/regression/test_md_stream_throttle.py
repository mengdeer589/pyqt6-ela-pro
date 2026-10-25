"""回归测试：流式渲染的节流契约。

第 2 步的结论是「已有自适应节流，只差一个常数」，不是「缺一层 pacer」：
``_STREAM_INTERVAL`` 从 40ms 调到 24ms 以提升视觉平滑度（实测 10.7 -> 16.9
次/秒，墙钟不变）。

这里锁定的是**契约**而不是具体速率（速率依赖机器与事件循环时序，写死会 flaky）：

1. 刷新次数被节流约束 —— 12 万字符不得退化成逐分片渲染（这正是 AGENTS.md
   警告的 O(n²) 回归）
2. 小尾部的间隔必须落在人眼平滑阈值内
3. 超长尾部必须切到 150/400ms 档保护吞吐
"""

from __future__ import annotations

import time

import pytest

from PyQt6.QtTest import QTest

import pyqt6_ela_pro.ela_markdown_viewer as M
from pyqt6_ela_pro.ela_markdown_viewer import ElaMarkdownViewer

pytestmark = pytest.mark.slow


def _count_renders(monkeypatch, qapp, text: str, chunk: int, wait_ms: int = 8):
    """流式喂入 text，返回 (渲染次数, 流式墙钟秒数)。"""
    calls = []
    original = M.ElaMarkdownViewer._render_fragment

    def traced(self, fragment, resource_doc):
        calls.append(len(fragment))
        return original(self, fragment, resource_doc)

    monkeypatch.setattr(M.ElaMarkdownViewer, "_render_fragment", traced)

    v = ElaMarkdownViewer()
    v.resize(600, 400)
    v.show()
    qapp.processEvents()
    v.beginStream()
    t0 = time.monotonic()
    for i in range(0, len(text), chunk):
        v.appendMarkdown(text[i : i + chunk])
        if wait_ms:
            QTest.qWait(wait_ms)
    v.endStream()
    for _ in range(4):
        qapp.processEvents()
    span = time.monotonic() - t0
    v.deleteLater()
    qapp.processEvents()
    return calls, span


class TestStreamThrottle:
    def test_renders_bounded_by_wall_clock_not_chunk_count(self, qapp, monkeypatch):
        """核心不变量：渲染次数由**时间**决定（≈ 墙钟 / 间隔），与分片数无关。

        这是 O(n²) 回归的真正防护：分片可以任意密，但刷新次数有上界。
        """
        chunk = "The quick brown fox jumps over the lazy dog. "
        text = chunk * 2200  # ~88k chars
        calls, span = _count_renders(monkeypatch, qapp, text, chunk=len(chunk))
        n_chunks = len(text) // len(chunk)

        assert calls, "完全没有渲染"
        budget = (span * 1000.0) / M._STREAM_INTERVAL
        assert len(calls) <= budget * 1.5 + 8, (
            f"{n_chunks} 分片 / {span:.1f}s 内渲染 {len(calls)} 次，"
            f"超出时间预算 {budget:.0f} 次 —— 节流失效"
        )

    def test_small_tail_interval_is_within_perceptual_range(self):
        """小尾部刷新间隔必须落在人眼平滑区间（约 20-40ms）。"""
        assert 16 <= M._STREAM_INTERVAL <= 32, (
            f"_STREAM_INTERVAL={M._STREAM_INTERVAL}ms，过慢会读成'分段跳变'，过快会刷屏"
        )

    def test_heavy_tail_tiers_stay_conservative(self):
        """超长尾部的两档不得为观感让路 —— 它们负责保护渲染吞吐。"""
        assert M._STREAM_INTERVAL_MID >= M._STREAM_INTERVAL * 3
        assert M._STREAM_INTERVAL_LONG >= M._STREAM_INTERVAL_MID * 2
        assert M._STREAM_MID_CHARS < M._STREAM_LONG_CHARS

    def test_rendered_volume_covers_input(self, qapp, monkeypatch):
        """渲染总量应覆盖整个输入（节流不得吞掉内容）。"""
        chunk = "data point "
        text = chunk * 3000  # ~33k chars
        calls, _span = _count_renders(monkeypatch, qapp, text, chunk=len(chunk))
        assert calls, "完全没有渲染"
        assert sum(calls) >= len(text) * 0.5, (
            f"渲染总量 {sum(calls)} 明显小于输入 {len(text)}，可能被截断"
        )

    def test_tail_never_shrinks_below_committed(self, qapp):
        """稳定段单调推进：已提交前缀不会被反复重排。"""
        v = ElaMarkdownViewer()
        v.resize(600, 400)
        v.show()
        qapp.processEvents()
        v.beginStream()
        for i in range(20):
            v.appendMarkdown("word%d " % i)
            QTest.qWait(5)
        v.endStream()
        assert v._stream_committed <= len(v._stream_source)
        v.deleteLater()
        qapp.processEvents()
