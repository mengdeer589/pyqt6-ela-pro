# 图表 option 覆盖审计

审计日期：2026-11-21  
范围：`pyqt6_ela_pro/charts`（ElaChartWidget、23 个系列、组件、交互、导出）  
方法：静态扫描 `option.get(...)` / 模型字段 + 现有测试 + 真实桌面截图抽查

状态说明：

- **完整**：核心语义可用，有守卫测试
- **部分**：主路径可用，子选项 / 边界缺失
- **未实现**：接受但忽略，或未建模
- **扩展**：本库自定义能力

## 总体结论

- 23 个系列全部注册，均可基础渲染。
- 高频路径（setOption、tooltip、legend、dataZoom、label、markPoint/markLine、导出、流式推送）覆盖较完整。
- 本轮补齐跨图 `universalTransition`、轴级 `axisPointer.link`、map 系列 / 顶层 geo 去重、`dataZoom.brushSelect`、`graphic.group`，并加入流式基准。
- 主要缺口转向：更多系列的渐进分帧、`graphic` polygon / 动画、`encode.tooltip` / `encode.itemStyle`、polar / geo 轴指针联动。
- 模型字段已清零空转：463 个字段全部有运行时读取路径或已删除。
- 大量 option 的「存在」不等于「完整」：下表的「部分」项是后续最值得补的。

## 顶层 option

| Option | 状态 | 已覆盖 | 缺口 / 说明 |
|---|---|---|---|
| `animation` | 部分 | `animation` / 持续时间 / 延迟 / easing / update 系列 / threshold | 逐数据项函数延迟未支持；部分系列只做整体淡入 |
| `color` | 完整 | 调色板、逐系列 / 逐项取色 | — |
| `backgroundColor` | 完整 | 图表底色、导出底色 | — |
| `textStyle` | 完整 | color / fontSize / fontWeight / fontFamily / fontStyle | 富文本 `rich` 支持数据标签 / 轴标签 / 图例 / title；其它文字位未接 |
| `dataset` | 部分 | 二维数组、对象数组、sourceHeader、dimensions、encode、seriesName 拆分、`seriesLayoutBy: row/column` 自动拆系列、filter/sort/aggregate | transform 只支持三类算子；类型化 dimensions 不完整；`encode.tooltip` / `encode.itemStyle` 未支持 |
| `xAxis` / `yAxis` | 完整 | category / value / time / log、多轴、gridIndex、label / line / tick / split / name、min/max/scale/interval | 轴级 `axisPointer` 子配置仍走全局 |
| `grid` | 完整 | 多 grid、百分比 / 像素边距、containLabel、背景 / 边框 | — |
| `polar` / `angleAxis` / `radiusAxis` | 部分 | bar / line / scatter / effectScatter；radius / center；markArea 环形扇区 | 部分组件不支持 |
| `singleAxis` | 部分 | line / scatter / themeRiver；单轴范围；markArea 区间带 | markArea 仅 xAxis 区间 |
| `calendar` | 部分 | heatmap 日历、range / cellSize / label nameMap；markArea 日期区间 | 非 heatmap 系列仍有限 |
| `geo` | 部分 | GeoJSON 注册、Polygon / MultiPolygon、孔洞、equirectangular / mercator、scatter / lines 叠加、roam、`geoIndex` / 多 geo、区域 hover/select、跨 180° 经线、map 系列与顶层 geo 去重 | — |
| `radar` | 部分 | indicator、radius / center、split / axis 样式 | 顶层 radar 只供 radar 系列读取；rich label 不支持 |
| `series` | 部分 | 23 类型全部注册 | 各类型子项差异见系列表 |
| `tooltip` | 部分 | item / axis / none、formatter、valueFormatter、axisPointer、order / hitRadius / hoverAnywhere / clickAnywhere / confine / enterable | rich / appendToBody 未支持 |
| `legend` | 部分 | 多图例、orient / position、selected / selectedMode、分页、maxRows、pageIconSize、rich、inactiveColor | 自定义 icon 未支持 |
| `title` | 部分 | 多标题、text / subtext、位置、样式、rich、link | target 窗口策略未区分 |
| `visualMap` | 部分 | continuous / piecewise、min/max、seriesIndex、dimension、inRange / outOfRange、pieces、calculable | 文案 / 位置 / 手柄样式子项有限 |
| `dataZoom` | 部分 | inside / slider、start/end、startValue/endValue、filterMode、zoomLock、min/maxSpan、move/wheel 开关、brushSelect | 仅 grid 轴；orient 等子项有限 |
| `timeline` | 部分 | baseOption / options、currentIndex、autoPlay、playInterval、label / lineStyle / checkpoint / control | 复杂 timeline 联动组件未覆盖 |
| `toolbox` | 部分 | saveAsImage / saveAsSvg / dataZoom / restore / zoomIn / zoomOut / magicType / dataView | 自定义 feature / icon 样式 |
| `brush` | 部分 | rect / lasso、outOfBrush、brushMode single/multiple、选中回传 | throttle / 更多 brushType 未支持 |
| `graphic` | 部分 | circle / rect / text / line / group、left/top/right/bottom 定位、children、rotation / origin / scale / z | 无 polygon / 动画 |
| `axisPointer` | 部分 | line / shadow / cross / none、label、lineStyle、snap、跨图联动、`link` 轴级映射（`"all"` / `xAxisIndex` / `yAxisIndex` 分组） | polar / geo 轴指针联动未支持 |
| `labelLayout` | 部分 | `hideOverlap`、`moveOverlap`（shiftX / shiftY） | 轴标签 / 图例 rich、多行布局未支持 |
| `universalTransition` | 部分 | 单图 / 跨图：bar / line / scatter 几何插值，其它类型交叉淡出；按 `id` → `name` → 下标匹配 | 任意坐标系共享元素未支持 |
| `progressive` | 部分 | line / bar / scatter 逐点分帧；`progressiveChunkMode: sequential/mod`；导出自动关闭 | 其它系列无逐项分帧；无时间预算 |
| `labelLine` | 部分 | pie 外侧标签 `show` / `length` / `length2` / `lineStyle` | funnel / 其他系列的 labelLine 未接入 |
| `parallelAxis` | 部分 | 维度名、axisLabel / nameTextStyle、数据范围 | 复杂轴样式有限 |
| `annotations` | 扩展 | 可拖动标注、可编辑文本、事件回传 | 非 ECharts 标准 |

