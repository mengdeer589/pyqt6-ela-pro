"""蓝图画布的绘制视口（可选 GL 加速），与画布 1:1 重合。

软件 / GL 两条路径共用同一份绘制代码；细节见 ``docs/blueprint.md``。"""

from __future__ import annotations

import logging
import os

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QGuiApplication, QPainter
from PyQt6.QtOpenGLWidgets import QOpenGLWidget
from PyQt6.QtWidgets import QWidget

logger = logging.getLogger(__name__)

__all__ = ["gl_available", "create_viewport"]

#: GL 可用性探测结果（模块级缓存，``None`` 表示尚未探测）
_GL_STATE = None


def gl_available() -> bool:
    """当前环境是否可用 GL 视口（结果缓存；受 ``ELABLUEPRINT_GL`` 控制）。
    ``QApplication`` 尚未创建时不写缓存：此时探测必然为假但结论不可信
    （GL 设施随应用创建），缓存会把进程永久锁定在软件渲染。
    """
    global _GL_STATE
    if _GL_STATE is None:
        if QGuiApplication.instance() is None:
            return False
        _GL_STATE = _probe_gl()
    return _GL_STATE


def _probe_gl() -> bool:
    """实际探测：环境变量 → 平台名 → 试探创建 GL 上下文。
    **默认软件渲染**（``ELABLUEPRINT_GL`` 未设）：GL 视口是原生子窗口，挂到已显示的
    窗口上会让 Windows/Qt 重建顶层 HWND（窗口闪一下）；想要 GPU 加速请显式
    """
    env = (
        os.environ.get("ELABLUEPRINT_GL", os.environ.get("UIKIT_BLUEPRINT_GL", "off"))
        .strip()
        .lower()
    )
    if env == "off":
        return False
    app = QGuiApplication.instance()
    if app is None:
        return False
    platform = app.platformName()
    if platform in ("offscreen", "minimal", "minimalegl"):
        if env == "on":
            logger.warning(
                "ELABLUEPRINT_GL=on 但平台 %s 不支持 GL，回退软件渲染", platform
            )
        return False
    try:
        from PyQt6.QtGui import QOffscreenSurface, QOpenGLContext

        ctx = QOpenGLContext()
        if not ctx.create():
            raise RuntimeError("QOpenGLContext.create 失败")
        surface = QOffscreenSurface()
        surface.setFormat(ctx.format())
        surface.create()
        if not surface.isValid():
            raise RuntimeError("QOffscreenSurface 创建失败")
        if not ctx.makeCurrent(surface):
            raise RuntimeError("QOpenGLContext.makeCurrent 失败")
        ctx.doneCurrent()
        return True
    except Exception as exc:
        if env == "on":
            logger.warning("ELABLUEPRINT_GL=on 但 GL 探测失败（%s），回退软件渲染", exc)
        return False


class _ViewportMixin:
    """视口公共行为：持有画布引用、转发交互事件（1:1 重合，坐标一致）。"""

    def _init_viewport(self, canvas) -> None:
        self._canvas = canvas
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAutoFillBackground(False)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self._canvas.mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        self._canvas.mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._canvas.mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:  # noqa: N802
        self._canvas.wheelEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._canvas.leaveEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        self._canvas.keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:  # noqa: N802
        self._canvas.keyReleaseEvent(event)


class _RasterViewport(_ViewportMixin, QWidget):
    """软件回退视口：普通 QWidget，paintEvent 走 CPU raster。
    节点由真实子控件自绘（``supports_node_proxy = False``），保证
    offscreen 测试的像素级行为与纯软件版本一致。
    """

    #: 不支持节点位图代理（节点自行 paintEvent）
    supports_node_proxy = False

    def __init__(self, canvas) -> None:
        super().__init__(canvas)
        self._init_viewport(canvas)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._canvas._paint_contents(p, event.rect())
        p.end()


class _GLViewport(_ViewportMixin, QOpenGLWidget):
    """GPU 视口：QOpenGLWidget，paintGL 中 QPainter 自动走 GL paint engine。

    节点位图代理（``supports_node_proxy = True``）：无可见自定义体的节点用
    ``cache_pixmap()`` 位图统一绘制，视图手势期间全体节点临时切换代理，内容
    零重绘；节点控件保持透明，只承担交互与动态子控件。GL 模式不做脏矩形
    裁剪（整幅 FBO 重绘）。首帧可能送上旧合成结果，``showEvent`` 强制一次
    ``update()``。
    """

    #: 支持节点位图代理绘制
    supports_node_proxy = True

    def __init__(self, canvas) -> None:
        super().__init__(canvas)
        self._init_viewport(canvas)

    def showEvent(self, event) -> None:  # noqa: N802
        """首次显示后强制一次重绘，规避半透明顶层窗口下的首帧合成缺陷。"""
        super().showEvent(event)
        self.update()

    def paintGL(self) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._canvas._paint_contents(p, None)
        self._paint_proxied_nodes(p)
        p.end()

    def _paint_proxied_nodes(self, p: QPainter) -> None:
        """按场景坐标实时绘制全部可见代理节点的缓存位图（节点在边之上）。
        位置直接由 ``scene_to_view(node.pos)`` 计算而非读取控件几何：
        视图手势（平移 / 滚轮缩放）期间画布会跳过逐节点几何落位，此处
        """
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        canvas = self._canvas
        z = canvas._zoom
        ox, oy = canvas._offset.x(), canvas._offset.y()
        vw, vh = self.width(), self.height()
        for w in canvas._node_widgets.values():
            # uses_proxy 覆盖常规代理（无可见体）与手势代理（手势期全体）
            if not w.isVisible() or not w.uses_proxy():
                continue
            node = w.node
            # 内联浮点换算（scene_to_view 等价），避免逐节点调用开销
            tx = node.pos.x() * z + ox
            ty = node.pos.y() * z + oy
            nw = node.size.width() * z
            nh = node.size.height() * z
            if tx > vw or ty > vh or tx + nw < 0 or ty + nh < 0:
                continue
            pm = w.cache_pixmap()
            if abs(w._cache_scale - z) > 1e-3:
                # 缩放手势中：旧位图按目标矩形拉伸（GPU 纹理缩放）
                p.drawPixmap(QRectF(tx, ty, nw, nh), pm, QRectF(pm.rect()))
            else:
                p.drawPixmap(QPointF(tx, ty), pm)


def _warnLateNativeAttach(canvas) -> None:
    """GL 视口是**原生子窗口**：挂到已显示的窗口上会让 Windows/Qt 重建顶层 HWND。
    表现为主窗口闪一下（类名 ``QWindowIcon`` → ``QWindowOwnDCIcon``）。必须在
    ``window.show()`` 之前构建画布，或保持默认软件视口。
    """
    try:
        window = canvas.window()
        if window is not None and window.isVisible():
            logger.warning(
                "ElaBlueprintCanvas 的 GL 视口是原生子窗口，挂到已显示的窗口上会重建顶层 "
                "HWND（窗口闪一下）：请在 window.show() 之前构建画布，或不设 ELABLUEPRINT_GL"
            )
    except Exception:  # noqa: BLE001 —— 提醒不该影响创建
        pass


def create_viewport(canvas) -> QWidget:
    """按 GL 可用性为画布创建绘制视口（调用方负责铺满与 show）。"""
    if gl_available():
        try:
            _warnLateNativeAttach(canvas)
            return _GLViewport(canvas)
        except Exception as exc:  # 防御：构造期异常同样回退
            logger.warning("GL 视口创建失败，回退软件渲染: %s", exc)
    return _RasterViewport(canvas)
