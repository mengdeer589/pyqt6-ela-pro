# 图表 API 规范

图表家族（`ElaChartWidget` / `ElaPlotWidget` / `ElaFigureCanvas` / `ElaDashboardGauge`）
统一 **camelCase** 命名；`ElaChartWidget` 的实例接口与 **ECharts 对齐**，
配置 / 控制 / 事件三层如下。

覆盖状态与缺口见 [charts-coverage.md](charts-coverage.md)。

**模块分工**：`core/` = 主控件 / option 合并 / 绘制 / 查询 / 事件；`axes/` = 坐标与轴模型；`components/` = 标注 / markPoint 等组件；`interact/` = dataZoom / brush / visualMap / timeline / toolbox；`series_cartesian/` 与 `series_hierarchy/` = 系列渲染器；`layout.py` / `interaction.py` / `exporter.py` = 布局 / 宿主交互 / 导出。

**Option 模型**：`charts/models.py` 只保留薄 `OptionModel`（dict + `snake_case` 属性访问），不再为每个 option 键维护 dataclass 字段：

```python
from pyqt6_ela_pro.charts import ChartOption, AxisOption, OptionModel, SeriesOption

chart.setOption(ChartOption(
    animation=False,
    x_axis=AxisOption(type="category", data=["A", "B"]),
    y_axis=AxisOption(type="value"),
    series=[
        SeriesOption(
            type="bar",
            name="营收",
            data=[120, 180],
            item_style=OptionModel(color="color.primary"),
        )
    ],
))
```

`setOption(dict)` 同样可用；`getOption()` 返回 `ChartOption`（`series` / 轴为 `SeriesOption` / `AxisOption`），`getOptionDict()` 返回普通 dict。嵌套样式直接使用 `OptionModel` 或普通 dict。

**配置与查询**

| 方法 | 说明 |
|---|---|
| `setOption(option, notMerge=False, lazyUpdate=False)` | 设置 option；**同时接受 `ChartOption` 与 dict**（dict 在入口转薄模型）。默认合并语义与 ECharts 一致：`series` / `dataZoom` / `graphic` 等按 `id` / `name` / 下标逐项合并，其余 list 整体替换。`notMerge=True` 全量替换、重置图例选择与 dataZoom 窗口；`lazyUpdate=True` 延迟到下一事件循环重建。返回 self |
| `updateAxis(axis, patch, axisIndex=0)` | 只更新一条轴（深合并；`axis` = `"x"` / `"y"` / `"single"`），其余轴原样保留。多轴场景改轴标签 / 刻度 / 样式用它，别手写整个轴数组。`radar` 不支持（维度在 `series.indicator`，且本库不读顶层 `radar` 组件） |
| `setAxisLabelStyle(axis, *, fontSize=None, fontWeight=None, bold=None, color=None, fontFamily=None, fontStyle=None, align=None, verticalAlign=None, rotate=None, margin=None, axisIndex=0)` | 轴刻度标签样式（只改传入的键；`axis` = `"x"` / `"y"` / `"single"` / `"both"`）。`bold=True` 是 `fontWeight=700` 的糖；`align="auto"` / `verticalAlign="auto"` 恢复默认。轴不存在 / 参数非法 / 没有任何键时返回 `False` 且不写入（`both` 为原子操作，缺一条轴就不写） |
| `axisLabelStyle(axis, axisIndex=0)` | 该轴标签的实际样式（含默认值）：`fontSize` / `fontWeight` / `fontFamily` / `fontStyle` / `color` / `align` / `verticalAlign` / `margin` / `rotate` |
| `updateSeries(patch, *, seriesIndex/seriesName/seriesId)` | 只更新一个系列（按 `id` → `name` → 下标定位，深合并）；保留用户缩放窗口 |
| `setAxisLabelFormatter(axis, formatter, axisIndex=0)` | 设置轴标签 formatter（字符串模板或 `callable(value, index)`；**index 是刻度下标**） |
| `setCategoryLabels(labels, axisIndex=0)` | 替换类目轴标签列表，保留该轴其它 option 与缩放窗口 |
| `setFontFamily(family)` / `fontFamily()` | 全图字体族（**单个族名**；`None` 恢复系统默认）。逗号列表取第一个并告警 —— Win7 上多族列表会走逐字形族匹配的慢 shaping 并毒化后续文本。组件级 `textStyle.fontFamily` / `axisLabel.fontFamily` / `label.fontFamily` 可覆盖 |
| `getOption()` / `getOptionDict()` | 当前 option 深拷贝：`getOption()` 返回 `ChartOption`（同时支持 dict 下标；`series` / 轴为薄模型），`getOptionDict()` 返回普通 ECharts dict |
| `validateOption(option)` | 校验模型 / dict option，返回 `list[OptionIssue]`（未知系列类型等） |
| `seriesItems(seriesName, *, seriesIndex/seriesId)` | 系列全部数据项 → `list[SeriesItem]` |
| `itemAt(seriesName, index, *, seriesIndex/seriesId)` | 按统一 dataIndex 取数据项 → `SeriesItem` |
| `labelRects(seriesName, *, seriesIndex/seriesId)` | 当前数据标签命中框 → `list[LabelHit]` |
| `hitTestAll(pos)` | 光标下全部命中项 → `list[HitResult]`（组件优先，其次系列） |
| `seriesRenderers` / `coords` / `components` | 渲染器 / 坐标系 / 组件实例列表（属性） |
| `palette()` / `colorForSeries(series)` | 当前调色板 / 指定系列主色（默认取图表主题色板，`option["color"]` 优先） |
| `setChartTheme(name)` / `chartTheme()` | 切换 / 读取图表配色主题（内置或已注册；`None` / `""` 恢复全局默认）。切换会失效布局 / 调色板 / 系列层位图缓存并重绘 |
| `chartThemes()` / `defaultChartTheme()` / `setDefaultChartTheme(name)` | 主题列表 / 默认主题 / 设置默认主题（只影响之后新建的图表） |
| `registerChartTheme(name, palette=None, palette_dark=None, light=None, dark=None)` / `unregisterChartTheme(name)` / `chartThemeSpec(name)` | 注册 / 注销 / 读取主题定义（`ela` 不可注销） |
| `registerColormap(name, colors)` / `colormapNames()` / `colormapColors(name)` | 注册 / 查询 `image` 系列的色带（内置 viridis / plasma / inferno / magma / cividis / gray / hot / coolwarm / jet） |
| `registerMap(name, geojson)` / `unregisterMap(name)` / `mapNames()` | 注册 / 注销 / 查询 GeoJSON 地图（FeatureCollection / Feature / Polygon / MultiPolygon；支持孔洞）。`map` 系列用 `"map": name` 引用；投影取 `geo.projection` / `series.projection`（`equirectangular` 默认 / `mercator`） |
| `primaryCoord()` / `coordFor(seriesOpt)` | 主坐标系 / 按系列解析坐标系 |
| `hitItem(pos)` / `hoverInfo()` | 坐标 → ECharts click params / 当前悬停命中 |
| `convertToPixel(finder, value)` / `convertFromPixel(finder, value)` / `containPixel(finder, value)` | 数据 ↔ 像素换算与命中判定（finder：`"grid"` / `{"seriesIndex": 0}` 等） |
| `getWidth()` / `getHeight()` / `getDevicePixelRatio()` | 尺寸查询 |
| `preferredHeight(seriesIndex=None, rowHeight=26, padding=88)` | 系列建议高度（甘特按展示行数算；无实现时返回当前高度） |

**控制**