## 23 系列

图例：✅ 完整 / 🟡 部分 / ⛔ 未实现

| 系列 | 坐标 | 标签 | visualMap | 选中 | 图例项 | mark* | dataZoom | 渐进 | 形变 | 备注 |
|---|---|---|---|---|---|---|---|---|---|---|
| bar | grid / polar | ✅ | ✅ | ✅ | ✅ series | ✅ | ✅ grid | ✅ | ✅ | stack / barWidth / barGap / radius |
| line | grid / polar / single | ✅ | ✅ | ✅ | ✅ series | ✅ | ✅ grid | ✅ | ✅ | sampling / LOD / areaStyle / endLabel / connectNulls |
| pie | 自有 | ✅ | ✅ | ✅ | ✅ items | ⛔ | ⛔ | ⛔ | 🟡 淡出 | radius / center / roseType / totalLabel |
| scatter | grid / polar / single / geo | ✅ | ✅ | ✅ | ✅ series | ✅ | ✅ grid | ✅ | ✅ | LOD / symbolSize / ripple |
| effectScatter | grid / polar / single / geo | ✅ | ✅ | ✅ | ✅ series | ✅ | ✅ grid | ✅ | ✅ | rippleEffect 周期 / 缩放 |
| candlestick | grid | ✅ | ⛔ | ⛔ | ✅ series | ✅ | ✅ grid | ⛔ | 🟡 淡出 | color / color0 / borderColor / borderColor0 |
| boxplot | grid | ✅ | ⛔ | ⛔ | ✅ series | ✅ | ✅ grid | ⛔ | 🟡 淡出 | 五数概括 |
| pictorialBar | grid | ✅ | ✅ | ✅ | ✅ series | ✅ | ✅ grid | ⛔ | 🟡 淡出 | symbol / symbolRepeat / barWidth |
| heatmap | grid / calendar | ✅ | ✅ | ⛔ | ✅ series | ⛔ | ✅ grid | ⛔ | 🟡 淡出 | calendar 不走 dataZoom |
| funnel | 自有 | ✅ | ✅ | ✅ | ✅ items | ⛔ | ⛔ | ⛔ | 🟡 淡出 | orient / sort / gap / minSize / funnelAlign |
| gauge | 自有 | 🟡 detail / title | ⛔ | ⛔ | ✅ series | ⛔ | ⛔ | ⛔ | 🟡 淡出 | progress / pointer / anchor / splitNumber |
| radar | 自有 | ✅ | ⛔ | ⛔ | ✅ series | ⛔ | ⛔ | ⛔ | 🟡 淡出 | indicator / shape / split / axis |
| graph | 自有 | ✅ | ✅ 节点 | 🟡 | ✅ categories | ⛔ | ⛔ | ⛔ | 🟡 淡出 | force / roam / draggable / edgeSymbol |
| tree | 自有 | ✅ | ⛔ | 🟡 | ✅ series | ⛔ | ⛔ | ⛔ | 🟡 淡出 | orient / roam / expandAndCollapse / edgeShape |
| treemap | 自有 | ✅ | ⛔ | 🟡 | ✅ series | ⛔ | ⛔ | ⛔ | 🟡 淡出 | breadcrumb / drill / gapWidth |
| sunburst | 自有 | ✅ | ⛔ | 🟡 | ✅ series | ⛔ | ⛔ | ⛔ | 🟡 淡出 | nodeClick / minAngle |
| sankey | 自有 | ✅ | ⛔ | 🟡 | ✅ series | ⛔ | ⛔ | ⛔ | 🟡 淡出 | nodes / links / nodeAlign / drag |
| themeRiver | singleAxis | 🟡 | ⛔ | ⛔ | ✅ streams | ⛔ | ⛔ | ⛔ | 🟡 淡出 | 数据项 `[time, value, name]` |
| parallel | 自有 | ⛔ | ⛔ | ⛔ | ✅ series | ⛔ | ⛔ | ⛔ | 🟡 淡出 | parallelAxis / lineStyle |
| lines | grid / geo | ⛔ | ✅ | ⛔ | ✅ series | ⛔ | ⛔ | ⛔ | 🟡 淡出 | coords / curveness / effect |
| map | 自有 + geo | ✅ | ✅ | 🟡 | ✅ series | ⛔ | ⛔ | ⛔ | 🟡 淡出 | map / geo.regions / nameProperty / roam |
| image | grid / calendar | ⛔ | ✅ | ⛔ | ✅ series | ⛔ | ✅ grid | ⛔ | 🟡 淡出 | cmap / vmin / vmax / extent / aspect |
| gantt | grid | ✅ | ⛔ | ⛔ | ✅ series | ⛔ | ✅ grid | ⛔ | 🟡 淡出 | editable / dependencies / critical / deadline / baseline |

