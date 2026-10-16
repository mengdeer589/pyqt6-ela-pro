"""
[pyqt6_ela_pro] ElaChartWidget 图表引擎页面

类 ECharts 原生图表引擎（纯 QPainter + Ela 主题感知）：
21 个系列 + 交互组件演示。每个图表均带「随机数据」与「鼠标交互开关」按钮。
"""

import math
import random
from datetime import date, timedelta

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QVBoxLayout
from PyQt6ElaWidgetTools import ElaText, ElaPushButton, ElaLineEdit, ElaCheckBox

from pyqt6_ela_pro import ElaChartWidget, ElaChip
from .base_page import ExamplePage

_WEEKS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

#: GitHub 绿 5 档色带（visualMap.inRange.colors 示例）
_GITHUB_GREENS = ["#ebedf0", "#9be9a8", "#40c463", "#30a14e", "#216e39"]


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
        self._demoLineChart(main_layout)
        main_layout.addSpacing(24)
        self._demoBarChart(main_layout)
        main_layout.addSpacing(24)
        self._demoPieChart(main_layout)
        main_layout.addSpacing(24)
        self._demoScatterBubble(main_layout)
        main_layout.addSpacing(24)
        self._demoCalendarHeatmap(main_layout)
        main_layout.addSpacing(24)
        self._demoFinanceCharts(main_layout)
        main_layout.addSpacing(24)
        self._demoHierarchyCharts(main_layout)
        main_layout.addSpacing(24)
        self._demoRelationalCharts(main_layout)
        main_layout.addSpacing(24)
        self._demoBigData(main_layout)
        main_layout.addSpacing(24)
        self._demoInteractComponents(main_layout)

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
            s["data"] = [list(d[:2]) + [random.randint(0, 24)] for d in data]
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
        else:
            s["data"] = [random.randint(5, 100) for _ in data]

    # ── 鼠标交互开关 ────────────────────────────────────────────────────

    def _toggleInteraction(self, chart, btn):
        """切换鼠标交互（提示框 / 图例 / 缩放 / 刷选 / 时间轴 / 工具箱）。

        走 ``chart.setInteractive`` 总开关：数据与绘制不变，仅鼠标交互失效。
        """
        on = btn.text().endswith("开")
        chart.setInteractive(not on)
        btn.setText("交互: 关" if on else "交互: 开")

    # ── 01 折线图 ───────────────────────────────────────────────────────

    def _demoLineChart(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "01. ElaChartWidget 折线图 (smooth + 面积 + tooltip)",
                self._demoLineChart,
            )
        )
        self._addInfoText(
            "ECharts 风格 option：series.type = line；支持 smooth 平滑、areaStyle 面积渐变填充、"
            "虚线 lineStyle、悬停 axis 十字线提示、图例点击显隐",
            parent_layout,
        )
        self._lineChart = ElaChartWidget(self)
        self._lineChart.setMinimumHeight(320)
        self._lineChart.setOption(self._buildLineOption())
        self._addChartWithControls(parent_layout, self._lineChart)

    def _buildLineOption(self):
        return {
            "title": {
                "text": "一周访问趋势",
                "subtext": "三系列对比",
                "left": "center",
            },
            "legend": {"top": "top"},
            "tooltip": {"trigger": "axis"},
            "xAxis": {"type": "category", "data": _WEEKS},
            "yAxis": {"type": "value", "name": "访问量"},
            "series": [
                {
                    "type": "line",
                    "name": "邮件营销",
                    "smooth": True,
                    "areaStyle": {"opacity": 0.15},
                    "data": [120, 132, 101, 134, 90, 230, 210],
                },
                {
                    "type": "line",
                    "name": "联盟广告",
                    "smooth": True,
                    "areaStyle": {"opacity": 0.15},
                    "data": [220, 182, 191, 234, 290, 330, 310],
                },
                {
                    "type": "line",
                    "name": "视频广告",
                    "lineStyle": {"type": "dashed"},
                    "data": [150, 232, 201, 154, 190, 330, 410],
                },
            ],
        }

    # ── 02 柱状图 ───────────────────────────────────────────────────────

    def _demoBarChart(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "02. ElaChartWidget 柱状图 (stack 堆叠)", self._demoBarChart
            )
        )
        self._addInfoText(
            "多系列同名 stack 自动累加堆叠；数值轴范围按堆叠总和自适应；"
            "支持 itemStyle.borderRadius 圆角",
            parent_layout,
        )
        self._barChart = ElaChartWidget(self)
        self._barChart.setMinimumHeight(320)
        self._barChart.setOption(self._buildBarOption())
        self._addChartWithControls(parent_layout, self._barChart)

    def _buildBarOption(self):
        return {
            "title": {"text": "一周销售量构成", "left": "center"},
            "legend": {"top": "top"},
            "tooltip": {"trigger": "axis"},
            "xAxis": {"type": "category", "data": _WEEKS},
            "yAxis": {"type": "value", "name": "销量"},
            "series": [
                {
                    "type": "bar",
                    "name": "直接访问",
                    "stack": "total",
                    "itemStyle": {"borderRadius": 3},
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

    # ── 03 饼图 ─────────────────────────────────────────────────────────

    def _demoPieChart(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "03. ElaChartWidget 饼图 (环形 + 中心总计)", self._demoPieChart
            )
        )
        self._addInfoText(
            "radius 双值生成环形图，totalLabel 显示中心总计；label.position = outside 绘制外部引线",
            parent_layout,
        )
        self._pieChart = ElaChartWidget(self)
        self._pieChart.setMinimumHeight(340)
        self._pieChart.setOption(self._buildPieOption())
        self._addChartWithControls(parent_layout, self._pieChart)

    def _buildPieOption(self):
        return {
            "title": {"text": "访问来源", "left": "center"},
            "legend": {"top": "bottom"},
            "tooltip": {"trigger": "item"},
            "series": [
                {
                    "type": "pie",
                    "radius": ["38%", "62%"],
                    "center": ["50%", "54%"],
                    "totalLabel": {"show": True, "text": "总计"},
                    "data": [
                        {"name": "搜索引擎", "value": 1048},
                        {"name": "直接访问", "value": 735},
                        {"name": "邮件营销", "value": 580},
                        {"name": "联盟广告", "value": 484},
                        {"name": "视频广告", "value": 300},
                    ],
                }
            ],
        }

    # ── 04 散点（气泡） ────────────────────────────────────────────────

    def _demoScatterBubble(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "04. ElaChartWidget 散点图（气泡）",
                self._demoScatterBubble,
            )
        )
        self._addInfoText(
            "scatter 数据第三维映射气泡大小；grid 直角热力见系列能力，日历热力见下一节",
            parent_layout,
        )
        self._scatterChart = ElaChartWidget(self)
        self._scatterChart.setMinimumHeight(300)
        self._scatterChart.setOption(self._buildScatterOption())

        row = QHBoxLayout()
        row.setSpacing(12)
        row.addLayout(
            self._chartTile("气泡分布（第三维映射尺寸）", self._scatterChart), 1
        )
        parent_layout.addLayout(row)

    def _buildScatterOption(self):
        def bubble(x0, y0, n, dx, dy):
            return [[x0 + dx * i, y0 + dy * i, 8 + i * 2] for i in range(n)]

        return {
            "legend": {"top": "top", "right": "right"},
            "tooltip": {"trigger": "item"},
            "xAxis": {"type": "value", "name": "X"},
            "yAxis": {"type": "value", "name": "Y"},
            "series": [
                {
                    "type": "scatter",
                    "name": "集群A",
                    "data": bubble(5, 5, 10, 1.6, 1.3),
                },
                {
                    "type": "scatter",
                    "name": "集群B",
                    "data": bubble(45, 35, 10, -1.4, 0.9),
                },
            ],
        }

    # ── 05 日历热力（Token 活动） ──────────────────────────────────────

    def _demoCalendarHeatmap(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "05. ElaChartWidget 日历热力（GitHub 风格 Token 活动）",
                self._demoCalendarHeatmap,
            )
        )
        self._addInfoText(
            "calendar 坐标系：周(列)×星期(行) 年历网格（默认周日在上，"
            "dayLabel.firstDay 可切换周一）；无数据日自动铺浅色底格"
            '（calendar.itemStyle.color 可改 / "none" 关闭）；'
            "悬停显示「日期 + 自定义文案」（数据项 tooltip.formatter）；"
            "每日 / 每周（周汇总）/ 累计（前缀和）切换；配色默认跟随主题，可切 GitHub 绿。",
            parent_layout,
        )
        self._calendar_data = _build_token_activity()
        self._calendar_mode = "daily"
        self._calendar_green = False
        self._calendar_chart = ElaChartWidget(self)
        self._calendar_chart.setMinimumHeight(240)
        self._calendar_chart.setOption(self._buildCalendarHeatmapOption())

        tile = QVBoxLayout()
        tile.setSpacing(6)
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        calendar_title = ElaText("Token 活动", self)
        calendar_title.setTextPixelSize(14)
        title_row.addWidget(calendar_title)
        title_row.addStretch()
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
        tile.addLayout(title_row)
        tile.addWidget(self._calendar_chart, 1)
        parent_layout.addLayout(tile)

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
            {
                "visualMap": self._buildCalendarHeatmapOption()["visualMap"],
            }
        )

    # ── 06 金融类图表 ───────────────────────────────────────────────────

    def _demoFinanceCharts(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "06. K线 / 箱线 / 象形柱 / 主题河", self._demoFinanceCharts
            )
        )
        self._addInfoText(
            "candlestick（红涨绿跌）、boxplot（须线 + 箱体）、pictorialBar（symbol 重复填充）、"
            "themeRiver（时间 × 系列流带）",
            parent_layout,
        )
        self._kChart = ElaChartWidget(self)
        self._kChart.setMinimumHeight(260)
        self._kChart.setOption(
            {
                "title": {"text": "K 线 · 红涨绿跌"},
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
        self._boxChart = ElaChartWidget(self)
        self._boxChart.setMinimumHeight(260)
        self._boxChart.setOption(
            {
                "title": {"text": "箱线图"},
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
        self._pictorialChart = ElaChartWidget(self)
        self._pictorialChart.setMinimumHeight(260)
        self._pictorialChart.setOption(
            {
                "title": {"text": "象形柱 · 圆形重复"},
                "xAxis": {"type": "category", "data": ["一", "二", "三", "四"]},
                "yAxis": {"type": "value"},
                "series": [
                    {
                        "type": "pictorialBar",
                        "name": "库存",
                        "data": [8, 5, 9, 4],
                        "symbol": "circle",
                        "symbolRepeat": True,
                        "symbolSize": 16,
                    }
                ],
            }
        )
        self._riverChart = ElaChartWidget(self)
        self._riverChart.setMinimumHeight(260)
        self._riverChart.setOption(
            {
                "title": {"text": "主题河"},
                "series": [
                    {
                        "type": "themeRiver",
                        "name": "流量",
                        "data": [
                            ["2015-11-08", 10, "游戏"],
                            ["2015-11-09", 15, "游戏"],
                            ["2015-11-10", 13, "游戏"],
                            ["2015-11-11", 18, "游戏"],
                            ["2015-11-08", 5, "音乐"],
                            ["2015-11-09", 8, "音乐"],
                            ["2015-11-10", 7, "音乐"],
                            ["2015-11-11", 10, "音乐"],
                            ["2015-11-08", 3, "旅游"],
                            ["2015-11-09", 6, "旅游"],
                            ["2015-11-10", 5, "旅游"],
                            ["2015-11-11", 8, "旅游"],
                        ],
                    }
                ],
            }
        )
        row1 = QHBoxLayout()
        row1.setSpacing(12)
        row1.addLayout(self._chartTile("", self._kChart), 1)
        row1.addLayout(self._chartTile("", self._boxChart), 1)
        row2 = QHBoxLayout()
        row2.setSpacing(12)
        row2.addLayout(self._chartTile("", self._pictorialChart), 1)
        row2.addLayout(self._chartTile("", self._riverChart), 1)
        parent_layout.addLayout(row1)
        parent_layout.addSpacing(12)
        parent_layout.addLayout(row2)

    # ── 07 层级图表 ─────────────────────────────────────────────────────

    def _demoHierarchyCharts(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "07. 雷达 / 仪表 / 漏斗 / 旭日 / 矩形树 / 树",
                self._demoHierarchyCharts,
            )
        )
        self._addInfoText(
            "radar（自绘蛛网）、gauge（分段色弧 + 指针）、funnel（梯形层叠）、"
            "sunburst / treemap / tree（层级数据）",
            parent_layout,
        )
        self._radarChart = ElaChartWidget(self)
        self._radarChart.setMinimumHeight(270)
        self._radarChart.setOption(
            {
                "title": {"text": "能力雷达"},
                "legend": {"top": "bottom"},
                "series": [
                    {
                        "type": "radar",
                        "name": "能力",
                        "indicator": [
                            {"name": "销售", "max": 6500},
                            {"name": "管理", "max": 16000},
                            {"name": "技术", "max": 30000},
                            {"name": "客服", "max": 38000},
                            {"name": "研发", "max": 52000},
                            {"name": "市场", "max": 25000},
                        ],
                        "data": [
                            {
                                "name": "预算",
                                "value": [4200, 3000, 20000, 35000, 50000, 18000],
                            },
                            {
                                "name": "实际",
                                "value": [5000, 14000, 28000, 26000, 42000, 21000],
                            },
                        ],
                    }
                ],
            }
        )
        self._gaugeChart = ElaChartWidget(self)
        self._gaugeChart.setMinimumHeight(270)
        self._gaugeChart.setOption(
            {
                "title": {"text": "仪表盘"},
                "series": [
                    {
                        "type": "gauge",
                        "name": "速度",
                        "data": [{"name": "速度", "value": 72}],
                        "progress": {"show": True, "width": 10},
                        "axisLine": {
                            "lineStyle": {
                                "width": 14,
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
        self._funnelChart = ElaChartWidget(self)
        self._funnelChart.setMinimumHeight(270)
        self._funnelChart.setOption(
            {
                "title": {"text": "漏斗"},
                "series": [
                    {
                        "type": "funnel",
                        "name": "转化",
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
        self._sunburstChart = ElaChartWidget(self)
        self._sunburstChart.setMinimumHeight(280)
        self._sunburstChart.setOption(
            {
                "title": {"text": "旭日图"},
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
        self._treemapChart = ElaChartWidget(self)
        self._treemapChart.setMinimumHeight(280)
        self._treemapChart.setOption(
            {
                "title": {"text": "矩形树图"},
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
        self._treeChart = ElaChartWidget(self)
        self._treeChart.setMinimumHeight(280)
        self._treeChart.setOption(
            {
                "title": {"text": "树图"},
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
        row1 = QHBoxLayout()
        row1.setSpacing(12)
        row1.addLayout(self._chartTile("", self._radarChart), 1)
        row1.addLayout(self._chartTile("", self._gaugeChart), 1)
        row1.addLayout(self._chartTile("", self._funnelChart), 1)
        row2 = QHBoxLayout()
        row2.setSpacing(12)
        row2.addLayout(self._chartTile("", self._sunburstChart), 1)
        row2.addLayout(self._chartTile("", self._treemapChart), 1)
        row2.addLayout(self._chartTile("", self._treeChart), 1)
        parent_layout.addLayout(row1)
        parent_layout.addSpacing(12)
        parent_layout.addLayout(row2)

    # ── 08 关系图表 ─────────────────────────────────────────────────────

    def _demoRelationalCharts(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "08. 桑基 / 关系图 / 平行坐标 / 地图", self._demoRelationalCharts
            )
        )
        self._addInfoText(
            "sankey（贝塞尔流带）、graph（力导 / 圆环布局，roam 缩放平移 + draggable 拖拽节点）、"
            "parallel（多维折线）、map（区域着色，示意地图，roam 缩放平移）",
            parent_layout,
        )
        self._sankeyChart = ElaChartWidget(self)
        self._sankeyChart.setMinimumHeight(280)
        self._sankeyChart.setOption(
            {
                "title": {"text": "桑基图"},
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
        self._graphChart = ElaChartWidget(self)
        self._graphChart.setMinimumHeight(280)
        self._graphChart.setOption(
            {
                "title": {"text": "关系图 · 力导"},
                "series": [
                    {
                        "type": "graph",
                        "name": "关系",
                        "layout": "force",
                        "roam": True,
                        "draggable": True,
                        "data": [
                            {"name": "核心", "symbolSize": 24},
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
        self._parallelChart = ElaChartWidget(self)
        self._parallelChart.setMinimumHeight(280)
        self._parallelChart.setOption(
            {
                "title": {"text": "平行坐标"},
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
        self._mapChart = ElaChartWidget(self)
        self._mapChart.setMinimumHeight(280)
        self._mapChart.setOption(
            {
                "title": {"text": "地图 · 示意区块"},
                "series": [
                    {
                        "type": "map",
                        "name": "区域",
                        "map": "demo",
                        "roam": True,
                        "data": [
                            {"name": "华北", "value": 120},
                            {"name": "华东", "value": 200},
                            {"name": "华南", "value": 80},
                            {"name": "西南", "value": 150},
                        ],
                    }
                ],
            }
        )
        row1 = QHBoxLayout()
        row1.setSpacing(12)
        row1.addLayout(self._chartTile("", self._sankeyChart), 1)
        row1.addLayout(self._chartTile("", self._graphChart), 1)
        row2 = QHBoxLayout()
        row2.setSpacing(12)
        row2.addLayout(self._chartTile("", self._parallelChart), 1)
        row2.addLayout(self._chartTile("", self._mapChart), 1)
        parent_layout.addLayout(row1)
        parent_layout.addSpacing(12)
        parent_layout.addLayout(row2)

    # ── 09 大数据动态采样 ───────────────────────────────────────────────

    def _demoBigData(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "09. ElaChartWidget 大数据动态采样 (tsdownsample)", self._demoBigData
            )
        )
        self._addInfoText(
            "数据量超过 threshold（默认 2000）时按当前绘图范围（x 轴数值窗口 × 画布像素宽度）"
            "动态降采样，只渲染窗口内数据；sampling 支持 ECharts 字符串"
            "（lttb / average / min / max / minmax / sum）或 dict 精细配置",
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
        inter_btn = ElaPushButton("交互: 关", self)
        inter_btn.setFixedWidth(90)
        inter_btn.clicked.connect(
            lambda: self._toggleInteraction(self._bigChart, inter_btn)
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
        for j in range(k):
            base = random.randint(300, 700)
            a1 = random.uniform(120, 260)
            w1 = random.uniform(120, 260)
            a2 = random.uniform(40, 120)
            w2 = random.uniform(25, 60)
            data = [
                base + a1 * math.sin(i / w1) + a2 * math.sin(i / w2) for i in range(n)
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

    # ── 10 交互组件 ─────────────────────────────────────────────────────

    def _demoInteractComponents(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "10. 交互组件：dataZoom / visualMap / mark* / toolbox / timeline",
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