| 方法 | 说明 |
|---|---|
| `resize(opts=None)` / `resize(w, h)` | 重排；dict 形式 `{"width":…, "height":…}`，也兼容 QWidget 两参数 |
| `dispatchAction(payload)` | `legendToggleSelect` / `legendSelect` / `legendUnSelect` / `legendAllSelect` / `legendInverseSelect` / `dataZoom`（`start/end` 或 `startValue/endValue`）/ `restore` / `showTip` / `hideTip` / `highlight` / `downplay` / `select` / `unselect` / `toggleSelect`（`seriesIndex`/`seriesName` + `dataIndex`）/ `timelineChange` / `timelinePlayChange`；返回是否识别 |
| `setInteractive(bool)` / `interactiveEnabled()` | 交互总开关（静态化整图）。**打开 = 全开**：置 `True` 会清空逐项开关的覆盖（之前 `setInteractionEnabled` 关掉的项一并复位）；关闭期间逐项覆盖保留 |
| `setAnnotationEditingEnabled(bool)` / `annotationEditingEnabled()` | 标注标签双击行内编辑开关（默认开）；关闭后只发 `annotationEditRequested`，宿主自行弹框并可调 `setAnnotationText` 提交 |
| `setAnnotationText(seriesName, componentType, dataIndex, text)` | 修改 `markPoint` / `markLine` / `markArea` 的 `data[i].name` 或 `annotations[i].text`，重建并发出 `annotationEdited`；`seriesName` 为空时取第一个匹配组件（annotations 按同层数组下标） |
| `setSeriesLabelText(seriesName="", dataIndex=0, text="", *, seriesIndex=None, seriesId=None)` | 修改某个数据点的标签文本（写入 `series.labelTexts[str(index)]`），空字符串 = 恢复默认数值文案；系列可按 `seriesId` → `seriesName` → `seriesIndex` 寻址（都为空取首个可见系列）；默认只失效系列层位图并重绘，发出 `annotationEdited`（`componentType="seriesLabel"`） |
| `seriesLabelTexts(seriesName="", *, seriesIndex=None, seriesId=None)` / `clearSeriesLabelTexts(...)` | 读取 / 清空某系列的全部数据点标签覆盖 |
| `setInteractionEnabled(feature, bool)` / `isInteractionEnabled(feature)` | 逐项开关：`tooltip` / `legend` / `dataZoom` / `brush` / `timeline` / `toolbox` / `annotations` / `gantt` |
| `showLoading(type="default", opts=None)` / `hideLoading()` / `isLoading` | 加载遮罩（`text` / `color` / `textColor` / `maskColor` / `fontSize` / `showSpinner` / `spinnerRadius` / `lineWidth`） |
| `appendData({"seriesIndex"|"seriesName"|"seriesId", "data": …})` | 追加数据点（**原地增量**：不重建渲染器 / 组件，保留轴窗口；数值数组仍有一次 O(n) 物化） |
| `pushData(series, points, maxPoints=None)` / `setDataWindow(series, data, maxPoints=None)` / `streamLength(series)` | 流式数据：`series` 可为名称 / `id` / 下标；内部 `DataRing` 环形窗口，只保留最后 `maxPoints` 点。适合 line / scatter / image 实时波形；`setOption` 替换系列后流窗口自动重新初始化 |
| `setGroup(name)` / `connectCharts(group)` / `disconnectCharts(group)` | 图表组跨图联动（dataZoom / legend / axis tooltip / universalTransition）；`axisPointer.link: False` 可断开单图的 axis tooltip 联动；`connectCharts` 从包顶层导入 |
| `toggleMagicType()` | 折线 → 柱状 → 堆叠柱状 → 折线循环（toolbox 的 `magicType` 按钮调用） |
| `setEmptyText(text)` / `emptyText()` / `setErrorText(text)` / `errorText()` | 空态 / 错误态占位文案（画布中心；空数据时显示空态，错误态优先并带虚线框）。`""` 关闭 |
| `setHighContrast(bool)` / `highContrast()` | 高对比度辅助模式：空态 / 错误态文字改用主文本色 |
| `setKeyboardShortcutsEnabled(bool)` / `keyboardShortcutsEnabled()` | 键盘辅助开关。默认开：`Home` / `Ctrl+0` 重置视图，`+` / `-` 缩放，`L` 反选图例，`Esc` 关闭提示 |
| `saveImage(path=None, *, format=None, quality=None, scale=None, multiPage=False)` | 文件版导出 PNG / JPEG / SVG / **PDF**（按 `format` 或扩展名判定；`path=None` 弹保存对话框）。PNG / JPEG 支持 `scale`（`pixelRatio`）与 JPEG `quality`；PDF 单页 / `multiPage=True` 纵向分页。底色规则同上（JPEG / PDF 自动压到主题底） |
| `printChart(printer=None, *, multiPage=False)` | 打印当前图表；`printer=None` 时弹系统打印对话框，也可传 `QPrinter` 静默打印。`multiPage=True` 对长图按纵向分页。返回是否完成 |
| `previewPrint(printer=None)` | 系统打印预览（`QPrintPreviewDialog`）。 |
| `getDataURL(opts=None)` | 导出 `data:` URL：`type` = `"png"` / `"jpeg"` / `"jpg"` / `"svg"` / `"pdf"`，另有 `pixelRatio` / `scale` / `quality` / `multiPage` / `backgroundColor` |
| `clear()` | 清空（等价 `setOption({}, notMerge=True)`） |
| `dispose()` / `isDisposed()` | 销毁（停定时器 / 断主题 / deleteLater）与状态查询。**销毁后再调用 `setOption` / `getOption` / `dispatchAction` / `appendData` / `resize` / 导出等公开 API 会抛 `RuntimeError`**（ECharts 语义） |

**`ElaGanttView`（甘特滚动容器）**：`setOption` / `setRowHeight` / `scrollToRow` /
`topRow` / `visibleRows` / `refresh` / `chart()` / `setChartTheme`；
`ganttTaskChanged` 直接转发内嵌图表信号。详见甘特章节。

**事件**

`on(eventName, handler)` 的 handler 接收 **`ChartEvent`（薄 dict 模型）**；它同时实现 dict / `Mapping` 访问，所以旧代码的 `params["dataIndex"]` / `params.get("seriesName")` 仍然可用。Qt 信号 `itemClicked` / `annotation*` / `gantt*` 同样传 `ChartEvent`（信号签名改为 `object`）；`event.as_dict()` 可转普通 dict。

ECharts 事件名经 `on(eventName, handler)` / `off(eventName=None, handler=None)`
注册（handler 收 `ChartEvent`，异常被吞掉并告警，不会终止进程）：

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
| `annotationEditRequested`（Qt 信号） | `{seriesName, componentType, dataIndex, text}` | 双击 `markPoint` / `markLine` / `markArea` 标签，或双击可拖动标注（`componentType="annotations"`） |
| `annotationEdited`（Qt 信号） | `{seriesName, componentType, dataIndex, text}` | 标签 / 可拖动标注编辑提交 |
| `annotationDragged`（Qt 信号） | `{index, id, name, componentType, seriesName, text, x, y, ax, ay}` | 可拖动标注拖动结束（`index` 是同层 `annotations` 数组下标） |
| `ganttTaskChanged`（Qt 信号） | `{series, seriesIndex, dataIndex, name, mode, start, end, prevStart, prevEnd, startText, endText}` | 甘特任务条拖动结束（`mode`: `move` / `resize-start` / `resize-end`） |

同时保留 Qt 信号（宿主可直接 connect）：`legendToggled(str, bool)` /
`dataZoomChanged(float, float)` / `timelineChanged(int)` / `itemClicked(object)` /
`toolboxTriggered(str)` / `brushChanged(list)` / `annotationDragged(object)` /
`ganttTaskChanged(object)` / `finished()`。参数为 `ChartEvent`（兼容 dict 访问）。

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
    def paint(self, p, animT): ...   # 颜色经 chartToken("color.primary", self.chart) 取主题令牌

