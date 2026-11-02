"""图表工作台：工作区懒构建 / 切换 / 全局控制。

页面从「一条 2400 行的长滚动」改成「概览 / 系列画廊 / 交互 / 大数据 / 高级 / 主题 / 小波」
七个工作区：首屏只建概览，其余首次切换时才建（27 张画廊图 + 大数据图一起
eager 构建会把首次显示拖慢）。
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QRect, Qt
from PyQt6ElaWidgetTools import ElaText

from pyqt6_ela_pro import ElaChartWidget
from pyqt6_ela_pro.charts import colormapColors
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
            "主题",
            "小波",
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
        assert counts[5] >= 7  # 主题：2 张切换演示 + 6 张主题画廊
        assert counts[6] >= 1  # 小波：1 张实时 scalogram

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


class TestThemeWorkspace:
    def test_gallery_uses_distinct_themes(self, make):
        page = _page(make)
        page._activate_workspace(5)
        gallery = page._theme_gallery_charts
        assert len(gallery) == 6
        assert [chart.chartTheme() for chart in gallery] == [
            "echarts",
            "matlab",
            "plotly",
            "ggplot2",
            "seaborn",
            "tableau",
        ]
        assert len({chart.palette()[0].name() for chart in gallery}) == 6

    def test_combo_switches_all_demo_charts(self, make):
        page = _page(make)
        page._activate_workspace(5)
        combo = page._theme_combo
        index = combo.findText("matlab")
        assert index >= 0
        combo.setCurrentIndex(index)
        assert all(chart.chartTheme() == "matlab" for chart in page._theme_demo_charts)
        assert [c.name() for c in page._theme_demo_charts[0].palette()][:3] == [
            "#0072bd",
            "#d95319",
            "#edb120",
        ]

    def test_custom_theme_registered_and_listed(self, make):
        from pyqt6_ela_pro.charts import chartThemes

        page = _page(make)
        page._activate_workspace(5)
        assert "example-coral" in chartThemes()
        assert page._theme_combo.findText("example-coral") >= 0
        index = page._theme_combo.findText("example-coral")
        page._theme_combo.setCurrentIndex(index)
        assert page._theme_demo_charts[0].chartTheme() == "example-coral"
        assert page._theme_demo_charts[0].palette()[0].name() == "#e76f51"


class TestGlobalTheme:
    def test_global_theme_applies_to_current_and_new_workspaces(self, make):
        page = _page(make)
        page._activate_workspace(0)
        combo = page._global_theme_combo
        combo.setCurrentIndex(combo.findText("matlab"))
        assert page._global_chart_theme == "matlab"
        assert all(chart.chartTheme() == "matlab" for chart in page._active_charts())

        page._activate_workspace(1)  # 画廊首次构建，应继承全局主题
        assert all(chart.chartTheme() == "matlab" for chart in page._active_charts())

        page._activate_workspace(5)  # 主题工作区：演示图继承，画廊固定
        assert all(chart.chartTheme() == "matlab" for chart in page._theme_demo_charts)
        assert [chart.chartTheme() for chart in page._theme_gallery_charts] == [
            "echarts",
            "matlab",
            "plotly",
            "ggplot2",
            "seaborn",
            "tableau",
        ]

    def test_global_theme_syncs_local_combo(self, make):
        page = _page(make)
        page._activate_workspace(5)
        combo = page._global_theme_combo
        combo.setCurrentIndex(combo.findText("plotly"))
        assert page._theme_combo.currentText() == "plotly"
        assert page._theme_state_label.text() == "当前：plotly"

    def test_local_theme_does_not_change_global(self, make):
        page = _page(make)
        page._activate_workspace(5)
        local = page._theme_combo
        local.setCurrentIndex(local.findText("plotly"))
        assert all(chart.chartTheme() == "plotly" for chart in page._theme_demo_charts)
        assert page._global_chart_theme == "ela"
        assert page._global_theme_combo.currentText() == "ela"
        page._activate_workspace(0)
        assert all(chart.chartTheme() == "ela" for chart in page._active_charts())

    def test_custom_theme_is_added_to_global_selector(self, make):
        page = _page(make)
        page._activate_workspace(5)
        combo = page._global_theme_combo
        index = combo.findText("example-coral")
        assert index >= 0
        combo.setCurrentIndex(index)
        assert page._global_chart_theme == "example-coral"
        assert page._theme_demo_charts[0].chartTheme() == "example-coral"


class TestWaveletWorkspace:
    def _wavelet_page(self, make):
        pytest.importorskip("numpy")
        page = _page(make)
        page._activate_workspace(6)
        return page

    def test_initial_state(self, make):
        page = self._wavelet_page(make)
        assert page._wavelet_matrix.shape == (512, 4096)
        assert page._wavelet_chart.seriesRenderers[0].opt["type"] == "image"
        assert page._wavelet_timer.interval() == 80
        assert page._wavelet_timer.isActive() is False

    def test_tick_advances_and_updates_stat(self, make):
        page = self._wavelet_page(make)
        before = page._wavelet_step
        page._wavelet_timer.timeout.emit()
        assert page._wavelet_step > before
        assert "重建" in page._wavelet_stat_label.text()
        assert "512 × 4096" in page._wavelet_stat_label.text()

    def test_start_pause_and_tab_switch(self, make):
        page = self._wavelet_page(make)
        page._wavelet_toggle_btn.click()
        assert page._wavelet_timer.isActive() is True
        assert page._wavelet_toggle_btn.text() == "暂停实时"
        page._activate_workspace(0)
        assert page._wavelet_timer.isActive() is False
        page._activate_workspace(6)
        assert page._wavelet_timer.isActive() is True
        page._wavelet_toggle_btn.click()
        assert page._wavelet_timer.isActive() is False
        assert page._wavelet_toggle_btn.text() == "开始实时"

    def test_size_switch_rebuilds_matrix_and_extent(self, make):
        page = self._wavelet_page(make)
        page._wavelet_size_combo.setCurrentIndex(0)
        assert page._wavelet_matrix.shape == (256, 2048)
        series = page._wavelet_chart.getOption()["series"][0]
        assert series["extent"] == [0, 2048, 1, 256]

    def test_cmap_switch_updates_series_and_colorbar(self, make):
        page = self._wavelet_page(make)
        page._wavelet_cmap_combo.setCurrentIndex(
            page._wavelet_cmap_combo.findText("jet")
        )
        option = page._wavelet_chart.getOption()
        assert option["series"][0]["cmap"] == "jet"
        assert option["visualMap"]["inRange"]["colors"] == colormapColors("jet")

    def test_global_theme_keeps_fixed_cmap(self, make):
        page = self._wavelet_page(make)
        combo = page._global_theme_combo
        combo.setCurrentIndex(combo.findText("matlab"))
        assert page._wavelet_chart.chartTheme() == "matlab"
        option = page._wavelet_chart.getOption()
        assert option["visualMap"]["inRange"]["colors"] == colormapColors("viridis")


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
