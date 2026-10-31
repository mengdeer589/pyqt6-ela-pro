# 图表 API 规范

图表家族（`ElaChartWidget` / `ElaPlotWidget` / `ElaFigureCanvas` / `ElaDashboardGauge`）
统一 **camelCase** 命名；`ElaChartWidget` 的实例接口与 **ECharts 对齐**，
配置 / 控制 / 事件三层如下。

**配置与查询**

| 方法 | 说明 |
|---|---|
| `setOption(option, notMerge=False, lazyUpdate=False)` | **默认合并**（ECharts 语义）：dict 深合并；`series` / `dataZoom` / `graphic` 按 `id` → `name` → 下标逐项合并（未匹配旧项保留、新项追加）；**`xAxis` / `yAxis` / `singleAxis` 按下标逐项合并**（轴名不是身份）；其余 list 整体替换。`notMerge=True` 全量替换、重置图例选择**与 dataZoom 窗口**；`lazyUpdate=True` 延迟到下一事件循环重建（重建时使系列层位图失效，不会贴回旧数据）。返回 self |
| `updateAxis(axis, patch, axisIndex=0)` | 只更新一条轴（深合并；`axis` = `"x"` / `"y"` / `"single"`），其余轴原样保留。多轴场景改轴标签 / 刻度 / 样式用它，别手写整个轴数组。`radar` 不支持（维度在 `series.indicator`，且本库不读顶层 `radar` 组件） |
| `updateSeries(patch, *, seriesIndex/seriesName/seriesId)` | 只更新一个系列（按 `id` → `name` → 下标定位，深合并）；保留用户缩放窗口 |
| `setAxisLabelFormatter(axis, formatter, axisIndex=0)` | 设置轴标签 formatter（字符串模板或 `callable(value, index)`；**index 是刻度下标**） |
| `setCategoryLabels(labels, axisIndex=0)` | 替换类目轴标签列表，保留该轴其它 option 与缩放窗口 |
| `setFontFamily(family)` / `fontFamily()` | 全图字体族（**单个族名**；`None` 恢复系统默认）。逗号列表取第一个并告警 —— Win7 上多族列表会走逐字形族匹配的慢 shaping 并毒化后续文本。组件级 `textStyle.fontFamily` / `axisLabel.fontFamily` / `label.fontFamily` 可覆盖 |
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
| `dispatchAction(payload)` | `legendToggleSelect` / `legendSelect` / `legendUnSelect` / `legendAllSelect` / `legendInverseSelect` / `dataZoom`（`start/end` 或 `startValue/endValue`）/ `restore` / `showTip` / `hideTip` / `highlight` / `downplay` / `select` / `unselect` / `toggleSelect`（`seriesIndex`/`seriesName` + `dataIndex`）/ `timelineChange` / `timelinePlayChange`；返回是否识别 |
| `setInteractive(bool)` / `interactiveEnabled()` | 交互总开关（静态化整图）。**打开 = 全开**：置 `True` 会清空逐项开关的覆盖（之前 `setInteractionEnabled` 关掉的项一并复位）；关闭期间逐项覆盖保留 |
| `setAnnotationEditingEnabled(bool)` / `annotationEditingEnabled()` | 标注标签双击行内编辑开关（默认开）；关闭后只发 `annotationEditRequested`，宿主自行弹框并可调 `setAnnotationText` 提交 |
| `setAnnotationText(seriesName, componentType, dataIndex, text)` | 修改 `markPoint` / `markLine` 的 `data[i].name`，重建并发出 `annotationEdited`；`seriesName` 为空时取第一个匹配组件 |
| `setSeriesLabelText(seriesName="", dataIndex=0, text="", *, seriesIndex=None, seriesId=None)` | 修改某个数据点的标签文本（写入 `series.labelTexts[str(index)]`），空字符串 = 恢复默认数值文案；系列可按 `seriesId` → `seriesName` → `seriesIndex` 寻址（都为空取首个可见系列）；默认只失效系列层位图并重绘，发出 `annotationEdited`（`componentType="seriesLabel"`） |
| `seriesLabelTexts(seriesName="", *, seriesIndex=None, seriesId=None)` / `clearSeriesLabelTexts(...)` | 读取 / 清空某系列的全部数据点标签覆盖 |
| `setInteractionEnabled(feature, bool)` / `isInteractionEnabled(feature)` | 逐项开关：`tooltip` / `legend` / `dataZoom` / `brush` / `timeline` / `toolbox` |
| `showLoading(type="default", opts=None)` / `hideLoading()` / `isLoading` | 加载遮罩（`text` / `color` / `textColor` / `maskColor` / `fontSize` / `showSpinner` / `spinnerRadius` / `lineWidth`） |
| `appendData({"seriesIndex"|"seriesName"|"seriesId", "data": …})` | 追加数据点（**原地增量**：不重建渲染器 / 组件，保留轴窗口；数值数组仍有一次 O(n) 物化） |
| `setGroup(name)` / `connectCharts(group)` / `disconnectCharts(group)` | 图表组跨图联动（dataZoom / legend / axis tooltip）；`connectCharts` 从包顶层导入 |
| `toggleMagicType()` | 折线 → 柱状 → 堆叠柱状 → 折线循环（toolbox 的 `magicType` 按钮调用） |
| `getDataURL(opts=None)` | 导出 `data:image/png;base64,…`（`type` / `pixelRatio` / `backgroundColor`）。底色与 ECharts 同序：`backgroundColor`（导出参数）在最底层 → 图表自身 `backgroundColor` 覆盖其上 → 都没给用主题底；任一层传 `"transparent"` 得透明 PNG（JPEG 自动压到主题底上）。离屏重绘，工具条按钮等子控件不入镜 |
| `saveImage(path=None)` | 文件版导出 PNG / JPEG / SVG（按 `format` 或扩展名判定；`path=None` 弹保存对话框）。底色规则同上（SVG 同样吃图表 `backgroundColor`；JPEG 自动压到主题底） |
| `clear()` | 清空（等价 `setOption({}, notMerge=True)`） |
| `dispose()` / `isDisposed()` | 销毁（停定时器 / 断主题 / deleteLater）与状态查询。**销毁后再调用 `setOption` / `getOption` / `dispatchAction` / `appendData` / `resize` / 导出等公开 API 会抛 `RuntimeError`**（ECharts 语义） |