registerSeries("myType", MySeries)   # 同名覆盖会告警
```

> 自定义系列若自己驱动逐帧动效（QTimer + 相位），**每帧必须
> `self.requestSeriesRepaint()`**：只 `chart.update()` 会贴回系列层位图
> （相位不在缓存键里），表现为「只有鼠标移动时动效才动」。

**数据格式**（与系列 `data` 一致）：`number` / `[x, y]` / `[x, y, value]` /
`{"value": [...], "tooltip": {"formatter": "自定义文案"}, "itemStyle": {"color": "#..."}, ...}`；
坐标系由 `coordinateSystem` 声明（缺省 `grid`，可选 `polar` / `singleAxis` / `calendar` / `geo`）。
`series.colorBy: "data"` 时按数据项索引取全局调色板，而不是整条系列同色。`series.selectedMap` / `series.selected` 可作为选中态初值；`series.realtimeSort` 会按值重排单图 bar 的类目轴与数据。
`image` 系列例外：`data` 是 2D 标量矩阵或 3D RGB(A)，见下文「矩阵图像（imshow）」。

**数据集（`dataset` / `encode` / `transform`）**

`dataset.source` 支持二维数组（首行字符串自动当表头，或用 `sourceHeader` / `dimensions` 显式声明）与对象数组。`series.encode` 用维度名或下标映射 `x` / `y` / `value` / `itemName` / `seriesName`；`seriesName` 会把一份模板拆成多条系列。`seriesLayoutBy: "column"` 按列拆系列（列名作系列名，首列作类目），`"row"` 按行拆系列（行首作系列名，表头作类目）。

```python
chart.setOption({
    "dataset": {
        "source": [
            ["month", "sales", "cost"],
            ["Jan", 120, 80], ["Feb", 180, 90],
        ],
        "transform": [
            {"type": "filter", "dimension": "sales", "gt": 100},
            {"type": "sort", "dimension": "sales", "order": "desc"},
        ],
    },
    "xAxis": {"type": "category"},
    "yAxis": {"type": "value"},
    "series": [
        {"type": "bar", "encode": {"x": "month", "y": "sales"}},
        {"type": "line", "encode": {"x": 0, "y": 2}},
    ],
})
```

`transform` 只做安全的内置算子：`filter`（`eq` / `ne` / `gt` / `gte` / `lt` / `lte` / `in` / `notIn`）、`sort`（`dimension` / `order`）、`aggregate`（`groupBy` / `dimension` / `method` = `sum` / `avg` / `min` / `max` / `count`）。未知算子告警一次后跳过；不执行任意代码。

**流式数据**

```python
chart.setOption({
    "xAxis": {"type": "value", "min": 0, "max": 20},
    "yAxis": {"type": "value", "min": -1, "max": 1},
    "series": [{"type": "line", "name": "wave", "data": []}],
})
chart.pushData("wave", [[0.0, 0.2], [0.1, 0.5]], maxPoints=2000)
chart.setDataWindow("wave", points, maxPoints=2000)
```

`DataRing` 只追加 / 淘汰窗口外的点，`getOption` 会保留窗口对象；`pushData` 只刷新坐标系范围与 dataZoom 窗口，不重建组件 / 渲染器，也不复制整窗数据。10 万点 / 1 万点窗口的本机基准与跑法见 `docs/charts-stream-bench.md`。

**标记区间（`markArea`）**

`markArea.data` 每项是两端点对（`{"xAxis"}` / `{"yAxis"}` / `{"coord"}`）；支持组件级与端点级 `itemStyle`（`color` / `opacity` / `borderColor` / `borderWidth`）和 `label`（`show` / `text` / `position` / 字号颜色）。`silent=True` 关闭背景命中。支持 `grid` / `singleAxis` / `polar`（环形扇区）/ `calendar`（日期区间）；标签可双击编辑。

**富文本标签**

`label` 新增 `backgroundColor` / `borderColor` / `borderWidth` / `borderRadius` / `padding`（数字或 `[t, r, b, l]`），以及 `label.rich` 的 `{style|text}` 分段：

```python
"label": {
    "show": True,
    "formatter": "{name|华东}{value| 320}",
    "backgroundColor": "#fff4e5",
    "borderColor": "#f0b35b",
    "borderWidth": 1,
    "borderRadius": 4,
    "padding": [2, 6],
    "rich": {
        "name": {"color": "#8a5a00", "fontSize": 11},
        "value": {"color": "#c0392b", "fontSize": 14, "fontWeight": 700},
    },
}
```

富文本已接入 bar / line / scatter / candlestick / boxplot / heatmap / gantt / pie / funnel / tree / treemap / sunburst / map，以及轴标签、图例、title。每个 rich 分段也支持自己的 `backgroundColor` / `borderColor` / `borderWidth`。`labelLayout.hideOverlap: True` 跳过与已画标签相交的标签；`labelLayout.moveOverlap: "shiftY"` / `"shiftX"` 先尝试避让。pie 外侧标签支持 `labelLine.show` / `length` / `length2` / `lineStyle`。

**GeoJSON 地图**

```python
from pyqt6_ela_pro.charts import registerMap, unregisterMap

registerMap("my-region", geojson)   # FeatureCollection / MultiPolygon 均可
chart.setOption({
    "geo": {"projection": "mercator"},
    "series": [{"type": "map", "map": "my-region", "data": [{"name": "A", "value": 3}]}],
})
```

区域名取 `properties.name` / `NAME` / `Name` / `id`；Polygon 的第一个 ring 为外环，后续 ring 为孔洞，MultiPolygon 的多个岛用奇偶填充规则合并。`geo.regions` 仍可传 `{名称: [[x, y], ...]}` 或 `{名称: [ring, ...]}`。

顶层 `geo` 会创建独立 `GeoCoord`：`scatter` / `effectScatter` / `lines` 用 `coordinateSystem: "geo"` 即可叠加到地图上；`geoIndex` 选择多个 geo 中的某一个，`geo` 数组支持 `left` / `top` / `right` / `bottom` / `width` / `height` 定位。`geo.roam` 支持滚轮缩放与拖拽平移，`geo.label.show` 显示区域名，区域支持 hover、`selectedMode` 选中与跨 180° 经线。

`map` 系列与顶层 `geo` 同图时不重复画底图：显式 `series.geoIndex`，或 `series.map` 与 `geo.map` 同名即自动复用 `GeoCoord` 的路径。此时底图 / 区域 hover / select / roam 都归 `geo`，`map` 系列只叠加有数据区域的着色；`series.label.show` 未显式设置时不再叠一层标签。`geo.label.show` 的标签在系列着色之后绘制，未显式给 `label.color` 时按实际底色自动选深 / 浅字色。

**图形元素**

`graphic` 支持 `circle` / `rect` / `text` / `line` / `group`。`left` / `top`（或 `right` / `bottom`）接受像素、`"center"` / `"middle"`、`"N%"`；`group.children` 的坐标相对 group，`left` / `top` 定位 group 基点，`rotation` / `origin` / `scale` / `scaleX` / `scaleY` 作用于整组，`z` 决定组内与顶层绘制顺序。`silent` 只影响命中（graphic 本身不参与交互）。

**交互细节**

- `tooltip.axisPointer.type = "line" / "shadow" / "cross" / "none"`，跨图轴提示由 `setGroup` + `connectCharts` 联动；`axisPointer.link: False` 可断开单图。`axisPointer.link: "all"` 或 `[{"xAxisIndex": [0, 1]}]` / `[{"yAxisIndex": [0, 1]}]` 在同图内联动多条同类轴：主指针之外再画联动轴的指示线，tooltip 仍合并所有系列。
- `tooltip.confine`：`True` 时越界翻转 / 收敛到图表内；`False` 时保持鼠标右侧偏移，超出画布由控件裁剪。`tooltip.enterable` 时鼠标可进入浮层，进入后暂停跟随。
- `dataZoom` 支持 `zoomLock` / `minValueSpan` / `maxValueSpan` / `minSpan` / `maxSpan`；`brushSelect`（默认 `True`）控制 slider 轨道能否拖出新窗口，`False` 时轨道只显示，手柄仍可拖动。
- graph 支持 `edgeSymbol: ["none", "arrow"]` / `edgeSymbolSize: [4, 8]`，箭头随边方向旋转。

**渐进渲染与形变过渡**

- `progressive` / `progressiveThreshold` / `progressiveChunkMode`：数据量超过阈值后按帧预算补画；line / bar / scatter 逐点分帧，其它系列按系列层补齐。`progressiveChunkMode` 支持 `sequential` / `mod`（mod 跨数据均匀取样）。导出 / 打印会临时关闭渐进，保证一次画完整。
- `universalTransition`：同一图表内系列形态切换时过渡；bar / line / scatter 做位置、尺寸、颜色插值，其它类型或类型变化时旧系列层交叉淡出。`{enabled, duration}` 可配。
- 跨图 `universalTransition`：同组图表（`setGroup` + `connectCharts`）都启用 `universalTransition` 时，源图更新前把旧几何按数据项 `id` → `name` → 下标编码广播；目标图把归一化位置映射到自己的绘图区，bar / scatter 按 key 匹配做位置 / 尺寸 / 颜色形变，line 按点序形变，其它类型缩放淡出源图截图。目标图未启用或不同组时不接收。

**键盘与可访问性**

`setAccessibleName` / `setAccessibleDescription` 走 Qt 原生接口；默认名称为“图表”，描述里列出系列与快捷键；键盘焦点时绘制焦点框。`setKeyboardShortcutsEnabled(False)` 可整体关闭。

**主题 × 系列能力矩阵（示例工作台）**

`pyqt6_ela_pro.example.charts_page` 的「主题」工作区新增 23 系列 × 7 主题矩阵：单个自绘控件只画视口内的行，底部五个圆点依次表示数据标签 / visualMap / 选中 / 图例项 / 极坐标支持；点击格子打开对应完整示例。

**文字样式（字号 / 颜色 / 字重）**

`title.text` 支持 `title.link`，点击标题文字打开对应 URL。  
每个文字组件都接受 ECharts 标准键，**未设置的键回退顶层 `textStyle`**。
填充色上的数据标签（bar inside / heatmap / pie / funnel / treemap / sunburst /
map / gantt）在没有显式 `label.color` 时：**实色填充按填充色选黑 / 白**，
**半透明填充跟随主题文字色**（流带 / 半透明色块在暗色主题上不选黑字）。
显式 `label.color`（数据项 → 系列 → 顶层 `textStyle`）优先。

```python
chart.setOption({
    "textStyle": {"fontSize": 13, "color": "#555"},          # 全图默认（只含外观键）
    "legend": {"textStyle": {"fontSize": 15, "fontWeight": 600}},
    "title": {"textStyle": {"fontWeight": "bold"}, "subtextStyle": {"color": "#888"}},
    "tooltip": {"textStyle": {"fontSize": 12}},
    "xAxis": {"axisLabel": {"fontSize": 12, "fontWeight": 600}},
    "series": [{"type": "line", "label": {"show": True, "fontSize": 11}}],
})

