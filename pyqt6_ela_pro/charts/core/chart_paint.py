"""ElaChartWidget 的绘制 / 系列层缓存 / loading / 基准方法组。"""

from __future__ import annotations

from typing import TYPE_CHECKING


from ..._internal import is_deleted
from PyQt6.QtCore import (
    QRectF,
    Qt,
)
from PyQt6.QtGui import (
    QColor,
    QFontMetricsF,
    QImage,
    QPainter,
    QPen,
)
from PyQt6ElaWidgetTools import eTheme

from ..._motion import start_idle_loop
from ..option import (
    _series_data_len,
    _series_geom_len,
    _series_type_name,
)
from .._tokens import (
    SPINNER_TICK_MS,
    T,
)
from .._utils import parse_color, text_italic, warn_key, warn_once
from ..layout import layout_all
from ..axes import (
    chartFont,
)
from ._shared import (
    _elapsed_ms,
    _now,
)


if TYPE_CHECKING:
    pass


class _ChartPaintMixin:
    """方法组 mixin：状态由 ``ElaChartWidget.__init__`` 建立。"""

    def showLoading(self, type: str = "default", opts: dict = None) -> None:
        """显示加载遮罩（ECharts ``showLoading``）。

        opts：``text`` / ``color`` / ``textColor`` / ``maskColor`` /
        ``fontSize`` / ``showSpinner`` / ``spinnerRadius`` / ``lineWidth``。
        """
        self._loading = True
        self._loading_type = str(type or "default")
        self._loading_opts = dict(opts or {})
        if self._loading_opts.get("showSpinner", True):
            # 持续动效：Reduced/Disabled 下不转。角度冻结在当前值 —— 遮罩与文字
            # 都照常画，只是不再转，所以看起来是「有遮罩但静止」。
            start_idle_loop(self._spinner_timer, SPINNER_TICK_MS)
        self.update()

    def hideLoading(self) -> None:
        """隐藏加载遮罩（ECharts ``hideLoading``）。"""
        self._spinner_timer.stop()
        self._loading = False
        self._loading_opts = {}
        self.update()

    @property
    def isLoading(self) -> bool:
        """当前是否显示加载遮罩（扩展查询）。"""
        return bool(self._loading)

    def _tick_spinner(self) -> None:
        if self._disposed or is_deleted(self):
            return
        self._spinner_angle = (self._spinner_angle + 12) % 360
        self.update()

    def _paint_loading(self, p: QPainter) -> None:
        opts = self._loading_opts
        mask = parse_color(opts.get("maskColor") or QColor(T("color.bg.base")))
        if not opts.get("maskColor"):
            mask.setAlpha(204)
        p.fillRect(self.rect(), mask)
        font_size = float(opts.get("fontSize", T("font.sm")))
        font = chartFont(
            font_size,
            None,
            opts.get("fontFamily") or self.fontFamily(),
            text_italic(opts.get("fontStyle")),
        )
        p.setFont(font)
        text = str(opts.get("text", "加载中"))
        fm = QFontMetricsF(font)
        text_w = fm.horizontalAdvance(text) if text else 0.0
        if opts.get("showSpinner", True) and self._loading_type != "none":
            radius = max(6.0, float(opts.get("spinnerRadius", 14)))
            line_w = max(1.0, float(opts.get("lineWidth", 3)))
            color = parse_color(opts.get("color") or T("color.primary"))
            pen = QPen(color, line_w)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            cx = self.width() / 2
            cy = self.height() / 2 - (fm.height() / 2 if text else 0.0)
            p.drawArc(
                QRectF(cx - radius, cy - radius, radius * 2, radius * 2),
                int(90 - self._spinner_angle) * 16,
                270 * 16,
            )
        if text:
            p.setPen(parse_color(opts.get("textColor") or T("color.text.secondary")))
            p.drawText(
                QRectF(
                    self.width() / 2 - max(120.0, text_w) / 2 - 10,
                    self.height() / 2 + fm.height() / 2 + 2,
                    max(120.0, text_w) + 20,
                    fm.height() + 2,
                ),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                text,
            )

    def benchmark(
        self,
        frames: int = 8,
        forceLayout: bool = True,
        perSeries: bool = True,
    ) -> dict:
        """性能剖析：分项测量各阶段耗时（诊断用，不改变任何状态）。

        **为什么需要它**：大数据量下「慢」的归因必须靠实测，不能猜。本机
        100 万点 / 单系列实测（offscreen，1200x700）::

            ingestMs  15.0    摄入（setOption 全程）
            layoutMs  19.6    布局（坐标 + 系列几何，含采样与坐标映射）
            paintMs  107.4    绘制（纯光栅化，画到离屏 QImage）
            frameMs  127.0    → 远超 60 Hz 预算 16.7 ms

        **关键结论：瓶颈在绘制，不在点数也不在摄入。** 采样后只画 2256 个
        点却仍要 107 ms —— 说明成本来自「每段抗锯齿折线的光栅化」而非点数
        规模。因此优化方向是绘制阶段（分层位图缓存 / GPU 直绘），而不是
        继续优化采样或数据摄入。

        :param frames: 重复帧数（取平均，降低单帧噪声）。默认 8。
        :param forceLayout: 每次都强制重排（``_layout_all(force=True)``），
            绕过布局缓存。传 ``False`` 测的是「命中缓存的稳态」——那才是
            悬停 / 动画期的真实成本。
        :param perSeries: 是否额外测**每条系列**的布局 / 绘制耗时。多系列
            场景下总耗时只说明「慢」，逐系列读数才能定位到具体哪条曲线。
        :returns: 各项耗时（毫秒）与规模信息。**所有时间单位为毫秒（ms）**。
            ``seriesTimings`` 为逐系列读数（``perSeries=False`` 时为 ``[]``），
            每项含 ``name`` / ``type`` / ``dataPoints`` / ``drawnPoints`` /
            ``layoutMs`` / ``paintMs``。键集合由测试钉住。
        """
        frames = max(1, int(frames))
        # 记录需复原的状态。``setOption(notMerge=True)`` 内部会重置图例
        # 选中态（``_series_state``）并重新起动画，所以二者都要在测量
        # **之后**按调用前的值覆盖，否则 benchmark 会顺手改掉用户的图例。
        was_anim = self.anim.isRunning()
        saved_state = dict(self._series_state)
        # 悬浮提示：``notMerge`` 会 ``tooltip.hide()``。tooltip 自身持有
        # 全部状态，直接留一个对象引用即可复原。
        saved_tip = (
            self.tooltip,
            self.tooltip.active,
            self.tooltip._pos,
            self.tooltip._lines,
            self.tooltip._marker_pos,
        )
        try:
            # 固定到终态：动画每帧都在变，会让布局缓存永久失效，测出来的
            # 是「动画中」而非「稳态」的成本。
            self.anim.stop()
            self.anim.setProgress(1.0)
            # -- 摄入：setOption 全程（含合并 / 快照 / 重建） --
            t0 = _now()
            self.setOption(self._option, notMerge=True)
            ingest_ms = _elapsed_ms(t0)
            self.anim.stop()
            self.anim.setProgress(1.0)
            # ``notMerge`` 清空了图例选中态，测量前先复原 —— 否则被隐藏的
            # 系列也会被计入布局 / 绘制耗时。
            self._series_state = dict(saved_state)
            for r in self._series:
                r.visible = self._seriesVisible(r.name)
            # -- 布局：坐标系 + 系列几何（含采样与坐标映射） --
            t0 = _now()
            for _ in range(frames):
                self._layout_all(force=forceLayout)
            layout_ms = _elapsed_ms(t0) / frames
            # -- 绘制：坐标轴 + 系列 + 组件（不含布局） --
            t0 = _now()
            for _ in range(frames):
                self._render_to_painter()
            paint_ms = _elapsed_ms(t0) / frames
            # -- 逐系列：定位到具体哪条曲线慢（多系列时的关键读数） --
            series_timings = self._benchmark_series() if perSeries else []
        finally:
            # 复原图例选中态与悬浮提示（``notMerge`` 会清空两者）
            self._series_state = dict(saved_state)
            tip, was_active, pos, lines, marker = saved_tip
            if was_active:
                tip.showAt(pos, list(lines), marker)
            else:
                tip.hide()
            # 复原动画状态：调用前在跑 → 重新起；否则保持停止。
            if was_anim:
                self.anim.start()
            else:
                self.anim.stop()
                self.anim.setProgress(1.0)
        return self._benchmark_reduce(ingest_ms, layout_ms, paint_ms, series_timings)

    def _benchmark_series(self) -> list:
        """逐系列测量布局 / 绘制耗时（每项跑一轮，不取平均）。

        多系列场景下总耗时只回答「慢不慢」，答不出「哪条慢」。本方法把每条
        可见系列**单独**跑一遍布局与绘制，代价是总耗时约翻倍（仅诊断时用）。

        每条系列独测：关掉其余系列的可见性，避免把邻居的成本算到它头上
        （先画的系列会受益于「后画的还没覆盖这块区域」，同测才有可比性）。

        **只跑一轮**，不按 ``frames`` 取平均：逐系列读数用于横向比较「谁更
        慢」，量级差异远大于单轮噪声；而重复取平均在 8 系列 × 20 万点下会
        把一次 benchmark 拖到分钟级（实测 ``_render`` 单轮 122 ms）。

        **``layoutMs`` 读数含「其余系列被隐藏」的重排成本**：折线系列的
        布局会扫描全量 ``series_opts`` 重建槽位，故单测一条线时该值仍与
        总系列数相关（实测各折线均为 ~660 ms，而总布局 635 ms）。故该值
        只宜**横向比较同一批读数**（同轮、同条件），不可当作「这条线的
        布局绝对成本」。``paintMs`` 无此问题（绘制确实只画可见系列）。
        """
        out = []
        saved_state = dict(self._series_state)
        # 在进入循环前**快照**目标列表：循环内会把 ``r.visible`` 置为
        # False，而那正是循环的跳过条件 —— 直接遍历 ``self._series`` 会
        # 在第一轮之后全部被跳过（实测 3 条系列只返回 1 条）。
        targets = [r for r in self._series if getattr(r, "visible", True)]
        try:
            for target in targets:
                # 只留目标系列可见
                for r in self._series:
                    r.visible = r is target
                # 布局跑一次即可拿到几何 —— 逐系列读数要的是「这条线自身
                # 多贵」，重复 frames 轮取平均在多系列大数据下会拖到分钟级
                # （8 系列 × 6 帧实测 16 s），而布局幂等、单轮噪声远小于
                # 系列间的量级差异。
                self.invalidateLayout()
                t0 = _now()
                self._layout_all(force=True)
                s_layout = _elapsed_ms(t0)
                # 绘制同理跑一次。
                t0 = _now()
                self._render_to_painter()
                s_paint = _elapsed_ms(t0)
                out.append(
                    {
                        "name": str(target.name),
                        "type": _series_type_name(target),
                        "dataPoints": _series_data_len(target),
                        "drawnPoints": _series_geom_len(target),
                        "layoutMs": round(s_layout, 3),
                        "paintMs": round(s_paint, 3),
                    }
                )
        finally:
            self._series_state = dict(saved_state)
            for r in self._series:
                r.visible = self._seriesVisible(r.name)
            self.invalidateLayout()
        # 按「每单位几何的绘制成本」降序：多系列下真正可比的指标是密度，
        # 绝对 paintMs 会被图元数直接带偏（bar 20k 图元 515 ms vs 折线
        # 2256 点 32 ms，看着差 16 倍，实际每图元只差 3 倍）。
        out.sort(key=lambda d: -(d["paintMs"] / max(1, d["drawnPoints"])))
        return out

    def _render_to_painter(self) -> None:
        """把当前内容画到离屏 QImage（走与 ``paintEvent`` 相同的绘制路径）。

        不直接用 ``paintEvent``：那需要真实可见的控件，且 Qt 的合成 /
        窗口交换等待会计入读数，把「算法成本」和「系统等待」混在一起。
        """
        img = QImage(
            max(1, self.width()),
            max(1, self.height()),
            QImage.Format.Format_ARGB32_Premultiplied,
        )
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            self._paint_content(p)
        finally:
            p.end()

    def _benchmark_reduce(self, ingest_ms, layout_ms, paint_ms, series_timings) -> dict:
        """汇总 benchmark 结果。

        返回键集合**固定**（由 ``tests/ela_chart_widget/test_chart_benchmark.py``
        钉住）—— 诊断接口靠 key 取值，键悄悄变动会让调用方静默拿到 ``None``，
        比没有这个接口更糟。

        规模字段的口径：

        - ``dataPoints``：**单个可见系列**的最大数据量（多系列时不是总和；
          ``totalDataPoints`` 才是总和）；
        - ``drawnPoints``：所有可见系列**实际绘制**的点数之和（已被采样
          压缩到视口像素量级，故远小于数据量）；
        - ``seriesTimings``：逐系列读数，按 ``paintMs`` 降序（最慢的在前），
          用于定位具体是哪条曲线吃掉了帧时间。
        """
        largest = 0
        total_data = 0
        drawn = 0
        visible = 0
        series_kinds = {}
        for r in self._series:
            if not getattr(r, "visible", True):
                continue
            visible += 1
            kind = _series_type_name(r)
            series_kinds[kind] = series_kinds.get(kind, 0) + 1
            n = _series_data_len(r)
            largest = max(largest, n)
            total_data += n
            drawn += _series_geom_len(r)
        return {
            # -- 耗时（毫秒） --
            "ingestMs": round(ingest_ms, 3),
            "layoutMs": round(layout_ms, 3),
            "paintMs": round(paint_ms, 3),
            "frameMs": round(layout_ms + paint_ms, 3),
            # -- 规模 --
            "dataPoints": largest,
            "totalDataPoints": total_data,
            "drawnPoints": drawn,
            "seriesCount": visible,
            "seriesKinds": series_kinds,
            "width": int(self.width()),
            "height": int(self.height()),
            "dpr": self.getDevicePixelRatio(),
            "frameBudget60HzMs": round(1000.0 / 60.0, 3),
            # -- 逐系列（按每图元绘制成本降序） --
            "seriesTimings": series_timings,
        }

    def _content_rect(self) -> QRectF:
        """扣除全部标题 / 图例后的坐标系可用区（多实例逐个占条带）。"""
        rect = QRectF(0, 0, max(1, self.width()), max(1, self.height()))
        content = QRectF(rect)
        # 标题：顶部 / 底部各取最大占用（同侧多个按各自锚点覆盖，不叠加）
        for title in self.titles:
            band = title.bandRect(rect.width(), rect.height())
            if band.isNull():
                continue
            if title.atBottom:
                content.setBottom(max(content.top() + 1.0, band.top()))
            else:
                content.setTop(min(content.bottom() - 1.0, band.bottom()))
        # 图例：同侧多个依次向外堆叠条带
        top_legends = []
        bottom_legends = []
        left_legends = []
        right_legends = []
        for legend in self.legends:
            if not legend.shown:
                continue
            if legend.orient == "horizontal":
                if "top" in legend.opt:
                    top_legends.append(legend)
                else:
                    bottom_legends.append(legend)
            else:
                if "left" in legend.opt:
                    left_legends.append(legend)
                else:
                    right_legends.append(legend)
        for legend in top_legends:
            _lw, lh = legend.preferredSize(content.width(), content.height())
            band = QRectF(content.left(), content.top(), content.width(), lh)
            content.setTop(content.top() + lh)
            legend.layout(band)
        for legend in bottom_legends:
            _lw, lh = legend.preferredSize(content.width(), content.height())
            band = QRectF(content.left(), content.bottom() - lh, content.width(), lh)
            content.setBottom(content.bottom() - lh)
            legend.layout(band)
        for legend in left_legends:
            lw, _lh = legend.preferredSize(content.width(), content.height())
            band = QRectF(content.left(), content.top(), lw, content.height())
            content.setLeft(content.left() + lw)
            legend.layout(band)
        for legend in right_legends:
            lw, _lh = legend.preferredSize(content.width(), content.height())
            band = QRectF(content.right() - lw, content.top(), lw, content.height())
            content.setRight(content.right() - lw)
            legend.layout(band)
        return content

    def invalidateLayout(self) -> None:
        """使布局缓存失效（下次绘制 / 布局时全量重排）。

        同时递增 ``_geometry_epoch``（进 ``_series_layer_key``）—— 渲染器除了
        图表级状态还有自己那份几何（下钻焦点、roam 平移缩放、treemap / sankey
        布局），那些变更一律经本方法通知，否则系列层位图会被原样贴回
        （实测旭日图下钻后位图逐字节不变，表现为「点了没反应」）。
        「哪些状态必须走这里」的清单见 AGENTS.md「charts」。
        """
        self._layout_key = None
        self._geometry_epoch += 1

    def _layout_all(self, force: bool = False) -> None:
        layout_all(self, force)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._annotation_editor is not None and self._annotation_editor.isVisible():
            self._hide_annotation_editor()
        self._layout_all()
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            p.fillRect(self.rect(), self._background_color())
            self._layout_all()
            self._paint_content(p)
        except Exception as exc:  # noqa: BLE001
            # **这里原来只有 try/finally 没有 except** —— 任何漏网的异常都会
            # 穿过 Qt 回调边界 = 0xC0000409 静默终止（零 traceback）。
            # 已知入口：``backgroundColor`` 传 list / dict 时 ``QColor(bg)`` 抛
            # TypeError，而它在 ``_paint_content`` 的逐块守卫之外。
            # 绘制失败退化成「这一帧画得不全」，不能拖垮整个进程。
            warn_once("paint-event", f"绘制异常（已跳过本帧剩余内容）: {exc!r}")
        finally:
            # 无论任何绘制路径抛异常，QPainter 都必须收尾，
            # 否则后续绘制状态被污染会导致 Qt 崩溃
            p.end()

    def _background_color(self) -> QColor:
        """``backgroundColor`` → QColor，非法值回退主题底色。

        宿主可能传 list / dict / 任何非 str 值（``QColor(list)`` 是 TypeError），
        所以这里不能直接构造。
        """
        bg = self._option.get("backgroundColor")
        if isinstance(bg, QColor):
            return parse_color(bg)
        if isinstance(bg, str) and bg.strip():
            color = parse_color(bg)
            if color.isValid():
                return color
            warn_once(
                "background-color", f"backgroundColor 非法，已回退主题底色: {bg!r}"
            )
        return QColor(T("color.bg.base"))

    def _series_layer_key(self):
        """系列层位图缓存键（``None`` 表示本帧不缓存）。

        **只包含影响系列外观的状态**：option 版本 / ``_geometry_epoch`` /
        视口尺寸 / 主题 / dataZoom 窗口 / 逐系列可见性 / hover 命中 / 动画进度。
        后两项（hover、几何纪元）少一个就会「贴回旧外观」，逐项理由与踩坑见
        AGENTS.md「charts」。
        """
        if self.anim.isRunning():
            return None  # 动画每帧几何都在变，缓存无意义
        hover = None
        if self._hover is not None:
            r, hit = self._hover
            hover = (
                id(r),
                str(r.name),
                hit.get("dataIndex") if isinstance(hit, dict) else None,
            )
        axis_hover = (
            tuple(
                (id(r), hit.get("dataIndex") if isinstance(hit, dict) else None)
                for r, hit in self._axis_hover
            )
            or None
        )
        return (
            self._opt_version,
            self._geometry_epoch,
            self.width(),
            self.height(),
            round(self.getDevicePixelRatio(), 4),
            eTheme.getThemeMode(),
            self._series_layer_key_zoom(),
            tuple((id(r), r.visible) for r in self._series),
            hover,
            axis_hover,
            self._selection_epoch,
            # 图例悬停高亮会改系列不透明度 → 必须进键，否则贴回旧外观
            self._legend_hover,
        )

    def _series_layer_key_zoom(self):
        """dataZoom 窗口（影响采样与坐标映射）。"""
        return tuple(
            (getattr(c, "start", 0.0), getattr(c, "end", 100.0))
            for c in self._components
            if getattr(c, "optionKey", "") == "dataZoom"
        )

    def _paint_series_cached(self, p: QPainter, t: float) -> None:
        """绘制系列层（命中缓存则整幅位图贴回）。

        为什么值得：实测 8 系列 × 20 万点（1200×700）单帧绘制中
        **系列占 99.7%**（914 ms/3 帧 vs 坐标轴 2.9 ms/3 帧）。而悬停
        每移动一像素就 ``update()`` 一次 —— 200 次移动实测 40.7 秒
        （每次 203 ms），交互完全不可用。

        缓存命中时只做一次 ``drawImage``，悬停 / 动画期的重绘成本从
        「重建全部折线路径」降到「贴一张位图」。

        失效条件全部在 ``_series_layer_key`` 里；坐标轴、组件、图例、
        标题、tooltip **不缓存**（它们要么本来就便宜，要么逐帧变化）。
        """
        key = self._series_layer_key()
        if key is None:
            self._paint_series(p, t)
            return
        if self._series_pixmap_cache is not None and self._series_pixmap_key == key:
            p.drawImage(0, 0, self._series_pixmap_cache)
            return
        w, h = max(1, self.width()), max(1, self.height())
        dpr = self.getDevicePixelRatio()
        # 每维都要 ``max(1, ...)``：DPR < 1 时 ``int(round(1 * 0.5))`` 走银行家
        # 舍入得 **0**，QImage(0, h) 是空图，QPainter 画上去什么都不出 ——
        # 而外面那层 ``max(1, self.width())`` 让人以为已经防住了。
        img = QImage(
            max(1, int(round(w * dpr))),
            max(1, int(round(h * dpr))),
            QImage.Format.Format_ARGB32_Premultiplied,
        )
        img.setDevicePixelRatio(dpr)
        img.fill(Qt.GlobalColor.transparent)
        p2 = QPainter(img)
        try:
            p2.setRenderHint(QPainter.RenderHint.Antialiasing)
            p2.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            self._paint_series(p2, t)
        finally:
            p2.end()
        self._series_pixmap_cache = img
        self._series_pixmap_key = key
        p.drawImage(0, 0, img)

    def _paint_series(self, p: QPainter, t: float) -> None:
        """逐系列绘制（单系列异常不影响整图，且至少可见一次）。

        图例悬停高亮（``_legend_hover``）：命中系列正常绘制，其余降到 35%
        不透明度 —— 对齐 Plotly「悬停图例条目高亮对应 trace」的行为。
        """
        highlight = self._legend_hover
        focus_series = None
        focus_scope = "coordinateSystem"
        if self._hover is not None:
            hovered = self._hover[0]
            if hovered.emphasisFocus() == "series":
                focus_series = hovered
                focus_scope = hovered.blurScope()
        for r in self._series:
            if not r.visible:
                continue
            try:
                # 记下本次进度：命中分发可能发生在下一帧 paint 之前
                r._anim_t = r.animProgress(t)
                if highlight is not None:
                    p.setOpacity(1.0 if r.name == highlight else 0.35)
                elif (
                    focus_series is not None
                    and focus_scope != "series"
                    and r is not focus_series
                ):
                    p.setOpacity(0.35)
                r.paint(p, r._anim_t)
            except Exception as exc:
                warn_once(
                    warn_key(
                        "series-paint", r.__class__.__name__, r.name, type(exc).__name__
                    ),
                    f"系列绘制异常（{r.name}）: {exc!r}",
                )
            finally:
                if highlight is not None or focus_series is not None:
                    p.setOpacity(1.0)

    def invalidateSeriesLayer(self) -> None:
        """使系列层位图缓存失效（数据 / 主题 / 尺寸变化时调用）。"""
        self._series_pixmap_cache = None
        self._series_pixmap_key = None

    def _paint_content(self, p: QPainter) -> None:
        """内容绘制体（坐标轴 → 系列 → 组件 → 图例/标题/提示框/遮罩）。

        从 ``paintEvent`` 抽出，使 ``benchmark`` 能画到离屏 QImage 上测
        **纯绘制成本**（不掺入窗口合成 / 交换等待）。**绘制顺序不可调换**
        （画家算法）。
        """
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        t = self.anim.t
        for c in self._coords:
            try:
                c.paintAxes(p)
            except Exception as exc:
                # 坐标绘制异常不能中断整帧：记录并跳过（否则 QPainter
                # 未收尾会污染绘制状态导致 Qt 崩溃）
                warn_once(
                    f"coord-paint:{c.__class__.__name__}",
                    f"坐标绘制异常（{c.__class__.__name__}）: {exc!r}",
                )
        self._paint_series_cached(p, t)
        for comp in self._components:
            paint = getattr(comp, "paint", None)
            if callable(paint):
                try:
                    paint(p, t)
                except TypeError:
                    try:
                        paint(p)
                    except Exception as exc:
                        warn_once(
                            f"component-paint:{comp.__class__.__name__}",
                            f"组件绘制异常（{comp.__class__.__name__}）: {exc!r}",
                        )
                except Exception as exc:
                    warn_once(
                        f"component-paint:{comp.__class__.__name__}",
                        f"组件绘制异常（{comp.__class__.__name__}）: {exc!r}",
                    )
        for legend in self.legends:
            try:
                legend.paint(p)
            except Exception as exc:
                warn_once("legend-paint", f"图例绘制异常: {exc!r}")
        for title in self.titles:
            try:
                title.paint(p, title.bandRect(self.width(), self.height()))
            except Exception as exc:
                warn_once("title-paint", f"标题绘制异常: {exc!r}")
        try:
            self.tooltip.paint(p)
        except Exception as exc:
            warn_once("tooltip-paint", f"提示框绘制异常: {exc!r}")
        if self._loading:
            try:
                self._paint_loading(p)
            except Exception as exc:
                warn_once("loading-paint", f"加载遮罩绘制异常: {exc!r}")
