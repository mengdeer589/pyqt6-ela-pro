# 图表 API 规范

图表家族（`ElaChartWidget` / `ElaPlotWidget` / `ElaFigureCanvas` / `ElaDashboardGauge`）
统一 **camelCase** 命名；`ElaChartWidget` 的实例接口与 **ECharts 对齐**，
配置 / 控制 / 事件三层如下。

**配置与查询**

| 方法 | 说明 |
|---|---|
| `setOption(option, notMerge=False, lazyUpdate=False)` | **默认合并**（ECharts 语义）：dict 深合并；`series` / `dataZoom` / `graphic` 按 `id` → `name` → 下标逐项合并（未匹配旧项保留、新项追加）；其余 list 整体替换。`notMerge=True` 全量替换并重置图例选择；`lazyUpdate=True` 延迟到下一事件循环重建。返回 self |
| `getOption()` | 当前 option 深拷贝（`options` 帧保留，当前帧已合并） |
| `seriesRenderers` / `coords` / `components` | 渲染器 / 坐标系 / 组件实例列表（属性） |
| `palette()` / `colorForSeries(series)` | 当前调色板 / 指定系列主色 |
| `primaryCoord()` / `coordFor(seriesOpt)` | 主坐标系 / 按系列解析坐标系 |
| `hitItem(pos)` / `hoverInfo()` | 坐标 → ECharts click params / 当前悬停命中 |
| `convertToPixel(finder, value)` / `convertFromPixel(finder, value)` / `containPixel(finder, value)` | 数据 ↔ 像素换算与命中判定（finder：`"grid"` / `{"seriesIndex": 0}` 等） |
| `getWidth()` / `getHeight()` / `getDevicePixelRatio()` | 尺寸查询 |

**控制**

| 方法 | 说明 |
|---|---|
| `resize(opts=None)` / `resize(w, h)` | 重排；dict 形式 `{"width":…, "height":…}`，也兼容 QWidget 两参数 |
| `dispatchAction(payload)` | `legendToggleSelect` / `legendSelect` / `legendUnSelect` / `legendAllSelect` / `legendInverseSelect` / `dataZoom`（`start/end` 或 `startValue/endValue`）/ `restore` / `showTip` / `hideTip` / `highlight` / `downplay` / `timelineChange` / `timelinePlayChange`；返回是否识别 |
| `setInteractive(bool)` / `interactiveEnabled()` | 交互总开关（静态化整图）。**打开 = 全开**：置 `True` 会清空逐项开关的覆盖（之前 `setInteractionEnabled` 关掉的项一并复位）；关闭期间逐项覆盖保留 |
| `setInteractionEnabled(feature, bool)` / `isInteractionEnabled(feature)` | 逐项开关：`tooltip` / `legend` / `dataZoom` / `brush` / `timeline` / `toolbox` |
| `showLoading(type="default", opts=None)` / `hideLoading()` / `isLoading` | 加载遮罩（`text` / `color` / `textColor` / `maskColor` / `fontSize` / `showSpinner` / `spinnerRadius` / `lineWidth`） |
| `appendData({"seriesIndex"|"seriesName"|"seriesId", "data": …})` | 追加数据点（保留过渡动画） |
| `getDataURL(opts=None)` | 导出 `data:image/png;base64,…`（`type` / `pixelRatio` / `backgroundColor`） |
| `saveImage(path=None)` | 文件版导出 PNG（扩展；`path=None` 弹保存对话框） |
| `clear()` | 清空（等价 `setOption({}, notMerge=True)`） |
| `dispose()` / `isDisposed()` | 销毁（停定时器 / 断主题 / deleteLater）与状态查询 |

**事件**

ECharts 事件名经 `on(eventName, handler)` / `off(eventName=None, handler=None)`
注册（handler 收 ECharts params dict，异常被吞掉并告警，不会终止进程）：