# 轴标签专用接口（等价于写 xAxis.axisLabel / yAxis.axisLabel）
chart.setAxisLabelStyle("x", fontSize=12, bold=True, color="#c0392b", margin=8)
chart.setAxisLabelStyle("y", align="center")      # y 轴标签在列内水平居中
chart.setAxisLabelStyle("both", fontFamily="Microsoft YaHei")  # x + y 一次改
```

- 顶层 `textStyle` 是**兜底**：`fontSize` / `fontWeight` / `fontFamily` /
  `fontStyle` / `color` 五个键参与，组件自己的同名键优先；`show` / `formatter`
  这类行为键**不会**被合并（写 `{"textStyle": {"show": True}}` 不会打开所有
  数据点标签）。
- **轴标签默认对齐（直角坐标，ECharts 语义）**：x 轴标签**水平居中于刻度**；y 轴标签
  **垂直居中于刻度线**、水平方向贴轴（左侧轴右对齐、右侧轴左对齐 —— 不同位数
  的数字保持个位贴近轴线）。需要 y 轴标签在标签列内水平居中时用
  `chart.setAxisLabelStyle("y", align="center")`，`align="auto"` 恢复默认；
  `axisLabel.align` / `verticalAlign` / `margin` 也可直接写在 option 里。
  标签与轴线的默认间距为 x 轴 5px / y 轴 6px，可用 `margin` 调整。
- **轴标签样式统一入口**：`chart.setAxisLabelStyle("x", fontSize=13, bold=True,
  color="#c0392b")`（`axis="both"` 同时改 x / y；`axisIndex` 针对多轴）。
  `bold` 优先于 `fontWeight`；`fontWeight="bold"` 与数字等价。读取实际值用
  `chart.axisLabelStyle("x")`（含默认对齐 / 间距，不是原始 option 片段）。
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
- `dataZoom.filterMode` 支持 `"filter"` / `"weakFilter"` / `"empty"` / `"none"`：
  本库**不物理删除系列数据**（类目轴用 `_all_categories` + `windowOffset` 保留
  全局下标），模式只决定类目轴的取样方式 —— `"filter"` / `"weakFilter"` 按
  类目序号严格取样（类目中心落在窗口外就整项剔除），`"weakFilter"` 对跨窗口
  的多值数据项同样保留（本库不删数据，天然满足）；`"none"` 按 band 取样
  （与窗口相交的半格类目保留）；`"empty"` 同 `"filter"`，但零宽窗口不再吸附
  到最近类目，轴清空、图表留白。连续数值轴在各模式下都只改显示范围。

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

**配色主题（`setChartTheme` / 自定义注册）**

主题 = 分类色板（浅 / 深两档）+ 一组语义颜色槽位；每个图表实例可独立切换。
**几何在所有主题间统一为 Ela / Fluent 风格**（默认隐藏轴线与刻度、浅色分割线、
圆角柱、圆点图例、8px 圆角提示框），主题只决定色板与明暗表面。默认主题 `ela`
直接跟随 Ela 明暗主题。内置 7 套：

| 主题 | 系列色板 | 明暗外观 | 色带 |
|---|---|---|---|
| `ela` | Ela / Fluent 9 色（浅 / 深两档） | 跟随 `eTheme` | `primary.subtle → primary`（随明暗重算） |
| `echarts` | ECharts 9 色 + 暗色档 | 白底 / 官方暗紫底 | ECharts 蓝黄红 + 暗色档 |
| `matlab` | MATLAB 7 色 + 暗色档 | 白底 / 深灰底 | parula + 暗色档 |
| `plotly` | Plotly 10 色 + 暗色档 | 白底 / `#111` | viridis + 暗色档 |
| `ggplot2` | hue 10 色 + 暗色档 | 白底 / 深灰底 | 蓝渐变 + 暗色档 |
| `seaborn` | deep 10 色 + 暗色档 | 白底 / 深灰底 | 蓝渐变 + 暗色档 |
| `tableau` | Tableau 10 色 + 暗色档 | 白底 / 深灰底 | 蓝渐变 + 暗色档 |

所有内置主题都提供暗色数据色：`palette_dark`、`dark.color.ramp` 与
`success` / `warning` / `danger` 的暗色变体，按暗底对比度提升并固化；
切换明暗档时分类图、连续色带、K 线涨跌色和语义色都会变化。自定义主题仍可
只写 `palette`，此时明暗两档共用同一套数据色。

```python
from pyqt6_ela_pro.charts import (
    ElaChartWidget, chartThemes, registerChartTheme, setDefaultChartTheme,
)

chart = ElaChartWidget(parent)
chart.setChartTheme("matlab")        # 实例级；None / "" 恢复默认
chart.chartTheme()                   # -> "matlab"

setDefaultChartTheme("plotly")       # 只影响之后新建的图表
chartThemes()                        # ["ela", "echarts", ...]

registerChartTheme(
    "brand",
    palette=["#0b6e99", "#e08a1e", "#7a5ea8"],
    palette_dark=["#4cc2ff", "#ffb86b", "#c4a7e7"],
    light={"color.bg.base": "#ffffff", "color.text.primary": "#1f2328"},
    dark={"color.bg.base": "#15181e", "color.text.primary": "#f0f6fc"},
)
chart.setChartTheme("brand")
```

- 槽位键：`color.bg.base` / `color.bg.elevated` / `color.bg.muted` /
  `color.border` / `color.border.strong` / `color.text.primary` /
  `color.text.secondary` / `color.text.tertiary` / `color.text.disabled` /
  `color.primary` / `color.success` / `color.warning` / `color.danger` /
  `color.ramp`（色带，至少 2 色）。未写的槽位回退 `ela`（eTheme），**不跨
  明暗档借用** —— 只写色板也能在明暗两档下保持可读。
- 系列色板：内置主题全部提供 `palette` + `palette_dark`；自定义主题的
  `palette_dark` 可选，未写则两档共用 `palette`（`ela` 内置两套 Fluent 色板）。
- 用户颜色入口统一支持 `color.*` 令牌：`option.color` / `series.color` /
  `backgroundColor` / `itemStyle.*` / `lineStyle.*` / `label.*` / 轴 / 日历 /
  dataZoom / loading / tooltip / legend / visualMap / timeline。
- 优先级：`option` 显式颜色 / 宽度 / `show`（`color` / `series.color` /
  `itemStyle.color` / `backgroundColor` / 组件 `textStyle`）> 图表主题 > eTheme。
- 几何默认值（轴线 / 刻度 / splitLine / 图例 / 标题 / 提示框 / 柱角 / 折线 /
  dataZoom / visualMap）由 `charts/_style.py` 统一提供，不属于主题，自定义主题
  同样复用；显式 option 仍逐项覆盖。
- 色带作用于 `visualMap` / 直角与日历 `heatmap` / `image` / `map` 的默认
  配色；显式 `visualMap.inRange.colors` / `series.cmap` 仍优先。未写
  `color.ramp` 时按 `color.primary.subtle`（不透明画布底 + 12% 主色）→
  `color.primary` 生成 —— 暗色档的低端是深色底，不是白色。