**事件**

ECharts 事件名经 `on(eventName, handler)` / `off(eventName=None, handler=None)`
注册（handler 收 ECharts params dict，异常被吞掉并告警，不会终止进程）：

| 事件名 | 载荷 | 触发 |
|---|---|---|
| `click` | params（`componentType` / `seriesType` / `seriesIndex` / `seriesName` / `name` / `dataIndex` / `data` / `value` / `color` / `offsetX` / `offsetY`） | 点击命中数据项 |
| `mouseover` / `mouseout` / `mousemove` / `globalout` | 同 click params（`globalout` 无数据项） | 悬停进入 / 离开数据项、移动、离开图表 |
| `selectchanged` | `{fromAction, selected: [{seriesIndex, seriesName, dataIndex, name}], fromOutside}` | 选中态变化（点击 / `select` 动作） |
| `legendselectchanged` | `{name, selected}` | 图例点击切换系列 |
| `datazoom` | `{start, end, batch}` | 缩放窗口变化（滚轮 / 拖拽 / 平移 / restore） |
| `timelinechanged` | `{currentIndex}` | 时间轴换帧（含自动播放） |
| `brushselected` | `{batch: [{brushId, areas, selected: [...]}], selected}` | 刷选变化 |
| `restore` / `highlight` / `downplay` | 对应 params | 动作触发 |
| `finished` | `{}` | 动画播放完毕 |
| `annotationEditRequested`（Qt 信号） | `{seriesName, componentType, dataIndex, text}` | 双击 `markPoint` / `markLine` 标签 |
| `annotationEdited`（Qt 信号） | `{seriesName, componentType, dataIndex, text}` | 标签编辑提交 |

