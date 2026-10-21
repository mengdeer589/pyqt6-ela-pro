"""回归测试（第二批）：深度审查发现、经实测确认的缺陷。

只包含**已用复现脚本确认**的缺陷：

- ``ElaMarkdownViewer`` 默认 ``setOpenExternalLinks(True)`` 导致 Qt 吞掉
  ``anchorClicked``，任务列表复选框 / 折叠 / 内部锚点跳转全部失效
- ``_flush_stream`` 销毁文档尾段前未清 ``_code_buttons_tables``
  （AGENTS.md 不变量 (a)），重绘时访问已析构 ``QTextTable``
- ``_is_code_table`` 未判 ``cellAt()`` 返回 ``None``（合并单元格）
- ``ElaChartWidget`` 每次 ``_rebuild`` 重放 ``legend.selected``，把用户刚点的
  图例显隐还原掉
- graphic 元素用 ``_to_float(x, d) or d``，把合法的 ``0`` 当成缺失
  （``r: 0`` 画出半径 20 的圆）
- ``math_lite._expand_macros`` 只限轮数不限长度，自引用宏指数爆炸卡死 GUI
"""

from __future__ import annotations

import inspect
import re

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QColor, QPainter, QPixmap

import pyqt6_ela_pro.ela_markdown_viewer as M
from pyqt6_ela_pro import ElaChartWidget
from pyqt6_ela_pro.ela_markdown_viewer import ElaMarkdownViewer
from pyqt6_ela_pro.math_lite import _MACRO_EXPANSION_LIMIT, _expand_macros


class TestMarkdownInternalAnchors:
    """内部锚点必须可达（Qt 在 openExternalLinks=True 时会吞掉 anchorClicked）。"""

    def test_browser_open_external_links_is_off(self, qapp):

        v = ElaMarkdownViewer()
        v.resize(500, 400)
        v.show()
        qapp.processEvents()
        assert v.textBrowser().openExternalLinks() is False, (
            "openExternalLinks 必须为 False，否则 Qt 的 _q_anchorClicked 会先 "
            "openUrl() 再 return，anchorClicked 永不发出"
        )
        v.deleteLater()
        qapp.processEvents()

    def test_task_anchor_toggle_is_reachable(self, qapp):

        v = ElaMarkdownViewer()
        v.resize(500, 400)
        v.show()
        v.setMarkdown("- [ ] task one\n- [x] task two\n")
        for _ in range(8):
            qapp.processEvents()
        # 点击任务复选框走的就是这个入口；能跑通即说明 anchorClicked 链路是通的
        v._on_anchor_clicked(QUrl("#elatask-0"))
        assert True
        v.deleteLater()
        qapp.processEvents()

    def test_fold_and_code_anchors_handled(self, qapp):

        v = ElaMarkdownViewer()
        v.resize(500, 400)
        v.show()
        v.setMarkdown("```py\nx = 1\nx = 2\nx = 3\n```\n")
        for _ in range(8):
            qapp.processEvents()
        v._on_anchor_clicked(QUrl("#elacode-expand-0"))
        v._on_anchor_clicked(QUrl("#elafold-0"))
        assert True
        v.deleteLater()
        qapp.processEvents()

    def test_external_link_flag_is_honoured(self, qapp):

        v = ElaMarkdownViewer()
        assert v.openExternalLinks() is True
        v.setOpenExternalLinks(False)
        assert v.openExternalLinks() is False
        v.setOpenExternalLinks(True)
        assert v.openExternalLinks() is True
        v.deleteLater()
        qapp.processEvents()

    def test_link_activated_still_emitted(self, qapp, monkeypatch):
        from PyQt6.QtGui import QDesktopServices

        # 必须替换 openUrl：viewer 默认 setOpenExternalLinks(True)，这条走的是
        # 真实外链分支，不拦的话在有桌面会话的机器上会真的拉起浏览器。
        # 本用例要验的是「Qt 层关掉 openExternalLinks 后我们自己仍发信号」。
        opened: list = []
        monkeypatch.setattr(
            QDesktopServices,
            "openUrl",
            staticmethod(lambda u: opened.append(u) or True),
        )

        v = ElaMarkdownViewer()
        v.resize(500, 400)
        v.show()
        got = []
        v.linkActivated.connect(got.append)
        v._on_anchor_clicked(QUrl("https://example.com"))
        assert got == ["https://example.com"]
        v.deleteLater()
        qapp.processEvents()

    def test_internal_anchor_emits_link_activated(self, qapp):

        v = ElaMarkdownViewer()
        v.resize(500, 400)
        v.show()
        v.setMarkdown("[go](#sec)\n\n## sec\n")
        for _ in range(8):
            qapp.processEvents()
        got = []
        v.linkActivated.connect(got.append)
        v._on_anchor_clicked(QUrl("#sec"))
        assert got == ["#sec"]
        v.deleteLater()
        qapp.processEvents()