- `registerChartTheme` 严格校验：主题名、色板非空、颜色可解析、槽位键合法、
  `color.ramp` ≥ 2 色；同名注册会合并未给的段（只改 dark 不会丢 light）。
- `unregisterChartTheme` 可移除自定义 / 非 `ela` 内置主题；移除当前默认
  主题会回落到 `ela`。
- 扩展自定义系列时用 `chartToken("color.primary", self.chart)` 取主题色；
  漏传 `chart` 会退回全局默认主题。`color.ramp` 是多色带，不是标量令牌，
  用 `chartThemeSpec(name)[variant]["color.ramp"]` 读取。
- 工具条按钮是上游 `ElaIconButton`（图标色由 Ela 主题控制），不随图表配色主题变化；
  其余画布内容（背景 / 轴 / 网格 / 图例 / 标题 / tooltip / 组件 / 系列）都跟随主题。
- 示例工作台顶部「全局主题」下拉框切换**整页**图表（新建工作区继承；主题工作区的
  7 张对比图固定展示、不参与）；「主题」工作区的「本区主题」只改两张演示图，
  演示实例级 `setChartTheme`。

**ECharts 兼容要点**

- **配色**：默认系列色板为 Ela / Fluent 9 色（浅 / 深两档，暗色自动切
  `palette_dark`），可用顶层 `"color": [...]` 覆盖；图表主题（`setChartTheme`）
  提供系列色板与背景 / 文字 / 轴 / 网格 / 提示框默认值，系列
  `itemStyle.color` / 数据项 `itemStyle.color` 逐级优先。几何由
  `charts/_style.py` 统一（Ela 风格，不随主题变化）。所有颜色字符串都接受
  `#rgb` / `#rrggbb` / 具名色 / `rgb()` / `rgba()`（`QColor` 不认后两者，
  库内统一过 `_colors.parse_color`）。
- **雷达**：维度定义支持顶层 `radar.indicator`（ECharts 写法）与
  `series.indicator`（系列优先）；`center` / `radius` 同理（百分比相对内容区
  短边的一半），`axisName` 只在会顶出内容区时收窄半径。
- **地图**：`label.show`（默认 **True**，与 ECharts 的默认关闭不同）/
  `color` / `fontSize` / `fontWeight`；未给 `color` 时：实色区域按底色亮度选
  黑 / 白字，半透明区域跟随主题文字色（饼 / 漏斗 / 旭日 / 树图 / 甘特的内嵌
  标签同一策略）。
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
  `outOfRange.color`（缺省中性色）。色带作用于 `map` / 直角与日历 `heatmap` /
  **`image`（矩阵图像）**、**`scatter`（气泡图按值上色）**，以及
  `bar` / `pie` / `funnel` / `boxplot` / `candlestick` / `parallel` 的数据项：
  取值维度由 `visualMap.dimension` 指定，缺省用数据最后一维（`[x, y, value]`
  即 value）；`seriesIndex` / `seriesId` 可把色带绑定到指定系列，数据项自己的
  `itemStyle.color` 优先级高于映射。
- **日历 + visualMap**：横向连续色带贴在日期网格底部（约 10px），纵向连续色带对齐网格顶部，
  分段色块同理；不再钉在画布边缘。全年日历 `cellSize: "auto"` 被宽度限制时不会出现大段空白；
  网格撑满高度时回退到底部 / 右侧条带。
- **矩阵图像（imshow）**：`series.type: "image"`。`data` 支持 `M×N` 标量矩阵
  （list / numpy ndarray）与 `M×N×3/4` RGB(A)（整数按 0–255、浮点按 0–1）。
  `extent: [left, right, bottom, top]` 缺省 `[-0.5, N-0.5, -0.5, M-0.5]`；
  `origin: "upper"`（默认，第 0 行在顶部）/ `"lower"`。纯 image 的 value 轴
  直接固定在 `extent`（图像铺满绘图区、不向 nice 刻度外扩），与其他系列混用时
  取并集。`cmap` 收内置色带名（`viridis` / `plasma` / `inferno` / `magma` /
  `cividis` / `gray` / `hot` / `coolwarm` / `jet`，宿主可用
  `registerColormap(name, colors)` 注册）或颜色列表；**有 `visualMap` 时色带以
  它为准**（显式 `inRange.colors` 优先；未给且绑定到 image 时自动采用该系列的
  `cmap`，色条与图像一致；连续色带生效，`piecewise` 分段目前只影响色条显示）。
  范围优先级：
  `vmin` / `vmax` → `visualMap.min/max` → 数据有限值范围。
  `interpolation: "nearest"`（默认）/ `"bilinear"`；`aspect: "auto"`（默认，铺满
  绘图区）/ `"equal"`（1:1 数据像素，自动 letterbox 居中）；NaN / inf 透明。
  tooltip 用 `trigger: "item"`（返回行、列、值 / RGB 色；圆点颜色取该点的
  实际 LUT / RGB 渲染色）；dataZoom 与滚轮缩放
  自动裁切图像。超过 1600 万格时按整数步长降采样显示（悬停仍按原矩阵取值）。
  复数矩阵会被拒绝（先 `np.abs(...)` / `np.real(...)`）；`updateSeries` 换数据
  会重建 QImage，缩放 / 平移不会。本机实测（900×500、float64）：`512×4096`
  约 35 ms/次、`1024×8192` 约 134 ms/次（固定 `vmin/vmax` 约 118 ms），超大矩阵
  建议先在 worker 里降采样。可运行示例：`example/charts_page.py` 的「小波」工作区。
- **饼图半径与外侧标签**：`radius` 百分比相对内容区短边的一半（ECharts 语义），
  不再预留固定边距；外侧标签同侧按 y 排开，引线 + 半行文字会顶出内容区时
  自动收窄半径（最多压到一半，避免遮住图例）。
- **饼图 / 漏斗百分比模板**：`label.formatter` 与 `tooltip.formatter` 里的
  `{d}` / `percent` 都是**百分数本身**（不带 `%`），模板写 `"{b} {d}%"`；
  默认标签 / 默认 tooltip 仍自动带 `%`。回调参数里的 `percent` 同样是数值
  （如 `42` 或 `42.5`），不是 `"42%"`。
- **环形饼中心总计**：`totalLabel` 支持 `show` / `text` / `fontSize` / `fontWeight` /
  `fontFamily` / `fontStyle` / `color` / `subtextFontSize` / `subtextFontWeight` /
  `subtextFontStyle` / `subtextColor`；字号默认按内半径自适应（12–22px），
  不再固定 `font.title.md`，小环形图不会被大数字撑满中心孔。
- **仪表盘中心数值**：`gauge.detail.fontSize` 显式优先；默认同样随表盘半径
  自适应（12–22px），不再固定 17px。
- **dataZoom**：`textStyle`（滑块两端文案）、`zoomLock`（锁定窗口大小，滚轮
  不缩放、仍可平移）、`filterMode`（`"filter"` / `"weakFilter"` / `"empty"` /
  `"none"`，见上）。
- **轴名**：`xAxis` / `yAxis` 的 `nameGap` 与 `nameTextStyle`（`color` /
  `fontSize` / `fontWeight`）生效。
- **通用键**：`itemStyle`（`color` / `opacity` / `borderColor` / `borderWidth` /
  `borderRadius`）、`label`（`show` / `formatter` 模板或回调 /
  `fontSize` / `color` / `position`；直角系列 + 饼图 / 漏斗图 / 热力图的
  `show: true` 数据点标签可双击编辑，
  编辑结果存 `series.labelTexts[str(index)]`，`label.editable: false` 可关；
  运行时用 `setSeriesLabelText(...)` 改单点、`updateSeries({"label": ...})` 改整体系列）、
  `line.stack` + `areaStyle.color`（渐变
  colorStops）、`barGap` / `barCategoryGap`、`emphasis` / `blur`（命中项
  `emphasis.itemStyle.color`；未命中项只在 `emphasis.focus: "self"` 时按
  `blur.itemStyle.opacity` 淡化，`none`（默认）/ `series` 都不淡化其它项）、
  `silent`（跳过命中）、`animation`（系列级关闭动画）、`id`（合并匹配键）。
- **平行坐标配色**（`parallel`）：每条数据线按行序号取调色板色（ECharts 语义）；
  系列 `lineStyle.color` 统一覆盖全部，`data[i].lineStyle.color` 覆盖单行。
