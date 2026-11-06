"""回归测试（第九批）：通知 / 文本格式 / 角标 / 按钮定时器 / 缓存与数据边界。"""

from __future__ import annotations

from PyQt6 import sip
from PyQt6.QtCore import QByteArray, QEvent, QPointF, Qt, QUrl
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QWidget

from pyqt6_ela_pro._diff import parseUnifiedDiff
from pyqt6_ela_pro.blueprint.registry import ElaNodeRegistry, register_node_type
from pyqt6_ela_pro.charts import ElaChartWidget
from pyqt6_ela_pro.ela_button import ElaButton
from pyqt6_ela_pro.ela_diff_view import ElaDiffView
from pyqt6_ela_pro.ela_info_badge import ElaInfoBadge
from pyqt6_ela_pro.message_dialog import ElaMessageDialog
from pyqt6_ela_pro.notify_popup import ElaNotifyManager, ElaNotifyPopup
from pyqt6_ela_pro.terminal_view import ElaTerminalView
from pyqt6_ela_pro.terminal_view.ansi import AnsiColor, TerminalStyle
from pyqt6_ela_pro.tooltips import _ToolTipLabel
from pyqt6_ela_pro.markdown_viewer import media


class TestNotifyManager:
    def test_closed_and_deleted_popups_are_pruned(self, qapp):
        manager = ElaNotifyManager()
        manager._popups.clear()
        manager.showNotification("t", "c", timeout=100000)
        popup = manager._popups[0]
        popup.close()
        qapp.processEvents()
        manager.showNotification("t2", "c2", timeout=100000)
        assert popup not in manager._popups
        sip.delete(popup)
        manager.showNotification("t3", "c3", timeout=100000)  # 不得抛
        for item in list(manager._popups):
            item.deleteLater()
        manager._popups.clear()
        qapp.processEvents()


class TestPlainText:
    def test_notify_tooltip_and_dialog_use_plain_text(self, qapp):
        host = QWidget()
        popup = ElaNotifyPopup("t", "c", parent=host)
        assert popup._title_text.textFormat() == Qt.TextFormat.PlainText
        assert popup._content_text.textFormat() == Qt.TextFormat.PlainText
        assert _ToolTipLabel("x").textFormat() == Qt.TextFormat.PlainText
        dialog = ElaMessageDialog(parent=host)
        assert dialog._message_widget.textFormat() == Qt.TextFormat.PlainText
        assert dialog._titleWidget.textFormat() == Qt.TextFormat.PlainText
        dialog.deleteLater()
        popup.deleteLater()
        qapp.processEvents()


class TestInfoBadgeGeometry:
    def test_value_growth_stays_inside_target(self, qapp):
        target = QWidget()
        target.resize(200, 40)
        badge = ElaInfoBadge(value=1)
        badge.attachTo(target)
        badge.setValue(999)
        assert badge.x() + badge.width() <= target.width()
        badge.setMaxValue(5)
        assert badge.x() + badge.width() <= target.width()
        assert badge.width() == badge.sizeHint().width()
        badge.detach()
        badge.deleteLater()
        target.deleteLater()
        qapp.processEvents()


class TestButtonLoadingTimer:
    def test_hide_and_disable_stop_spinner(self, qapp):
        button = ElaButton("x")
        button.show()
        qapp.processEvents()
        button.setLoading(True)
        assert button._spin_timer.isActive()
        button.hide()
        qapp.processEvents()
        assert not button._spin_timer.isActive()
        button.show()
        qapp.processEvents()
        assert button._spin_timer.isActive()
        button.setEnabled(False)
        qapp.processEvents()
        assert not button._spin_timer.isActive()
        button.deleteLater()
        qapp.processEvents()


class TestTerminalFormatCache:
    def test_cache_is_bounded_and_cleared(self, qapp):
        view = ElaTerminalView()
        for value in range(600):
            view._format_for(TerminalStyle(fg=AnsiColor("rgb", value)))
        assert len(view._format_cache) <= 512
        view.clear()
        assert not view._format_cache
        view.deleteLater()
        qapp.processEvents()


class TestDataUriPrecheck:
    def test_oversized_payload_is_rejected_before_decode(self, monkeypatch):
        called = []

        def decode(*_args, **_kwargs):
            called.append(1)
            return b""

        monkeypatch.setattr(media.base64, "b64decode", decode)
        encoded = "A" * (media._MAX_DATA_URI_BYTES * 4 // 3 + 100)
        assert (
            media._decode_data_uri(QUrl(f"data:image/png;base64,{encoded}"))
            == QByteArray()
        )
        assert not called


class TestDiffFilePath:
    def test_header_click_reports_path_and_file_at(self, qapp):
        diff = """diff --git a/a.py b/a.py
--- a/a.py
+++ b/a.py
@@ -1,1 +1,1 @@
-old
+new
"""
        view = ElaDiffView()
        view.setFiles(parseUnifiedDiff(diff))
        assert view.fileAt(0) == "a.py"
        seen = []
        view.fileClicked.connect(seen.append)
        pos = QPointF(1, 1)
        view.mousePressEvent(
            QMouseEvent(
                QEvent.Type.MouseButtonPress,
                pos,
                pos,
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
        )
        assert seen == ["a.py"]
        view.deleteLater()
        qapp.processEvents()


class TestCategoryNonFinite:
    def test_bar_and_heatmap_survive_nan_x(self, qapp):
        bar = ElaChartWidget()
        bar.resize(400, 300)
        bar.setOption(
            {
                "animation": False,
                "xAxis": {"type": "category", "data": ["a", "b", "c"]},
                "yAxis": {"type": "value"},
                "series": [
                    {
                        "type": "bar",
                        "data": [[float("nan"), 1], [1, 2], [float("nan"), 3]],
                    }
                ],
            }
        )
        bar.anim.setProgress(1.0)
        bar.grab()
        assert bar.seriesRenderers[0]._bars

        heat = ElaChartWidget()
        heat.resize(400, 300)
        heat.setOption(
            {
                "animation": False,
                "xAxis": {"type": "category", "data": ["a", "b"]},
                "yAxis": {"type": "category", "data": ["c", "d"]},
                "series": [
                    {
                        "type": "heatmap",
                        "data": [[float("nan"), 0, 5], [1, 1, 7]],
                    }
                ],
            }
        )
        heat.anim.setProgress(1.0)
        heat.grab()
        assert heat.seriesRenderers[0]._cells
        bar.deleteLater()
        heat.deleteLater()
        qapp.processEvents()


class TestRegistryMultiBool:
    def test_string_false_is_false(self, qapp):
        register_node_type(
            "__review_multi_false__",
            "M",
            "test",
            inputs=[{"id": "i", "multi": "false"}],
            outputs=[],
        )
        node = ElaNodeRegistry.instance().create("__review_multi_false__")
        assert node.inputs[0].multi is False
