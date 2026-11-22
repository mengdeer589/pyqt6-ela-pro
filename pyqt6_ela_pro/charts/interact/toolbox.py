"""工具箱组件。（``pyqt6_ela_pro.charts`` 内部模块）。"""

from __future__ import annotations


from PyQt6.QtCore import QRectF, Qt
from PyQt6ElaWidgetTools import ElaIconButton, ElaIconType
from PyQt6.QtGui import (
    QPainter,
)

from ..._internal import is_deleted
from ..._styles import coerceElaIcon
from ...tooltips import ElaToolTipPositionType, set_tooltip
from .._utils import warn_key, warn_once
from ..models import OptionModel


class ToolboxComponent:
    """右上角图标按钮组（真实 ``ElaIconButton`` 子控件）。
    option: ``"toolbox": {"feature": ["saveAsImage", "saveAsSvg", "dataZoom",
    "restore", "zoomIn", "zoomOut"]}``。``layout()`` 每帧幂等 ``move()`` 不重建
    """

    optionKey = "toolbox"
    #: 只支持单实例：数组写法取第一个 dict（见 ``_utils.single_option``）
    singleOption = True

    #: 按钮边长 / 间隙 / 图标像素尺寸 / 距绘图区右上角的边距
    BTN = 26.0
    GAP = 4.0
    ICON_PX = 15
    MARGIN = 8.0
    TOP = 4.0

    _KNOWN = (
        "saveAsImage",
        "saveAsSvg",
        "dataZoom",
        "restore",
        "zoomIn",
        "zoomOut",
        "magicType",
        "dataView",
    )

    #: 功能 → Ela 图标（``ElaIconType.IconName``）
    ICONS = {
        "saveAsImage": ElaIconType.IconName.Image,
        "saveAsSvg": ElaIconType.IconName.FileVector,
        "dataZoom": ElaIconType.IconName.MagnifyingGlass,
        "restore": ElaIconType.IconName.ArrowRotateRight,
        "zoomIn": ElaIconType.IconName.MagnifyingGlassPlus,
        "zoomOut": ElaIconType.IconName.MagnifyingGlassMinus,
        "magicType": ElaIconType.IconName.ChartMixed,
        "dataView": ElaIconType.IconName.Table,
    }

    #: 功能 → 提示文案（``toolTip`` 与 ``accessibleName`` 共用）
    TIPS = {
        "saveAsImage": "导出 PNG",
        "saveAsSvg": "导出 SVG 矢量图",
        "dataZoom": "缩放开关",
        "restore": "还原视图",
        "zoomIn": "放大",
        "zoomOut": "缩小",
        "magicType": "切换图表类型",
        "dataView": "查看数据",
    }

    def __init__(self, chart, opt):
        self.chart = chart
        self.opt = opt if isinstance(opt, OptionModel) else dict(opt or {})
        feat = self.opt.get("feature")
        if feat is None:
            names = [n for n in self._KNOWN if n != "dataView"]
        elif isinstance(feat, dict):
            # ECharts 规范写法是 {"saveAsImage": {}}：空 dict 代表启用，
            # 不能用真值判断，否则会误开全部功能。
            names = [k for k, v in feat.items() if v is not False]
        elif isinstance(feat, (list, tuple)):
            names = [str(f) for f in feat]
        else:
            names = []
        self.features = [n for n in names if n in self._KNOWN]
        #: 动作回调（可注入）：fn(feature_name)
        self.on_action = None
        #: 最近一次 saveAsImage / saveAsSvg 的保存路径
        self.last_saved = None
        #: 几何镜像 ``[(name, QRectF)]``（与子控件同步；定位与测试用）
        self._buttons = []
        #: ``{name: ElaIconButton}``（chart 的子控件）
        self._widgets: dict = {}

    def layout(self, rect: QRectF) -> None:
        """把按钮摆到绘图区右上角（每次布局幂等重放，不重建控件）。"""
        self._buttons = []
        if self.opt.get("show", True) is False:
            for button in self._widgets.values():
                if not is_deleted(button):
                    button.hide()
            return
        count = len(self.features)
        if count <= 0:
            return
        enabled = bool(
            getattr(self.chart, "isInteractionEnabled", lambda _f: True)("toolbox")
        )
        zoom_on = bool(getattr(self.chart, "_dataZoomEnabled", True))
        x = rect.right() - self.MARGIN - count * self.BTN - (count - 1) * self.GAP
        y = rect.top() + self.TOP
        for name in self.features:
            self._buttons.append((name, QRectF(x, y, self.BTN, self.BTN)))
            button = self._ensure_button(name)
            if button is not None:
                button.move(int(round(x)), int(round(y)))
                button.setVisible(True)
                button.setEnabled(enabled)
                if name == "dataZoom":
                    button.setIsSelected(zoom_on)
            x += self.BTN + self.GAP

    def buttonRect(self, name: str) -> QRectF:
        """指定功能按钮的矩形（未找到返回空矩形）。"""
        for n, r in self._buttons:
            if n == name:
                return QRectF(r)
        return QRectF()

    def buttonWidget(self, name: str):
        """指定功能的 ``ElaIconButton`` 子控件（未创建返回 ``None``）。"""
        return self._widgets.get(name)

    def _ensure_button(self, name: str):
        button = self._widgets.get(name)
        if button is not None and not is_deleted(button):
            return button
        icon = self.ICONS.get(name)
        if icon is None:
            return None
        try:
            button = ElaIconButton(
                coerceElaIcon(icon),
                self.ICON_PX,
                int(round(self.BTN)),
                int(round(self.BTN)),
                self.chart,
            )
        except Exception as exc:  # 图标字体 / 绑定异常不拖垮整图
            warn_once(
                warn_key("toolbox-icon", name, type(exc).__name__),
                f"工具条按钮创建失败（{name}）: {exc!r}",
            )
            return None
        # 图表是「画布型」控件：按钮不参与 Tab 焦点链（键盘交互归宿主）
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        set_tooltip(button, self.TIPS.get(name, name), ElaToolTipPositionType.Top)
        button.setAccessibleName(self.TIPS.get(name, name))
        button.clicked.connect(lambda _checked=False, n=name: self.trigger(n))
        self._widgets[name] = button
        return button

    def dispose(self) -> None:
        """丢弃子控件（``core`` 重建组件 / 图表析构路径）。"""
        for button in list(self._widgets.values()):
            if not is_deleted(button):
                button.setParent(None)
                button.deleteLater()
        self._widgets.clear()
        self._buttons = []

    def onInteractionChanged(self) -> None:
        """交互开关变化：立即同步按钮启用态（子控件不跟 chart 的重绘走）。"""
        enabled = bool(
            getattr(self.chart, "isInteractionEnabled", lambda _f: True)("toolbox")
        )
        for button in self._widgets.values():
            if not is_deleted(button):
                button.setEnabled(enabled)

    def trigger(self, name: str) -> None:
        """执行指定功能（按钮点击或外部调用；异常不能穿出 Qt 槽）。"""
        try:
            self._trigger_impl(name)
        except Exception as exc:
            warn_once(
                warn_key("toolbox-trigger", str(name), type(exc).__name__),
                f"toolbox 动作失败（{name}）: {exc!r}",
            )

    def _trigger_impl(self, name: str) -> None:
        if self.opt.get("show", True) is False:
            return
        if callable(self.on_action):
            try:
                self.on_action(name)
            except Exception:
                pass
        if name == "saveAsImage":
            self._save_image()
        elif name == "saveAsSvg":
            self._save_image(svg=True)
        elif name == "restore":
            self._restore()
        elif name == "zoomIn":
            self.chart.zoomStep(0.7)
        elif name == "zoomOut":
            self.chart.zoomStep(1.0 / 0.7)
        elif name == "magicType":
            self.chart.toggleMagicType()
        elif name == "dataView":
            self._show_data_view()
        elif name == "dataZoom":
            cur = bool(getattr(self.chart, "_dataZoomEnabled", True))
            self.chart._dataZoomEnabled = not cur
            # 按钮是子控件，外观不跟 chart 的重绘走：状态要当场同步
            button = self._widgets.get("dataZoom")
            if button is not None and not is_deleted(button):
                button.setIsSelected(not cur)
                set_tooltip(
                    button,
                    f"{self.TIPS['dataZoom']}（当前：{'开' if not cur else '关'}）",
                    ElaToolTipPositionType.Top,
                )
            self.chart.update()

    def _save_image(self, svg: bool = False) -> None:
        if svg:
            path = self.chart.saveImage(format="svg")
        else:
            path = self.chart.saveImage()
        self.last_saved = path or None

    def _show_data_view(self) -> None:
        """打开只读数据视图（ECharts toolbox ``dataView``）。"""
        try:
            import json

            from PyQt6.QtCore import Qt
            from PyQt6.QtWidgets import (
                QDialog,
                QPlainTextEdit,
                QVBoxLayout,
            )
        except ImportError:
            return
        try:
            dialog = QDialog(self.chart)
            dialog.setWindowTitle("数据视图")
            dialog.resize(560, 420)
            layout = QVBoxLayout(dialog)
            editor = QPlainTextEdit(dialog)
            editor.setReadOnly(True)
            editor.setPlainText(
                json.dumps(
                    self.chart.getOptionDict(),
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                )
            )
            layout.addWidget(editor)
            dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
            self._data_view = dialog
            dialog.show()
        except Exception:
            pass

    def _restore(self) -> None:
        """恢复初始状态（经 chart._restore_state 统一复位并发出 restore 事件）。"""
        restore_state = getattr(self.chart, "_restore_state", None)
        if callable(restore_state):
            restore_state()
            return
        for comp in self.chart.components:
            restore = getattr(comp, "restore", None)
            if callable(restore) and comp is not self:
                try:
                    restore()
                except Exception:
                    pass
        self.chart.update()

    def paint(self, p: QPainter, anim_t: float = 1.0) -> None:
        """无绘制：按钮是真实子控件，外观由 ``ElaIconButton`` 负责。"""
