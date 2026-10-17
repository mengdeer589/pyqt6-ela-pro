"""ElaChatStatusBar 测试：信息 / 状态文本、等级校验、busy 指示与主题刷新。"""

from __future__ import annotations

from PyQt6ElaWidgetTools import ElaThemeType

from pyqt6_ela_pro.chat import ElaChatStatusBar
from pyqt6_ela_pro.chat.status import STATUS_LEVELS


class TestContent:
    def test_defaults_empty(self, qapp, make):
        bar = make(ElaChatStatusBar)
        assert bar.info() == ""
        assert bar.status() == ""
        assert bar.level() == "info"
        assert bar.isBusy() is False

    def test_set_info_and_status(self, qapp, make):
        bar = make(ElaChatStatusBar)
        bar.setInfo("Spark-X2.5-4B-FP8 @ 127.0.0.1:8000/v1")
        bar.setStatus("生成中…", level="busy")
        assert bar.info() == "Spark-X2.5-4B-FP8 @ 127.0.0.1:8000/v1"
        assert bar.status() == "生成中…"
        assert bar.level() == "busy"

    def test_invalid_level_falls_back_to_info(self, qapp, make):
        bar = make(ElaChatStatusBar)
        bar.setStatus("x", level="bogus")
        assert bar.level() == "info"

    def test_all_levels_accepted(self, qapp, make):
        bar = make(ElaChatStatusBar)
        for level in STATUS_LEVELS:
            bar.setStatus(f"状态-{level}", level=level)
            assert bar.level() == level


class TestBusyIndicator:
    def test_set_busy(self, qapp, make):
        bar = make(ElaChatStatusBar)
        bar.setBusy(True)
        assert bar.isBusy() is True
        bar.setBusy(False)
        assert bar.isBusy() is False


class TestThemeSync:
    def test_theme_change_reapplies_styles(self, qapp, make):
        bar = make(ElaChatStatusBar)
        bar.setStatus("完成", level="success")
        before = bar._status_label.textColor()
        other = (
            ElaThemeType.ThemeMode.Dark
            if bar._theme_mode == ElaThemeType.ThemeMode.Light
            else ElaThemeType.ThemeMode.Light
        )
        bar._onThemeChanged(other)
        after = bar._status_label.textColor()
        assert bar._status_label.font().pixelSize() == 12
        assert before is not None and after is not None
        assert before != after

    def test_hidden_labels_when_empty(self, qapp, make):
        bar = make(ElaChatStatusBar)
        bar.show()
        qapp.processEvents()
        assert bar._info_label.isVisible() is False
        assert bar._status_label.isVisible() is False
        bar.setInfo("info")
        bar.setStatus("status")
        qapp.processEvents()
        assert bar._info_label.isVisible() is True
        assert bar._status_label.isVisible() is True
