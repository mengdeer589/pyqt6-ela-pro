"""ElaFigureCanvas - 主题感知 Matplotlib 画布组件。"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QSizePolicy

from PyQt6ElaWidgetTools import eTheme, ElaThemeType

from ._internal import connect_theme_signal, disconnect_theme
from ._theme import blend, border, surface, surfaceRaised, text, textMuted

# ── Optional matplotlib import ──────────────────────────

try:
    from matplotlib.backends.backend_qtagg import (
        FigureCanvasQTAgg as _FigureCanvas,
    )
    from matplotlib.figure import Figure
    import matplotlib as mpl
except ImportError:
    _FigureCanvas = None
    Figure = None
    mpl = None


def _rc_params(mode) -> dict:
    """按 Ela 主题生成 Matplotlib rcParams（UI chrome，不含数据系列色）。"""
    base = surface(mode)
    line = border(mode)
    return {
        "figure.facecolor": base.name(),
        "axes.facecolor": surfaceRaised(mode).name(),
        "axes.edgecolor": line.name(),
        "axes.labelcolor": text(mode).name(),
        "xtick.color": textMuted(mode).name(),
        "ytick.color": textMuted(mode).name(),
        "grid.color": blend(base, line, 0.5).name(),
        "text.color": text(mode).name(),
    }


_CJK_FONTS = [
    "Microsoft YaHei",
    "SimHei",
    "Noto Sans SC",
    "DengXian",
    "Microsoft JhengHei",
]


if _FigureCanvas is not None:

    class ElaFigureCanvas(_FigureCanvas):
        """主题感知 Matplotlib 画布。

        自动跟随 Ela 主题切换 Light/Dark 配色。
        支持所有 FigureCanvasQTAgg 原有功能。

        :param parent: 父控件
        """

        def __init__(
            self,
            parent: Optional[QWidget] = None,
        ) -> None:
            fig = Figure()
            _FigureCanvas.__init__(self, fig)
            if parent is not None:
                self.setParent(parent)

            self.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
            )
            self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

            self._theme_mode = eTheme.getThemeMode()
            connect_theme_signal(self)
            self._setup_cjk_font()
            self._apply_theme()

        # ── Public API ────────────────────────────────────

        def setStyleParams(self, rcparams: dict) -> None:
            """应用额外的 matplotlib rcParams 样式参数。
            **进程级副作用**：直接写全局 ``mpl.rcParams``，影响宿主**所有**
            matplotlib 图（与构造期的 CJK 注入 / 换肤同一口径）。
            """
            if mpl:
                mpl.rcParams.update(rcparams)
            self.draw_idle()

        # ── Internal ──────────────────────────────────────

        @staticmethod
        def _setup_cjk_font() -> None:
            if not mpl:
                return
            existing = mpl.rcParams.get("font.sans-serif", [])
            for f in _CJK_FONTS:
                if f not in existing:
                    existing.insert(0, f)
            mpl.rcParams["font.sans-serif"] = existing
            mpl.rcParams["axes.unicode_minus"] = False

        def deleteLater(self) -> None:
            disconnect_theme(self)
            super().deleteLater()

        def _onThemeChanged(self, mode: ElaThemeType.ThemeMode) -> None:
            self._theme_mode = mode
            self._apply_theme()
            self.draw_idle()

        def _apply_theme(self) -> None:
            if not mpl:
                return
            rc = _rc_params(self._theme_mode)
            mpl.rcParams.update(rc)
            self.figure.set_facecolor(rc["figure.facecolor"])
            for ax in self.figure.axes:
                ax.set_facecolor(rc["axes.facecolor"])
                ax.tick_params(
                    colors=rc["xtick.color"],
                    which="both",
                )
                ax.title.set_color(rc["text.color"])
                ax.xaxis.label.set_color(rc["axes.labelcolor"])
                ax.yaxis.label.set_color(rc["axes.labelcolor"])
                for spine in ax.spines.values():
                    spine.set_color(rc["axes.edgecolor"])
                legend = ax.get_legend()
                if legend is not None:
                    frame = legend.get_frame()
                    frame.set_facecolor(rc["axes.facecolor"])
                    frame.set_edgecolor(rc["axes.edgecolor"])
                    for legend_text in legend.get_texts():
                        legend_text.set_color(rc["axes.labelcolor"])


else:

    class ElaFigureCanvas:  # type: ignore[no-redef]
        """matplotlib 未安装时的占位类。"""

        def __init__(self, *args, **kwargs):
            raise ImportError(
                "ElaFigureCanvas 需要 matplotlib，请运行: uv pip install matplotlib"
            )