| 事件名 | 载荷 | 触发 |
|---|---|---|
| `click` | params（`componentType` / `seriesType` / `seriesIndex` / `seriesName` / `name` / `dataIndex` / `data` / `value` / `color` / `offsetX` / `offsetY`） | 点击命中数据项 |
| `legendselectchanged` | `{name, selected}` | 图例点击切换系列 |
| `datazoom` | `{start, end, batch}` | 缩放窗口变化（滚轮 / 拖拽 / 平移 / restore） |
| `timelinechanged` | `{currentIndex}` | 时间轴换帧（含自动播放） |
| `brushselected` | `{batch, selected}` | 刷选变化 |
| `restore` / `highlight` / `downplay` | 对应 params | 动作触发 |
| `finished` | `{}` | 动画播放完毕 |

同时保留 Qt 信号（宿主可直接 connect）：`legendToggled(str, bool)` /
`dataZoomChanged(float, float)` / `timelineChanged(int)` / `itemClicked(dict)` /
`toolboxTriggered(str)` / `brushChanged(list)` / `finished()`。
`selectchanged`（选中态）本轮未实现。

**扩展（自定义系列 / 组件）**

```python
from pyqt6_ela_pro.charts import (
    SeriesRenderer, registerSeries, chartToken,
)

class MySeries(SeriesRenderer):
    optionKey = "line"           # 或注册自己的 "myType"

    def hitTest(self, pos): ...  # 返回 {"name", "value", "series"[可选 text/title]}
    def valueAtIndex(self, i): ...
    def layout(self, rect): ...
    def paint(self, p, animT): ...   # 颜色经 chartToken("color.primary") 取主题令牌

registerSeries("myType", MySeries)   # 同名覆盖会告警
```

**数据格式**（与系列 `data` 一致）：`number` / `[x, y]` / `[x, y, value]` /
`{"value": [...], "tooltip": {"formatter": "自定义文案"}, "itemStyle": {"color": "#..."}, ...}`；
坐标系由 `coordinateSystem` 声明（缺省 `grid`，可选 `polar` / `singleAxis` / `calendar`）。

**ECharts 兼容要点**

- **配色**：默认调色板为 ECharts 官方 9 色（`ECHARTS_PALETTE`），可用顶层
  `"color": [...]` 覆盖；系列 `itemStyle.color` / 数据项 `itemStyle.color`
  逐级优先。
- **通用键**：`itemStyle`（`color` / `opacity` / `borderColor` / `borderWidth` /
  `borderRadius`）、直角系列 `label`（`show` / `formatter` 模板或回调 /
  `fontSize` / `color` / `position`）、`line.stack` + `areaStyle.color`（渐变
  colorStops）、`barGap` / `barCategoryGap`、`emphasis` / `blur`（命中项
  `emphasis.itemStyle.color`、未命中项 `blur.itemStyle.opacity`，缺省加亮 / 淡化）、
  `silent`（跳过命中）、`animation`（系列级关闭动画）、`id`（合并匹配键）。
- **坐标轴键**：`boundaryGap` / `inverse` / `scale` / `nameLocation` / `nameGap` /
  `interval` / `minInterval` / `maxInterval` / `splitNumber` /
  `axisLabel`（`show` / `interval` / `rotate` / `formatter` / `color` / `fontSize`）/
  `axisTick` / `axisLine` / `splitLine` / `splitArea`；`grid` 支持
  `show` / `containLabel` / `borderColor` / `borderWidth` / `backgroundColor`。
- **tooltip 键**：`formatter`（模板 / callable）/ `valueFormatter` /
  `axisPointer.type`（`line` / `shadow` / `cross` / `none`）/ `backgroundColor` /
  `borderColor` / `borderWidth` / `textStyle`；数据项可用
  `{"value": …, "tooltip": {"formatter": …}}` 覆盖单点文案。
- **timeline**：顶层 `baseOption` + `options` 帧，`timeline.currentIndex`
  指定初始帧；`goto()` / `dispatchAction({"type": "timelineChange"})` 换帧时
  `baseOption` 深合并帧 option 并保留过渡动画。