- **逐项颜色与命中同源**：`pictorialBar` / `boxplot` 按数据项 `itemStyle`、
  `candlestick` 按 `itemStyle.color` / `color0`、`lines` 按 `data[i].lineStyle.color`
  着色；命中 / tooltip 圆点取的就是绘制时那一份颜色。
- **层级系列默认配色**（`treemap` / `sunburst` / `tree`）：按「第一个能分出支的
  层级」取调色板色 —— 单根包装（`根 → A/B/C`）会下潜到 `A/B/C`，不会整图
  只有一种颜色；多根数据仍按根分行。子级同色相逐级提亮。嵌套节点的
  `itemStyle`（`color` / `opacity` / `borderColor` / `borderWidth`）逐项覆盖。
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

**可运行示例**：`example/charts_page.py`（概览 / 系列画廊 / 交互 / 大数据 / 高级 / 主题 / 小波 / 实时八个工作区；小波页为滚动矩阵 + 固定 cmap + 主题外框切换；实时页为 1 kHz / 1M 环形缓冲 + 2000 显示点 / 10 Hz）；`ElaChartWidget` 的能力速览（23 系列 / 交互 / 大数据 / 主题）见 README「核心能力」。

---

## 甘特图（`series.type: "gantt"`）

用于工作计划 / 研发排期：任务条、进度覆盖、里程碑、依赖箭头、今天线、基线 / 截止日期、关键路径和拖动改期。

### 坐标系

```python
{
    "xAxis": {"type": "time"},          # 或 "value"（数值工期）
    # 必须；data 省略时按 data[].name 自动生成。
    # inverse: True 让第一行在顶部（ECharts 类目轴默认 0 在底部）。
    "yAxis": {"type": "category", "inverse": True},
    "series": [{
        "type": "gantt",
        "name": "研发计划",
        "data": [
            {"name": "需求梳理", "start": "2026-11-02", "end": "2026-11-06",
             "progress": 1.0},
            {"name": "方案设计", "start": "2026-11-05", "end": "2026-11-09",
             "progress": 0.9, "dependencies": ["需求梳理"]},
            {"name": "上线评审", "start": "2026-11-27", "milestone": True},
        ],
    }],
}
```

- `start` / `end` 支持 `date` / `datetime` / ISO 字符串 / 毫秒时间戳；`end` 缺省 = 里程碑。
- 区间按半开区间 `[start, end)` 绘制，`end` 与 `start` 相等时画菱形。
- `data` 支持 `{"name","start","end","progress","milestone","dependencies"}`、
  `[start, end]` / `[start, end, progress]`、`{"value": [start, end, progress]}`。
- x 轴范围自动包含任务的 `start` / `end`、`baseline` 两端与 `deadline`，
  基线 / 截止日期不会被轴范围裁掉。
- **状态色**：数据项可给 `status: "done"`，系列用 `statusColors` 映射到
  **主题令牌**（如 `"color.primary"` / `"color.warning"`）或普通颜色字符串；
  主题切换时按令牌重新解析，不会像写死 `itemStyle.color` 那样停在旧颜色。
  优先级：项 `itemStyle.color` > `statusColors[status]` > 系列 `itemStyle.color` > 调色板。
- 图表只按 `data` 顺序画任务行；**分组 / 折叠 / 汇总行由宿主自己决定**
  （可用 `yAxis.data` 排序、分成多个系列 / 多张图，或在外层列表里折叠）。
- `yAxis.data` 显式给定时按给定顺序排列；省略时从 `data[].name` 自动生成，
  但**任一条目缺 `name` 就整轴跳过自动生成**（此时必须显式给 `yAxis.data`）。
- 类目轴沿用 ECharts 语义：0 在底部。工作计划一般加 `yAxis.inverse: True`
  让第一行在顶部；此时任务条、轴标签、axis tooltip 会一起翻转。
- 长任务名需要 `grid.left` 留白（或 `grid.containLabel: true`）；`xAxis.type: "log"` /
  类目 x 轴不支持，`yAxis` 非 `category` 时整系列跳过并告警。

### 任务选项

| 键 | 说明 |
|---|---|
| `barWidth` | 行高占比（0~1）或像素；默认行高的 60% |
| `progress` | `{"show": True, "editable": False, "step": 0.01, "color": None, "baseColor": None, "baseOpacity": 0.35}`；数据项 `progress` 取 0~1（>1 且 ≤100 按百分比）；`editable` 开启后拖任务条上方圆点改进度；`baseColor=None` 时底轨用条色，设为 `color.border.strong` 等令牌可换成中性底轨 |
| `baseline` | `{"show": True, "color": None, "height": 3, "opacity": 0.55, "overdueColor": None}`；数据项 `baseline: {start, end}` 或 `[start, end]`，画在任务条下方的细基线，实际结束超出时尾段用 overdueColor |
| `deadline` | `{"show": True, "color": None, "overdueColor": None}`；数据项 `deadline` 支持日期 / datetime / ISO / 毫秒；未完成且结束晚于截止时旗标标红 |
| `criticalPath` | `{"show": False, "color": None, "width": 1.5, "arrows": True}`；单系列内按 finish-to-start 依赖找**最长依赖链**（按工期累加，不把日期空隙算浮动），关键任务加描边、关键箭头用危险色 |
| `milestone` | `{"symbolSize": 12}`；数据项 `milestone: true` 或只给 `start` 时画菱形 |
| `dependencies` | `{"show": True, "color": None, "width": 1}`；数据项 `dependencies: ["前置任务名"]`，可跨甘特系列按名查找 |
| `todayLine` | `{"show": False, "date": None, "color": None, "label": "今天"}`；`date` 缺省取当前时间，测试 / 演示建议固定 |
| `weekend` | `{"show": False, "color": None, "opacity": 0.55}`；时间轴周六 / 周日底纹（默认关） |
| `rowStripe` | 交替行底纹，默认 `False`；需要密集任务分带时再开 |
| `label` | 标准标签键：`show` / `position`（`inside` / `left` / `right`）/ `formatter`；`{b}` 是任务名，`{c}` 也是任务名 |
| `editable` | 默认 `False`；开启后左键拖动任务条整体平移，拖动左右 6px 边缘拉伸 |
| `snap` | 时间轴默认 `"day"`（吸附本地午夜）；也支持 `"hour"` / 毫秒步长 / `False` |
| `statusColors` | `{"done": "color.primary", "doing": "color.warning"}`；值支持主题令牌 / 普通颜色；颜色自带 alpha 会与 `itemStyle.opacity` / `progress.baseOpacity` 相乘，不会被覆盖 |

多个甘特系列共用一张图时，`todayLine` 只在一个系列上开（否则同一位置会画多条）。

`criticalPath` v1 只在**单个甘特系列内**、按 **finish-to-start** 依赖计算：把任务工期沿依赖链累加，取最长的一条作为关键链（日期之间的空隙不算浮动）；跨系列依赖忽略并告警，成环时跳过。需要严格 CPM 的日期 slack 时，由宿主在数据层计算后写 `criticalPath` 或自行标注。

### 拖动改期

- **按下优先级**：`annotations` → 可拖动系列（甘特）→ `dataZoom` / `brush` → 其它系列。
  因此默认 `inside` 缩放开着时，拖任务条不会误触平移；拖空白绘图区仍然平移 / 框选。
- 拖动范围**钳制在按下时的轴窗口内**，不会一边拖一边改轴范围；松手也不重排全图，
  视图保持拖动前的位置。
- 数据写回保持原类型：原来是 `"2026-11-02"` 仍写日期字符串，原来是 `datetime`
  仍写 `datetime`，原来是毫秒数仍写数字；进度 / 依赖 / 颜色等其它字段不变。
- 松手发 `ganttTaskChanged(dict)`；`setInteractionEnabled("gantt", False)` 可整体关闭拖动。

```python
chart.ganttTaskChanged.connect(lambda p: print(p["name"], p["startText"], p["endText"]))
# {"series","seriesIndex","dataIndex","name","mode":"move|resize-start|resize-end",
#  "start","end","prevStart","prevEnd","startText","endText"}
```

`mode` 为 `move` / `resize-start` / `resize-end`；`start` / `end` 是毫秒时间戳
（或数值轴上的数值），`startText` / `endText` 是格式化文案。

### 任务交互信号

