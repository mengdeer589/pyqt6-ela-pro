"""
蓝图菜单：节点创建菜单与节点右键菜单模板（Ela 组件重构版）。

- ``ElaNodeCreationMenu``：**ElaLineEdit** 搜索框 + **ElaListView** 分类
  分组列表，Popup 弹出、主题感知（窗口底色 / 边框 / 图标色实时取自
  ``eTheme``），回车创建第一项；支持按「待连接引脚」过滤（拖到空白
  松开的 UE5 行为）；
- ``ElaNodeContextMenu``：基于 **ElaMenu** 的节点右键菜单模板（图标动作
  + 主题自动感知），各动作只发信号，开发者自由挂接实现；
  ``add_custom_action`` 可追加自定义动作。

移植自 InstructionX_UIKit.blueprint.menu（原库为 PyQt6，类名 Ela*
前缀；原 QDialog+QLineEdit+QListWidget+QSS 已重构为 Ela 组件；
原库无 LICENSE，保留出处）。
"""

from __future__ import annotations

from PyQt6.QtCore import QPoint, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import (
    QAction,
    QColor,
    QFont,
    QPainter,
    QPen,
    QStandardItem,
    QStandardItemModel,
)
from PyQt6.QtWidgets import QDialog, QLineEdit, QVBoxLayout
from PyQt6ElaWidgetTools import (
    ElaIcon,
    ElaIconType,
    ElaLineEdit,
    ElaListView,
    ElaMenu,
    ElaThemeType,
    eTheme,
)

from ._tokens import theme_changed_slot
from .model import ElaPinDirectionType, types_compatible
from .registry import ElaNodeRegistry

__all__ = ["ElaNodeCreationMenu", "ElaNodeContextMenu"]

#: 语义槽位（**必须是枚举成员**：PyQt6 的 getThemeColor 只接受枚举，
#: 传位次数字直接 `TypeError: argument 2 has unexpected type 'int'`）
_TC_POPUP_BASE = ElaThemeType.ThemeColor.PopupBase
_TC_POPUP_BORDER = ElaThemeType.ThemeColor.PopupBorder
_TC_TEXT = ElaThemeType.ThemeColor.BasicText
_TC_TEXT_CATEGORY = ElaThemeType.ThemeColor.BasicTextCategory

#: 分类 → 列表项图标（未知分类回退 Circle）
_CATEGORY_ICONS = {
    "输入": ElaIconType.IconName.ArrowDownToBracket,
    "输出": ElaIconType.IconName.ArrowUpFromBracket,
    "处理": ElaIconType.IconName.Wrench,
    "流程": ElaIconType.IconName.RightFromBracket,
}
_DEFAULT_CATEGORY_ICON = ElaIconType.IconName.Circle
#: 分类图标缓存（主题切换后失效重建；键 = (IconName, 主题色 hex)）
_CATEGORY_ICON_CACHE = {}


def _theme_color(color: ElaThemeType.ThemeColor) -> str:
    """按主题槽位取色（hex 字符串）。"""
    return eTheme.getThemeColor(eTheme.getThemeMode(), color).name()


def _category_icon(category: str):
    """分类对应的列表项图标。"""
    return _CATEGORY_ICONS.get(category, _DEFAULT_CATEGORY_ICON)


def _item_icon(category: str) -> None:
    """生成分类项图标（按 图标名 + 主题色 缓存，主题切换后键变化自动重建）。"""
    key = (_category_icon(category), _theme_color(_TC_TEXT))
    icon = _CATEGORY_ICON_CACHE.get(key)
    if icon is None:
        icon = ElaIcon.getInstance().getElaIcon(key[0], 14, QColor(key[1]))
        if len(_CATEGORY_ICON_CACHE) >= 32:
            _CATEGORY_ICON_CACHE.clear()
        _CATEGORY_ICON_CACHE[key] = icon
    return icon