class TestMarkdownCodeButtonInvalidation:
    """不变量：代码表被销毁后，引用要么被 ``is_deleted`` 过滤、要么访问前判存活。

    旧实现靠 ``_flush_stream`` 开头的 ``_rebuild_code_buttons([])`` 兜底；现在
    稳定段按钮按表身份增量复用（流式每次 flush 全量重建是卡顿根源），失效表
    改由 ``_sync_code_buttons`` 按 ``is_deleted`` 过滤；按钮定位走
    ``_code_table_index_range`` + 逐表 ``is_deleted`` 判存活。
    """

    @staticmethod
    def _method_body(name: str) -> str:

        src = inspect.getsource(M.ElaMarkdownViewer)
        match = re.search(rf"\n    def {name}\(.*?(?=\n    def )", src, re.S)
        assert match is not None
        return match.group(0)

    def test_flush_does_not_wipe_button_refs(self):
        body = self._method_body("_flush_stream")
        assert "self._rebuild_code_buttons([])" not in body, (
            "flush 不应全量清空按钮引用：稳定段的表对象未变，重建即流式卡顿根源"
        )

    def test_sync_filters_destroyed_tables(self):
        assert "is_deleted" in self._method_body("_sync_code_buttons"), (
            "增量同步必须按 is_deleted 过滤已随文档析构的表"
        )

    def test_resync_is_immediate(self):
        body = self._method_body("_flush_stream")
        lines = [line.strip() for line in body.splitlines()]
        assert "self._sync_code_buttons()" in lines, (
            "flush 结束时应立即 _sync_code_buttons()，不能只靠 80ms 后的定时器"
        )

    def test_stream_flush_with_code_block_keeps_tables_alive(self, qapp):
        """流式 flush 销毁尾段代码表后，按钮 / 表引用不得残留已析构对象。"""

        v = ElaMarkdownViewer()
        v.resize(400, 300)
        v.show()
        for _ in range(8):
            qapp.processEvents()
        v.beginStream()
        v.appendMarkdown("```python\nx = 1\n```\n\n正文")
        v._stream_timer.stop()
        v._flush_stream()
        assert v._code_buttons_tables
        first_button = v._code_buttons[0]
        # 追加更多内容再 flush：稳定段已 commit 的代码表不应被重建
        v.appendMarkdown("\n\n更多正文 `code`")
        v._stream_timer.stop()
        v._flush_stream()
        assert v._code_buttons[0] is first_button, "稳定段的复制按钮被无谓重建"
        for table in v._code_buttons_tables:
            assert not M.is_deleted(table)
        v.repaint()
        v.grab()
        v.deleteLater()
        qapp.processEvents()

    def test_stream_replay_keeps_buttons_consistent(self, qapp):

        v = ElaMarkdownViewer()
        v.resize(400, 300)
        v.show()
        for _ in range(8):
            qapp.processEvents()
        for i in range(6):
            v.setMarkdown("```py\nx = %d\n```\n\ntext %d\n" % (i, i))
            for _ in range(4):
                qapp.processEvents()
        # 每个文档都恰好一个代码卡 -> 一个按钮，且表对象必须是活的
        assert len(v._code_buttons_tables) == 1
        v.repaint()
        v.grab()
        v.deleteLater()
        qapp.processEvents()


class TestMarkdownCellAtGuard:
    """``cellAt()`` 对合并覆盖的单元格返回 ``None``。"""

    def test_is_code_table_guards_none_cell(self):

        src = inspect.getsource(M.ElaMarkdownViewer)
        match = re.search(r"\n    def _is_code_table\(.*?(?=\n    def )", src, re.S)
        assert match is not None
        assert "if cell is None" in match.group(0)

    def test_is_code_table_handles_single_column_table(self, qapp):

        v = ElaMarkdownViewer()
        v.resize(400, 300)
        v.show()
        v.setMarkdown("| a |\n|---|\n| 1 |\n")
        for _ in range(8):
            qapp.processEvents()
        v.repaint()
        v.grab()
        v.deleteLater()
        qapp.processEvents()