- **交互**：
  - `sunburst` / `treemap`：点击父级扇区/矩形下钻，点击中心孔 / 空白 / 面包屑
    返回，`resetDrill()` 直接回顶层；
  - `graph`：`draggable: true` 时按住节点拖拽（拖拽后位置固定，
    `resetPositions()` 复位）；`roam` 开启滚轮缩放 + 空白拖拽平移
    （`resetRoam()` 复位）；
  - `map`：`roam: true` 开启滚轮缩放（0.2~6）、拖拽平移，`resetRoam()` 复位；
  - 其余交互统一由 `setInteractive` / `setInteractionEnabled` 管控。
- **布局排布**：竖直 `visualMap` 占右侧条带、`timeline` 最底、`dataZoom` 与
  横向 `visualMap` 依次上移，坐标系自动避开，互不遮挡。


---

**可运行示例**：`example/charts_page.py`；`ElaChartWidget` 的能力速览（21 系列 / 交互 / 大数据）见 README「核心能力」。

---

## 折线 / 散点：大数据与 Plotly 对齐的交互（2026-10）

### 大数据行为（默认开，无需配置）

| 机制 | 语义 |
|---|---|
| **窗口 + 抽稀** | 所有轴类型（value / category / polar / singleAxis）都按「当前窗口 × 绘图像素宽 × `sampling.pointsPerPixel`」抽稀；默认算法 `minmax`（包络保形），可换 `lttb` / `m4` / `minmaxLTTB`，或 `sampling: {algorithm, threshold, pointsPerPixel}`；**`sampling: false` 关闭抽稀**（1M 点约 1.7s/帧，保真度优先时用） |
| **x 不单调也能抽稀** | tsdownsample 要求 x 严格递增；不满足时自动退化到 numpy 按桶 min/max（`_downsample.bucket_minmax_indices`），无 numpy 时再退化为等距抽稀 |
| **单调 x 快路径** | 时间基**一次性分析**（单调性 / 步长 / 记录中断位置，`_downsample.analyze_x`）：窗口走 `searchsorted` 连续段 + **切片视图**（免掩码免拷贝，10M 点 ≈ 0.01ms；替代原先每次布局的 `is_sorted` + 全量掩码）；2D `[x, y]` 输入自动转出 C 连续副本（列视图会被 tsdownsample **静默拒绝** → 掉进 numpy 兜底慢约 20 倍） |
| **记录中断（gap）** | 相邻时间差 > 4.1 × 步长（**正差中位数**）处 = 记录中断；中断在当前窗口的像素宽度 **≥ 4px 才断开**（亚像素空洞照常连线，不产生闪烁断缝）。`addGaps: false` 或 `connectNulls: true` 关闭；数值时间戳生效 |
| **采样结果缓存** | 小 LRU（6 槽）+ **全景常驻槽**：窗口 A→B→A、缩回全景均不重算；换数据（数据身份变化）整体作废 |
| **窗口裁剪对所有数据形态生效** | numpy 快路径按轴范围过滤；纯 Python 兜底路径（dict 项 / 混合类型 / 含 `None`）走 `_py_window`（x 有序用 `bisect`，无序线性扫描 + 缓存）—— 缩放 / 平移后曲线始终铺满窗口，不会「越缩放越稀」 |
| **坐标轴标签 / 刻度 / 网格线** | `interval: 'auto'`：按「标签宽度 ÷ 每类目像素」跳着画（显式 `axisLabel.interval` 优先）。1M 个类目的轴不再画 1M 个标签 |
| **数据点符号** | 抽稀清单在布局期算好，按「至少每 10px 一个」控制数量；绘制走预渲染位图（`QPainterPath` 合并反而慢 50 倍） |
| **散点** | 与折线同一套窗口 + 抽稀（`_LOD_POINTS_PER_PX` = 4） |