> 「形变」的 🟡 表示 `universalTransition` 走旧系列层交叉淡出；bar / line / scatter 才是几何插值。

## 组件细节

### Tooltip

已支持：

- `trigger`: `item` / `axis` / `none`
- `formatter`（callable / 模板）、`valueFormatter`
- `axisPointer.type` / `label` / `lineStyle` / `snap`
- `order`、`hitRadius`、`hoverAnywhere`、`clickAnywhere`
- `confine`：`True` 时越界翻转 / 收敛到图表内；`False` 时允许超出画布（由控件裁剪）
- item 级 `tooltip.formatter`

缺口：

- `appendToBody` / `extraCssText` / rich / alwaysShowContent 未支持

### Legend

已支持多图例、orient、位置、selected / selectedMode、分页、maxRows、item 宽高间距。

缺口：自定义 icon / rich text 不完整。

### dataZoom

已支持 inside / slider、窗口、value 窗口、filterMode、zoomLock、min/maxSpan、move/wheel 开关、`brushSelect`（slider 轨道拖出新窗口）。

缺口：主要作用于 grid 轴；orient / 手柄样式等子项有限。

### visualMap

连续 / 分段、min/max、dimension、seriesIndex、inRange / outOfRange、pieces、calculable。

缺口：text / textGap / itemWidth/Height / 手柄样式等 UI 子项覆盖有限。

### brush / toolbox / timeline

- brush：rect / lasso，outOfBrush，`brushMode: "single"/"multiple"`，选中回传。
- toolbox：saveAsImage / saveAsSvg / dataZoom / restore / zoomIn / zoomOut / magicType。
- timeline：baseOption / options、播放、标签、线 / checkpoint / control 样式。

