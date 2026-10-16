"""图表（第三方库）

包第三方绘图库的组件：实时波形（pyqtgraph）、静态图（matplotlib）、
仪表盘，以及 GraphicsScene / GraphicsView。

**ElaChartWidget 自成一体** —— 它的 10 组图表、采样、交互都在
「ElaChartWidget 图表引擎」专题页。那一页讲的是本库自己的图表
引擎，和这里的「接第三方库」是两回事。
"""

import random
import math
from PyQt6.QtWidgets import QGraphicsScene, QGraphicsView, QHBoxLayout, QVBoxLayout
from PyQt6.QtCore import QTimer, Qt
from PyQt6ElaWidgetTools import (
    ElaCheckBox,
    ElaLineEdit,
    ElaPushButton,
    ElaSlider,
    ElaText,
)
from pyqt6_ela_pro import ElaDashboardGauge, ElaPlotWidget
from .base_page import ExamplePage

try:
    import pyqtgraph  # noqa: F401

    _HAS_PYQTGRAPH = True
except ImportError:
    _HAS_PYQTGRAPH = False

try:
    import matplotlib  # noqa: F401

    _HAS_MATPLOTLIB = True
except ImportError:
    _HAS_MATPLOTLIB = False


class ChartLibPage(ExamplePage):
    """图表（第三方库）示例页。"""

    PAGE_TITLE = "图表（第三方库）"

    def __init__(self, parent=None):
        self._basicTable = None
        self._asyncTable = None
        self._styleTable = None
        self._sortTable = None
        self._sortingEnabled = False
        super().__init__(parent)

    def _addDemoContent(self, main_layout):
        self._demoPyqtgraphChart(main_layout)
        self._demoFigureCanvas(main_layout)
        self._demoDashboardGauge(main_layout)
        self._demoGraphicsView(main_layout)

    def _onPgGenerateData(self):
        if self._pg_index >= self._pg_total:
            self._pg_sim_timer.stop()
            return
        val = (
            math.sin(self._pg_t * 0.02) * 50
            + 50
            + 0.5 * math.sin(self._pg_t * 0.05) * 25
            + random.gauss(0, 1) * 5
        )
        self._pg_data_y[self._pg_index] = val
        self._pg_t += 1.0
        self._pg_index += 1

    def _onPgReset(self):
        self._pg_sim_timer.stop()
        self._pg_ui_timer.stop()
        self._pg_toggle_btn.setText("开始实时")
        self._pg_data_y = [0.0] * self._pg_total
        self._pg_t = 0.0
        self._pg_index = 0
        self._pg_curve.setData([], [])
        self._pg_plot.setXRange(0, 1000)

    def _onPgUpdatePlot(self):
        n = self._pg_index
        if n == 0:
            return
        self._pg_curve.setData(self._pg_data_x[:n], self._pg_data_y[:n])
        if self._pg_auto_scale_cb.isChecked():
            if n > 100:
                self._pg_plot.setXRange(max(0, n - 600), n + 100)
            else:
                self._pg_plot.setXRange(0, 1000)
        else:
            self._pg_plot.setXRange(0, max(n + 100, 1000))

    def _onTogglePyqtgraphRealtime(self):
        running = self._pg_sim_timer.isActive()
        if running:
            self._pg_sim_timer.stop()
            self._pg_ui_timer.stop()
            self._pg_toggle_btn.setText("开始实时")
        else:
            try:
                gen_interval = max(1, int(self._pg_gen_input.text()))
            except ValueError:
                gen_interval = 1
            try:
                ui_interval = max(10, int(self._pg_ui_input.text()))
            except ValueError:
                ui_interval = 30
            self._pg_sim_timer.setInterval(gen_interval)
            self._pg_ui_timer.setInterval(ui_interval)
            self._pg_sim_timer.start()
            self._pg_ui_timer.start()
            self._pg_toggle_btn.setText("停止实时")

    def _demoPyqtgraphChart(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "03. ela_ext - ElaPlotWidget 实时波形图 (pyqtgraph)",
                self._demoPyqtgraphChart,
            )
        )
        if not _HAS_PYQTGRAPH:
            self._addInfoText(
                "ElaPlotWidget 需要 pyqtgraph，请运行: pip install pyqtgraph",
                parent_layout,
            )
            return
        self._addInfoText(
            "基于 pyqtgraph 的高性能实时绘图，支持主题自适应\n"
            "使用 ``setDownsampling`` 自动降采样以处理大量数据点",
            parent_layout,
        )

        self._pg_widget = ElaPlotWidget(self)
        self._pg_widget.setFixedSize(600, 300)

        self._pg_plot = self._pg_widget.plot(title="实时波形 (pyqtgraph)")
        self._pg_plot.showGrid(x=True, y=True, alpha=0.5)
        self._pg_plot.setLabel("left", "幅度")
        self._pg_plot.setLabel("bottom", "sample")
        self._pg_plot.setDownsampling(mode="peak")

        self._pg_total = 40000
        self._pg_data_x = list(range(self._pg_total))
        self._pg_data_y = [0.0] * self._pg_total
        self._pg_t = 0.0
        self._pg_index = 0
        self._pg_curve = self._pg_plot.plot([], [], pen="b")

        # 数据生成 timer
        self._pg_sim_timer = QTimer(self)
        self._pg_sim_timer.setInterval(1)
        self._pg_sim_timer.timeout.connect(self._onPgGenerateData)

        # UI 刷新 timer
        self._pg_ui_timer = QTimer(self)
        self._pg_ui_timer.setInterval(30)
        self._pg_ui_timer.timeout.connect(self._onPgUpdatePlot)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        self._pg_toggle_btn = ElaPushButton("开始实时", self)
        self._pg_toggle_btn.setFixedWidth(100)
        self._pg_toggle_btn.clicked.connect(self._onTogglePyqtgraphRealtime)
        btn_layout.addWidget(self._pg_toggle_btn)
        reset_btn = ElaPushButton("重置数据", self)
        reset_btn.setFixedWidth(100)
        reset_btn.clicked.connect(self._onPgReset)
        btn_layout.addWidget(reset_btn)
        gen_label = ElaText("生成(ms):", self)
        gen_label.setTextPixelSize(14)
        btn_layout.addWidget(gen_label)
        self._pg_gen_input = ElaLineEdit(self)
        self._pg_gen_input.setFixedWidth(60)
        self._pg_gen_input.setText("1")
        btn_layout.addWidget(self._pg_gen_input)
        ui_label = ElaText("刷新(ms):", self)
        ui_label.setTextPixelSize(14)
        btn_layout.addWidget(ui_label)
        self._pg_ui_input = ElaLineEdit(self)
        self._pg_ui_input.setFixedWidth(60)
        self._pg_ui_input.setText("30")
        btn_layout.addWidget(self._pg_ui_input)
        self._pg_auto_scale_cb = ElaCheckBox("平移X轴", self)
        self._pg_auto_scale_cb.setChecked(True)
        btn_layout.addWidget(self._pg_auto_scale_cb)
        btn_layout.addStretch()
        parent_layout.addWidget(self._pg_widget)
        parent_layout.addLayout(btn_layout)

    def _onMplGenerateData(self):
        if self._mpl_index >= self._mpl_total:
            self._mpl_sim_timer.stop()
            return
        val = (
            math.sin(self._mpl_t * 0.02)
            + 0.5 * math.sin(self._mpl_t * 0.05)
            + random.gauss(0, 1) * 0.1
        )
        self._mpl_data_y[self._mpl_index] = val
        self._mpl_t += 1.0
        self._mpl_index += 1

    def _onMplReset(self):
        self._mpl_sim_timer.stop()
        self._mpl_ui_timer.stop()
        self._mpl_toggle_btn.setText("开始实时")
        self._mpl_data_y = [0.0] * self._mpl_total
        self._mpl_t = 0.0
        self._mpl_index = 0
        self._mpl_line.set_data([], [])
        self._mpl_ax.set_xlim(0, 1000)
        self._mpl_canvas.draw_idle()
        self._mpl_canvas.draw_idle()

    def _onMplUpdatePlot(self):
        n = self._mpl_index
        if n == 0:
            return
        self._mpl_line.set_data(self._mpl_data_x[:n], self._mpl_data_y[:n])
        if self._mpl_auto_scale_cb.isChecked():
            if n > 100:
                self._mpl_ax.set_xlim(max(0, n - 600), n + 100)
            else:
                self._mpl_ax.set_xlim(0, 1000)
        else:
            self._mpl_ax.set_xlim(0, max(n + 100, 1000))
        self._mpl_canvas.draw_idle()

    def _onToggleMatplotlibRealtime(self):
        running = self._mpl_sim_timer.isActive()
        if running:
            self._mpl_sim_timer.stop()
            self._mpl_ui_timer.stop()
            self._mpl_toggle_btn.setText("开始实时")
        else:
            try:
                gen_interval = max(1, int(self._mpl_gen_input.text()))
            except ValueError:
                gen_interval = 1
            try:
                ui_interval = max(10, int(self._mpl_ui_input.text()))
            except ValueError:
                ui_interval = 30
            self._mpl_sim_timer.setInterval(gen_interval)
            self._mpl_ui_timer.setInterval(ui_interval)
            self._mpl_sim_timer.start()
            self._mpl_ui_timer.start()
            self._mpl_toggle_btn.setText("停止实时")

    def _demoFigureCanvas(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "04. ela_ext - ElaFigureCanvas 图表 (matplotlib)",
                self._demoFigureCanvas,
            )
        )
        if not _HAS_MATPLOTLIB:
            self._addInfoText(
                "ElaFigureCanvas 需要 matplotlib，请运行: pip install matplotlib",
                parent_layout,
            )
            return
        from pyqt6_ela_pro import ElaFigureCanvas
        from matplotlib.backends.backend_qtagg import NavigationToolbar2QT

        self._addInfoText(
            "基于 matplotlib 的图表画布，支持主题自适应\n"
            "跟随 Ela 主题自动切换 Light/Dark 配色\n"
            "数据生成与 UI 刷新分离，使用两个 QTimer 实现流畅更新",
            parent_layout,
        )
        self._mpl_canvas = ElaFigureCanvas(self)
        self._mpl_canvas.setFixedSize(600, 300)
        self._mpl_toolbar = NavigationToolbar2QT(self._mpl_canvas, self)
        self._mpl_ax = self._mpl_canvas.figure.subplots()
        self._mpl_ax.set_xlim(0, 1000)
        self._mpl_ax.set_ylim(-2, 2)
        self._mpl_ax.set_xlabel("sample")
        self._mpl_ax.set_ylabel("value")
        self._mpl_ax.set_title("实时波形")
        self._mpl_ax.grid(True, alpha=0.7)
        self._mpl_canvas.figure.tight_layout()

        (self._mpl_line,) = self._mpl_ax.plot([], [], "b-", lw=0.5)
        self._mpl_total = 40000
        self._mpl_data_x = list(range(self._mpl_total))
        self._mpl_data_y = [0.0] * self._mpl_total
        self._mpl_t = 0.0
        self._mpl_index = 0

        # 数据生成 timer（高频）
        self._mpl_sim_timer = QTimer(self)
        self._mpl_sim_timer.setInterval(1)
        self._mpl_sim_timer.timeout.connect(self._onMplGenerateData)

        # UI 刷新 timer（低频）
        self._mpl_ui_timer = QTimer(self)
        self._mpl_ui_timer.setInterval(30)
        self._mpl_ui_timer.timeout.connect(self._onMplUpdatePlot)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        self._mpl_toggle_btn = ElaPushButton("开始实时", self)
        self._mpl_toggle_btn.setFixedWidth(100)
        self._mpl_toggle_btn.clicked.connect(self._onToggleMatplotlibRealtime)
        btn_layout.addWidget(self._mpl_toggle_btn)
        reset_btn = ElaPushButton("重置数据", self)
        reset_btn.setFixedWidth(100)
        reset_btn.clicked.connect(self._onMplReset)
        btn_layout.addWidget(reset_btn)
        gen_label = ElaText("生成(ms):", self)
        gen_label.setTextPixelSize(14)
        btn_layout.addWidget(gen_label)
        self._mpl_gen_input = ElaLineEdit(self)
        self._mpl_gen_input.setFixedWidth(60)
        self._mpl_gen_input.setText("1")
        btn_layout.addWidget(self._mpl_gen_input)
        ui_label = ElaText("刷新(ms):", self)
        ui_label.setTextPixelSize(14)
        btn_layout.addWidget(ui_label)
        self._mpl_ui_input = ElaLineEdit(self)
        self._mpl_ui_input.setFixedWidth(60)
        self._mpl_ui_input.setText("30")
        btn_layout.addWidget(self._mpl_ui_input)
        self._mpl_auto_scale_cb = ElaCheckBox("平移X轴", self)
        self._mpl_auto_scale_cb.setChecked(True)
        btn_layout.addWidget(self._mpl_auto_scale_cb)
        btn_layout.addStretch()
        parent_layout.addWidget(self._mpl_toolbar)
        parent_layout.addWidget(self._mpl_canvas)
        parent_layout.addLayout(btn_layout)

    def _onGaugeSetValue(self, val):
        self._gauge.setValue(val)
        self._gauge_slider.setValue(val)
        self._gauge_val_label.setText(f"值: {int(val)}")

    def _onGaugeSliderChanged(self, val):
        self._gauge.setValue(val)
        self._gauge_val_label.setText(f"值: {int(val)}")

    def _onGaugeTick(self):
        self._gauge_tick_val += self._gauge_tick_dir * 10
        if self._gauge_tick_val >= self._gauge.maximum():
            self._gauge_tick_val = self._gauge.maximum()
            self._gauge_tick_dir = -1
        elif self._gauge_tick_val <= self._gauge.minimum():
            self._gauge_tick_val = self._gauge.minimum()
            self._gauge_tick_dir = 1
        self._gauge_val_label.setText(f"值: {int(self._gauge_tick_val)}")
        self._gauge_slider.setValue(int(self._gauge_tick_val))
        self._gauge.setValue(self._gauge_tick_val)

    def _onToggleGaugeAuto(self):
        if self._gauge_timer.isActive():
            self._gauge_timer.stop()
            self._gauge_auto_btn.setText("自动扫描")
        else:
            self._gauge_tick_val = self._gauge.value()
            self._gauge_tick_dir = 1
            self._gauge_timer.start()
            self._gauge_auto_btn.setText("停止扫描")

    def _demoDashboardGauge(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "05. ela_ext - ElaDashboardGauge 仪表盘", self._demoDashboardGauge
            )
        )
        self._addInfoText(
            "全 QPainter 自绘仪表盘，支持弧形刻度、指针、颜色分段和动画过渡",
            parent_layout,
        )

        self._gauge = ElaDashboardGauge(self)
        self._gauge.setMinimum(0)
        self._gauge.setMaximum(1000)
        self._gauge.setValue(0)
        self._gauge.setTitle("引擎转速")
        self._gauge.setUnit("r/min")
        self._gauge.setDangerPercent(0.9)
        self._gauge.setWarningPercent(0.7)

        gauge_layout = QHBoxLayout()
        gauge_layout.setSpacing(15)
        gauge_layout.addWidget(self._gauge)

        control_layout = QVBoxLayout()
        control_layout.setSpacing(8)

        val_label = ElaText("值: 0", self)
        val_label.setTextPixelSize(18)
        font = val_label.font()
        font.setBold(True)
        val_label.setFont(font)
        control_layout.addWidget(val_label)
        self._gauge_val_label = val_label

        self._gauge_slider = ElaSlider(Qt.Orientation.Horizontal, self)
        self._gauge_slider.setMinimum(0)
        self._gauge_slider.setMaximum(1000)
        self._gauge_slider.setValue(0)
        self._gauge_slider.setFixedWidth(200)
        self._gauge_slider.valueChanged.connect(self._onGaugeSliderChanged)
        control_layout.addWidget(self._gauge_slider)

        size_label = ElaText("表盘尺寸:", self)
        size_label.setTextPixelSize(14)
        control_layout.addWidget(size_label)

        btn_size = QHBoxLayout()
        btn_size.setSpacing(8)
        for s in [100, 150, 200, 260, 300, 350]:
            btn = ElaPushButton(str(s), self)
            btn.setFixedWidth(50)
            btn.clicked.connect(lambda checked, x=s: self._gauge.setFixedSize(x, x))
            btn_size.addWidget(btn)
        control_layout.addLayout(btn_size)

        btn_row2 = QHBoxLayout()
        btn_row2.setSpacing(8)
        self._gauge_auto_btn = ElaPushButton("自动扫描", self)
        self._gauge_auto_btn.setFixedWidth(100)
        self._gauge_auto_btn.clicked.connect(self._onToggleGaugeAuto)
        btn_row2.addWidget(self._gauge_auto_btn)
        reset_btn = ElaPushButton("归零", self)
        reset_btn.setFixedWidth(70)
        reset_btn.clicked.connect(lambda: self._onGaugeSetValue(0))
        btn_row2.addWidget(reset_btn)
        control_layout.addLayout(btn_row2)
        control_layout.addStretch()

        gauge_layout.addLayout(control_layout)
        gauge_layout.addStretch()
        parent_layout.addLayout(gauge_layout)

        self._gauge_timer = QTimer(self)
        self._gauge_timer.setInterval(50)
        self._gauge_timer.timeout.connect(self._onGaugeTick)
        self._gauge_tick_val = 0.0
        self._gauge_tick_dir = 1

    def _demoGraphicsView(self, parent_layout):
        from PyQt6.QtGui import QColor, QBrush, QPen

        parent_layout.addLayout(
            self._createHeaderRow(
                "06. PyQt6ElaWidgetTools - ElaGraphicsScene / ElaGraphicsView 图形视图",
                self._demoGraphicsView,
            )
        )
        self._addInfoText(
            "Ela 主题的图形视图框架，支持场景中放置可交互的图形项", parent_layout
        )
        scene = QGraphicsScene(self)
        scene.setSceneRect(-200, -200, 400, 400)
        view = QGraphicsView(self)
        view.setScene(scene)
        view.setFixedHeight(300)
        view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)

        rect = view.scene().addRect(
            -60, -60, 120, 120, QPen(QColor("#1677ff"), 2), QBrush(QColor("#e6f4ff"))
        )
        rect.setFlag(rect.GraphicsItemFlag.ItemIsMovable, True)
        rect.setFlag(rect.GraphicsItemFlag.ItemIsSelectable, True)

        circle = view.scene().addEllipse(
            -50, -50, 100, 100, QPen(QColor("#52c41a"), 2), QBrush(QColor("#f6ffed"))
        )
        circle.setPos(150, 0)
        circle.setFlag(circle.GraphicsItemFlag.ItemIsMovable, True)
        circle.setFlag(circle.GraphicsItemFlag.ItemIsSelectable, True)

        from PyQt6.QtGui import QPainterPath

        tp = QPainterPath()
        tp.moveTo(0, -50)
        tp.lineTo(50, 50)
        tp.lineTo(-50, 50)
        tp.closeSubpath()
        triangle = view.scene().addPath(
            tp, QPen(QColor("#fa8c16"), 2), QBrush(QColor("#fff7e6"))
        )
        triangle.setPos(-150, 100)
        triangle.setFlag(triangle.GraphicsItemFlag.ItemIsMovable, True)
        triangle.setFlag(triangle.GraphicsItemFlag.ItemIsSelectable, True)

        parent_layout.addWidget(view)
        parent_layout.addSpacing(20)
