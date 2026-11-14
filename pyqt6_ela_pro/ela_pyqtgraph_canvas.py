"""ElaPlotWidget - 主题感知 pyqtgraph 绘图控件。"""

from __future__ import annotations

from PyQt6.QtWidgets import QWidget, QSizePolicy

from PyQt6ElaWidgetTools import eTheme, ElaThemeType

from ._internal import connect_theme_signal, disconnect_theme
from ._theme import blend, border, surface, text, textMuted

# ── Optional pyqtgraph import ──────────────────────────

try:
    import pyqtgraph as pg
except ImportError:
    pg = None


def _theme_for_mode(mode) -> dict[str, str]:
    """按 Ela 主题生成 pyqtgraph 的 UI chrome 颜色。"""
    base = surface(mode)
    line = border(mode)
    return {
        "background": base.name(),
        "foreground": text(mode).name(),
        "axis": line.name(),
        "grid": blend(base, line, 0.5).name(),
        "label": textMuted(mode).name(),
    }


if pg is not None:

    class ElaPlotWidget(pg.GraphicsLayoutWidget):
        """主题感知 pyqtgraph 绘图控件。

        自动跟随 Ela 主题切换 Light/Dark 配色。
        基于 ``GraphicsLayoutWidget``，支持多图布局。

        :param parent: 父控件
        """

        def __init__(self, parent: QWidget | None = None) -> None:
            super().__init__(parent)

            self.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
            )

            self._theme_mode = eTheme.getThemeMode()
            connect_theme_signal(self)
            self._apply_theme()

        # ── Public API ────────────────────────────────────

        def plot(self, *args, **kwargs) -> pg.PlotItem:
            """``addPlot`` 的别名。"""
            return self.addPlot(*args, **kwargs)

        def addPlot(self, *args, **kwargs) -> pg.PlotItem:
            """创建 PlotItem 后立即套用当前主题的轴/文字颜色。"""
            item = super().addPlot(*args, **kwargs)
            self._style_plot(item)
            return item

        def setStyleParams(self, **kwargs) -> None:
            """额外的 pyqtgraph 全局配置（转发 ``setConfigOptions``）。
            **进程级副作用**：改的是 pyqtgraph 的全局配置，影响宿主**所有**
            pyqtgraph 图。名字刻意不叫 ``setStyle``（那会遮蔽
            """
            pg.setConfigOptions(**kwargs)

        # ── Internal ──────────────────────────────────────

        def _apply_theme(self) -> None:
            theme = _theme_for_mode(self._theme_mode)
            self.setBackground(theme["background"])
            try:
                items = list(self.ci.items)
            except Exception:
                return
            for item in items:
                if isinstance(item, pg.PlotItem):
                    self._style_plot(item)

        def _style_plot(self, item) -> None:
            """轴/标签颜色跟随主题；背景由 ``setBackground`` 统一处理。"""
            theme = _theme_for_mode(self._theme_mode)
            for name in ("left", "bottom", "right", "top"):
                try:
                    axis = item.getAxis(name)
                    axis.setPen(pg.mkPen(theme["axis"]))
                    axis.setTextPen(pg.mkPen(theme["label"]))
                except Exception:
                    continue

        def _onThemeChanged(self, mode: ElaThemeType.ThemeMode) -> None:
            self._theme_mode = mode
            self._apply_theme()

        def deleteLater(self) -> None:
            disconnect_theme(self)
            super().deleteLater()

else:

    class ElaPlotWidget:  # type: ignore[no-redef]
        """pyqtgraph 未安装时的占位类。"""

        def __init__(self, *args, **kwargs):
            raise ImportError(
                "ElaPlotWidget 需要 pyqtgraph，请运行: uv pip install pyqtgraph"
            )
