"""
蓝图节点控件（绑定 ``ElaBlueprintNode``）。

节点外观全部以「逻辑坐标」自绘，画布缩放时控件几何 = 逻辑矩形 × zoom，
``paintEvent`` 内 ``painter.scale`` 同步缩放（高 DPI / 任意缩放清晰）；
引脚热区 ``ElaPinHandle`` 是真实子控件（透明），画布据其全局坐标画线、
并以其接收鼠标按下。运行状态视觉：running = 标题栏旋转圈 + accent 脉冲
描边；done = success 描边 + 耗时徽标；error = danger 描边 + 错误图标。

移植自 InstructionX_UIKit.blueprint.node_widget（原库为 PyQt6，
类名 Ela* 前缀；主题令牌经 blueprint._tokens 适配 eTheme；
旋转圈为内置精简 SpinnerArc；原库无 LICENSE，保留出处）。
"""

from __future__ import annotations

import logging
import math

from PyQt6.QtCore import QPointF, QRectF, QSizeF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import QFrame, QVBoxLayout, QWidget

from .._motion import start_idle_loop
from ._spinner import SpinnerArc
from ._tokens import T, theme_changed_slot
from .model import ElaBlueprintNode, ElaPinDirectionType
from .registry import ElaNodeRegistry, pin_color

logger = logging.getLogger(__name__)

__all__ = ["ElaNodeWidget", "ElaPinHandle", "format_elapsed"]

#: 逻辑尺寸常量（px，缩放由画布视图系数负责）
TITLE_H = 28.0
PIN_ROW_H = 24.0
PIN_DOT_R = 5.0
PIN_HANDLE = 18.0
PAD_X = 10.0
PAD_BOTTOM = 8.0
BODY_LINE_H = 20.0
MIN_W = 160.0
SPINNER_SIZE = 14.0
#: 节点体可见的最低画布缩放（低于此隐藏体容器，仅保留标题栏 + 引脚）
BODY_MIN_ZOOM = 0.8
#: running 脉冲描边周期（ms）
PULSE_MS = 320