同时保留 Qt 信号（宿主可直接 connect）：`legendToggled(str, bool)` /
`dataZoomChanged(float, float)` / `timelineChanged(int)` / `itemClicked(dict)` /
`toolboxTriggered(str)` / `brushChanged(list)` / `finished()`。

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

> 自定义系列若自己驱动逐帧动效（QTimer + 相位），**每帧必须
> `self.requestSeriesRepaint()`**：只 `chart.update()` 会贴回系列层位图
> （相位不在缓存键里），表现为「只有鼠标移动时动效才动」。

**数据格式**（与系列 `data` 一致）：`number` / `[x, y]` / `[x, y, value]` /
`{"value": [...], "tooltip": {"formatter": "自定义文案"}, "itemStyle": {"color": "#..."}, ...}`；
坐标系由 `coordinateSystem` 声明（缺省 `grid`，可选 `polar` / `singleAxis` / `calendar`）。

**文字样式（字号 / 颜色 / 字重）**

每个文字组件都接受 ECharts 标准键，**未设置的键回退顶层 `textStyle`**：

```python
chart.setOption({
    "textStyle": {"fontSize": 13, "color": "#555"},          # 全图默认（只含外观键）
    "legend": {"textStyle": {"fontSize": 15, "fontWeight": 600}},
    "title": {"textStyle": {"fontWeight": "bold"}, "subtextStyle": {"color": "#888"}},
    "tooltip": {"textStyle": {"fontSize": 12}},
    "xAxis": {"axisLabel": {"fontSize": 12, "fontWeight": 600}},
    "series": [{"type": "line", "label": {"show": True, "fontSize": 11}}],
})
```

- 顶层 `textStyle` 是**兜底**：`fontSize` / `fontWeight` / `fontFamily` /
  `fontStyle` / `color` 五个键参与，组件自己的同名键优先；`show` / `formatter`
  这类行为键**不会**被合并（写 `{"textStyle": {"show": True}}` 不会打开所有
  数据点标签）。
- 覆盖范围：图例 / 标题（含 subtext）/ 提示框（含 axisPointer 数值气泡）/
  轴标签与轴名（`axisLabel` / `nameTextStyle`）/ 数据点标签（直角系列、饼图 /
  树图 / 桑基 / 漏斗 / 雷达 / 仪表 / 地图）/ 折线 `endLabel` /
  `markPoint` / `markLine` 标签 / `dataZoom` 滑块文案 / `visualMap` 两端文案 /
  `timeline` 标签 / `calendar` 的 `dayLabel` / `monthLabel` / `yearLabel` /
  `parallelAxis`（`nameTextStyle` / `axisLabel`）/ `gauge.detail` 与 `title`。
- `fontWeight` 收数字（100–1000，含 650 这类非枚举值）与 `"normal"` /
  `"bold"` / `"bolder"` / `"lighter"`；`fontStyle` 收 `"normal"` / `"italic"` /
  `"oblique"`；非法值静默回退默认。
- **字体族只支持单族**（`setFontFamily("Microsoft YaHei")` / 顶层
  `textStyle.fontFamily` / 组件级 `fontFamily`）：逗号分隔的回退列表会被折叠成
  第一个并留一条 stderr 告警。多族在 Win7 上是慢 shaping 路径且进程级毒化后续
  文本（见 `AGENTS.md` 的 CJK 单族条），因此不做多族回退。纯英文图可用
  `"Consolas"`；含中文时请给单个中文字体（如默认雅黑）。
- `calendar.dayLabel.nameMap` / `monthLabel.nameMap` 支持数组（星期按 ECharts
  约定 **0 = 周日**；月份按 1 月起）与 dict。