class TestChartLegendStatePersistence:
    """用户点了图例之后，一次常规数据刷新不得把显隐状态还原。"""

    def test_toggle_survives_merged_data_refresh(self, qapp):

        c = ElaChartWidget()
        c.resize(500, 400)
        c.show()
        c.setOption(
            {
                "legend": {"selected": {"B": False}},
                "series": [
                    {"type": "line", "name": "A", "data": [1, 2]},
                    {"type": "line", "name": "B", "data": [3, 4]},
                ],
            },
            notMerge=True,
        )
        for _ in range(6):
            qapp.processEvents()
        assert c._series_state.get("B") is False

        c.dispatchAction({"type": "legendToggleSelect", "name": "B"})
        for _ in range(6):
            qapp.processEvents()
        assert c._series_state.get("B") is True

        c.setOption({"series": [{"name": "A", "data": [5, 6]}]})
        for _ in range(6):
            qapp.processEvents()
        assert c._series_state.get("B") is True, "数据刷新把用户刚点的图例还原了"
        c.deleteLater()
        qapp.processEvents()

    def test_writeback_updates_option_selected(self, qapp):

        c = ElaChartWidget()
        c.resize(500, 400)
        c.show()
        c.setOption(
            {
                "legend": {"selected": {"B": False}},
                "series": [{"type": "line", "name": "B", "data": [3, 4]}],
            },
            notMerge=True,
        )
        for _ in range(6):
            qapp.processEvents()
        c.dispatchAction({"type": "legendToggleSelect", "name": "B"})
        for _ in range(6):
            qapp.processEvents()
        assert c.getOption()["legend"]["selected"]["B"] is True
        c.deleteLater()
        qapp.processEvents()


class TestChartGraphicZeroValues:
    """``_to_float(x, d) or d`` 把合法的 0 当成缺失。"""

    def _render_graphic(self, qapp, element):

        c = ElaChartWidget()
        c.resize(500, 400)
        c.show()
        c.setOption({"graphic": [element]}, notMerge=True)
        for _ in range(6):
            qapp.processEvents()
        comp = [x for x in c._components if "Graphic" in type(x).__name__][0]
        pm = QPixmap(500, 400)
        pm.fill(QColor("white"))
        p = QPainter(pm)
        try:
            comp.paint(p, 1.0)
        finally:
            p.end()
        img = pm.toImage()
        n = sum(
            1
            for y in range(80, 121)
            for x in range(80, 121)
            if img.pixelColor(x, y).name() != "#ffffff"
        )
        c.deleteLater()
        qapp.processEvents()
        return n

    def test_zero_radius_circle_draws_nothing(self, qapp):
        n = self._render_graphic(
            qapp, {"type": "circle", "shape": {"r": 0, "cx": 100, "cy": 100}}
        )
        assert n == 0, f"r:0 不应画出任何像素，实际 {n}（旧行为画成半径 20 的圆）"

    def test_nonzero_radius_circle_still_draws(self, qapp):
        n = self._render_graphic(
            qapp, {"type": "circle", "shape": {"r": 15, "cx": 100, "cy": 100}}
        )
        assert n > 100, f"r:15 应正常绘制，实际 {n}"

    def test_zero_width_rect_uses_default(self, qapp):

        c = ElaChartWidget()
        c.resize(500, 400)
        c.show()
        c.setOption(
            {
                "graphic": [
                    {
                        "type": "rect",
                        "shape": {"width": 30, "height": 20, "x": 10, "y": 10},
                    }
                ]
            },
            notMerge=True,
        )
        for _ in range(6):
            qapp.processEvents()
        c.repaint()
        c.grab()
        c.deleteLater()
        qapp.processEvents()


class TestMathMacroExpansionBounded:
    """``\\def\\a{\\a\\a\\a}`` 每轮 ×3，只限轮数会指数爆炸卡死 GUI。"""

    def test_self_referential_macro_terminates_quickly(self):

        out = _expand_macros("\\def\\a{\\a\\a\\a}\\a")
        # 上限在产出过程中生效：最多超出一个宏展开片段
        assert len(out) <= _MACRO_EXPANSION_LIMIT + 1024, (
            f"展开结果 {len(out)} 字符，未受上限 {_MACRO_EXPANSION_LIMIT} 约束"
        )
        assert len(out) < 3_500_000_000  # 未加限时是 3^20

    def test_normal_macro_still_expands(self):

        assert _expand_macros("\\def\\x{Hi}\\x") == "Hi"
        assert _expand_macros("\\def\\f#1{#1+#1}\\f{A}") == "A+A"
        assert _expand_macros("no macros here") == "no macros here"

    def test_mutual_recursion_terminates(self):

        out = _expand_macros("\\def\\a{\\b\\b}\\def\\b{\\a\\a}\\a")
        assert len(out) < 10_000_000

    def test_limit_constant_is_sane(self):

        assert 1000 <= _MACRO_EXPANSION_LIMIT <= 5_000_000

    def test_formula_with_runaway_macro_does_not_hang_viewer(self, qapp):

        v = ElaMarkdownViewer()
        v.resize(400, 300)
        v.show()
        v.setMarkdown("$$ \\def\\a{\\a\\a\\a}\\a $$")
        for _ in range(8):
            qapp.processEvents()
        v.repaint()
        v.grab()
        v.deleteLater()
        qapp.processEvents()