def _finite(value) -> bool:
    """值是否可安全转 float（挡掉 NaN / inf / 不可转对象）。"""
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def _to_int(value, default: int = 0) -> int:
    """把外部数值安全转 int：不可转 / 非有限一律给 ``default``。

    ``int(float("inf"))`` 抛的 ``OverflowError`` 继承 ``ArithmeticError``，
    **不是** ``ValueError`` 的子类 —— 只写 ``except (TypeError, ValueError)``
    的地方它会直接穿出去。凡是「外部数据 → int」都走这里。
    """
    try:
        out = int(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return out


def _transparent(widget: QWidget) -> None:
    """让控件背景真正透明（不铺底、也不走 QSS 的 styled background）。"""
    widget.setAutoFillBackground(False)


def _resolve_color(value, fallback_key: str) -> QColor:
    """把令牌键 / 颜色字面量 / None 解析为 QColor（实时取色，主题感知）。

    非法值**降级成 ``fallback_key``**，不抛也不返回无效色。理由与
    ``registry.pin_color`` 同源：原先的 ``value.startswith("rgb")`` 分支
    会把 ``rgb(1,2,3)`` 原样交给 ``QColor``，而 ``QColor`` 不解析 CSS
    函数记法（``isValid()`` 为 ``False``），于是 accent 栏**静默变黑**。
    """
    if not value:
        return QColor(str(T(f"color.{fallback_key}")))
    text = str(value)
    try:
        resolved = str(T(f"color.{text}"))
    except KeyError:
        resolved = None
    if resolved is not None:
        return QColor(resolved)
    color = QColor(text)
    if color.isValid():
        return color
    logger.warning("配色 %r 无法解析，回退到 color.%s", text, fallback_key)
    return QColor(str(T(f"color.{fallback_key}")))


def _relative_luminance(color: QColor) -> float:
    """WCAG 相对亮度（sRGB 线性化）。"""

    def _linear(channel: int) -> float:
        v = channel / 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    return (
        0.2126 * _linear(color.red())
        + 0.7152 * _linear(color.green())
        + 0.0722 * _linear(color.blue())
    )


def _contrast_ratio(a: QColor, b: QColor) -> float:
    """两色 WCAG 对比度（1–21）。"""
    la, lb = _relative_luminance(a), _relative_luminance(b)
    hi, lo = (la, lb) if la >= lb else (lb, la)
    return (hi + 0.05) / (lo + 0.05)


def _text_on(color: QColor) -> QColor:
    """按**实际对比度**在主题的「正文色 / 强调前景色」之间选更可读的一档。

    两个候选 token 的语义随主题翻转：亮色主题 ``text.primary``=黑、
    ``on.primary``=白；深色主题恰好相反（``text.primary``=白、
    ``on.primary``≈黑）。所以这里不按亮度分档写死哪一支 —— 直接比较
    两候选与底色 ``color`` 的 WCAG 对比度取大者，深浅主题同时正确。

    前一版按 YIQ 150 分档挑 token，在深色主题下整支取反：亮色 accent
    （``#d2a668`` / ``#4cc2ff``）拿到白字，对比度只有 ~1.6–2.0:1，
    标题基本糊在色带上（浅色主题的琥珀 ``#c08a3e`` 配白字同样只有
    ~2.4:1，其实黑字有 ~7:1）。
    """
    c1 = QColor(str(T("color.text.primary")))
    c2 = QColor(str(T("color.on.primary")))
    return c1 if _contrast_ratio(color, c1) >= _contrast_ratio(color, c2) else c2


def format_elapsed(ms) -> str:
    """把毫秒格式化为耗时徽标文本：``"12 ms"`` / ``"1.2 s"``。

    非有限值（``inf`` / ``nan``）按「未统计」返回空串 —— 直接格式化会得到
    ``"inf ms"`` 这种怪徽标（显示层问题，不崩）。
    """
    if ms is None:
        return ""
    ms = float(ms)
    if not math.isfinite(ms):
        return ""
    if ms < 1000.0:
        return f"{ms:.0f} ms"
    return f"{ms / 1000.0:.1f} s"


class ElaPinHandle(QWidget):
    """引脚热区控件（透明小方块，居中于引脚圆点）。

    画布对它安装事件过滤器以捕获按下拖线；``pin`` 为 ``ElaPin`` 数据对象，
    ``node_widget`` 回指所属节点控件。
    """

    def __init__(self, node_widget: "ElaNodeWidget", pin):
        super().__init__(node_widget)
        self.node_widget = node_widget
        self.pin = pin
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setToolTip(f"{pin.name} ({pin.data_type})")
        _transparent(self)

    def logical_center(self) -> QPointF:
        """引脚圆心的节点逻辑坐标。"""
        return self.node_widget.pin_logical_center(self.pin)

    def scene_center(self) -> QPointF:
        """引脚圆心的场景坐标（节点 pos + 逻辑偏移）。"""
        return self.node_widget.node.pos + self.logical_center()


class ElaNodeWidget(QFrame):
    """蓝图节点控件（绑定 ``ElaBlueprintNode``）。

    :param node: 数据节点（引脚 / 标题 / 属性 / 状态变化会自动反映到外观）
    :param parent: 父控件（通常为 ``ElaBlueprintCanvas``）
    :param owner: 注册表命名空间标识（缺省 None）；用于按「该 owner + 全局」
        解析 ``ElaNodeSpec.body_builder``

    供画布使用的接口：
    ``pin_widget(pin_id)`` / ``set_selected(bool)`` / ``apply_view(scene_pos, scale)`` /
    ``badge_rect()`` / ``elapsed_text()`` / ``cache_pixmap()`` / ``uses_proxy()`` /
    ``begin_gesture_proxy()`` / ``end_gesture_proxy()`` / ``refresh_theme()``。
    """

    #: 新引脚热区建成时发出，参数为控件列表（画布据此补装事件过滤器）
    pinsSynced = pyqtSignal(object)

    def __init__(self, node: ElaBlueprintNode, parent=None, owner: str = None):
        super().__init__(parent)
        self.node = node
        self._owner = owner
        self._selected = False
        self._scale = 1.0
        self._handles = {}
        self._body = None
        self._spinner = None
        self._pulse = 0.0
        self._body_h = 0.0
        # 外观位图缓存（GL 视口代理绘制用；仅 GL 模式生效）
        self._cache_pm = None
        self._cache_scale = 0.0
        self._cache_dirty = True
        # 布局版本与引脚逻辑坐标缓存（_relayout 重建；边端点几何键使用）
        self._layout_rev = 0
        self._pin_offsets = {}
        # GL 位图代理状态缓存（_relayout 重算；见 uses_proxy）
        self._proxy_state = False
        # 视图手势（平移 / 滚轮缩放）临时位图代理标记
        self._gesture_proxy = False
        # 体「期望可见性」（按缩放算）：不要用 isVisible() 代替 —— 父链
        # 未显示时 isVisible() 恒为 False，会把「没显示」误判成「体该隐藏」
        # 而每次 apply_view 都触发一次全量重排。
        self._body_shown = False
        _transparent(self)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setMouseTracking(True)

        # 引脚热区（键 = (方向, 引脚 id)：输入 / 输出允许同名 id）
        for pin in node.inputs + node.outputs:
            self._handles[(pin.direction, pin.id)] = ElaPinHandle(self, pin)
        # ``add_input`` / ``add_output`` 后补建热区 —— 新引脚没有
        # ``ElaPinHandle`` 就既无悬停提示也拖不出连线
        node.changed.connect(self.sync_pins)
        # 自定义体 / 缺省 properties 展示（按 owner 解析注册表，画布传入）
        spec = ElaNodeRegistry.instance().spec(node.type_name, owner=self._owner)
        if spec is not None and spec.body_builder is not None:
            self._body = QWidget(self)
            _transparent(self._body)
            lay = QVBoxLayout(self._body)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(int(T("space.1")))
            spec.body_builder(node, self._body)

        # running 旋转圈（标题栏状态图标区）
        self._spinner = SpinnerArc(size=int(SPINNER_SIZE), line_width=2, parent=self)
        _transparent(self._spinner)
        self._spinner.hide()

        # running 脉冲描边定时器
        self._pulse_timer = QTimer(self)
        self._pulse_timer.timeout.connect(self._tick_pulse)
        self._pulse_interval = max(16, PULSE_MS // 10)

        node.changed.connect(self._on_node_changed)
        node.status_changed.connect(self._on_status_changed)
        # 绑定方法连接：控件销毁时 Qt 自动断连（接收方销毁即断）
        theme_changed_slot(self, self._on_theme_changed)

        self._relayout()
        self._on_status_changed(node.status)

    # ------------------------------------------------------------------
    # 布局（逻辑坐标）
    # ------------------------------------------------------------------
    def _title_font(self) -> QFont:
        f = QFont(self.font())
        f.setPixelSize(int(T("font.sm")))
        f.setWeight(QFont.Weight.DemiBold)
        return f

    def _pin_font(self) -> QFont:
        f = QFont(self.font())
        f.setPixelSize(int(T("font.xs")))
        return f

    def _body_visible(self) -> bool:
        """当前缩放下节点体是否可见（低于 ``BODY_MIN_ZOOM`` 隐藏）。"""
        return self._body is not None and self._scale >= BODY_MIN_ZOOM

    def _relayout(self) -> None:
        """按内容重算逻辑尺寸并写回 ``node.size``，再重排子控件。"""
        title_font = self._title_font()
        tw = QFontMetrics(title_font).horizontalAdvance(self.node.title) + 64.0
        pin_font = self._pin_font()
        pfm = QFontMetrics(pin_font)
        rows = max(len(self.node.inputs), len(self.node.outputs))
        pin_w = 0.0
        for i in range(rows):
            lw = (
                pfm.horizontalAdvance(self.node.inputs[i].name)
                if i < len(self.node.inputs)
                else 0
            )
            rw = (
                pfm.horizontalAdvance(self.node.outputs[i].name)
                if i < len(self.node.outputs)
                else 0
            )
            pin_w = max(pin_w, float(lw + rw) + 72.0)
        body_w = 0.0
        self._body_h = 0.0
        if self._body is not None:
            visible = self._body_visible()
            self._body_shown = visible
            # 手势代理期间体控件由 begin_gesture_proxy 隐藏，此处不得恢复显示；
            # 但尺寸仍按「体可见」计算，避免手势中节点逻辑尺寸抖动
            if not self._gesture_proxy and self._body.isVisible() != visible:
                self._body.setVisible(visible)
            if visible:
                hint = self._body.sizeHint()
                body_w = float(max(hint.width(), 0)) + 2 * PAD_X
                self._body_h = float(max(hint.height(), 0)) + 8.0
        elif self.node.properties:
            keys = list(self.node.properties.items())
            for k, v in keys:
                body_w = max(
                    body_w, float(pfm.horizontalAdvance(f"{k}: {v}")) + 2 * PAD_X
                )
            self._body_h = BODY_LINE_H * len(keys) + 6.0
        w = max(MIN_W, tw, pin_w, body_w)
        h = TITLE_H + rows * PIN_ROW_H + self._body_h + PAD_BOTTOM
        self.node.size = QSizeF(w, h)
        # 引脚逻辑坐标缓存 + 布局版本
        self._pin_offsets = {}
        for i, pin in enumerate(self.node.inputs):
            self._pin_offsets[(ElaPinDirectionType.Input, pin.id)] = QPointF(
                0.0, TITLE_H + i * PIN_ROW_H + PIN_ROW_H / 2
            )
        for i, pin in enumerate(self.node.outputs):
            self._pin_offsets[(ElaPinDirectionType.Output, pin.id)] = QPointF(
                w, TITLE_H + i * PIN_ROW_H + PIN_ROW_H / 2
            )
        self._layout_rev += 1
        # 位图代理状态：父视口支持代理且无可见自定义体
        self._proxy_state = (
            getattr(self.parentWidget(), "supports_node_proxy", False)
            and not self._body_visible()
        )
        self._arrange_children()

    def _arrange_children(self) -> None:
        """把子控件（引脚热区 / 自定义体 / 旋转圈）按视图系数落位。"""
        s = self._scale
        hs = max(8.0, PIN_HANDLE * s)
        for handle in self._handles.values():
            c = self.pin_logical_center(handle.pin)
            handle.setGeometry(
                int(c.x() * s - hs / 2), int(c.y() * s - hs / 2), int(hs), int(hs)
            )
        if self._body is not None and self._body.isVisible():
            y = (
                TITLE_H
                + max(len(self.node.inputs), len(self.node.outputs)) * PIN_ROW_H
                + 4.0
            ) * s
            self._body.setGeometry(
                int(PAD_X * s),
                int(y),
                max(10, int(self.width() - 2 * PAD_X * s)),
                max(10, int(self._body_h * s - 8)),
            )
        ss = max(8.0, SPINNER_SIZE * s)
        self._spinner.setGeometry(
            int(self.width() - ss - 7 * s),
            int((TITLE_H * s - ss) / 2),
            int(ss),
            int(ss),
        )

    def pin_logical_center(self, pin) -> QPointF:
        """引脚圆心的节点逻辑坐标（输入在左缘、输出在右缘，布局缓存）。"""
        c = self._pin_offsets.get((pin.direction, pin.id))
        if c is not None:
            return QPointF(c)
        # 回退：布局缓存尚未建立时的直接计算
        w = self.node.size.width()
        if pin.direction is ElaPinDirectionType.Input:
            idx = self.node.inputs.index(pin)
            return QPointF(0.0, TITLE_H + idx * PIN_ROW_H + PIN_ROW_H / 2)
        idx = self.node.outputs.index(pin)
        return QPointF(w, TITLE_H + idx * PIN_ROW_H + PIN_ROW_H / 2)

    def pin_widget(self, pin_id: str, direction=None):
        """返回引脚热区控件（供画布取全局坐标 / 命中检测）。

        :param direction: 可选 ``ElaPinDirectionType``；输入 / 输出同名 id 时
            必须指定方向；省略时按先输入后输出返回首个命中。
        """
        if direction is not None:
            return self._handles.get((direction, pin_id))
        return self._handles.get((ElaPinDirectionType.Input, pin_id)) or self._handles.get(
            (ElaPinDirectionType.Output, pin_id)
        )

    def sync_pins(self) -> list:
        """按 ``node.inputs + node.outputs`` 校准引脚热区，返回新建的热区列表。

        节点在构造之后 ``add_input`` / ``add_output`` 时，新引脚此前没有对应的
        ``ElaPinHandle``（构造时的快照不含它），画布既拿不到热区也无法从它拖出
        连线。画布据返回列表补装事件过滤器。
        """
        wanted = {
            (pin.direction, pin.id): pin for pin in self.node.inputs + self.node.outputs
        }
        created = []
        for key, pin in wanted.items():
            if key not in self._handles:
                handle = ElaPinHandle(self, pin)
                self._handles[key] = handle
                created.append(handle)
        for key in [k for k in self._handles if k not in wanted]:
            stale = self._handles.pop(key)
            try:
                stale.hide()
                stale.deleteLater()
            except RuntimeError:  # C++ 对象已销毁
                pass
        if created or len(self._handles) != len(wanted):
            self.updateGeometry()
        if created:
            self.pinsSynced.emit(created)
        return created

    # ------------------------------------------------------------------
    # 视图放置（由画布调用）
    # ------------------------------------------------------------------
    def apply_view(self, scene_pos: QPointF, scale: float) -> None:
        """按场景坐标与缩放系数放置控件（几何 = 逻辑矩形 × scale）。

        ``int()`` 的四个实参**逐个兜底**：``int(inf)`` 抛 ``OverflowError``、
        ``int(nan)`` 抛 ``ValueError``，而这条路径由 ``paintEvent`` 之外的
        画布布局调用，任一异常穿出去都会让控件停在半更新状态。数据入口
        （``ElaBlueprintNode.from_dict``）已拒收非有限值，这里是最后一道。
        """
        self._scale = max(0.05, float(scale)) if _finite(scale) else 1.0
        if self._body is not None and self._body_shown != self._body_visible():
            self._relayout()
        self.setGeometry(
            _to_int(scene_pos.x()),
            _to_int(scene_pos.y()),
            max(20, _to_int(self.node.size.width() * self._scale)),
            max(20, _to_int(self.node.size.height() * self._scale)),
        )
        self._arrange_children()
        self.update()

    # ------------------------------------------------------------------
    # GL 代理绘制（位图缓存）
    # ------------------------------------------------------------------
    def uses_proxy(self) -> bool:
        """当前是否由 GL 视口以位图缓存代理绘制。"""
        return bool(self._proxy_state or self._gesture_proxy)

    def begin_gesture_proxy(self) -> None:
        """视图手势开始：切换为临时位图代理（幂等）。

        先抓取再置代理标记（grab() 触发 paintEvent，代理态下直接返回）。
        """
        if self._gesture_proxy or self._proxy_state:
            return
        if not getattr(self.parentWidget(), "supports_node_proxy", False):
            return
        pm = self.grab()
        self._gesture_proxy = True
        self._cache_pm = pm
        self._cache_scale = self._scale
        self._cache_dirty = False
        if self._body is not None:
            self._body.hide()
        self._spinner.hide()

    def end_gesture_proxy(self) -> None:
        """视图手势结束：恢复真实子控件渲染（幂等）。"""
        if not self._gesture_proxy:
            return
        self._gesture_proxy = False
        if self._body is not None:
            # 恢复到「按缩放应该有的」可见性（isVisible 在父链隐藏时不可信）
            self._body.setVisible(self._body_shown)
        self._spinner.setVisible(self.node.status == "running")
        self._invalidate_cache()
        self.update()

    def _invalidate_cache(self) -> None:
        """内容 / 状态 / 主题变化后标记缓存失效。"""
        self._cache_dirty = True

    def cache_pixmap(self) -> "QPixmap":
        """外观缓存位图（惰性重建；缩放手势中沿用旧位图纹理缩放）。"""
        if self._gesture_proxy and self._cache_pm is not None:
            return self._cache_pm
        zooming = False
        vp = self.parentWidget()
        canvas = getattr(vp, "_canvas", None)
        if canvas is not None:
            zooming = bool(getattr(canvas, "_zooming", False))
        if (
            self._cache_pm is None
            or self._cache_dirty
            or (abs(self._cache_scale - self._scale) > 1e-3 and not zooming)
        ):
            self._render_cache()
        return self._cache_pm

    def _render_cache(self) -> None:
        """把节点外观（逻辑坐标内容）离屏渲染为按 缩放 × DPR 的位图。"""
        s = self._scale
        dpr = self.devicePixelRatioF()
        w = self.node.size.width() * s * dpr
        h = self.node.size.height() * s * dpr
        pm = QPixmap(max(1, math.ceil(w)), max(1, math.ceil(h)))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.scale(s, s)
        self._paint_content(p)
        p.end()
        self._cache_pm = pm
        self._cache_scale = s
        self._cache_dirty = False

    def update(self, *args) -> None:
        """代理模式下重绘请求转发给视口（自身透明，无需控件级重绘）。"""
        if self.uses_proxy():
            vp = self.parentWidget()
            if vp is not None:
                vp.update(self.geometry())
            return
        super().update(*args)

    # ------------------------------------------------------------------
    # 选中 / 状态
    # ------------------------------------------------------------------
    def set_selected(self, on: bool) -> None:
        """设置选中态：primary 2px 描边（本控件内）+ 外发光（画布层自绘）。"""
        on = bool(on)
        if on == self._selected:
            return
        self._selected = on
        self._invalidate_cache()
        self.update()

    def is_selected(self) -> bool:
        """当前是否选中。"""
        return self._selected

    def elapsed_text(self) -> str:
        """当前耗时徽标文本（done 状态有值，其余为空串）。"""
        if self.node.status == "done" and self.node.elapsed_ms is not None:
            return format_elapsed(self.node.elapsed_ms)
        return ""

    def badge_rect(self) -> QRectF:
        """done 耗时徽标的节点逻辑矩形（无徽标时返回空矩形）。"""
        text = self.elapsed_text()
        if not text:
            return QRectF()
        f = QFont(self.font())
        f.setPixelSize(int(T("font.xs")))
        tw = QFontMetrics(f).horizontalAdvance(text)
        bw, bh = tw + 14.0, 18.0
        return QRectF(self.node.size.width() - bw - 6.0, (TITLE_H - bh) / 2, bw, bh)

    def accent_color(self) -> QColor:
        """标题栏强调色（令牌键 / hex 实时解析，缺省灰）。"""
        return _resolve_color(self.node.accent, "text.tertiary")

    # ------------------------------------------------------------------
    # 状态切换
    # ------------------------------------------------------------------
    def _on_status_changed(self, status: str) -> None:
        running = status == "running"
        # 手势代理期间旋转圈冻结进位图，状态切换不得重新显示
        self._spinner.setVisible(running and not self._gesture_proxy)
        if running:
            self._spinner.start()
            # 持续动效：Reduced/Disabled 下不脉冲。停掉时相位冻结在当前值，
            # 描边仍然是画出来的（只是不动），所以不需要摆姿态钩子。
            start_idle_loop(self._pulse_timer, self._pulse_interval)
        else:
            self._spinner.stop()
            self._pulse_timer.stop()
            self._pulse = 0.0
        if status == "error" and self.node.error_message:
            self.setToolTip(self.node.error_message)
        else:
            self.setToolTip("")
        self._invalidate_cache()
        self.update()

    def _on_node_changed(self) -> None:
        self._relayout()
        # 父控件可能是画布或画布内的绘制视口，逐级找落位回调
        parent = self.parentWidget()
        handler = getattr(parent, "_node_layout_changed", None)
        if handler is None and parent is not None:
            handler = getattr(parent.parentWidget(), "_node_layout_changed", None)
        if handler is not None:
            handler(self)
        self._invalidate_cache()
        self.update()

    def _tick_pulse(self) -> None:
        # 相位推进量与计时器间隔一致（PULSE_MS 的 1/10）
        self._pulse += PULSE_MS / 10000.0
        self._invalidate_cache()
        self.update()

    def _on_theme_changed(self) -> None:
        """主题切换：外观全部实时取色，直接触发重绘。"""
        self.update()

    # ------------------------------------------------------------------
    # 绘制
    # ------------------------------------------------------------------
    def paintEvent(self, _event) -> None:
        if self.uses_proxy():
            return  # GL 视口代理绘制：自身仅作交互容器
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.scale(self._scale, self._scale)
        self._paint_content(p)
        p.end()

    def _paint_content(self, p: QPainter) -> None:
        """节点外观全部内容（逻辑坐标；调用方已 scale 并开抗锯齿）。"""
        w, h = self.node.size.width(), self.node.size.height()
        radius = float(T("radius.lg"))
        accent = self.accent_color()
        status = self.node.status

        # 底
        rect = QRectF(1.0, 1.0, w - 2.0, h - 2.0)
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(str(T("color.bg.elevated"))))
        p.drawPath(path)

        # 标题栏（accent 色带，上圆角）
        band = QPainterPath()
        band.addRoundedRect(QRectF(1.0, 1.0, w - 2.0, TITLE_H + radius), radius, radius)
        clip = QPainterPath()
        clip.addRect(QRectF(1.0, 1.0, w - 2.0, TITLE_H))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(accent)
        p.drawPath(band.intersected(clip))
        # 标题栏分隔线
        p.setPen(QPen(QColor(str(T("color.border"))), 1.0))
        p.drawLine(QPointF(1.0, TITLE_H), QPointF(w - 1.0, TITLE_H))

        # 标题文本
        p.setFont(self._title_font())
        p.setPen(_text_on(accent))
        title_rect = QRectF(PAD_X, 0.0, w - 2 * PAD_X - 24.0, TITLE_H)
        p.drawText(
            title_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            self.node.title,
        )

        # 状态图标区（标题右侧）
        if status == "done":
            text = self.elapsed_text()
            if text:
                br = self.badge_rect()
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(str(T("color.bg.muted"))))
                p.drawRoundedRect(br, br.height() / 2, br.height() / 2)
                f = QFont(self.font())
                f.setPixelSize(int(T("font.xs")))
                p.setFont(f)
                p.setPen(QColor(str(T("color.text.secondary"))))
                p.drawText(br, Qt.AlignmentFlag.AlignCenter, text)
        elif status == "error":
            cx = w - 6.0 - SPINNER_SIZE / 2
            cy = TITLE_H / 2
            r = SPINNER_SIZE / 2
            danger = QColor(str(T("color.danger")))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(danger)
            p.drawEllipse(QPointF(cx, cy), r, r)
            # 叉号前景按实际对比度选（深色主题里 on.primary 近黑，压红底只有
            # 3.7:1；白色有 4.7:1）
            p.setPen(
                QPen(
                    _text_on(danger),
                    1.8,
                    Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap,
                )
            )
            d = r * 0.42
            p.drawLine(QPointF(cx - d, cy - d), QPointF(cx + d, cy + d))
            p.drawLine(QPointF(cx - d, cy + d), QPointF(cx + d, cy - d))

        # 引脚区
        self._draw_pins(p)

        # 缺省体：properties 键值
        if self._body is None and self.node.properties:
            f = self._pin_font()
            p.setFont(f)
            y = (
                TITLE_H
                + max(len(self.node.inputs), len(self.node.outputs)) * PIN_ROW_H
                + 4.0
            )
            for k, v in self.node.properties.items():
                p.setPen(QColor(str(T("color.text.tertiary"))))
                p.drawText(
                    QRectF(PAD_X, y, w - 2 * PAD_X, BODY_LINE_H),
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                    f"{k}: {v}",
                )
                y += BODY_LINE_H

        # 描边（选中 > 状态 > 普通）
        border_color = QColor(str(T("color.border")))
        border_w = 1.2
        if status == "done":
            border_color = QColor(str(T("color.success")))
            border_w = 2.0
        elif status == "error":
            border_color = QColor(str(T("color.danger")))
            border_w = 2.0
        elif status == "running":
            # 脉冲周期 = PULSE_MS
            pulse = 0.55 + 0.45 * math.sin(
                self._pulse * 2 * math.pi / (PULSE_MS / 1000.0)
            )
            border_color = QColor(accent)
            border_color.setAlpha(int(120 + 135 * pulse))
            border_w = 2.0
        if self._selected:
            border_color = QColor(str(T("color.primary")))
            border_w = 2.0
        p.setPen(QPen(border_color, border_w))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

    def _draw_pins(self, p: QPainter) -> None:
        """绘制引脚行：彩色圆点（multi 双环）+ 名称。"""
        f = self._pin_font()
        p.setFont(f)
        w = self.node.size.width()
        text_color = QColor(str(T("color.text.secondary")))
        for pin in self.node.inputs:
            c = self.pin_logical_center(pin)
            color = QColor(pin_color(pin.data_type))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            p.drawEllipse(c, PIN_DOT_R, PIN_DOT_R)
            if pin.multi:  # 双环
                p.setPen(QPen(color, 1.4))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(c, PIN_DOT_R + 3.0, PIN_DOT_R + 3.0)
            p.setPen(text_color)
            p.drawText(
                QRectF(c.x() + 10.0, c.y() - PIN_ROW_H / 2, w / 2, PIN_ROW_H),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                pin.name,
            )
        for pin in self.node.outputs:
            c = self.pin_logical_center(pin)
            color = QColor(pin_color(pin.data_type))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            p.drawEllipse(c, PIN_DOT_R, PIN_DOT_R)
            if pin.multi:
                p.setPen(QPen(color, 1.4))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(c, PIN_DOT_R + 3.0, PIN_DOT_R + 3.0)
            p.setPen(text_color)
            p.drawText(
                QRectF(c.x() - 10.0 - w / 2, c.y() - PIN_ROW_H / 2, w / 2, PIN_ROW_H),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                pin.name,
            )

    # ------------------------------------------------------------------
    # 事件
    # ------------------------------------------------------------------
    def refresh_theme(self) -> None:
        """主题切换时重排并重绘（画布 / 测试可直接调用）。"""
        self._invalidate_cache()
        self._relayout()
        self.update()