- `calendar.range` 支持年份（`2026` / `"2026"`）、月份（`"2026-01"`）、
  单日期与 `[start, end]`（元素可为年份 / 月份 / 日期）；非法值回退当前年。
- `series.label.rotate`（度，绕文字中心旋转）与 `label.align`（`left` /
  `center` / `right`，按数据点调整水平锚点）已在直角系列（line / bar /
  scatter / heatmap）生效；旋转后的命中框取外接矩形。
- `dataZoom.filterMode` 支持 `"filter"` / `"none"`：本库两条路径都**只改轴窗口、
  不物理删除系列数据**（类目轴用 `_all_categories` + `windowOffset` 保留全局
  下标）—— 这正是 `"none"` 的语义；`"weakFilter"` / `"empty"` 未实现，按
  filter 处理并留一条告警。

**组件数组写法（单实例 / 多实例）**

- **多实例**（数组逐项建实例）：
  - `title`：每个元素一个标题（各自 `left` / `top` / `bottom` / `textStyle`）；
    顶部 / 底部条带取同侧最大占用。`chart.title` 仍是第一个，完整列表是
    `chart.titles`。
  - `legend`：每个元素一个图例（各自 `data` 白名单 / `top` / `bottom` /
    `orient` / `selected`）；同侧按数组顺序向外堆叠。`chart.legend` 是第一个，
    完整列表是 `chart.legends`；悬停 / 点击按坐标路由到命中的那个
    （`chart.legendAt(pos)`）。**未写 `legend` 键时默认不显示图例**（ECharts
    语义）；要显示必须显式给 `legend: {}` 或具体配置。
  - `grid`：每个元素一块网格，显式给 `left` / `top` / `right` / `bottom` /
    `width` / `height`（数值 px 或 `"N%"`）；轴用 `gridIndex` 归属网格，
    系列用 `xAxisIndex` / `yAxisIndex` 选轴（轴归属哪个网格，系列就画在哪）：
    ```python
    chart.setOption({
        "grid": [
            {"left": 50, "right": "52%", "top": 40, "bottom": 40},
            {"left": "55%", "right": 30, "top": 40, "bottom": 40},
        ],
        "xAxis": [
            {"type": "category", "data": ["A", "B"], "gridIndex": 0},
            {"type": "category", "data": ["C", "D"], "gridIndex": 1},
        ],
        "yAxis": [
            {"type": "value", "gridIndex": 0},
            {"type": "value", "gridIndex": 1, "position": "right"},
        ],
        "series": [
            {"type": "line", "data": [1, 2], "xAxisIndex": 0, "yAxisIndex": 0},
            {"type": "bar", "data": [5, 2], "xAxisIndex": 1, "yAxisIndex": 1},
        ],
    })
    ```
    **交互归属**：axis tooltip 以光标下的网格为准（只列该网格的系列）；
    brush 在起手网格内选区；dataZoom 的轴窗口作用于**全部共享轴**（可用
    `xAxisIndex` 限定），滚轮 / 拖拽平移按光标所在网格的绘图区换算。
    **多网格默认按轴标签实际宽度留白**（不要求显式 `containLabel`）：窄网格 +
    长数值 / 长轴名不会压到相邻网格。
- **单实例**（数组取第一个 dict，多元素留一条 stderr 告警）：`tooltip` /
  `polar` / `calendar` / `singleAxis` / `brush` / `toolbox` / 顶层 `radar`。
  单元素数组与直接写对象完全等价。
- `xAxis` / `yAxis` / `singleAxis` **支持多轴**（按 `xAxisIndex` / `yAxisIndex` 选轴）；
  `series` / `dataZoom` / `graphic` / `visualMap` 的数组按 `id` → `name` → 下标
  逐项合并。

**ECharts 兼容要点**

