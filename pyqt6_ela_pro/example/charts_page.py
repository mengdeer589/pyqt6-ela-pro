"""
[pyqt6_ela_pro] ElaChartWidget 图表引擎页面

页面分两块：

- **系列画廊（01-06）**：全部 21 种系列按能力分组，3 / 2 列紧凑网格并排陈列
  （折线 / 阶梯 / 柱状 → 数据点 → 分布与金融 → 占比与仪表 → 层级与关系 →
  特殊坐标），一屏能对比多种系列；每节一行「随机数据 / 交互开关」控制整节。
- **三个专题（07-09）**：大数据与采样（30 万点 + 滚轮缩放）、交互组件
  （tooltip / legend / dataZoom / visualMap / mark* / toolbox / timeline）、
  Plotly 对齐交互（双击复位 / dragmode / 套索 / 空区坐标 / SVG 导出）。

每节标题右侧的「</> 代码」按钮展示该节 demo 方法的源码（API 调用都写在方法体内，
不藏进 helper）；图表都是活的：滚轮缩放、拖拽、图例点击、刷选、导出 SVG 都可用。
"""

import math
import random
from datetime import date, timedelta

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QGridLayout, QHBoxLayout, QVBoxLayout
from PyQt6ElaWidgetTools import ElaText, ElaPushButton, ElaLineEdit, ElaCheckBox

from pyqt6_ela_pro import ElaChartWidget, ElaChip
from .base_page import ExamplePage

_WEEKS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

#: GitHub 绿 5 档色带（visualMap.inRange.colors 示例）
_GITHUB_GREENS = ["#ebedf0", "#9be9a8", "#40c463", "#30a14e", "#216e39"]


#: 画廊小图的紧凑绘图区（默认边距是按整宽大图定的，小格里太浪费）
_MINI_GRID = {"top": 28, "bottom": 24, "left": 44, "right": 14}


def _mini_grid(**extra) -> dict:
    grid = dict(_MINI_GRID)
    grid.update(extra)
    return grid


def _mini_legend(**extra) -> dict:
    """小图图例：字号 / 色块都收小，避免吃掉绘图区。"""
    legend = {
        "top": 2,
        "textStyle": {"fontSize": 10},
        "itemWidth": 14,
        "itemHeight": 8,
    }
    legend.update(extra)
    return legend


def _format_tokens(value: int) -> str:
    """Token 数值 → 中文单位（12345 → 1.2万）。"""
    if value >= 100_000_000:
        return f"{value / 100_000_000:.2f}亿"
    if value >= 10_000:
        return f"{value / 10_000:.1f}万"
    return str(value)


def _build_token_activity(year: int = 2026) -> list:
    """生成全年 Token 活动数据：[(date, tokens, rounds)]（确定性伪随机）。"""
    rows = []
    day = date(year, 1, 1)
    while day <= date(year, 12, 31):
        index = day.timetuple().tm_yday
        base = 12 + 10 * math.sin(index / 23.0) + 6 * math.sin(index / 7.0)
        if day.weekday() >= 5:
            base *= 0.35
        tokens = int(max(0.0, base) * 30000)
        if index % 13 == 0:
            tokens = 0
        rounds = max(1, int(base / 3))
        rows.append((day, tokens, rounds))
        day += timedelta(days=1)
    return rows


def _token_activity_series(rows: list, mode: str) -> list:
    """活动数据 → heatmap data（每日 / 每周汇总 / 累计）。

    - 绘图值用「万 tokens」为单位（视觉映射标签更紧凑），tooltip 显示完整单位；
    - weekly：按自然周（周日为一周起点）汇总，值放在该周周日格；
    - cumulative：前缀和（token 与轮数均累计）。
    """
    if mode == "weekly":
        weekly: dict = {}
        for day, tokens, rounds in rows:
            key = day - timedelta(days=(day.weekday() + 1) % 7)
            item = weekly.setdefault(key, [0, 0])
            item[0] += tokens
            item[1] += rounds
        return [
            {
                "value": [day.isoformat(), round(tokens / 10000, 2)],
                "tooltip": {
                    "formatter": f"{_format_tokens(tokens)} tokens · "
                    f"{rounds} 轮消息（本周合计）"
                },
            }
            for day, (tokens, rounds) in weekly.items()
        ]
    if mode == "cumulative":
        series = []
        total_tokens = total_rounds = 0
        for day, tokens, rounds in rows:
            total_tokens += tokens
            total_rounds += rounds
            series.append(
                {
                    "value": [day.isoformat(), round(total_tokens / 10000, 2)],
                    "tooltip": {
                        "formatter": (
                            f"{_format_tokens(total_tokens)} tokens · "
                            f"{total_rounds} 轮消息（累计）"
                        )
                    },
                }
            )
        return series
    return [
        {
            "value": [day.isoformat(), round(tokens / 10000, 2)],
            "tooltip": {
                "formatter": f"{_format_tokens(tokens)} tokens · {rounds} 轮消息"
            },
        }
        for day, tokens, rounds in rows
    ]


