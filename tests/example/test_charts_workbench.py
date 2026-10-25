"""图表工作台：工作区懒构建 / 切换 / 全局控制。

页面从「一条 2400 行的长滚动」改成「概览 / 系列画廊 / 交互 / 大数据 / 高级」
五个工作区：首屏只建概览，其余首次切换时才建（27 张画廊图 + 大数据图一起
eager 构建会把首次显示拖慢）。
"""

from __future__ import annotations

from PyQt6.QtCore import QRect, Qt
from PyQt6ElaWidgetTools import ElaText

from pyqt6_ela_pro import ElaChartWidget
from pyqt6_ela_pro.example.charts_page import ChartsPage


def _page(make) -> ChartsPage:
    page = make(ChartsPage)
    page.resize(1100, 820)
    return page


class TestWorkspaceShell:
    def test_names(self, make):
        page = _page(make)
        assert [w["name"] for w in page._workspaces] == [
            "概览",
            "系列画廊",
            "交互",
            "大数据",
            "高级",
        ]

    def test_lazy_build(self, make):
        page = _page(make)
        assert page._workspaces[0]["built"] is True
        assert all(not w["built"] for w in page._workspaces[1:])

        page._activate_workspace(1)
        assert page._workspaces[1]["built"] is True
        assert page._stack.currentIndex() == 1
        assert page._pivot.getCurrentIndex() == 1
        assert page._desc_label.text() == page._workspaces[1]["desc"]

    def test_overview_charts(self, make):
        page = _page(make)
        assert len(page._active_charts()) >= 4

    def test_every_workspace_builds_charts(self, make):
        page = _page(make)
        counts = []
        for index, workspace in enumerate(page._workspaces):
            page._activate_workspace(index)
            charts = page._active_charts()
            assert charts, f"{workspace['name']} 没有图表"
            counts.append(len(charts))
        assert counts[1] >= 20  # 画廊：21 种系列 + 变体
        assert counts[2] >= 3
        assert counts[3] >= 1
        assert counts[4] >= 5

    def test_switch_back_keeps_built_state(self, make):
        page = _page(make)
        page._activate_workspace(2)
        charts = page._active_charts()
        page._activate_workspace(0)
        page._activate_workspace(2)
        assert page._active_charts() == charts
        assert page._workspaces[2]["built"] is True


class TestWorkspaceControls:
    def test_interaction_toggle_is_scoped(self, make):
        page = _page(make)
        page._activate_workspace(1)
        active = page._active_charts()
        overview_chart = page._stack.widget(0).findChildren(ElaChartWidget)[0]
        assert overview_chart.interactiveEnabled() is True

        page._onToggleWorkspaceInteraction()
        assert all(not chart.interactiveEnabled() for chart in active)
        assert overview_chart.interactiveEnabled() is True
        assert page._interact_btn.text() == "交互: 关"

    def test_animation_toggle(self, make):
        page = _page(make)
        page._activate_workspace(0)
        assert page._anim_enabled is True
        page._onToggleAnimation()
        assert page._anim_enabled is False
        assert page._anim_btn.text() == "动效: 关"
        page._onToggleAnimation()
        assert page._anim_enabled is True
        assert page._anim_btn.text() == "动效: 开"

    def test_random_workspace_keeps_charts_alive(self, make):
        page = _page(make)
        page._activate_workspace(1)
        charts = page._active_charts()
        page._onRandomWorkspace()
        assert page._active_charts() == charts
        assert all(chart.getOption().get("series") for chart in charts)


class TestTileTitles:
    def test_titles_are_not_clipped(self, make, qapp):
        """小标题按实际宽度折行后的高度必须 ≤ 控件高度（钉了两行高度）。

        曾踩：`AlignLeft` 只给 `sizeHint()` 宽度 → 长标题在窄框里折成多行，
        固定高只留两行 → 第二/三行被裁掉（「文字标签出现了换行」）。
        """
        page = _page(make)
        page.show()
        problems = []
        for index in range(len(page._workspaces)):
            page._activate_workspace(index)
            qapp.processEvents()
            container = page._stack.widget(index)
            for label in container.findChildren(ElaText):
                text = label.text()
                if not text or label.maximumHeight() > 100:
                    continue  # 只看钉了高度的标题（_addGallery / _chartTile / 日历标题）
                need = (
                    label.fontMetrics()
                    .boundingRect(
                        QRect(0, 0, max(1, label.width()), 0),
                        int(Qt.TextFlag.TextWordWrap),
                        text,
                    )
                    .height()
                )
                if need > label.height():
                    problems.append(
                        f"工作区{index} {text!r}: 需要 {need}px，只有 {label.height()}px"
                    )
        assert not problems, "\n".join(problems)
