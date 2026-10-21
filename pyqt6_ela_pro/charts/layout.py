"""图表布局协调器：组件条带 / 坐标系 / 系列 / 组件几何。"""

from __future__ import annotations

from PyQt6.QtCore import QRectF
from PyQt6ElaWidgetTools import eTheme

from ._utils import warn_key, warn_once

#: 底部组件条带顺序（从外到内，最外层贴近画布底边）
BOTTOM_BAND_ORDER = ("timeline", "dataZoom", "visualMap")


def layout_cache_key(chart) -> tuple:
    """布局缓存键：option 版本 / 视口尺寸 / 主题 / dataZoom 窗口状态。"""
    theme = eTheme.getThemeMode()
    zoom = tuple(
        (getattr(component, "start", 0.0), getattr(component, "end", 100.0))
        for component in chart._components
        if getattr(component, "optionKey", "") == "dataZoom"
    )
    return (chart._opt_version, chart.width(), chart.height(), theme, zoom)


def layout_all(chart, force: bool = False) -> None:
    """全量布局：组件条带 / 坐标系 / 系列 / 组件几何。

    组件条带：竖直 visualMap 占右侧，timeline 占最底部、dataZoom 在其上；
    坐标系与系列避开全部条带，组件各自落在专属条带内（互不遮挡）。
    布局缓存：键命中直接返回；动画进行中不缓存（每帧重算）。
    """
    if force:
        chart._layout_key = None
    elif not chart.anim.isRunning():
        key = layout_cache_key(chart)
        if key == chart._layout_key:
            return
        chart._layout_key = key
    content = chart._content_rect()
    right_reserves = []
    bottom_reserves = []
    for component in chart._components:
        right_fn = getattr(component, "reserveRight", None)
        if callable(right_fn):
            try:
                size = float(right_fn())
            except Exception:
                size = 0.0
            if size > 0:
                right_reserves.append((component, size))
        bottom_fn = getattr(component, "reserveBottom", None)
        if callable(bottom_fn):
            try:
                size = float(bottom_fn())
            except Exception:
                size = 0.0
            if size > 0:
                bottom_reserves.append((component, size))
    band_order = {key: index for index, key in enumerate(BOTTOM_BAND_ORDER)}
    bottom_reserves.sort(
        key=lambda item: band_order.get(getattr(item[0], "optionKey", ""), 99)
    )
    bottom_total = sum(size for _, size in bottom_reserves)
    right_total = sum(size for _, size in right_reserves)

    coord_content = QRectF(content)
    if right_total > 0:
        coord_content.setRight(
            max(coord_content.left() + 20.0, coord_content.right() - right_total)
        )
    if bottom_total > 0:
        coord_content.setBottom(
            max(coord_content.top() + 20.0, coord_content.bottom() - bottom_total)
        )

    band_rects = {}
    cursor = content.bottom()
    for component, size in bottom_reserves:
        band_rects[id(component)] = QRectF(
            content.left(), cursor - size, content.width(), size
        )
        cursor -= size
    cursor = content.right()
    for component, size in right_reserves:
        band_rects[id(component)] = QRectF(
            cursor - size,
            content.top(),
            size,
            max(20.0, content.height() - bottom_total),
        )
        cursor -= size

    # dataZoom 窗口必须先写回坐标轴，再排系列：系列按当前轴窗口做
    # 「窗口裁剪 + 采样」，顺序反了就是「新轴 + 旧采样」的错配。
    for component in chart._components:
        apply_window = getattr(component, "applyWindow", None)
        if not callable(apply_window):
            continue
        try:
            apply_window()
        except Exception as exc:
            warn_once(
                warn_key(
                    "apply-window",
                    component.__class__.__name__,
                    type(exc).__name__,
                ),
                f"窗口写回坐标轴失败（{component.__class__.__name__}）: {exc!r}",
            )
    for coord in chart._coords:
        coord.layout(coord_content)
    for renderer in chart._series:
        try:
            renderer.layout(coord_content)
        except Exception as exc:
            warn_once(
                warn_key(
                    "series-layout",
                    renderer.__class__.__name__,
                    renderer.name,
                    type(exc).__name__,
                ),
                f"系列布局异常（{renderer.name}）: {exc!r}",
            )
    for component in chart._components:
        layout = getattr(component, "layout", None)
        if callable(layout):
            try:
                layout(band_rects.get(id(component), content))
            except Exception as exc:
                warn_once(
                    f"component-layout:{component.__class__.__name__}",
                    f"组件布局异常（{component.__class__.__name__}）: {exc!r}",
                )