class ChartsPage(ExamplePage):
    """ElaChartWidget：ECharts 风格 setOption 数据驱动图表引擎"""

    PAGE_TITLE = "ElaChartWidget 图表引擎"

    def __init__(self, parent=None):
        super().__init__(parent)

    def _addDemoContent(self, main_layout):
        # 系列画廊（紧凑网格，一屏看清多种系列）
        self._demoGalleryCartesian(main_layout)
        main_layout.addSpacing(24)
        self._demoGalleryPoints(main_layout)
        main_layout.addSpacing(24)
        self._demoGalleryDistribution(main_layout)
        main_layout.addSpacing(24)
        self._demoGalleryProportion(main_layout)
        main_layout.addSpacing(24)
        self._demoGalleryHierarchy(main_layout)
        main_layout.addSpacing(24)
        self._demoGalleryCoordinates(main_layout)
        main_layout.addSpacing(28)
        # 三个专题
        self._demoBigData(main_layout)
        main_layout.addSpacing(24)
        self._demoInteractComponents(main_layout)
        main_layout.addSpacing(24)
        self._demoPlotlyInteractions(main_layout)

    # ── 图表容器 ────────────────────────────────────────────────────────

    def _chartTile(self, title, chart, stretch=1, controls=True):
        """带标题的图表容器（纵向：标题 + 图表 + 控制行）。"""
        tile = QVBoxLayout()
        tile.setSpacing(6)
        title_label = ElaText(title, self)
        title_label.setTextPixelSize(14)
        tile.addWidget(title_label, 0, Qt.AlignmentFlag.AlignLeft)
        tile.addWidget(chart, stretch)
        if controls:
            self._attachControls(tile, chart)
        return tile

    def _addChartWithControls(self, parent_layout, chart):
        """直接加入图表（无标题容器），底部带随机数据 / 交互开关控制行。"""
        box = QVBoxLayout()
        box.setSpacing(6)
        box.addWidget(chart)
        self._attachControls(box, chart)
        parent_layout.addLayout(box)

    def _attachControls(self, tile, chart):
        """为图表添加控制行：随机数据 + 鼠标交互开关。"""
        row = QHBoxLayout()
        row.setSpacing(8)
        rand_btn = ElaPushButton("随机数据", self)
        rand_btn.setFixedWidth(90)
        rand_btn.clicked.connect(lambda: self._onRandomChart(chart))
        row.addWidget(rand_btn)
        inter_on = chart.interactiveEnabled()
        inter_btn = ElaPushButton("交互: 开" if inter_on else "交互: 关", self)
        inter_btn.setFixedWidth(90)
        inter_btn.clicked.connect(lambda: self._toggleInteraction(chart, inter_btn))
        row.addWidget(inter_btn)
        row.addStretch()
        tile.addLayout(row)

    # ── 随机数据 ────────────────────────────────────────────────────────

    def _onRandomChart(self, chart):
        """按各系列类型随机化 data 并播放过渡插值动画（setOption 合并语义）。"""
        opt = chart.getOption()
        series = opt.get("series") or []
        for s in series:
            if isinstance(s, dict):
                self._randomizeSeries(s)
        chart.setOption({"series": series})

    def _randomizeSeries(self, s: dict) -> None:
        t = str(s.get("type") or "line")
        data = s.get("data")
        if not isinstance(data, list) or not data:
            return
        if t in ("pie", "funnel"):
            s["data"] = [
                {**d, "value": random.randint(10, 900)}
                if isinstance(d, dict)
                else random.randint(10, 900)
                for d in data
            ]
        elif t == "gauge":
            if isinstance(data[0], dict):
                lo = float(s.get("min") or 0)
                hi = float(s.get("max") or 100)
                s["data"] = [{**data[0], "value": random.uniform(lo, hi)}]
        elif t == "radar":
            for it in data:
                if isinstance(it, dict) and isinstance(it.get("value"), list):
                    it["value"] = [
                        random.randint(int(v * 0.3), max(1, int(v)))
                        for v in it["value"]
                    ]
        elif t == "candlestick":
            out = []
            for _ in data:
                o, c = random.randint(10, 50), random.randint(10, 50)
                out.append(
                    [
                        o,
                        c,
                        random.randint(1, max(1, min(o, c) - 1)),
                        random.randint(max(o, c) + 1, 60),
                    ]
                )
            s["data"] = out
        elif t == "boxplot":
            s["data"] = [sorted(random.randint(1, 30) for _ in range(5)) for _ in data]
        elif t == "map":
            for it in data:
                if isinstance(it, dict):
                    it["value"] = random.randint(1, 300)
        elif t == "themeRiver":
            s["data"] = [[d[0], random.randint(3, 20), d[2]] for d in data]
        elif t == "sankey":
            for lk in s.get("links") or []:
                if isinstance(lk, dict):
                    lk["value"] = random.randint(1, 8)
        elif t in ("sunburst", "treemap", "tree"):

            def walk(node):
                if isinstance(node, dict):
                    if "value" in node:
                        node["value"] = random.randint(5, 100)
                    for ch in node.get("children") or []:
                        walk(ch)

            for d in data:
                walk(d)
        elif t == "graph":
            for it in data:
                if isinstance(it, dict) and "symbolSize" in it:
                    it["symbolSize"] = random.randint(10, 30)
        elif t == "parallel":
            s["data"] = [
                [random.randint(1, 10) for _ in row]
                for row in data
                if isinstance(row, (list, tuple))
            ]
        elif t == "heatmap":
            out = []
            for d in data:
                if isinstance(d, dict):
                    # 日历热力的 {value: [日期, 值]}：形状认不出就原样留着
                    out.append(d)
                elif isinstance(d, (list, tuple)) and len(d) >= 2:
                    out.append([d[0], d[1], random.randint(0, 24)])
            if out:
                s["data"] = out
        elif t == "lines":
            # 线图数据是 {coords: [[x, y], [x, y]]}：按原坐标数量重新掷点
            out = []
            for item in data:
                coords = item.get("coords") if isinstance(item, dict) else None
                if not isinstance(coords, (list, tuple)) or len(coords) < 2:
                    continue
                out.append(
                    {
                        **item,
                        "coords": [
                            [random.randint(0, 10), random.randint(0, 10)]
                            for _ in coords
                        ],
                    }
                )
            if out:
                s["data"] = out
        elif isinstance(data[0], dict) and "value" in data[0]:
            s["data"] = [{**d, "value": random.randint(5, 100)} for d in data]
        elif isinstance(data[0], (list, tuple)):
            out = []
            for d in data:
                if (
                    isinstance(d, (list, tuple))
                    and len(d) >= 2
                    and all(isinstance(v, (int, float)) for v in d[:2])
                ):
                    out.append([d[0], random.randint(5, 100)] + list(d[2:]))
                else:
                    out.append(d)
            s["data"] = out
        elif all(
            isinstance(v, (int, float)) and not isinstance(v, bool) for v in data[:8]
        ):
            s["data"] = [random.randint(5, 100) for _ in data]
        # 认不出的结构化数据（自定义字段 / 新系列形状）保持原样 —— 别把形状换成数字

    # ── 鼠标交互开关 ────────────────────────────────────────────────────

    def _toggleInteraction(self, chart, btn):
        """切换鼠标交互（提示框 / 图例 / 缩放 / 刷选 / 时间轴 / 工具箱）。

        走 ``chart.setInteractive`` 总开关：数据与绘制不变，仅鼠标交互失效。
        **状态源是图表本身**（不是按钮文案）—— 曾经按文案取反，某个示例初始文案
        写反了，第一次点击就把交互关掉、文案还不变（表现成「交互坏了」）。
        **打开 = 全开**：总开关置 True 会清空逐功能覆盖，所以交互组件那节的
        逐功能勾选框要同步回勾上，否则界面与真实状态不符。
        """
        on = bool(chart.interactiveEnabled())
        chart.setInteractive(not on)
        btn.setText("交互: 关" if on else "交互: 开")
        if not on and chart is getattr(self, "_interactChart", None):
            for _key, box in getattr(self, "_feature_boxes", ()):
                box.setChecked(True)

    # ══ 系列画廊（紧凑网格：一屏看清多种系列）═══════════════════════════

    #: 画廊每格图表高度（网格里高度必须一致才能对齐）
    GALLERY_H = 232

    def _galleryChart(self, height: int = None) -> ElaChartWidget:
        """画廊里的一格图表（统一高度）。"""
        chart = ElaChartWidget(self)
        chart.setFixedHeight(int(height or self.GALLERY_H))
        return chart

    def _addGallery(self, parent_layout, tiles, columns: int = 3):
        """紧凑网格：``tiles = [(小标题, 图表), ...]``，列宽均分；返回图表列表。"""
        grid = QGridLayout()
        grid.setSpacing(10)
        row = col = 0
        for title, chart in tiles:
            tile = QVBoxLayout()
            tile.setSpacing(4)
            label = ElaText(title, self)
            label.setTextPixelSize(13)
            # ElaText 默认 wordWrap=True：标题一长就折行，而 sizeHint 可能按单行算
            # → 折行部分被裁掉。统一钉成两行高度：网格里所有格子等高、标题也完整。
            label.setFixedHeight(label.fontMetrics().height() * 2)
            tile.addWidget(label, 0, Qt.AlignmentFlag.AlignLeft)
            tile.addWidget(chart, 1)
            grid.addLayout(tile, row, col)
            col += 1
            if col >= columns:
                row, col = row + 1, 0
        parent_layout.addLayout(grid)
        return [chart for _title, chart in tiles]

    def _attachGalleryControls(self, parent_layout, charts):
        """画廊统一控制行：整节「随机数据」+ 整节交互开关。

        画廊一格只有 ~230px 高，逐图摆两个按钮会把画面淹掉，所以按节控制。
        """
        row = QHBoxLayout()
        row.setSpacing(8)
        rand_btn = ElaPushButton(f"随机数据（{len(charts)} 张）", self)
        rand_btn.setFixedWidth(132)
        rand_btn.clicked.connect(
            lambda: [self._onRandomChart(chart) for chart in charts]
        )
        row.addWidget(rand_btn)
        inter_btn = ElaPushButton("交互: 开", self)
        inter_btn.setFixedWidth(90)
        inter_btn.clicked.connect(
            lambda: self._toggleGalleryInteraction(charts, inter_btn)
        )
        row.addWidget(inter_btn)
        row.addStretch()
        parent_layout.addLayout(row)

    def _toggleGalleryInteraction(self, charts, btn):
        """整节交互开关：以第一张的状态为准，其余跟随（文案由 ``_toggleInteraction`` 维护）。"""
        if not charts:
            return
        self._toggleInteraction(charts[0], btn)
        state = charts[0].interactiveEnabled()
        for chart in charts[1:]:
            chart.setInteractive(state)

    # ── 01 画廊 · 直角坐标 ───────────────────────────────────────────────

    def _demoGalleryCartesian(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "01. 系列画廊 · 直角坐标（折线 / 阶梯 / 堆叠柱 / 横向柱 / 多线轨迹）",
                self._demoGalleryCartesian,
            )
        )
        self._addInfoText(
            "line：smooth 平滑 + areaStyle 面积 + lineStyle 虚线；step 画阶梯；"
            "同名 stack 自动堆叠、itemStyle.borderRadius 圆角；横向柱把类目放到 yAxis；"
            "lines 用坐标对画多段轨迹，effect 让亮点沿线流动",
            parent_layout,
        )
        tiles = []

        smooth_line = self._galleryChart()
        smooth_line.setOption(
            {
                "legend": _mini_legend(),
                "grid": _mini_grid(),
                "tooltip": {"trigger": "axis"},
                "xAxis": {"type": "category", "data": _WEEKS},
                "yAxis": {"type": "value"},
                "series": [
                    {
                        "type": "line",
                        "name": "自然流量",
                        "smooth": True,
                        "areaStyle": {"opacity": 0.18},
                        "data": [120, 132, 101, 134, 90, 230, 210],
                    },
                    {
                        "type": "line",
                        "name": "付费流量",
                        "smooth": True,
                        "areaStyle": {"opacity": 0.12},
                        "lineStyle": {"type": "dashed"},
                        "data": [150, 232, 201, 154, 190, 330, 410],
                    },
                ],
            }
        )
        tiles.append(("折线 · smooth + 面积（line）", smooth_line))

        step_line = self._galleryChart()
        step_line.setOption(
            {
                "legend": _mini_legend(),
                "grid": _mini_grid(),
                "tooltip": {"trigger": "axis"},
                "xAxis": {"type": "category", "data": ["08", "09", "10", "11", "12"]},
                "yAxis": {"type": "value"},
                "series": [
                    {
                        "type": "line",
                        "name": "入库",
                        "step": "middle",
                        "data": [120, 132, 101, 134, 90],
                    },
                    {
                        "type": "line",
                        "name": "出库",
                        "step": "middle",
                        "data": [220, 182, 191, 234, 290],
                    },
                ],
            }
        )
        tiles.append(("阶梯折线 · step: middle", step_line))

        stack_bar = self._galleryChart()
        stack_bar.setOption(
            {
                "legend": _mini_legend(),
                "grid": _mini_grid(),
                "tooltip": {"trigger": "axis"},
                "xAxis": {"type": "category", "data": _WEEKS},
                "yAxis": {"type": "value"},
                "series": [
                    {
                        "type": "bar",
                        "name": "直接访问",
                        "stack": "total",
                        "itemStyle": {"borderRadius": [3, 3, 0, 0]},
                        "data": [320, 302, 301, 334, 390, 330, 320],
                    },
                    {
                        "type": "bar",
                        "name": "邮件营销",
                        "stack": "total",
                        "data": [120, 132, 101, 134, 90, 230, 210],
                    },
                    {
                        "type": "bar",
                        "name": "联盟广告",
                        "stack": "total",
                        "data": [220, 182, 191, 234, 290, 330, 310],
                    },
                ],
            }
        )
        tiles.append(("堆叠柱 · stack + 圆角（bar）", stack_bar))

        h_bar = self._galleryChart()
        h_bar.setOption(
            {
                "grid": _mini_grid(left=64, right=24),
                "tooltip": {"trigger": "axis"},
                "xAxis": {"type": "value"},
                "yAxis": {
                    "type": "category",
                    "data": ["搜索", "直连", "邮件", "视频", "联盟"],
                },
                "series": [
                    {
                        "type": "bar",
                        "name": "来源",
                        "itemStyle": {"borderRadius": [0, 4, 4, 0]},
                        "data": [1048, 735, 580, 300, 484],
                    }
                ],
            }
        )
        tiles.append(("横向柱 · yAxis 类目", h_bar))

        lines_chart = self._galleryChart()
        lines_chart.setOption(
            {
                "grid": _mini_grid(),
                "xAxis": {"type": "value", "min": 0, "max": 10},
                "yAxis": {"type": "value", "min": 0, "max": 10},
                "series": [
                    {
                        "type": "lines",
                        "name": "航路",
                        "coordinateSystem": "cartesian2d",
                        "lineStyle": {"width": 1.6, "curveness": 0.25},
                        "effect": {"show": True, "period": 4, "symbolSize": 5},
                        "data": [
                            {"coords": [[1, 1], [4, 7]]},
                            {"coords": [[1, 3], [7, 8]]},
                            {"coords": [[3, 1], [8, 5]]},
                            {"coords": [[5, 2], [9, 9]]},
                            {"coords": [[2, 8], [8, 2]]},
                        ],
                    }
                ],
            }
        )
        tiles.append(("多线轨迹 · lines + effect", lines_chart))

        charts = self._addGallery(parent_layout, tiles)
        self._attachGalleryControls(parent_layout, charts)

    # ── 02 画廊 · 数据点 ─────────────────────────────────────────────────

    def _demoGalleryPoints(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "02. 系列画廊 · 数据点（散点 / 气泡 / 涟漪 / 折线加点）",
                self._demoGalleryPoints,
            )
        )
        self._addInfoText(
            "scatter 数据第三维映射符号大小，visualMap 按值着色（气泡）；"
            "effectScatter 的 rippleEffect 驱动扩散圆动画（period / scale / brushType）；"
            "line 加 symbol 显示数据点，connectNulls 让断点直接连线",
            parent_layout,
        )
        tiles = []

        scatter_chart = self._galleryChart()
        scatter_chart.setOption(
            {
                "grid": _mini_grid(left=44),
                "tooltip": {"trigger": "item"},
                "xAxis": {"type": "value", "name": "X"},
                "yAxis": {"type": "value", "name": "Y"},
                "series": [
                    {
                        "type": "scatter",
                        "name": "样本",
                        "symbol": "circle",
                        "data": [
                            [5 + i * 1.6, 5 + i * 1.3, 10 + i * 3] for i in range(10)
                        ],
                    }
                ],
            }
        )
        tiles.append(("散点 · 大小随值（scatter）", scatter_chart))

        # 让散点图随机化时不至于把尺寸维度也换掉：随机数据按钮走 _randomizeSeries。
        bubble = self._galleryChart()
        bubble.setOption(
            {
                "grid": _mini_grid(left=44, right=52),
                "tooltip": {"trigger": "item"},
                "xAxis": {"type": "value"},
                "yAxis": {"type": "value"},
                "visualMap": {
                    "min": 0,
                    "max": 100,
                    "orient": "vertical",
                    "right": 4,
                    "top": "middle",
                    "itemWidth": 8,
                    "itemHeight": 60,
                    "textStyle": {"fontSize": 9},
                },
                "series": [
                    {
                        "type": "scatter",
                        "name": "气泡",
                        "symbolSize": 12,
                        "data": [
                            [12, 24, 12],
                            [24, 31, 45],
                            [33, 18, 62],
                            [46, 40, 80],
                            [55, 27, 95],
                        ],
                    }
                ],
            }
        )
        tiles.append(("气泡 · visualMap 着色", bubble))

        ripple = self._galleryChart()
        ripple.setOption(
            {
                "grid": _mini_grid(left=44),
                "tooltip": {"trigger": "item"},
                "xAxis": {"type": "value"},
                "yAxis": {"type": "value"},
                "series": [
                    {
                        "type": "effectScatter",
                        "name": "热点",
                        "symbolSize": 14,
                        "rippleEffect": {
                            "show": True,
                            "period": 3,
                            "scale": 2.8,
                            "number": 3,
                            "brushType": "stroke",
                        },
                        "data": [[10, 20], [30, 45], [50, 28], [66, 52]],
                    }
                ],
            }
        )
        tiles.append(("涟漪散点 · effectScatter", ripple))

        symbol_line = self._galleryChart()
        symbol_line.setOption(
            {
                "legend": _mini_legend(),
                "grid": _mini_grid(),
                "tooltip": {"trigger": "axis"},
                "xAxis": {
                    "type": "category",
                    "data": ["一", "二", "三", "四", "五", "六"],
                },
                "yAxis": {"type": "value"},
                "series": [
                    {
                        "type": "line",
                        "name": "有断点（切开）",
                        "symbol": "emptyCircle",
                        "symbolSize": 7,
                        "data": [12, 16, None, 22, 30, 26],
                    },
                    {
                        "type": "line",
                        "name": "connectNulls（连线）",
                        "symbol": "circle",
                        "symbolSize": 7,
                        "connectNulls": True,
                        "lineStyle": {"type": "dashed"},
                        "data": [12, 16, None, 22, 30, 26],
                    },
                ],
            }
        )
        tiles.append(("折线 + 数据点 · 断点与 connectNulls", symbol_line))

        charts = self._addGallery(parent_layout, tiles, columns=2)
        self._attachGalleryControls(parent_layout, charts)

    # ── 03 画廊 · 分布与金融 ─────────────────────────────────────────────

    def _demoGalleryDistribution(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "03. 系列画廊 · 分布与金融（箱线 / K 线 / 象形柱 / 直角热力）",
                self._demoGalleryDistribution,
            )
        )
        self._addInfoText(
            "candlestick 红涨绿跌（数据 [开, 收, 低, 高]）、boxplot 箱体含须线；"
            "pictorialBar 用 symbol 重复填充柱体；heatmap 在直角网格上按 "
            "[x, y, value] 填格，配 visualMap 上色",
            parent_layout,
        )
        tiles = []

        k_chart = self._galleryChart()
        k_chart.setOption(
            {
                "grid": _mini_grid(),
                "tooltip": {"trigger": "axis"},
                "xAxis": {
                    "type": "category",
                    "data": ["D1", "D2", "D3", "D4", "D5", "D6", "D7"],
                },
                "yAxis": {"type": "value"},
                "series": [
                    {
                        "type": "candlestick",
                        "name": "日K",
                        "data": [
                            [20, 34, 10, 38],
                            [40, 35, 30, 50],
                            [31, 38, 29, 42],
                            [38, 25, 34, 42],
                            [25, 30, 20, 40],
                            [35, 41, 31, 46],
                            [41, 36, 33, 45],
                        ],
                    }
                ],
            }
        )
        tiles.append(("K 线 · candlestick", k_chart))

        box_chart = self._galleryChart()
        box_chart.setOption(
            {
                "grid": _mini_grid(),
                "tooltip": {"trigger": "axis"},
                "xAxis": {"type": "category", "data": ["组A", "组B", "组C"]},
                "yAxis": {"type": "value"},
                "series": [
                    {
                        "type": "boxplot",
                        "name": "分布",
                        "data": [[1, 2, 3, 4, 8], [2, 3, 4, 5, 9], [1, 3, 5, 6, 10]],
                    }
                ],
            }
        )
        tiles.append(("箱线图 · boxplot", box_chart))

        pictorial = self._galleryChart()
        pictorial.setOption(
            {
                "grid": _mini_grid(),
                "xAxis": {"type": "category", "data": ["一", "二", "三", "四"]},
                "yAxis": {"type": "value"},
                "series": [
                    {
                        "type": "pictorialBar",
                        "name": "库存",
                        "data": [8, 5, 9, 4],
                        "symbol": "circle",
                        "symbolRepeat": True,
                        "symbolSize": 14,
                    }
                ],
            }
        )
        tiles.append(("象形柱 · pictorialBar", pictorial))

        heat = self._galleryChart()
        heat.setOption(
            {
                "grid": _mini_grid(left=64, bottom=40),
                "tooltip": {"trigger": "item"},
                "xAxis": {
                    "type": "category",
                    "data": ["周一", "周二", "周三", "周四", "周五"],
                },
                "yAxis": {"type": "category", "data": ["上午", "下午", "晚上"]},
                "visualMap": {
                    "min": 0,
                    "max": 10,
                    "orient": "horizontal",
                    "left": "center",
                    "bottom": 0,
                    "itemWidth": 10,
                    "itemHeight": 60,
                    "textStyle": {"fontSize": 9},
                },
                "series": [
                    {
                        "type": "heatmap",
                        "name": "活跃度",
                        "itemStyle": {"borderWidth": 1, "borderRadius": 2},
                        "data": [
                            [x, y, (x * 3 + y * 2) % 10]
                            for y in range(3)
                            for x in range(5)
                        ],
                    }
                ],
            }
        )
        tiles.append(("直角热力 · heatmap + visualMap", heat))

        charts = self._addGallery(parent_layout, tiles, columns=2)
        self._attachGalleryControls(parent_layout, charts)

    # ── 04 画廊 · 占比与仪表 ─────────────────────────────────────────────

    def _demoGalleryProportion(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "04. 系列画廊 · 占比与仪表（环形饼 / 玫瑰饼 / 漏斗 / 仪表盘）",
                self._demoGalleryProportion,
            )
        )
        self._addInfoText(
            "pie：radius 双值生成环形、totalLabel 显示中心合计、roseType 画南丁格尔玫瑰；"
            "funnel 梯形层叠展示转化；gauge 支持 progress 进度条与 "
            "axisLine.lineStyle.color 分段色弧",
            parent_layout,
        )
        tiles = []

        ring = self._galleryChart()
        ring.setOption(
            {
                "legend": _mini_legend(bottom=0, top=None),
                "tooltip": {"trigger": "item"},
                "series": [
                    {
                        "type": "pie",
                        "name": "访问来源",
                        "radius": ["42%", "68%"],
                        "center": ["50%", "50%"],
                        "totalLabel": {"show": True, "text": "总计"},
                        "data": [
                            {"name": "搜索引擎", "value": 1048},
                            {"name": "直接访问", "value": 735},
                            {"name": "邮件营销", "value": 580},
                            {"name": "联盟广告", "value": 484},
                        ],
                    }
                ],
            }
        )
        tiles.append(("环形饼 · radius + totalLabel", ring))

        rose = self._galleryChart()
        rose.setOption(
            {
                "legend": _mini_legend(bottom=0, top=None),
                "tooltip": {"trigger": "item"},
                "series": [
                    {
                        "type": "pie",
                        "name": "玫瑰",
                        "radius": ["16%", "72%"],
                        "center": ["50%", "50%"],
                        "roseType": "radius",
                        "data": [
                            {"name": "A", "value": 40},
                            {"name": "B", "value": 32},
                            {"name": "C", "value": 24},
                            {"name": "D", "value": 18},
                            {"name": "E", "value": 12},
                        ],
                    }
                ],
            }
        )
        tiles.append(("玫瑰饼 · roseType", rose))

        funnel = self._galleryChart()
        funnel.setOption(
            {
                "tooltip": {"trigger": "item"},
                "series": [
                    {
                        "type": "funnel",
                        "name": "转化",
                        "top": 12,
                        "bottom": 12,
                        "data": [
                            {"name": "访问", "value": 100},
                            {"name": "咨询", "value": 80},
                            {"name": "订单", "value": 50},
                            {"name": "成交", "value": 30},
                        ],
                    }
                ],
            }
        )
        tiles.append(("漏斗 · funnel", funnel))

        gauge = self._galleryChart()
        gauge.setOption(
            {
                "series": [
                    {
                        "type": "gauge",
                        "name": "速度",
                        "center": ["50%", "58%"],
                        "radius": "82%",
                        "data": [{"name": "速度", "value": 72}],
                        "progress": {"show": True, "width": 8},
                        "axisLine": {
                            "lineStyle": {
                                "width": 12,
                                "color": [
                                    [0.3, "#67e0e3"],
                                    [0.7, "#37a2da"],
                                    [1, "#fd666d"],
                                ],
                            }
                        },
                    }
                ],
            }
        )
        tiles.append(("仪表盘 · gauge", gauge))

        charts = self._addGallery(parent_layout, tiles, columns=2)
        self._attachGalleryControls(parent_layout, charts)

    # ── 05 画廊 · 层级与关系 ─────────────────────────────────────────────

    def _demoGalleryHierarchy(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "05. 系列画廊 · 层级与关系（矩形树 / 旭日 / 树 / 桑基 / 关系图）",
                self._demoGalleryHierarchy,
            )
        )
        self._addInfoText(
            "层级数据一律 children 递归；treemap 支持 breadcrumb 面包屑下钻、"
            "sunburst 画同心环、tree orient=LR 横向树；sankey 用 links 的 "
            "source/target/value 画贝塞尔流带；graph 力导布局 + roam 缩放平移 + "
            "draggable 拖节点",
            parent_layout,
        )
        tiles = []

        treemap = self._galleryChart()
        treemap.setOption(
            {
                "series": [
                    {
                        "type": "treemap",
                        "name": "矩形树",
                        "breadcrumb": {"show": True},
                        "data": [
                            {
                                "name": "根",
                                "children": [
                                    {"name": "A", "value": 50},
                                    {"name": "B", "value": 30},
                                    {"name": "C", "value": 20},
                                ],
                            }
                        ],
                    }
                ],
            }
        )
        tiles.append(("矩形树图 · treemap", treemap))

        sunburst = self._galleryChart()
        sunburst.setOption(
            {
                "series": [
                    {
                        "type": "sunburst",
                        "name": "层级",
                        "data": [
                            {
                                "name": "根",
                                "children": [
                                    {
                                        "name": "A",
                                        "value": 50,
                                        "children": [
                                            {"name": "A1", "value": 20},
                                            {"name": "A2", "value": 30},
                                        ],
                                    },
                                    {
                                        "name": "B",
                                        "value": 50,
                                        "children": [
                                            {"name": "B1", "value": 35},
                                            {"name": "B2", "value": 15},
                                        ],
                                    },
                                ],
                            }
                        ],
                    }
                ],
            }
        )
        tiles.append(("旭日图 · sunburst", sunburst))

        tree = self._galleryChart()
        tree.setOption(
            {
                "series": [
                    {
                        "type": "tree",
                        "name": "树",
                        "orient": "LR",
                        "data": [
                            {
                                "name": "根",
                                "children": [
                                    {
                                        "name": "A",
                                        "children": [{"name": "A1"}, {"name": "A2"}],
                                    },
                                    {
                                        "name": "B",
                                        "children": [{"name": "B1"}, {"name": "B2"}],
                                    },
                                ],
                            }
                        ],
                    }
                ],
            }
        )
        tiles.append(("树图 · tree（orient=LR）", tree))

        sankey = self._galleryChart()
        sankey.setOption(
            {
                "series": [
                    {
                        "type": "sankey",
                        "name": "流向",
                        "data": [
                            {"name": "a"},
                            {"name": "b"},
                            {"name": "c"},
                            {"name": "d"},
                            {"name": "e"},
                        ],
                        "links": [
                            {"source": "a", "target": "b", "value": 5},
                            {"source": "b", "target": "c", "value": 3},
                            {"source": "a", "target": "d", "value": 2},
                            {"source": "d", "target": "e", "value": 2},
                            {"source": "b", "target": "e", "value": 2},
                        ],
                    }
                ],
            }
        )
        tiles.append(("桑基图 · sankey", sankey))

        graph = self._galleryChart()
        graph.setOption(
            {
                "series": [
                    {
                        "type": "graph",
                        "name": "关系",
                        "layout": "force",
                        "roam": True,
                        "draggable": True,
                        "data": [
                            {"name": "核心", "symbolSize": 26},
                            {"name": "A"},
                            {"name": "B"},
                            {"name": "C"},
                            {"name": "D"},
                            {"name": "E"},
                        ],
                        "links": [
                            {"source": "核心", "target": "A"},
                            {"source": "核心", "target": "B"},
                            {"source": "核心", "target": "C"},
                            {"source": "A", "target": "D"},
                            {"source": "B", "target": "E"},
                            {"source": "C", "target": "E"},
                        ],
                    }
                ],
            }
        )
        tiles.append(("关系图 · graph（力导 + roam）", graph))

        charts = self._addGallery(parent_layout, tiles)
        self._attachGalleryControls(parent_layout, charts)

    # ── 06 画廊 · 特殊坐标与日历 ─────────────────────────────────────────

    def _demoGalleryCoordinates(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "06. 系列画廊 · 特殊坐标（雷达 / 平行坐标 / 地图 / 主题河 / 日历热力）",
                self._demoGalleryCoordinates,
            )
        )
        self._addInfoText(
            "radar 蛛网自绘、parallel 多维折线（parallelAxis 定义维度）；"
            "map 区域着色 + roam 缩放平移（示意地图）；themeRiver 时间 × 系列流带；"
            "日历热力是 calendar 坐标系的 heatmap：周(列)×星期(行) 年历网格，"
            "无数据日自动铺浅色底格，悬停显示数据项 tooltip.formatter 自定义文案",
            parent_layout,
        )
        tiles = []

        radar = self._galleryChart()
        radar.setOption(
            {
                "legend": _mini_legend(bottom=0, top=None),
                "series": [
                    {
                        "type": "radar",
                        "name": "能力",
                        "center": ["50%", "50%"],
                        "radius": "70%",
                        "indicator": [
                            {"name": "销售", "max": 6500},
                            {"name": "管理", "max": 16000},
                            {"name": "技术", "max": 30000},
                            {"name": "客服", "max": 38000},
                            {"name": "研发", "max": 52000},
                        ],
                        "data": [
                            {
                                "name": "预算",
                                "value": [4200, 3000, 20000, 35000, 50000],
                            },
                            {
                                "name": "实际",
                                "value": [5000, 14000, 28000, 26000, 42000],
                            },
                        ],
                    }
                ],
            }
        )
        tiles.append(("雷达 · radar", radar))

        parallel = self._galleryChart()
        parallel.setOption(
            {
                "parallelAxis": [
                    {"name": "维度A"},
                    {"name": "维度B"},
                    {"name": "维度C"},
                ],
                "series": [
                    {
                        "type": "parallel",
                        "name": "样本",
                        "data": [[1, 2, 3], [4, 5, 6], [2, 4, 8], [7, 3, 2], [5, 6, 1]],
                    }
                ],
            }
        )
        tiles.append(("平行坐标 · parallel", parallel))

        map_chart = self._galleryChart()
        map_chart.setOption(
            {
                "tooltip": {"trigger": "item"},
                "visualMap": {
                    "min": 0,
                    "max": 150,
                    "orient": "horizontal",
                    "left": "center",
                    "bottom": 0,
                    "itemWidth": 10,
                    "itemHeight": 60,
                    "textStyle": {"fontSize": 9},
                },
                "series": [
                    {
                        "type": "map",
                        "name": "区域",
                        "map": "demo",
                        "roam": True,
                        "data": [
                            {"name": "华北", "value": 120},
                            {"name": "华东", "value": 90},
                            {"name": "华南", "value": 60},
                            {"name": "西部", "value": 30},
                        ],
                    }
                ],
            }
        )
        tiles.append(("地图 · map（roam 缩放平移）", map_chart))

        river = self._galleryChart()
        river.setOption(
            {
                "tooltip": {"trigger": "item"},
                "series": [
                    {
                        "type": "themeRiver",
                        "name": "流量",
                        "data": [
                            [f"2015-11-{d:02d}", value, name]
                            for name, values in (
                                ("游戏", [10, 15, 13, 18]),
                                ("音乐", [5, 8, 7, 10]),
                                ("旅游", [3, 6, 5, 8]),
                            )
                            for d, value in zip(range(8, 12), values)
                        ],
                    }
                ],
            }
        )
        tiles.append(("主题河流 · themeRiver", river))

        charts = self._addGallery(parent_layout, tiles, columns=2)
        self._attachGalleryControls(parent_layout, charts)

        # 日历热力：宽格 + 模式切换（每日 / 每周 / 累计）与配色开关
        self._calendar_data = _build_token_activity()
        self._calendar_mode = "daily"
        self._calendar_green = False
        self._calendar_chart = self._galleryChart(height=248)

        wide = QVBoxLayout()
        wide.setSpacing(4)
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        calendar_title = ElaText("日历热力 · heatmap + calendar（Token 活动）", self)
        calendar_title.setTextPixelSize(13)
        calendar_title.setFixedHeight(calendar_title.fontMetrics().height() * 2)
        title_row.addWidget(calendar_title)
        title_row.addSpacing(8)
        green_box = ElaCheckBox("GitHub 绿配色", self)
        green_box.toggled.connect(self._onCalendarPaletteToggled)
        title_row.addWidget(green_box)
        self._calendar_chips = {}
        for key, label in (
            ("daily", "每日"),
            ("weekly", "每周"),
            ("cumulative", "累计"),
        ):
            chip = ElaChip(label, self)
            chip.setCheckable(True)
            chip.setChecked(key == "daily")
            chip.clicked.connect(lambda k=key: self._setCalendarMode(k))
            self._calendar_chips[key] = chip
            title_row.addWidget(chip)
        title_row.addStretch()
        wide.addLayout(title_row)
        wide.addWidget(self._calendar_chart, 1)
        parent_layout.addLayout(wide)
        self._calendar_chart.setOption(self._buildCalendarHeatmapOption())

    def _buildCalendarHeatmapOption(self):
        series_data = _token_activity_series(self._calendar_data, self._calendar_mode)
        values = [item["value"][1] for item in series_data]
        visual_map = {"min": 0, "max": max(values) if values else 1}
        if self._calendar_green:
            visual_map["inRange"] = {"colors": _GITHUB_GREENS}
        return {
            "tooltip": {"trigger": "item"},
            "calendar": {
                "range": 2026,
                "cellSize": "auto",
                "splitLine": {"show": False},
            },
            "visualMap": visual_map,
            "series": [
                {
                    "type": "heatmap",
                    "coordinateSystem": "calendar",
                    "name": "Token",
                    "itemStyle": {"borderWidth": 2, "borderRadius": 2},
                    "data": series_data,
                }
            ],
        }

    def _setCalendarMode(self, mode: str):
        self._calendar_mode = mode
        for key, chip in self._calendar_chips.items():
            chip.setChecked(key == mode)
        self._calendar_chart.setOption(self._buildCalendarHeatmapOption())

    def _onCalendarPaletteToggled(self, checked: bool):
        self._calendar_green = bool(checked)
        self._calendar_chart.setOption(
            {"visualMap": self._buildCalendarHeatmapOption()["visualMap"]}
        )

    # ── 07 大数据动态采样 ───────────────────────────────────────────────

    def _demoBigData(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "07. 大数据与采样 · 30 万点动态降采样 + 滚轮缩放", self._demoBigData
            )
        )
        self._addInfoText(
            "数据量超过 threshold（默认 2000）时按当前绘图范围（x 轴数值窗口 × 画布像素宽度）"
            "动态降采样，只渲染窗口内数据（任何轴类型都抽稀；坐标轴标签 / 刻度也按标签宽度抽稀）；"
            "滚轮即可缩放查看细节、拖拽平移；sampling 支持算法名"
            "（minmax 默认 / m4 / lttb / minmaxLTTB）、dict 精细配置"
            "（{algorithm, threshold, pointsPerPixel}）或 False 关闭抽稀。"
            "数据为显式时间戳（0.1s 间隔）且含一处 10 分钟记录中断：中断在可见处"
            "自动断开（addGaps: false 或 connectNulls: true 可关闭；亚像素空洞照常连线）",
            parent_layout,
        )
        self._bigChart = ElaChartWidget(self)
        self._bigChart.setMinimumHeight(300)
        self._bigChart.setOption(
            {
                "title": {"text": "点击下方按钮生成 30 万点数据", "left": "center"},
                "xAxis": {"type": "value"},
                "yAxis": {"type": "value"},
                "series": [{"type": "line", "name": "大数据", "data": []}],
            }
        )
        parent_layout.addWidget(self._bigChart)

        gen_btn = ElaPushButton("生成数据", self)
        gen_btn.setFixedWidth(90)
        gen_btn.clicked.connect(self._onGenBigData)
        self._sampling_cb = ElaCheckBox("启用降采样", self)
        self._sampling_cb.setChecked(True)
        self._sampling_cb.toggled.connect(self._onToggleSampling)
        points_label = ElaText("数据点数:", self)
        points_label.setTextPixelSize(14)
        self._points_input = ElaLineEdit(self)
        self._points_input.setFixedWidth(90)
        self._points_input.setText("300000")
        curves_label = ElaText("曲线条数:", self)
        curves_label.setTextPixelSize(14)
        self._curves_input = ElaLineEdit(self)
        self._curves_input.setFixedWidth(50)
        self._curves_input.setText("1")
        symbol_btn = ElaPushButton("形状: 开", self)
        symbol_btn.setFixedWidth(90)
        symbol_btn.clicked.connect(lambda: self._onToggleSymbol(symbol_btn))
        inter_btn = ElaPushButton(
            "交互: 开" if self._bigChart.interactiveEnabled() else "交互: 关", self
        )
        inter_btn.setFixedWidth(90)
        inter_btn.clicked.connect(
            lambda: self._toggleInteraction(self._bigChart, inter_btn)
        )
        # 状态行跟着缩放 / 平移刷新（否则滚轮缩放后窗口数字是旧的）
        self._bigChart.dataZoomChanged.connect(
            lambda _start, _end: self._updateBigStatus()
        )
        self._big_status = ElaText("", self)
        self._big_status.setTextPixelSize(12)

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(gen_btn)
        row.addWidget(self._sampling_cb)
        row.addSpacing(10)
        row.addWidget(points_label)
        row.addWidget(self._points_input)
        row.addWidget(curves_label)
        row.addWidget(self._curves_input)
        row.addSpacing(10)
        row.addWidget(symbol_btn)
        row.addWidget(inter_btn)
        row.addSpacing(10)
        row.addWidget(self._big_status)
        row.addStretch()
        parent_layout.addLayout(row)

        self._big_series = None
        self._big_symbol_on = True

    def _bigOption(self):
        sopt = True if self._sampling_cb.isChecked() else False
        opt = {
            "title": {"text": "大数据动态采样", "left": "left"},
            "xAxis": {"type": "value"},
            "yAxis": {"type": "value"},
            "series": self._big_series or [],
        }
        for s in opt["series"]:
            if isinstance(s, dict):
                s["sampling"] = sopt
                # 形状开关：关时隐藏数据点符号，开时大数据下稀疏绘制
                s["showSymbol"] = self._big_symbol_on
        return opt

    def _onToggleSymbol(self, btn):
        self._big_symbol_on = not self._big_symbol_on
        btn.setText("形状: 开" if self._big_symbol_on else "形状: 关")
        if self._big_series:
            self._bigChart.setOption(self._bigOption())
            self._updateBigStatus()

    def _onGenBigData(self):
        import math

        try:
            n = max(1, min(5_000_000, int(self._points_input.text())))
        except (TypeError, ValueError):
            n = 300000
        try:
            k = max(1, min(10, int(self._curves_input.text())))
        except (TypeError, ValueError):
            k = 1
        series = []
        half = n // 2
        for j in range(k):
            base = random.randint(300, 700)
            a1 = random.uniform(120, 260)
            w1 = random.uniform(120, 260)
            a2 = random.uniform(40, 120)
            w2 = random.uniform(25, 60)
            # 显式时间戳（0.1s 间隔）+ 一处 10 分钟记录中断：中断在可见处自动
            # 断开；纯 Python 生成，不强依赖 numpy。
            data = [
                [
                    i * 0.1 if i < half else i * 0.1 + 600.0,
                    base + a1 * math.sin(i / w1) + a2 * math.sin(i / w2),
                ]
                for i in range(n)
            ]
            series.append({"type": "line", "name": f"曲线{j + 1}", "data": data})
        self._big_series = series
        self._bigChart.setOption(self._bigOption())
        self._updateBigStatus()

    def _updateBigStatus(self):
        r = (
            self._bigChart.seriesRenderers[0]
            if self._bigChart.seriesRenderers
            else None
        )
        if r is None:
            return
        # 当前 x 轴显示范围（真实值域）与 dataZoom 百分比窗口
        coord = self._bigChart.primaryCoord()
        range_text = ""
        if coord is not None and hasattr(coord, "x_axis"):
            ax = coord.x_axis
            if ax.type == "value":
                range_text = f" · x 轴 {ax.vmin:.0f}~{ax.vmax:.0f}"
        dz = next(
            (c for c in self._bigChart.components if c.optionKey == "dataZoom"),
            None,
        )
        zoom_text = ""
        if dz is not None:
            zoom_text = f" · 窗口 {dz.start:.0f}%~{dz.end:.0f}%"
        text = (
            f"{len(self._bigChart.seriesRenderers)} 条曲线 · "
            f"首条原始 {r._data_len} 点 → 绘制 {len(r._points)} 点"
            + ("（已降采样）" if r._sampled else "（全量）")
            + range_text
            + zoom_text
        )
        self._big_status.setText(text)

    def _onToggleSampling(self):
        if self._big_series:
            self._bigChart.setOption(self._bigOption())
            self._updateBigStatus()

    # ── 08 交互组件 ─────────────────────────────────────────────────────

    def _demoInteractComponents(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "08. 交互组件：tooltip / legend / dataZoom / visualMap / mark* / toolbox / timeline",
                self._demoInteractComponents,
            )
        )
        self._addInfoText(
            "底部 dataZoom 滑块拖拽缩放（滚轮亦可）、visualMap 色带映射、markPoint/markLine/markArea "
            "标注、右上角 toolbox（导出图片 / 还原 / 缩放开关）、timeline 帧切换",
            parent_layout,
        )
        frames = [
            {
                "series": [
                    {
                        "type": "bar",
                        "name": "2024",
                        "data": [120, 200, 150, 80, 70, 110],
                    },
                    {
                        "type": "line",
                        "name": "趋势",
                        "data": [110, 180, 160, 90, 80, 120],
                    },
                ]
            },
            {
                "series": [
                    {
                        "type": "bar",
                        "name": "2025",
                        "data": [150, 180, 220, 130, 100, 140],
                    },
                    {
                        "type": "line",
                        "name": "趋势",
                        "data": [140, 170, 210, 120, 95, 135],
                    },
                ]
            },
            {
                "series": [
                    {
                        "type": "bar",
                        "name": "2026",
                        "data": [200, 240, 180, 160, 130, 190],
                    },
                    {
                        "type": "line",
                        "name": "趋势",
                        "data": [190, 230, 175, 155, 125, 180],
                    },
                ]
            },
        ]
        self._interactChart = ElaChartWidget(self)
        self._interactChart.setMinimumHeight(400)
        self._interactChart.setOption(
            {
                "title": {"text": "交互综合演示", "left": "left"},
                "legend": {"top": "top"},
                "tooltip": {"trigger": "axis"},
                "xAxis": {
                    "type": "category",
                    "data": ["1月", "2月", "3月", "4月", "5月", "6月"],
                },
                "yAxis": {"type": "value"},
                "series": [
                    {
                        "type": "bar",
                        "name": "2024",
                        "data": [120, 200, 150, 80, 70, 110],
                        "markPoint": {"data": [{"type": "max", "name": "峰值"}]},
                        "markLine": {"data": [{"type": "average", "name": "均值"}]},
                        "markArea": {"data": [[{"xAxis": "1月"}, {"xAxis": "2月"}]]},
                    },
                    {
                        "type": "line",
                        "name": "趋势",
                        "data": [110, 180, 160, 90, 80, 120],
                        "smooth": True,
                    },
                ],
                "dataZoom": [
                    {"type": "slider", "start": 20, "end": 80},
                    {"type": "inside"},
                ],
                "visualMap": {"min": 0, "max": 260, "orient": "horizontal"},
                "toolbox": {"feature": ["saveAsImage", "restore", "dataZoom"]},
                "timeline": {"data": ["2024", "2025", "2026"], "autoPlay": False},
                "options": frames,
            }
        )
        self._addChartWithControls(parent_layout, self._interactChart)

        # ECharts 实例 API 演示：dispatchAction / on / showLoading / getDataURL
        api_row = QHBoxLayout()
        api_row.setSpacing(8)
        api_label = ElaText("ECharts API：", self)
        api_label.setTextPixelSize(14)
        api_row.addWidget(api_label)
        for label, action in (
            ("切换图例", {"type": "legendToggleSelect", "name": "2024"}),
            ("缩放 20~70%", {"type": "dataZoom", "start": 20, "end": 70}),
            ("高亮峰值", {"type": "highlight", "seriesIndex": 0, "dataIndex": 1}),
            ("还原", {"type": "restore"}),
        ):
            btn = ElaPushButton(label, self)
            btn.setFixedWidth(100)
            btn.clicked.connect(
                lambda _checked=False, a=action: self._interactChart.dispatchAction(a)
            )
            api_row.addWidget(btn)
        loading_btn = ElaPushButton("加载遮罩", self)
        loading_btn.setFixedWidth(100)
        loading_btn.clicked.connect(lambda: self._toggleInteractLoading(loading_btn))
        api_row.addWidget(loading_btn)
        export_btn = ElaPushButton("导出 dataURL", self)
        export_btn.setFixedWidth(110)
        export_btn.clicked.connect(self._onExportDataUrl)
        api_row.addWidget(export_btn)
        api_row.addStretch()
        parent_layout.addLayout(api_row)

        # 逐功能交互开关（setInteractionEnabled）
        feature_row = QHBoxLayout()
        feature_row.setSpacing(12)
        feature_label = ElaText("交互开关：", self)
        feature_label.setTextPixelSize(14)
        feature_row.addWidget(feature_label)
        # 逐功能勾选框登记起来：总开关「交互: 开」是全开（清空逐功能覆盖），
        # 勾选框要跟着回到勾上，界面才与真实状态一致
        self._feature_boxes = []
        for key, label in (
            ("tooltip", "提示框"),
            ("legend", "图例"),
            ("dataZoom", "缩放"),
            ("toolbox", "工具箱"),
            ("timeline", "时间轴"),
        ):
            box = ElaCheckBox(label, self)
            box.setChecked(True)
            box.toggled.connect(
                lambda checked, k=key: self._interactChart.setInteractionEnabled(
                    k, checked
                )
            )
            feature_row.addWidget(box)
            self._feature_boxes.append((key, box))
        feature_row.addStretch()
        parent_layout.addLayout(feature_row)

        # 图表级事件（统一事件接口）：Qt 信号 + ECharts on() 双通道
        signal_status = ElaText(
            "事件：—（图例切换 / 缩放 / 帧切换 / 数据点点击 / toolbox / 刷选）", self
        )
        signal_status.setTextPixelSize(13)
        self._interactChart.legendToggled.connect(
            lambda name, visible: signal_status.setText(
                f"legendToggled: {name} → {'显示' if visible else '隐藏'}"
            )
        )
        self._interactChart.dataZoomChanged.connect(
            lambda start, end: signal_status.setText(
                f"dataZoomChanged: {start:.1f}% - {end:.1f}%"
            )
        )
        self._interactChart.timelineChanged.connect(
            lambda index: signal_status.setText(f"timelineChanged: 第 {index + 1} 帧")
        )
        self._interactChart.itemClicked.connect(
            lambda info: signal_status.setText(
                f"itemClicked: {info.get('seriesName')} = {info.get('value')}"
            )
        )
        self._interactChart.toolboxTriggered.connect(
            lambda action: signal_status.setText(f"toolboxTriggered: {action}")
        )
        self._interactChart.brushChanged.connect(
            lambda items: signal_status.setText(f"brushChanged: 选中 {len(items)} 个点")
        )
        # ECharts 事件名（on/off）：click / datazoom / legendselectchanged / finished
        self._interactChart.on(
            "click",
            lambda params: signal_status.setText(
                f"on('click'): series={params.get('seriesName')} "
                f"name={params.get('name')} value={params.get('value')}"
            ),
        )
        self._interactChart.on(
            "datazoom",
            lambda params: signal_status.setText(
                f"on('datazoom'): {params.get('start'):.1f}% - {params.get('end'):.1f}%"
            ),
        )
        self._interactChart.on(
            "finished",
            lambda _params: signal_status.setText("on('finished'): 动画结束"),
        )
        parent_layout.addWidget(signal_status)

    def _toggleInteractLoading(self, btn):
        """showLoading / hideLoading 演示。"""
        if self._interactChart.isLoading:
            self._interactChart.hideLoading()
            btn.setText("加载遮罩")
        else:
            self._interactChart.showLoading("default", {"text": "加载中…"})
            btn.setText("关闭遮罩")

    def _onExportDataUrl(self):
        """getDataURL 演示：导出为文件并提示尺寸。"""
        from PyQt6.QtCore import QBuffer, QIODevice
        from PyQt6.QtGui import QImage

        url = self._interactChart.getDataURL({"type": "png", "pixelRatio": 2})
        if not url:
            return
        payload = url.split(",", 1)[-1]
        image = QImage()
        buffer = QBuffer()
        buffer.setData(__import__("base64").b64decode(payload))
        buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        image.loadFromData(buffer.data())
        buffer.close()
        if image.isNull():
            return
        target = "chart_dataurl.png"
        image.save(target, "PNG")
        self._interactChart.setToolTip(f"getDataURL 已保存：{target}")

    # ── 09 Plotly 对齐的交互 ─────────────────────────────────────────────

    def _demoPlotlyInteractions(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "09. Plotly 对齐：双击复位 / dragmode / 套索 / 空区坐标 / SVG 导出",
                self._demoPlotlyInteractions,
            )
        )
        self._addInfoText(
            "曲线 / 柱状等直角坐标图默认支持滚轮缩放与按住拖动平移（无 dataZoom 选项时自动内置）；"
            "拖拽模式可切换（平移 / 框选缩放 / 框选 / 套索），框选缩放的框松手即消失、"
            "框选则保留；双击复位视图，zoomStep 步进缩放；tooltip.order 让联合提示按值排序、"
            "hitRadius 控制命中距离；hoveranywhere 与 clickanywhere 让空区也出提示并发出 "
            "itemClicked（载荷带数据坐标）；connectNulls 让断点连线；图例悬停高亮对应系列；"
            "工具条是真实 ElaIconButton（含导出 SVG / 放大 / 缩小）",
            parent_layout,
        )
        chart = ElaChartWidget(self)
        chart.setMinimumHeight(380)
        gap_series = [80, 96, None, 132, 150, None, 118, 104, 126, None, 158, 170]
        chart.setOption(
            {
                "title": {"text": "拖拽 / 双击 / 悬停图例试试", "left": "left"},
                "legend": {"top": "top"},
                "tooltip": {"trigger": "axis", "order": "valueDesc", "hitRadius": 14},
                "xAxis": {
                    "type": "category",
                    "data": [f"{i + 1}月" for i in range(12)],
                },
                "yAxis": {"type": "value"},
                "grid": {"top": 74, "bottom": 70},
                "series": [
                    {
                        "type": "line",
                        "name": "波动",
                        "data": [
                            round(
                                100 + 40 * math.sin(i / 2.4) + 7 * math.sin(i / 0.7), 1
                            )
                            for i in range(12)
                        ],
                        "smooth": True,
                    },
                    {
                        "type": "line",
                        "name": "趋势",
                        "data": [60 + 9 * i for i in range(12)],
                    },
                    {"type": "line", "name": "断点·切开", "data": gap_series},
                    {
                        "type": "line",
                        "name": "断点·连线",
                        "data": gap_series,
                        "connectNulls": True,
                        "lineStyle": {"type": "dashed"},
                    },
                ],
                "dataZoom": [{"type": "inside", "start": 0, "end": 100}],
                "brush": {"type": "rect"},
                "toolbox": {
                    "feature": [
                        "saveAsImage",
                        "saveAsSvg",
                        "dataZoom",
                        "restore",
                        "zoomIn",
                        "zoomOut",
                    ]
                },
                "hoveranywhere": True,
                "clickanywhere": True,
            }
        )
        parent_layout.addWidget(chart)
        chart.setDragMode("pan")  # 初始：拖拽平移 + 滚轮缩放

        status = ElaText("事件：—（拖拽 / 双击 / 图例悬停 / 刷选 / 空区点击）", self)
        status.setTextPixelSize(13)
        chart.dataZoomChanged.connect(
            lambda start, end: status.setText(
                f"dataZoomChanged：{start:.1f}% - {end:.1f}%"
            )
        )
        chart.brushChanged.connect(
            lambda items: status.setText(f"brushChanged：选中 {len(items)} 个数据点")
        )

        def _on_item(info: dict) -> None:
            if info.get("componentType") == "grid":

                def _text_of(value):
                    try:
                        return f"{float(value):.1f}"
                    except (TypeError, ValueError, OverflowError):
                        return str(value)

                status.setText(
                    f"空区点击 → x={_text_of(info.get('x'))} "
                    f"y={_text_of(info.get('y'))}"
                )
            else:
                status.setText(
                    f"itemClicked：{info.get('seriesName')} = {info.get('value')}"
                )

        chart.itemClicked.connect(_on_item)

        def _export_svg() -> None:
            """getDataURL(type="svg") → 落盘为 chart_dataurl.svg（矢量）。"""
            import base64
            import pathlib

            url = chart.getDataURL({"type": "svg"})
            if not url:
                status.setText("导出 SVG：失败（QtSvg 不可用）")
                return
            payload = base64.b64decode(url.split(",", 1)[-1])
            target = pathlib.Path("chart_dataurl.svg")
            target.write_bytes(payload)
            status.setText(f"getDataURL(type=svg)：{len(payload)} 字节 → {target}")

        controls = QHBoxLayout()
        controls.setSpacing(8)
        mode_label = ElaText("拖拽模式：", self)
        mode_label.setTextPixelSize(14)
        controls.addWidget(mode_label)
        for label, mode in (
            ("平移", "pan"),
            ("框选缩放", "zoom"),
            ("框选", "select"),
            ("套索", "lasso"),
        ):

            def _set_mode(_checked=False, m=mode):
                chart.setDragMode(m)
                status.setText(
                    f"dragMode = {chart.dragMode()}（brush.type = "
                    f"{chart.brushComponent().brush_type()}）"
                )

            mode_btn = ElaPushButton(label, self)
            mode_btn.setFixedWidth(84)
            mode_btn.clicked.connect(_set_mode)
            controls.addWidget(mode_btn)
        controls.addSpacing(12)
        zoom_in_btn = ElaPushButton("放大", self)
        zoom_in_btn.setFixedWidth(70)
        zoom_in_btn.clicked.connect(lambda: chart.zoomStep(0.7))
        controls.addWidget(zoom_in_btn)
        zoom_out_btn = ElaPushButton("缩小", self)
        zoom_out_btn.setFixedWidth(70)
        zoom_out_btn.clicked.connect(lambda: chart.zoomStep(1.0 / 0.7))
        controls.addWidget(zoom_out_btn)
        reset_btn = ElaPushButton("复位视图", self)
        reset_btn.setFixedWidth(84)
        reset_btn.clicked.connect(chart.resetView)
        controls.addWidget(reset_btn)
        dbl_cb = ElaCheckBox("双击复位", self)
        dbl_cb.setChecked(chart.doubleClickReset())
        dbl_cb.toggled.connect(chart.setDoubleClickReset)
        controls.addWidget(dbl_cb)
        svg_btn = ElaPushButton("导出 SVG", self)
        svg_btn.setFixedWidth(90)
        svg_btn.clicked.connect(_export_svg)
        controls.addWidget(svg_btn)
        controls.addStretch()
        parent_layout.addLayout(controls)
        parent_layout.addWidget(status)