class ElaNodeCreationMenu(QDialog):
    """节点创建菜单（Popup 弹出，搜索 + 分类分组列表）。

    信号:
        type_chosen(str): 用户选定了某节点类型（参数为 ``type_name``）。

    用法::

        menu = ElaNodeCreationMenu(canvas)
        menu.type_chosen.connect(lambda t: canvas.add_node_at(t, scene_pos))
        menu.popup_at(QCursor.pos())

    拖线到空白松开的场景可传 ``compatible`` 过滤：

        # 只列出拥有「Input 且兼容 image」引脚的节点类型
        menu.popup_at(pos, compatible=(ElaPinDirectionType.Input, "image"))

    :param parent: 父控件
    :param owner: 命名空间标识（缺省 None 列全部类型）；给定时只列出
        「该 owner + 全局命名空间」的节点类型

    生命周期：每次弹出新建实例，选定条目或关闭后自毁
    （``WA_DeleteOnClose``）。
    """

    #: 选定节点类型信号，参数为 type_name
    type_chosen = pyqtSignal(str)

    def __init__(self, parent=None, owner: str = None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        # 半透明窗口：四角由自绘圆角裁出（否则先铺满矩形底色，圆角描边
        # 只是画在矩形里的一圈线，窗口本身还是方的）
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMinimumWidth(280)
        self._compatible = None
        self._owner = owner
        # _rebuild 才赋值；keyPressEvent 的 returnPressed 分支会读它，
        # 首帧之前按 Enter 会 AttributeError（抛进 Qt 回调 = 进程 abort）。
        self._first_item = None
        # 双击 / 回车可能让 clicked 与 activated 同时到达；首个 _pick 生效
        self._picked = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        # 搜索框：ElaLineEdit（主题感知 + 清除按钮 + 放大镜图标）
        self.search_edit = ElaLineEdit(self)
        self.search_edit.setPlaceholderText("搜索节点…")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setBorderRadius(6)
        self._search_icon_action = QAction(self.search_edit)
        self.search_edit.addAction(
            self._search_icon_action, QLineEdit.ActionPosition.LeadingPosition
        )

        # 分类列表：ElaListView（主题感知自绘 + ElaScrollBar）
        self.list = ElaListView(self)
        self.list.setItemHeight(32)
        self.list.setIsTransparent(True)
        self.list.setMinimumHeight(220)
        self.list.setMaximumHeight(360)
        self._model = QStandardItemModel(self.list)
        self.list.setModel(self._model)
        lay.addWidget(self.search_edit)
        lay.addWidget(self.list)

        self.search_edit.textChanged.connect(lambda _t: self._rebuild())
        self.search_edit.returnPressed.connect(self._choose_first)
        self.list.clicked.connect(self._on_index)
        self.list.activated.connect(self._on_index)
        # 绑定方法连接：receiver（本对话框）随 WA_DeleteOnClose 销毁时
        # 自动断连，单例信号上不残留死对象包装
        theme_changed_slot(self, self._retheme)
        self._retheme()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        """自绘圆角外框（弹层底色 + 1px 边）—— 禁 QSS 后由这里接管。

        窗口带 ``WA_TranslucentBackground``，只有圆角盒内被填充，四角
        真正透明（窗口本身是方的，不铺满看不出圆角）。
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(_theme_color(_TC_POPUP_BASE)))
        painter.drawRoundedRect(rect, 6.0, 6.0)
        painter.setPen(QPen(QColor(_theme_color(_TC_POPUP_BORDER)), 1.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, 6.0, 6.0)
        painter.end()

    def _retheme(self) -> None:
        """主题感知的外框重绘与搜索图标色（内容控件自绘随主题）。"""
        self.update()
        icon = ElaIcon.getInstance().getElaIcon(
            ElaIconType.IconName.MagnifyingGlass, 14, QColor(_theme_color(_TC_TEXT))
        )
        self._search_icon_action.setIcon(icon)

    # -- 弹出 ------------------------------------------------------------
    def popup_at(self, global_pos: QPoint, compatible=None) -> None:
        """在全局坐标弹出菜单，搜索框聚焦。

        :param compatible: 可选 ``(ElaPinDirectionType, data_type)``——只列出
            拥有该方向且类型兼容引脚的节点类型（拖线建节点时传入）。
        """
        self._compatible = compatible
        self.search_edit.clear()
        self._rebuild()
        self.move(global_pos)
        self.show()
        self.raise_()
        self.search_edit.setFocus()

    # -- 列表 ------------------------------------------------------------
    def _spec_visible(self, spec) -> bool:
        """按 compatible 过滤：spec 至少有一个方向 / 类型兼容的引脚。"""
        if self._compatible is None:
            return True
        direction, data_type = self._compatible
        pins = spec.inputs if direction is ElaPinDirectionType.Input else spec.outputs
        for pd in pins:
            pd_type = pd.get("data_type", "any")
            if direction is ElaPinDirectionType.Input:
                if types_compatible(data_type, pd_type):
                    return True
            else:
                if types_compatible(pd_type, data_type):
                    return True
        return False

    def _rebuild(self) -> None:
        """按搜索词 / 兼容过滤重建分类列表（分类头不可选 + 粗体）。"""
        self._model.clear()
        keyword = self.search_edit.text()
        reg = ElaNodeRegistry.instance()
        specs = [
            s for s in reg.search(keyword, owner=self._owner) if self._spec_visible(s)
        ]
        first_item = None
        for category in reg.categories(owner=self._owner):
            cat_specs = [s for s in specs if s.category == category]
            if not cat_specs:
                continue
            header = QStandardItem(category)
            header.setFlags(Qt.ItemFlag.NoItemFlags)
            f = QFont(self.font())
            f.setWeight(QFont.Weight.DemiBold)
            header.setFont(f)
            header.setForeground(QColor(_theme_color(_TC_TEXT_CATEGORY)))
            self._model.appendRow(header)
            for spec in cat_specs:
                item = QStandardItem(f"  {spec.title}")
                item.setData(spec.type_name, Qt.ItemDataRole.UserRole)
                if spec.description:
                    item.setToolTip(spec.description)
                item.setIcon(_item_icon(spec.category))
                self._model.appendRow(item)
                if first_item is None:
                    first_item = item
        self._first_item = first_item
        if first_item is not None:
            self.list.setCurrentIndex(self._model.indexFromItem(first_item))

    def matching_types(self) -> list:
        """当前过滤条件下可见的 ``type_name`` 列表（测试 / 调试友好）。"""
        result = []
        for i in range(self._model.rowCount()):
            t = self._model.item(i).data(Qt.ItemDataRole.UserRole)
            if t:
                result.append(t)
        return result

    def _choose_first(self) -> None:
        """回车：创建当前过滤结果的第一项。"""
        item = self._first_item
        if item is not None:
            self._pick(item.data(Qt.ItemDataRole.UserRole))

    def _on_index(self, index) -> None:
        item = self._model.itemFromIndex(index)
        if item is None:
            return
        type_name = item.data(Qt.ItemDataRole.UserRole)
        if not type_name:
            return
        self._pick(type_name)

    def _pick(self, type_name) -> None:
        """选定类型：关闭并发射信号（close + WA_DeleteOnClose 自毁）。

        幂等：``clicked`` 与 ``activated`` 可能对同一次交互都到达
        （双击 / 某些平台样式），首个生效，之后忽略 —— 否则建两个节点。
        """
        if self._picked is not None:
            return
        self._picked = type_name
        self.close()
        self.type_chosen.emit(type_name)


class ElaNodeContextMenu(ElaMenu):
    """节点右键菜单模板（ElaMenu 图标动作，各动作只发信号，开发者可挂回调）。

    内置动作与信号（参数均为节点 id）：
    ``rename_requested`` 重命名 / ``duplicate_requested`` 复制 /
    ``disconnect_requested`` 断开所有连线 / ``delete_requested`` 删除 /
    ``properties_requested`` 属性。

    画布为「复制 / 断开 / 删除」挂了默认实现；「重命名 / 属性」完全交给
    开发者（例如打开属性面板）。追加自定义动作::

        menu = ElaNodeContextMenu(node.id, canvas)
        menu.add_custom_action("导出子图", lambda nid: print("导出", nid))
        menu.exec(QCursor.pos())
    """

    rename_requested = pyqtSignal(str)
    duplicate_requested = pyqtSignal(str)
    disconnect_requested = pyqtSignal(str)
    delete_requested = pyqtSignal(str)
    properties_requested = pyqtSignal(str)

    def __init__(self, node_id: str, parent=None):
        super().__init__(parent)
        # 与 ElaNodeCreationMenu 一致：画布每次右键都 new 一个，parent 是 canvas，
        # 不设 WA_DeleteOnClose 的话局部引用一掉就被 GC 忽略（QObject 有父），
        # 每右键一次就在 canvas 上永久挂一个 QMenu。
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.node_id = node_id
        self._add(ElaIconType.IconName.PenToSquare, "重命名", self.rename_requested)
        self._add(ElaIconType.IconName.Copy, "复制", self.duplicate_requested)
        self._add(ElaIconType.IconName.LinkSlash, "断开所有连线", self.disconnect_requested)
        self.addSeparator()
        self._add(ElaIconType.IconName.Gear, "属性…", self.properties_requested)
        self.addSeparator()
        self._add(ElaIconType.IconName.TrashCan, "删除", self.delete_requested)

    def _add(self, icon, text: str, signal) -> None:
        self.addElaIconAction(icon, text).triggered.connect(
            lambda: signal.emit(self.node_id)
        )

    def add_custom_action(self, text: str, callback) -> None:
        """追加自定义动作；``callback`` 接收节点 id 作为唯一参数。"""
        self.addAction(text, lambda: callback(self.node_id))