- **配色**：默认调色板为 ECharts 官方 9 色（`ECHARTS_PALETTE`），可用顶层
  `"color": [...]` 覆盖；系列 `itemStyle.color` / 数据项 `itemStyle.color`
  逐级优先。所有颜色字符串都接受 `#rgb` / `#rrggbb` / 具名色 / `rgb()` /
  `rgba()`（`QColor` 不认后两者，库内统一过 `_colors.parse_color`）。
- **雷达**：维度定义支持顶层 `radar.indicator`（ECharts 写法）与
  `series.indicator`（系列优先）；`center` / `radius` 同理（百分比相对内容区）。
- **地图**：`label.show`（默认 **True**，与 ECharts 的默认关闭不同）/
  `color` / `fontSize` / `fontWeight`；未给 `color` 时按区域底色亮度自动选
  黑 / 白字。
- **提示框指示线**：`tooltip.axisPointer.label`（`show` / `formatter` /
  `backgroundColor` / `borderColor` / `color` / `fontSize`）与
  `axisPointer.lineStyle`（`color` / `width` / `type`）均已接入。
- **visualMap**：连续型支持 `text`（两端文案）/ `textStyle` / `calculable`
  （可拖拽把手：拖动收窄 `min..max`，色带外的区间加暗色遮罩）；**分段型**
  `type: "piecewise"` 或直接给 `pieces`：
  ```python
  "visualMap": {
      "type": "piecewise",
      "pieces": [
          {"min": 0, "max": 50, "label": "低", "color": "#a0c4ff"},
          {"min": 50, "max": 80, "label": "中", "color": "#ffd6a5"},
          {"min": 80, "max": 100, "label": "高", "color": "#ffadad"},
      ],
  }
  ```
  `pieces` 支持 `min` / `max`（闭区间）、`value`（精确值）、比较谓词
  `gt` / `gte` / `lt` / `lte`（可组合）与 `label` / `color`；不在任何分段的值走
  `outOfRange.color`（缺省中性色）。色带作用于 `map` / 直角与日历 `heatmap`，
  以及 **`scatter`（气泡图按值上色）**：取值维度由 `visualMap.dimension` 指定，
  缺省用数据最后一维（`[x, y, value]` 即 value）；`seriesIndex` / `seriesId`
  可把色带绑定到指定系列，数据项自己的 `itemStyle.color` 优先级高于映射。
- **dataZoom**：`textStyle`（滑块两端文案）、`zoomLock`（锁定窗口大小，滚轮
  不缩放、仍可平移）、`filterMode`（`"filter"` / `"none"`，见上）。
- **轴名**：`xAxis` / `yAxis` 的 `nameGap` 与 `nameTextStyle`（`color` /
  `fontSize` / `fontWeight`）生效。
- **通用键**：`itemStyle`（`color` / `opacity` / `borderColor` / `borderWidth` /
  `borderRadius`）、直角系列 `label`（`show` / `formatter` 模板或回调 /
  `fontSize` / `color` / `position`；`show: true` 的数据点标签可双击编辑，
  编辑结果存 `series.labelTexts[str(index)]`，`label.editable: false` 可关；
  运行时用 `setSeriesLabelText(...)` 改单点、`updateSeries({"label": ...})` 改整体系列）、
  `line.stack` + `areaStyle.color`（渐变
  colorStops）、`barGap` / `barCategoryGap`、`emphasis` / `blur`（命中项
  `emphasis.itemStyle.color`；未命中项只在 `emphasis.focus: "self"` 时按
  `blur.itemStyle.opacity` 淡化，`none`（默认）/ `series` 都不淡化其它项）、
  `silent`（跳过命中）、`animation`（系列级关闭动画）、`id`（合并匹配键）。