```python
chart.ganttTaskClicked.connect(lambda p: ...)              # 单击
chart.ganttTaskDoubleClicked.connect(lambda p: ...)        # 双击；不再触发 resetView
chart.ganttTaskContextMenuRequested.connect(lambda p: ...) # 右键；带 pos / globalPos
chart.ganttProgressChanged.connect(lambda p: ...)          # 进度拖动结束
```

载荷包含 `series / seriesIndex / dataIndex / name / status / start / end /
progress / startText / endText / progressText / overdue / critical`；
有 `baseline` / `deadline` 时还会带对应文本。`ElaGanttView` 原样转发这四类信号。

- 进度手柄画在任务条上方，不占用两端拉伸的命中区；拖动按 `step` 吸附。
- `progress.editable` 与 `editable` 相互独立：只开进度拖动时任务条不能整体平移 / 拉伸。
- 双击任务会抑制默认的 `resetView()`；双击空白区域仍复位视图。

### 视图工具条 / 缩放

```python
view.setToolbarVisible(True)      # 默认隐藏；显示 日 / 周 / 月 / 今天 / 适应行高
view.setScale("day")              # day = 14 天，week = 8 周，month = 6 个月
view.goToToday()                  # 保持当前窗口跨度，把今天放到中心
view.fitRows()                    # 按可见高度反推行高（最低 20px）
view.showFullRange()              # 横向恢复全量范围
view.scale() / view.toolbarVisible() / view.topRow() / view.visibleRows()
```

`setScale` / `goToToday` 走 `dataZoom` 的 x 窗口，纵向滚动只改 y 窗口，不会把
横向缩放重置。只支持 `xAxis.type: "time"` 的甘特图。

### 任务很多时（几十 / 上百行）

- **行高优先**：每行建议 ≥24~28px。40 行约需 **1000~1200px** 高度；
  600px 高度下 40 行只剩 13px/行，`axisLabel` 会自动隔行
  （`interval: "auto"`），任务条也会压得很薄。
- 用 `chart.preferredHeight()` 按当前展示行数算建议高度
  （默认 `rowHeight=26` / `padding=88`）：

  ```python
  chart.setFixedHeight(chart.preferredHeight())          # 40 行 ≈ 1128px
  chart.setFixedHeight(chart.preferredHeight(rowHeight=28, padding=96))
  ```

- **`ElaGanttView`**：固定 x 轴、右侧纵向滚动条按行切换窗口，滚轮直接滚动任务行：

  ```python
  from pyqt6_ela_pro.charts import ElaGanttView

  view = ElaGanttView(parent)
  view.setRowHeight(28)          # 期望行高，默认 26
  view.setOption(option)         # option 里的 dataZoom 由容器接管
  view.chart().ganttTaskChanged.connect(...)
  view.ganttTaskChanged.connect(...)   # 容器也转发信号
  ```

  容器会把第一条 `dataZoom` 改成隐藏的 `inside` + `yAxisIndex: 0`，
  关闭滚轮缩放 / 拖拽平移，避免和纵向滚动冲突；横向缩放仍可用
  `dispatchAction({"type": "dataZoom", "start": ..., "end": ...})`。

- 想在小高度里显示全部行名：把 `yAxis.axisLabel.fontSize` 降到 10 左右，
  或显式 `axisLabel.interval: 0`（行高不足时会互相压字，不推荐）。
- `label.show: true` 时，条高不足以放进文字会**自动跳过 inside 标签**，
  避免压到相邻行；需要更小字号可配 `label.fontSize`。
- 固定一屏展示几十个任务时，用滚动容器，或由宿主按阶段拆成多张图 / 多个系列。
- 性能：几十到几百个任务是线性布局 + 线性绘制，不是瓶颈；依赖箭头按
  任务名 O(1) 查找。

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
| `toolbox.feature` | 模式条按钮 | `saveAsImage` / **`saveAsSvg`** / `dataZoom` / `restore` / **`zoomIn`** / **`zoomOut`** / `magicType` / `dataView` |
| 图例悬停 | 悬停图例高亮 trace | 系列名悬停时该系列正常绘制、其余降到 35% 不透明度；**饼 / 漏斗的图例条目是数据项名，只高亮对应扇区 / 层，不压暗整图**；提示框让位 |

---

## 实时数据（1 kHz / 百万点）

`ElaChartWidget` 适合做**显示层**，不适合直接把原始高频点每帧送进来：

```text
采集线程 → 1M 环形缓冲（numpy） → 窗口选择 → min/max 降采样（≤2000 点）
        → 5–10 Hz setOption → 图表
```

- `appendData()` 是增量接口，但每次仍要 **O(n) 物化 + 全量布局**；100k 点约
  40 ms/次，不适合 1 kHz 长期逐点追加；固定窗口 / 环形缓冲更稳。
- 1M 点只进环形缓冲，图表每帧只接收降采样后的几千点；min/max 保留尖峰。
- 开发机实测（2 系列）：1000/2000/5000 显示点更新 + 重绘约
  `12 / 20 / 36 ms` 每帧；1M → 4k 的 min/max 降采样约 `0.33 ms`。
- 采集与 UI 分离：采集线程只写缓冲，UI 定时器取快照；不要在 1 ms 定时器里碰控件。
- 动画关闭、`showSymbol=False`；实时窗口小可关闭 sampling。
- 完整示例见 `example/charts_page.py` 的「实时」工作区（1M 环形缓冲 /
  2000 显示点 / 10 Hz / 窗口 10 秒、60 秒、全量）。

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

- `markPoint` / `markLine` 的标签，以及系列 `label.show: true` 画出的**数据点标签**，双击都能进入行内编辑：Enter / 失焦提交，Esc 取消。数据点标签覆盖折线 / 散点 / 柱状 / 饼图 / 漏斗 / 树图 / 矩形树图 / 旭日图 / 关系图 / 桑基图 / 地图等写入 `_label_rects` 的系列。
- 数据点标签编辑结果写入 `series.labelTexts[str(dataIndex)]`（不改 `data` 形状，百万点系列仍走 numpy / LOD 快路径）；空字符串删除覆盖、恢复默认数值文案。
- 标注提交回写 `data[i].name` 并重建，发 `annotationEdited` 信号。
- 可拖动标注（`annotations`）双击文本框同样进入行内编辑，提交回写 `annotations[i].text`；多行文本在未改动时保留换行（内置编辑器是单行，改动后变为单行）。
- `setAnnotationEditingEnabled(False)` 关闭内置编辑器；此时只发 `annotationEditRequested`，宿主可自行弹框并调用 `setAnnotationText(...)` / `setSeriesLabelText(...)` 提交。
- 单个系列可用 `label.editable: false` 关闭该系列的数据点标签编辑。
- 双击非标签区域仍是原来的 `resetView()`。

### 可拖动标注（annotations）

```python
chart.setOption({
    "xAxis": {"type": "category", "data": ["1月", "2月", "3月"]},
    "yAxis": {"type": "value"},
    "series": [{"type": "line", "data": [120, 200, 150]}],
    "annotations": [
        {
            "id": "peak",
            "x": "2月", "y": 200,          # 箭头指向的数据坐标（category 可写类目名）
            "text": "峰值 200",
            "ax": 54, "ay": 36,           # 箭头尾部（文本框锚点）相对数据点的像素偏移
            "arrowcolor": "#e46a6a",
            "bordercolor": "#e46a6a",
        }
    ],
})
```

| 键 | 说明 |
|---|---|
| `x` / `y` | 箭头终点的数据坐标；category 轴接受类目名或下标 |
| `xref` / `yref` | `"x"` / `"x2"` / `"paper"`（paper：0 在左 / 下、1 在右 / 上） |
| `ax` / `ay` | 箭头尾部（文本框锚点）相对数据点的像素偏移（默认 `0` / `-40`，`showarrow: false` 时默认 `0` / `0`）；文本框再按 `xanchor` / `yanchor` 摆在尾部周围 |
| `text` | 纯文本，支持 `\n` 与 `<br>` 换行 |
| `showarrow` / `arrowhead` / `arrowcolor` / `arrowwidth` / `arrowsize` / `standoff` | 箭头开关 / 箭头样式（0 无、1 开放、2 实心三角、3 圆点）/ 颜色 / 线宽 / 大小 / 与文本框的间距 |
| `bgcolor` / `bordercolor` / `borderwidth` / `borderpad` / `borderRadius` | 文本框填充 / 描边 / 内边距 / 圆角（默认主题 elevated 底 + 1px 主题描边；`bgcolor: "none"` 透明） |
| `font` | `size` / `fontSize`、`family` / `fontFamily`、`fontWeight`、`fontStyle`、`color`；未设置的键回退顶层 `textStyle`；标注级 `color` 也可直接给 |
| `align` | 多行文本对齐：`left` / `center` / `right` |
| `xanchor` / `yanchor` | 文本框相对 `ax` / `ay` 尾部的位置：`left` / `center` / `right`、`top` / `middle` / `bottom`（默认居中） |
| `draggable` | 是否可拖动（默认 `true`） |
| `show` / `visible` | 为 `false` 时整条不画、不参与命中 |