## 模型字段

当前静态扫描结果：**463 个模型字段，414 个运行时读取 option 键，0 个空转字段**。

本轮新增字段：`graphic.scale/scaleX/scaleY/rotation/origin/z/silent`、`dataZoom.brushSelect`、`tooltip.enterable`、`title.link/target`。此前删除的 `radarIndex`、`throttleType`、`throttleDelay` 保持删除，`seriesLayoutBy` 仍走 row / column 自动拆系列。

## dataset / geo / labels

### dataset

已实现：行式二维数组、对象数组、sourceHeader、dimensions、encode x/y/value/itemName/seriesName、`seriesLayoutBy: row/column` 自动拆系列、filter/sort/aggregate。

未实现：类型化 dimensions 的完整类型系统、更多 transform 算子、`encode.tooltip` / `encode.itemStyle`。

### geo

已实现：注册 GeoJSON、Polygon / MultiPolygon、孔洞、equirectangular / mercator、顶层 `geo` 叠加 scatter / lines、roam、`geoIndex` / 多 geo、区域 hover/select、跨 180° 经线。

`map` 系列与顶层 `geo` 同图时复用 `GeoCoord` 路径，不再重复投影 / 描边 / 画标签；无数据区域交给 `geo`，系列只叠加数据着色。`geo.label` 在系列填充之后绘制，并按区域实际底色自动选深 / 浅字色。

### label

已实现：label 样式、formatter、rich `{style|text}`、背景 / 边框 / 圆角 / padding、rich 分段背景、`hideOverlap`、`moveOverlap`、pie `labelLine`、轴标签 / 图例 / title rich。

未实现：多行 rich、label 动画、funnel / 其它系列 labelLine。

## 事件 / 动作 / 导出

- 事件：click / mouseover / mouseout / mousemove / globalout / selectchanged / legendselectchanged / datazoom / timelinechanged / brushselected / restore / highlight / downplay / finished。
- 动作：legend* / dataZoom / restore / showTip / hideTip / highlight / downplay / select / unselect / toggleSelect / timelineChange / timelinePlayChange。
- 导出：PNG / JPEG / SVG / PDF、多页 PDF、打印、打印预览、JPEG quality、位图 scale。
- 自定义：annotations 拖动 / 编辑、gantt 拖动事件。

## 优先修复建议

**P0**

无。

**P1**

1. 时间预算 / 更多系列渐进渲染
2. `graphic` polygon / 动画
3. `encode.tooltip` / `encode.itemStyle`
4. polar / geo 的 `axisPointer.link` 联动

**P2**

1. `toolbox` 自定义 feature / icon 样式
2. 任意坐标系之间的共享元素形变
3. `dataZoom` orient / 手柄样式子项
4. 完整 ECharts 迁移对照表

## 守卫测试

| 覆盖 | 测试 |
|---|---|
| 23 系列基础渲染 / 主题矩阵 | `tests/ela_chart_widget/test_chart_theme_coverage.py` |
| option 键解析 | `tests/ela_chart_widget/test_echarts_option_keys.py` |
| 轴 / tooltip / dataZoom | `tests/ela_chart_widget/test_chart_axis_tooltip.py`、`test_chart_datazoom_details.py` |
| markPoint / markLine / markArea | `test_chart_marks_api.py` |
| 富文本标签 | `test_chart_rich_labels.py` |
| dataset | `test_chart_dataset.py` |
| GeoJSON / geo 组件 | `test_chart_geo.py` |
| 流式 | `test_chart_stream.py`、`tools/perf/bench_charts_stream.py`、`docs/charts-stream-bench.md` |
| 渐进 / universalTransition | `test_chart_interaction_advanced.py`、`test_chart_universal_cross.py` |
| 导出 / 打印 | `test_chart_ux_export.py` |
| 主题矩阵 | `tests/example/test_theme_matrix.py` |
| 示例工作台新能力演示 | `tests/example/test_charts_workbench.py` |

## 复现审计

```powershell
uv run python tools/audit_charts_options.py
uv run python tools/audit_charts_options.py --json audit.json
```

脚本扫描其余模块的 `option.get(...)`，输出运行时读取的 option 键清单。