- **坐标轴键**：`type`（`category` / `value` / `log` / **`time`**）、`logBase`、`position`
  （`bottom` / `top` / `left` / `right`）、`offset`、`boundaryGap` / `inverse` /
  `scale` / `nameLocation` / `nameGap` / `interval` / `minInterval` /
  `maxInterval` / `splitNumber` / `axisLabel`（`show` / `interval` / `rotate` /
  `formatter`（模板或 `callable(value, index)`，category 轴同样生效）/ `color` /
  `fontSize`）/ `axisTick` / `axisLine` / `splitLine` /
  `splitArea`；运行时用 `setAxisLabelFormatter(...)` / `setCategoryLabels(...)` /
  `updateAxis(...)`，不要为了改一条轴而重写整个轴数组；`grid` 支持 `show` / `containLabel` / `borderColor` /
  `borderWidth` / `backgroundColor`。`xAxis` / `yAxis` 可传数组，系列用
  `xAxisIndex` / `yAxisIndex` 选轴（索引 0 默认左/下，其他默认右/上）。
- **折线 / 散点模式**：`mode: "lines" | "markers" | "lines+markers"`（Plotly 语义）。
  `line` 默认 `lines`（不画点）、`scatter` 默认 `markers`；`showSymbol: true`
  兼容为 `lines+markers`，`showSymbol: false` / 默认都是纯线。
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
| **采样统计** | `LineSeriesRenderer.samplingStats()` → `{"dataLen", "drawn", "sampled"}`（原始点数 / 实际绘制点数 / 是否降采样）；宿主做状态栏 / 诊断时用它，别读 `_data_len` / `_points` 私有字段 |

实测（1400×800，离屏；2026-10-18 在「窗口快路径 + 连续副本 + 采样 LRU」之后重测）：折线 1M 帧 **9.4ms**、category 1M 9.4ms、散点 1M 9.4ms；悬停 0.8ms。**同窗口重复缩放**（缓存命中）≈ 一帧 + 映射；**进入新窗口**（真实重采样）折线 1M ≈12ms、category ≈20ms、散点 ≈38ms；**缩回全景** 折线 ≈33ms、category ≈45ms。冲击 / 振动形态（显式时间戳 + 记录中断）：**单通道 5M** 帧 3.0ms、新窗口 8.3ms、缩回全景 10.4ms；**三通道 3×2M** 帧 6.4ms、新窗口 19.2ms。复跑：`tools/perf/bench_charts.py`（`zoom新窗口` / `缩回全景` 两列专门覆盖缓存效应）。

### Plotly 对齐的交互 / 数据 API

