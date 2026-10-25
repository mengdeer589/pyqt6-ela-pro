"""交互组件的共享小工具。（``pyqt6_ela_pro.charts`` 内部模块）。"""

from __future__ import annotations


def _axis_index_list(raw):
    """dataZoom ``xAxisIndex`` → 索引列表；None 表示「全部 x 轴」。"""
    if raw is None:
        return None
    values = raw if isinstance(raw, (list, tuple)) else [raw]
    out = []
    for value in values:
        try:
            out.append(int(value))
        except (TypeError, ValueError, OverflowError):
            continue
    return out or None