实测（1400×800，离屏；2026-10-18 在「窗口快路径 + 连续副本 + 采样 LRU」之后重测）：折线 1M 帧 **9.4ms**、category 1M 9.4ms、散点 1M 9.4ms；悬停 0.8ms。**同窗口重复缩放**（缓存命中）≈ 一帧 + 映射；**进入新窗口**（真实重采样）折线 1M ≈12ms、category ≈20ms、散点 ≈38ms；**缩回全景** 折线 ≈33ms、category ≈45ms。冲击 / 振动形态（显式时间戳 + 记录中断）：**单通道 5M** 帧 3.0ms、新窗口 8.3ms、缩回全景 10.4ms；**三通道 3×2M** 帧 6.4ms、新窗口 19.2ms。复跑：`tools/perf/bench_charts.py`（`zoom新窗口` / `缩回全景` 两列专门覆盖缓存效应）。

### Plotly 对齐的交互 / 数据 API

| API / option | 对应 Plotly | 说明 |
|---|---|---|
| `resetView()`、`setDoubleClickReset(True)` | `doubleClick: 'reset'` | 双击复位全部 dataZoom 窗口 + 漫游 / 缩放（默认开，可关） |
| `zoomStep(factor)` | 模式条 zoom in / out | `<1` 放大、`>1` 缩小，围绕窗口中心，最小 0.5% |
| `setDragMode("pan"/"zoom"/"select"/"lasso")` | `dragmode` | `zoom` = 拖拽框选即缩放；`select` / `lasso` = 框选 / 套索选择（结果走 `brushChanged`）。**拖拽与点击共存**：即使 dataZoom / brush 占用了按下，原地松开（位移 ≤4px）仍发 `itemClicked`，真拖拽不会误发 |
| `setDragMode("zoom")` 的选框 | `dragmode: 'zoom'` 的框选缩放 | 选框是**一次性手势**：松手缩放落地后自动消失（不留选中集）；`select` / `lasso` 则保留选框与选中集，点绘图区外收框（`brushComponent().clear()` 也可手工收） |
| `setWheelZoomEnabled(True)`、`wheelZoomEnabled()` | `config.scrollZoom` + `dragmode: 'pan'`（Plotly 都需手动开） | **默认开**：直角坐标图**滚轮缩放 + 按住拖动平移**（自动挂一个 `inside` 组件，`zoomOnMouseWheel` / `moveOnMouseMove` 均为 True，对齐 ECharts 默认值）；`setDragMode("zoom"/"select"/"lasso")` 把拖拽让给刷选。option 里自己配了 `dataZoom` 则完全听用户的，本开关不再插手 |
| `toolbox.buttonWidget(name)` | 模式条按钮句柄 | 工具条按钮是**真实 `ElaIconButton` 子控件**（Ela 图标字体 + 主题配色，不再是自绘小图标）；导出 PNG / SVG 时自动隐藏（导出的是图，不是 UI） |
| `brush: {"type": "lasso"}`、`brushComponent()` | lasso select | 套索轨迹多边形命中（`QPolygonF.containsPoint`），`selected` 信号给 `[{series, dataIndex, value, x}]` |
| `tooltip.hitRadius`（或 `hoverdistance`） | `hoverdistance` | 命中半径 px，默认 10；折线 / 散点共用 |
| `hoveranywhere` / `clickanywhere`（或 `tooltip.hoverAnywhere`） | 同名 | 空区也出提示 / 发 `itemClicked`，载荷带 `componentType:"grid"` 与数据坐标 |
| `tooltip.order: "valueAsc"/"valueDesc"`（兼容 `hoversort` 文案） | `hoversort` | `trigger: "axis"` 的联合提示按值排序 |
| `series.connectNulls` | `connectgaps` | 断点不切段（默认切开） |
| `saveImage("x.svg")` / `saveImage(format="svg")` / `getDataURL({"type": "svg"})` | 模式条导出 SVG | 走 `QSvgGenerator` 的同一绘制链（矢量图元 + 位图符号内嵌） |
| `toolbox.feature` | 模式条按钮 | `saveAsImage` / **`saveAsSvg`** / `dataZoom` / `restore` / **`zoomIn`** / **`zoomOut`** |
| 图例悬停 | 悬停图例高亮 trace | 指针压在图例条目上时该系列正常绘制、其余降到 35% 不透明度；提示框让位 |