| API / option | 对应 Plotly | 说明 |
|---|---|---|
| `resetView()`、`setDoubleClickReset(True)` | `doubleClick: 'reset'` | 双击复位全部 dataZoom 窗口 + 漫游 / 缩放（默认开，可关） |
| `zoomStep(factor)` | 模式条 zoom in / out | `<1` 放大、`>1` 缩小，围绕窗口中心，最小 0.5% |
| `setDragMode("pan"/"zoom"/"select"/"lasso")` | `dragmode` | `zoom` = 拖拽框选即缩放（**同时缩放 XY**）；`select` / `lasso` = 框选 / 套索选择（结果走 `brushChanged`）。**拖拽与点击共存**：即使 dataZoom / brush 占用了按下，原地松开（位移 ≤4px）仍发 `itemClicked`，真拖拽不会误发 |
| `setDragMode("zoom")` 的选框 | `dragmode: 'zoom'` 的框选缩放 | 选框是**一次性手势**：松手缩放落地后自动消失（不留选中集）；`select` / `lasso` 则保留选框与选中集，点绘图区外收框（`brushComponent().clear()` 也可手工收） |
| `setWheelZoomEnabled(True)`、`wheelZoomEnabled()` | `config.scrollZoom` + `dragmode: 'zoom'` | **默认开**：直角坐标图**滚轮缩放 + 左键框选缩放**，两者都**同时作用于 XY**（自动挂一个 `inside` 组件；`setDragMode("pan")` 可切回按住拖动平移）；`setDragMode("zoom"/"select"/"lasso")` 把拖拽让给刷选。option 里自己配了 `dataZoom` 则完全听用户的，本开关不再插手；显式配置 `brush` 而未调 `setDragMode` 时默认 `select`（框选数据） |
| `toolbox.buttonWidget(name)` | 模式条按钮句柄 | 工具条按钮是**真实 `ElaIconButton` 子控件**（Ela 图标字体 + 主题配色，不再是自绘小图标）；导出 PNG / SVG 时自动隐藏（导出的是图，不是 UI） |
| `brush: {"type": "lasso"}`、`brushComponent()` | lasso select | 套索轨迹多边形命中（`QPolygonF.containsPoint`），`selected` 信号给 `[{series, dataIndex, value, x}]` |
| `tooltip.hitRadius`（或 `hoverdistance`） | `hoverdistance` | 命中半径 px，默认 10；折线 / 散点共用 |
| `hoveranywhere` / `clickanywhere`（或 `tooltip.hoverAnywhere`） | 同名 | 空区也出提示 / 发 `itemClicked`，载荷带 `componentType:"grid"` 与数据坐标 |
| `tooltip.order: "valueAsc"/"valueDesc"`（兼容 `hoversort` 文案） | `hoversort` | `trigger: "axis"` 的联合提示按值排序 |
| `series.connectNulls` | `connectgaps` | 断点不切段（默认切开） |
| `saveImage("x.svg")` / `saveImage(format="svg")` / `getDataURL({"type": "svg"})` | 模式条导出 SVG | 走 `QSvgGenerator` 的同一绘制链（矢量图元 + 位图符号内嵌） |
| `toolbox.feature` | 模式条按钮 | `saveAsImage` / **`saveAsSvg`** / `dataZoom` / `restore` / **`zoomIn`** / **`zoomOut`** |
| 图例悬停 | 悬停图例高亮 trace | 指针压在图例条目上时该系列正常绘制、其余降到 35% 不透明度；提示框让位 |

---

## 多轴 / log / 标注编辑（2026-10）

### 多轴

```python
chart.setOption({
    "xAxis": [
        {"type": "category", "data": months},
        {"type": "category", "data": quarters, "position": "top"},
    ],
    "yAxis": [
        {"type": "value", "name": "销量"},
        {"type": "log", "position": "right", "name": "访问量"},
    ],
    "series": [
        {"type": "line", "data": sales},
        {"type": "line", "yAxisIndex": 1, "data": visits},
    ],
})
```

- `xAxis` / `yAxis` 接受单个 dict 或数组；`series.xAxisIndex` / `series.yAxisIndex` 选轴。
- 索引 0 默认左 / 下，索引 ≥1 默认右 / 上；显式 `position` 优先，同侧多轴可用 `offset` 外扩。
- 右侧 Y / 顶部 X 的标签与轴名会自动预留边距；副轴 `splitLine` 默认关闭（显式 `splitLine.show: true` 可开）。
- `dataZoom.xAxisIndex` 可指定要缩放的一条或多条 X 轴（缺省 = 全部）；显式 `dataZoom` 要缩放 Y 轴需给 `yAxisIndex`。自动挂的滚轮 / 框选组件默认**同时缩放 XY**，`dispatchAction` 可用扩展键 `yStart` / `yEnd` 写 Y 窗口；`dataZoom.yZoom: false` 可禁用交互式 Y 缩放。
- `convertToPixel` / `convertFromPixel` / `containPixel` 的 finder 支持 `{"xAxisIndex": 1}` / `{"yAxisIndex": 1}`。

### log 轴

- `type: "log"`，`logBase` 默认 10；X / Y 均可。
- 只接受正值：非正值数据点跳过（线断开、柱跳过）；全非正时回退默认量级并保持可绘制。
- 刻度按数量级生成；跨度不足两个数量级时补 1 / 2 / 5 子刻度；`<1e-4` 或 `>=1e6` 的标签用 `1e-5` / `1e6` 形式。
- `dataZoom` 在对数空间插值（50% 窗口 = 几何中点）；柱 / 面积基线落在 `axis.vmin`（绘图区底边）。