- **箭头终点永远停在 `x` / `y` 的数据点上**：拖动只改 `ax` / `ay`（箭头尾部像素偏移），不会改数据坐标；缩放 / 平移 / resize 后按当前坐标系重新映射锚点。
- 只有**文本框**是拖动热区（箭头线不算）；按下文本框时吞掉数据点击，拖动结束不会补发 `itemClicked`。
- 拖动结束发 `annotationDragged`（载荷含最终 `ax` / `ay`，可直接持久化）；`setOption` 合并模式按 `id` → `name` → 下标逐项合并 `annotations`，**未显式重给的 `ax` / `ay` 会保留**。
- 双击文本框进入内置行内编辑（Enter / 失焦提交、Esc 取消），提交回写 `annotations[i].text` 并发 `annotationEdited`；`setAnnotationEditingEnabled(False)` 关闭内置编辑器时只发 `annotationEditRequested`，宿主可自行弹框后 `setOption` 提交。双击不会触发 `resetView()`。
- `setInteractionEnabled("annotations", False)` 关闭拖动与悬停反馈（绘制不变）。

---

## 2026-10 交互补齐（axis tooltip / 选中态 / 时间轴 / 联动）

| 能力 | 说明 |
|---|---|
| **数值轴联合提示** | `tooltip.trigger: "axis"` 在 `xAxis.type: "value"` / `"time"` 上按「每条系列最近的 x」聚合（`SeriesRenderer.nearestIndexAt`），不再只支持 category；每条系列画命中点 marker，`axisPointer.label` 在轴上显示数值气泡 |
| **横向柱 axis tooltip** | 类目在 `yAxis` 时按 `y_axis.invert(pos.y(), plot.top(), plot.bottom())` 取行（类目 0 在顶部），内容 / 标题随鼠标行变化；`axisPointer` 的 line / shadow / label 同样走 y 朝向（横向行指示线、行阴影带、左侧类目气泡） |
| **axis tooltip 区域** | 只在绘图区内显示；光标移到标题 / 图例 / 边距 / dataZoom 条带等绘图区外会立即收起，不会按最近的 x 停在原地 |
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

---

## 2026-11 统一绘制语义

- **选中态**：`selectedMode` / `select.itemStyle` / `data[i].selected` / `selectedMap` 已统一到 `SeriesRenderer.stateStyle`。支持图元级选中的系列：bar / pictorial / line / scatter / effectScatter / gantt / pie / funnel / map / heatmap / treemap / sunburst / graph / sankey / radar / tree / boxplot / candlestick / parallel / lines。themeRiver / image / gauge 没有离散数据图元，选中态按不适用处理。
- **hover / emphasis / blur**：命中项统一走 `emphasis.itemStyle`（color / opacity / borderColor / borderWidth）；非命中项统一走 `blur.itemStyle.opacity`。map / treemap / parallel / tree 不再硬编码提亮或淡化值。
- **itemStyle 通用键**：`color` / `opacity` / `borderColor` / `borderWidth` / `borderRadius` 由基类统一解析；树图 / 地图 / 关系图 / 箱线图 / K 线 / 平行坐标 / 桑基图已接入 opacity 与 border（形状不支持的字段文档标注不适用）。
- **主题令牌颜色**：`itemStyle.color`、`emphasis.itemStyle.color`、`select.itemStyle.color`、`label.color`、`borderColor`、`axisLabel.color`、`tooltip.backgroundColor` 等用户颜色入口支持 `color.*` 令牌；不再只有 Gantt `statusColors` 支持。
- **label**：全局默认色统一为 `labelColorFor()`（实色填充内部仍按黑 / 白对比；半透明填充跟随主题文字）。themeRiver / map / tree / treemap / sunburst / graph / sankey 支持 `label.formatter`（callable + 模板）；bar 支持 top / bottom / left / right / inside / insideTop / insideBottom / insideLeft / insideRight。
- **坐标系**：line = grid / polar；scatter = grid / singleAxis；heatmap = grid / calendar；bar = grid / polar；candlestick / boxplot = grid。非支持组合会 `warn_once` 后跳过，不再静默空白。
- **查询**：`valueAtIndex` 对没有专用几何的层级 / 关系系列按 data 项兜底返回 `{name, value, color, series, dataIndex}`。
- **visualMap**：除 map / heatmap / image / scatter 外，bar / pie / funnel / boxplot / candlestick / parallel 也按数据值取色；数据项自己的 `itemStyle.color` 优先。
- **关系图图例**：`graph.categories` 有名称时图例按分类展示（颜色取分类 `itemStyle.color`，缺省取调色板），隐藏分类会同时跳过节点、关联边与命中。
- **层级标签编辑**：tree / treemap / sunburst / graph / sankey / map 的标签默认显示，并写入 `_label_rects`；双击编辑与 `setSeriesLabelText(...)` 同样走 `series.labelTexts[str(dataIndex)]`，节点级 `label.text` / `label.formatter` 优先于系列 formatter。
- **系列动画**：`series.animationDuration` / `animationEasing`（过渡时 `animationDurationUpdate` / `animationEasingUpdate`）按系列独立映射；顶层动画时钟取所有系列最大时长并线性推进，组件仍使用顶层缓动后的进度。
- **组件令牌**：`visualMap`（色带 / 分段色 / 文本）与 `timeline`（轴线 / 节点 / 播放按钮 / 标签）的用户颜色同样支持 `color.*` 主题令牌。
- **主题覆盖**：23 种系列默认主数据色全部来自主题 `palette` / `palette_dark` 或 `color.ramp`；7 套内置主题均提供暗色 palette、暗色色带和暗色语义色，切明暗档时分类图、连续色带、K 线涨跌色与语义色都会变化。显式 `option.color` / `series.color` / `itemStyle.color` 等仍优先于主题。
- **层级索引域**：tree / treemap / sunburst 的 `hitTest`、`valueAtIndex`、`nameAtIndex`、`selectedIndices` 与 `data[i].selected` 统一使用**扁平节点下标**；选中集裁剪与 `dispatchAction(select)` 不再按顶层根数据长度丢弃子节点。
- **数据标签补齐**：boxplot / candlestick 新增 `label`（含 `formatter` / `position` / 双击编辑）；pictorialBar 继承 bar 的标签链；radar / themeRiver 的标签写入 `_label_rects` 并支持 `labelTexts` 编辑；radar formatter 额外提供 `dimensionIndex`。
- **状态链补齐**：pictorialBar 接回 `stateStyle`（hover / emphasis / select），gauge / themeRiver 新增 hover 强调；themeRiver 命中返回 `dataIndex`，图例悬停会高亮对应流带。
- **关系 / 层级交互**：graph 支持系列级与逐边 `lineStyle`（color / width / opacity / curveness）及节点 `symbol`；tree 支持 `roam`、`expandAndCollapse`、`initialTreeDepth`；sankey 支持 `draggable` 与 `nodeAlign`（justify / left / right）；treemap / sunburst 支持 `nodeClick: false` 关闭下钻。
- **visualMap 扩面**：line / radar / tree / treemap / sunburst / graph / sankey / lines / gauge / themeRiver / pictorialBar 也接入 visualMap；层级节点按 `node.value`、流带按末时刻值、飞线按段值映射。
- **动画补齐**：`animationDelay` / `animationDelayUpdate` / `animationThreshold` 已支持；全局时钟按「延迟 + 时长」最大值推进，超过阈值的数据量直接呈现终态。
- **标记与命中**：`markPoint` / `markLine` 支持 polar 与 singleAxis；`markLine` 的极坐标半径圆 / 角度射线与单轴竖线可绘制、可命中；image 的 `valueAtIndex` 与像素 `dataIndex` 对齐。