### 标注 / 数据点标签双击编辑

- `markPoint` / `markLine` 的标签，以及系列 `label.show: true` 画出的**数据点标签**，双击都能进入行内编辑：Enter / 失焦提交，Esc 取消。数据点标签目前覆盖折线 / 散点 / 柱状（其它系列可后续按同一 `_label_rects` 协议接入）。
- 数据点标签编辑结果写入 `series.labelTexts[str(dataIndex)]`（不改 `data` 形状，百万点系列仍走 numpy / LOD 快路径）；空字符串删除覆盖、恢复默认数值文案。
- 标注提交回写 `data[i].name` 并重建，发 `annotationEdited` 信号。
- `setAnnotationEditingEnabled(False)` 关闭内置编辑器；此时只发 `annotationEditRequested`，宿主可自行弹框并调用 `setAnnotationText(...)` / `setSeriesLabelText(...)` 提交。
- 单个系列可用 `label.editable: false` 关闭该系列的数据点标签编辑。
- 双击非标签区域仍是原来的 `resetView()`。

---

## 2026-10 交互补齐（axis tooltip / 选中态 / 时间轴 / 联动）

| 能力 | 说明 |
|---|---|
| **数值轴联合提示** | `tooltip.trigger: "axis"` 在 `xAxis.type: "value"` / `"time"` 上按「每条系列最近的 x」聚合（`SeriesRenderer.nearestIndexAt`），不再只支持 category；每条系列画命中点 marker，`axisPointer.label` 在轴上显示数值气泡 |
| **axisPointer 语义** | 默认 `line`；只有 axis 触发才画（item 触发不画）；`axisPointer.snap`（category auto=true / value auto=false）已接入 |
| **选中态** | `series.selectedMode: false/single/multiple`、`select.itemStyle`、`data[i].selected`、`series.selectedMap`；点击 / `dispatchAction(select/unselect/toggleSelect)` / `selectchanged`；`getOption()` 回写 `selectedMap` |
| **悬停事件** | `on("mouseover"/"mouseout"/"mousemove"/"globalout", handler)`；`emphasis.focus: "self"` 淡化同系列其它项（默认 `none` 不淡化）、`"series"` + `blurScope` 淡化其它系列 |
| **光标反馈** | 数据 / 图例 = 手型；zoom / select / lasso = 十字；pan = 手型抓取；slider 把手 = 左右箭头 |
| **图例分页** | 条目自动换行（最多 3 行，`legend.maxRows` 可调）；`legend.type: "scroll"` 单行分页（‹ › + 页码） |
| **缩放状态保留** | `setOption` / `appendData` 不再把用户窗口打回 option 初始值；`getOption()` 返回实时 `dataZoom.start/end` 与 `legend.selected`；`notMerge` 才复位 |
| **时间轴** | `xAxis.type: "time"`：日期字符串 / `datetime` / 毫秒时间戳；自动时间刻度（秒→年）与标签；`min/max` 接受日期字符串；tooltip 标题按日期显示 |
| **折线专项** | `endLabel`、`smoothMonotone`、`step: [start, end]`、`areaStyle.origin`、`symbolRotate`、`showAllSymbol`、`lineStyle.opacity/cap/join`；`stackStrategy` 默认 `samesign`（正负分开堆叠）。**堆叠按 x / 类别值对齐**（不是数组下标），两条系列的 x 顺序不同也不会错位 |
| **mark 扩展** | `markLine.data[].coord` 任意两点、`lineStyle`、`symbol`；`markPoint.symbol/symbolSize`；`markArea.data[].coord` |
| **跨图联动** | `chart.setGroup(name)` + `connectCharts(name)`：dataZoom、图例选择、axis tooltip 同步；`disconnectCharts(name)` 断开 |
| **工具条** | `magicType`（折线/柱状/堆叠循环）、`saveAsImage` / `saveAsSvg` / `dataZoom` / `restore` / `zoomIn` / `zoomOut` |
