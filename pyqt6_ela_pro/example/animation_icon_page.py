"""
[pyqt6_ela_pro] 动画与图标组件页面

合并了以下来源的组件:
- pyqt6_ela_pro: 动画、SVG图标组件
- PyQt6ElaWidgetTools: 图标组件
"""

import os

from PyQt6.QtWidgets import QApplication, QHBoxLayout, QListView, QVBoxLayout, QWidget
from PyQt6.QtCore import Qt, QModelIndex
from PyQt6ElaWidgetTools import (
    ElaText,
    ElaIconButton,
    ElaIconType,
    ElaListView,
    ElaLineEdit,
    ElaMessageBar,
    ElaMessageBarType,
    ElaPushButton,
)
from pyqt6_ela_pro import (
    fade_in,
    fade_out,
    ElaAnimatedMixin,
    shake_window,
    ElaDialogBase,
    svg_to_icon,
    svg_to_pixmap,
    svg_icon_loader,
    Duration,
    ElaMotionModeType,
    motion,
)
from pyqt6_ela_pro.svg_icon import (
    ElaSvgIconLoader,
)
from .base_page import ExamplePage
from ..blueprint._spinner import SpinnerArc
from .icon_model import T_IconModel
from .icon_delegate import T_IconDelegate
from .es_icon_model import EsIconModel
from .es_icon_delegate import EsIconDelegate


#: 本页演示用的几个内联 SVG。**本库不再自带图标集**（曾随包分发 3.66 MB /
#: 2604 个 Fluent UI 图标），所以下面两节用这几个内联图标演示 loader 与渲染
#: 函数；宿主请用 ``setPackageDirectory`` + ``loadFromPackage`` / ``loadFromFile``
#: 换成自己的图标包（第 01 节底部有入口）。
_SVG_BODY = {
    "ic_demo_circle": '<circle cx="12" cy="12" r="8"/>',
    "ic_demo_square": '<rect x="5" y="5" width="14" height="14" rx="2"/>',
    "ic_demo_triangle": '<path d="M12 4 L21 20 L3 20 Z"/>',
    "ic_demo_arrow": '<path d="M4 12h14M13 6l6 6-6 6"/>',
    "ic_demo_bolt": '<path d="M13 2 L4 14 L11 14 L10 22 L20 10 L13 10 Z"/>',
    "ic_demo_star": '<path d="M12 3 L14.5 9.5 L21 10 L16 15 L17.5 22 L12 18.5 L6.5 22 L8 15 L3 10 L9.5 9.5 Z"/>',
}


def _stroke_svg(body: str) -> str:
    """把描边路径包成 24x24 的 SVG 源码（带主题色占位符）。"""
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"'
        ' stroke="<<<COLOR_CODE>>>" stroke-width="2" stroke-linecap="round"'
        f' stroke-linejoin="round">{body}</svg>'
    )


class _AnimatedDemoDialog(ElaAnimatedMixin, ElaDialogBase):
    def __init__(self, parent=None):
        super().__init__("ElaAnimatedMixin 演示", parent=parent)
        content_widget = QWidget(self)
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 10, 0, 0)
        info = ElaText(
            "通过 ElaAnimatedMixin 继承获得 fade_in() / fade_out()\n对话框自身拥有动画方法",
            content_widget,
        )
        info.setTextPixelSize(14)
        content_layout.addWidget(info)
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        shake_btn = ElaPushButton("抖动", content_widget)
        shake_btn.setFixedWidth(80)
        shake_btn.clicked.connect(self.shake)
        btn_layout.addWidget(shake_btn)
        content_layout.addLayout(btn_layout)
        self.setParamWidget(content_widget)
        self.setFixedHeight(300)
        self.fade_in()

    def shake(self):
        shake_window(self)


class AnimationIconPage(ExamplePage):
    """动画与图标组件页面"""

    PAGE_TITLE = "动画与图标"

    def __init__(self, parent=None):
        self._svg_loader = None
        # 浏览器段的模型 / 视图句柄：加载图标包的回调要用（列表是在
        # _addDemoContent 里才建的，所以这里必须先给默认值）
        self._svgModel = None
        self._svgView = None
        self._spinner = None
        self._motion_state = None
        super().__init__(parent)

    def _addDemoContent(self, main_layout):
        self._demoAnimation(main_layout)
        self._demoIcon(main_layout)
        self._demoSvgIcon(main_layout)

    def _demoAnimation(self, parent_layout):
        parent_layout.addWidget(self._createSectionHeader("=== ela_ext - 动画特效 ==="))
        self._demoFadeInOut(parent_layout)
        self._demoShakeWindow(parent_layout)
        self._demoAnimatedMixin(parent_layout)
        self._demoMotionPolicy(parent_layout)

    def _demoIcon(self, parent_layout):
        parent_layout.addWidget(
            self._createSectionHeader("=== PyQt6ElaWidgetTools - 图标组件 ===")
        )
        self._demoIconBrowser(parent_layout)
        self._demoIconButtons(parent_layout)

    def _demoSvgIcon(self, parent_layout):
        parent_layout.addWidget(
            self._createSectionHeader("=== ela_ext - SVG图标组件 ===")
        )
        self._demoSvgIconBrowser(parent_layout)
        self._demoSvgFunctions(parent_layout)

    def _demoFadeInOut(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "01. ela_ext - fade_in / fade_out 淡入淡出动画", self._demoFadeInOut
            )
        )
        self._addInfoText(
            "对任意 QWidget 执行淡入淡出动画，支持动画完成回调", parent_layout
        )
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(15)
        fade_in_btn = ElaPushButton("淡入窗口", self)
        fade_in_btn.setFixedWidth(100)
        fade_in_btn.clicked.connect(self._onFadeIn)
        btn_layout.addWidget(fade_in_btn)
        fade_out_btn = ElaPushButton("淡出窗口", self)
        fade_out_btn.setFixedWidth(100)
        fade_out_btn.clicked.connect(self._onFadeOut)
        btn_layout.addWidget(fade_out_btn)
        btn_layout.addStretch()
        parent_layout.addLayout(btn_layout)
        parent_layout.addSpacing(20)

    def _demoShakeWindow(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "02. ela_ext - shake_window 窗口抖动", self._demoShakeWindow
            )
        )
        self._addInfoText("使窗口产生抖动效果，常用于错误提示", parent_layout)
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(15)
        shake_btn = ElaPushButton("抖动窗口", self)
        shake_btn.setFixedWidth(100)
        shake_btn.clicked.connect(lambda: shake_window(self.window()))
        btn_layout.addWidget(shake_btn)
        btn_layout.addStretch()
        parent_layout.addLayout(btn_layout)
        parent_layout.addSpacing(20)

    def _demoAnimatedMixin(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "03. ela_ext - ElaAnimatedMixin 对话框动画混入", self._demoAnimatedMixin
            )
        )
        self._addInfoText(
            "通过继承 ElaAnimatedMixin，对话框自动获得 fade_in() / fade_out() 方法",
            parent_layout,
        )
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(15)
        open_btn = ElaPushButton("打开动画对话框", self)
        open_btn.setFixedWidth(120)
        open_btn.clicked.connect(self._openAnimatedDialog)
        btn_layout.addWidget(open_btn)
        btn_layout.addStretch()
        parent_layout.addLayout(btn_layout)
        parent_layout.addSpacing(20)

    def _onFadeIn(self):
        fade_in(self.window())

    def _onFadeOut(self):
        w = self.window()
        fade_out(w, on_finished=lambda: fade_in(w, duration=500))

    def _openAnimatedDialog(self):
        dialog = _AnimatedDemoDialog(self)
        dialog.exec()

    def _demoMotionPolicy(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "04. ela_ext - 全局动效策略 motion", self._demoMotionPolicy
            )
        )
        self._addInfoText(
            "默认跟随系统的「关闭动画」设置（SPI_GETCLIENTAREAANIMATION）。\n"
            "Reduced 不是关掉动画：状态过渡压到 50ms 内，只是持续动效停掉。\n"
            "Disabled 下过渡同步落终值，收尾回调当场触发、不等下一帧。",
            parent_layout,
        )
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(15)
        for mode in (ElaMotionModeType.Full, ElaMotionModeType.Reduced, ElaMotionModeType.Disabled):
            btn = ElaPushButton(mode.name, self)
            btn.setFixedWidth(100)
            btn.clicked.connect(lambda _checked=False, m=mode: self._onModeClicked(m))
            btn_layout.addWidget(btn)
        btn_layout.addSpacing(20)
        show_btn = ElaPushButton("播放一次淡出→淡入", self)
        show_btn.setFixedWidth(180)
        show_btn.clicked.connect(self._onPolicyFade)
        btn_layout.addWidget(show_btn)
        self._spinner = SpinnerArc(size=28, interval=40)
        btn_layout.addWidget(self._spinner)
        btn_layout.addStretch()
        parent_layout.addLayout(btn_layout)
        self._motion_state = ElaText(self._motionStateText(), self)
        self._motion_state.setTextPixelSize(14)
        parent_layout.addWidget(self._motion_state)
        self._note(
            parent_layout,
            "右侧圆弧是持续动效：Full 下转，Reduced/Disabled 下冻结在当前角度"
            "（停掉而不是放慢 —— 转得更慢的圈看起来像卡住）。",
        )
        parent_layout.addSpacing(20)

    def _motionStateText(self) -> str:
        return (
            f"当前模式：{motion.mode().name}    系统关闭动画：{motion.systemReduced()}"
        )

    def _note(self, parent_layout, text):
        label = ElaText(text, parent_layout.parentWidget())
        # ElaText 不设字号就用默认的 28px，整张卡的比例会直接崩掉
        label.setTextPixelSize(14)
        parent_layout.addWidget(label)

    def _onModeClicked(self, mode):
        # 宿主可以随时覆盖系统设置（测试也是靠它拿确定性）。
        motion.setOverrideSystem(True)
        motion.setMode(mode)
        if self._motion_state is not None:
            self._motion_state.setText(self._motionStateText())
        # 持续动效循环由 start_idle_loop 托管：切到 Reduced/Disabled 会自动停掉并
        # 落到静态基态，切回 Full 需要调用方自己再 start_idle_loop 一次。
        if self._spinner is not None:
            self._spinner.start()
        self._onPolicyFade()

    def _onPolicyFade(self):
        w = self.window()
        if w is None:
            return
        # 在 Reduced/Disabled 下这段代码完全不变：策略只改实际时长与是否同步落终值，
        # 收尾回调照常触发。宿主不需要为动效策略写任何分支。
        fade_out(w, on_finished=lambda: fade_in(w, duration=Duration.Normal))

    def _demoIconBrowser(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "01. PyQt6ElaWidgetTools - 图标浏览器 所有可用图标",
                self._demoIconBrowser,
            )
        )
        self._addInfoText("一堆常用图标被放置于此，左键单击以复制其枚举", parent_layout)
        parent_layout.addSpacing(10)
        self._iconKeys = [attr for attr in dir(ElaIconType) if not attr.startswith("_")]
        self._iconView = ElaListView(self)
        self._iconView.setIsTransparent(True)
        self._iconView.setFlow(QListView.Flow.LeftToRight)
        self._iconView.setViewMode(QListView.ViewMode.IconMode)
        self._iconView.setResizeMode(QListView.ResizeMode.Adjust)
        self._iconView.clicked.connect(self._onIconClicked)
        self._iconModel = T_IconModel(self)
        self._iconDelegate = T_IconDelegate(self)
        self._iconView.setModel(self._iconModel)
        self._iconView.setItemDelegate(self._iconDelegate)
        self._iconView.setFixedHeight(800)
        self._iconView.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._searchEdit = ElaLineEdit(self)
        self._searchEdit.setPlaceholderText("搜索图标")
        self._searchEdit.setFixedSize(300, 35)
        self._searchEdit.textEdited.connect(self._onSearchEditTextEdit)
        parent_layout.addWidget(self._searchEdit)
        parent_layout.addWidget(self._iconView)
        parent_layout.addSpacing(30)

    def _onIconClicked(self, index: QModelIndex):
        iconName = self._iconModel.getIconNameFromModelIndex(index)
        if not iconName:
            return
        from PyQt6.QtWidgets import QApplication

        QApplication.clipboard().setText(iconName)
        ElaMessageBar.success(
            ElaMessageBarType.PositionPolicy.Top,
            "复制完成",
            f"{iconName}已被复制到剪贴板",
            1000,
            self,
        )

    def _onSearchEditTextEdit(self, searchText: str):
        if not searchText:
            self._iconModel.setIsSearchMode(False)
            self._iconModel.setSearchKeyList([])
            self._iconView.clearSelection()
            self._iconView.viewport().update()
            return
        searchKeyList = []
        for key in self._iconKeys:
            if key.lower().__contains__(searchText.lower()):
                searchKeyList.append(key)
        self._iconModel.setIsSearchMode(True)
        self._iconModel.setSearchKeyList(searchKeyList)
        self._iconView.clearSelection()
        self._iconView.scrollTo(self._iconModel.index(0, 0))
        self._iconView.viewport().update()

    def _demoIconButtons(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "02. PyQt6ElaWidgetTools - 图标按钮 带图标的按钮", self._demoIconButtons
            )
        )
        self._addInfoText("图标按钮组件演示", parent_layout)
        parent_layout.addSpacing(10)
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(15)
        # noinspection PyTypeChecker
        icon_btn1 = ElaIconButton(ElaIconType.IconName.FloppyDisk, 16, self)
        icon_btn1.setFixedSize(40, 40)
        btn_layout.addWidget(icon_btn1)
        # noinspection PyTypeChecker
        icon_btn2 = ElaIconButton(ElaIconType.IconName.Pencil, 16, self)
        icon_btn2.setFixedSize(40, 40)
        btn_layout.addWidget(icon_btn2)
        # noinspection PyTypeChecker
        icon_btn3 = ElaIconButton(ElaIconType.IconName.Trash, 16, self)
        icon_btn3.setFixedSize(40, 40)
        btn_layout.addWidget(icon_btn3)
        # noinspection PyTypeChecker
        icon_btn4 = ElaIconButton(ElaIconType.IconName.MagnifyingGlass, 16, self)
        icon_btn4.setFixedSize(40, 40)
        btn_layout.addWidget(icon_btn4)
        btn_layout.addStretch()
        parent_layout.addLayout(btn_layout)

    def _getSvgLoader(self):
        """本页的 loader —— 先塞几个内联图标，让下面两节有东西可演示。

        真实宿主走 ``setPackageDirectory()`` + ``loadFromPackage()`` 加载自己的
        ``.icons`` 包（见第 01 节底部的加载入口）。
        """
        if self._svg_loader is None:
            self._svg_loader = ElaSvgIconLoader()
            for name, body in _SVG_BODY.items():
                self._svg_loader.append(name, _stroke_svg(body))
        return self._svg_loader

    def _onLoadPackageClicked(self, path: str) -> None:
        """加载按钮 / 回车的统一入口（列表句柄此时可能已就绪）。"""
        view = getattr(self, "_svgView", None)
        if view is None:
            return
        self._onLoadIconPackage(path, view)

    def _onLoadIconPackage(self, path: str, view) -> None:
        """按路径加载宿主的 ``.icons`` 图标包并刷新浏览器。

        ``setPackageDirectory`` 是关键：不设的话 ``loadFromPackage`` 会去库内置
        目录找，而那里现在什么都没有 —— 往 site-packages 里塞文件既脆弱又需要
        管理员权限，所以包目录必须由宿主给。
        """
        from PyQt6ElaWidgetTools import ElaMessageBar, ElaMessageBarType

        text = path.strip()
        if not text:
            return
        loader = self._getSvgLoader()
        try:
            loader.setPackageDirectory(text)
            loader.loadFromPackage(os.path.basename(text))
        except FileNotFoundError as exc:
            # 传进来的可能是完整文件路径，退一步按文件直接读
            try:
                loader.loadFromFile(text)
            except FileNotFoundError:
                ElaMessageBar.error(
                    ElaMessageBarType.PositionPolicy.Top,
                    "图标包加载失败",
                    str(exc),
                    3000,
                    self,
                )
                return
        except Exception as exc:  # noqa: BLE001 —— demo 回调，兜住别炸页面
            ElaMessageBar.error(
                ElaMessageBarType.PositionPolicy.Top,
                "图标包解析失败",
                str(exc),
                3000,
                self,
            )
            return

        names = loader.iconNames()
        model = getattr(self, "_svgModel", None)
        if model is not None:
            model.resetIconNames(names)
        view.viewport().update()
        ElaMessageBar.success(
            ElaMessageBarType.PositionPolicy.Top,
            "图标包已加载",
            f"当前共 {len(names)} 个图标",
            2000,
            self,
        )

    def _demoSvgIconBrowser(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "01. ela_ext - SVG图标浏览器 所有可用图标", self._demoSvgIconBrowser
            )
        )
        self._addInfoText(
            "本库不自带图标集 —— 下面几个是内联演示图标。宿主请把自己的\n"
            ".icons 图标包路径填进上面那栏，用 setPackageDirectory + "
            "loadFromPackage 加载（不设目录的话会去库内置目录找，而那里现在\n"
            "什么都没有）。点击图标可复制其名称。",
            parent_layout,
        )
        parent_layout.addSpacing(10)

        # 宿主图标包加载入口：setPackageDirectory + loadFromPackage
        pack_row = QHBoxLayout()
        pack_row.setSpacing(8)
        pack_edit = ElaLineEdit(self)
        pack_edit.setPlaceholderText("你的 .icons 图标包目录，例如 D:/assets/icons")
        # 列表在这之后才建，回调里可能还没句柄 —— 所以走 _onLoadPackageClicked
        # 自己去取，不要在 lambda 里绑一个还不存在的局部变量
        pack_edit.returnPressed.connect(
            lambda: self._onLoadPackageClicked(pack_edit.text())
        )
        pack_row.addWidget(pack_edit)
        pack_btn = ElaPushButton("加载图标包", self)
        pack_btn.setFixedWidth(110)
        pack_btn.clicked.connect(lambda: self._onLoadPackageClicked(pack_edit.text()))
        pack_row.addWidget(pack_btn)
        pack_row.addStretch()
        parent_layout.addLayout(pack_row)
        parent_layout.addSpacing(8)

        svg_list_view = ElaListView(self)
        svg_list_view.setIsTransparent(True)
        svg_list_view.setFlow(QListView.Flow.LeftToRight)
        svg_list_view.setViewMode(QListView.ViewMode.IconMode)
        svg_list_view.setFixedHeight(800)
        svg_list_view.setResizeMode(QListView.ResizeMode.Adjust)
        svg_list_view.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        loader = self._getSvgLoader()
        icon_names = loader.iconNames()
        svg_model = EsIconModel(icon_names, self)
        svg_delegate = EsIconDelegate(loader, self)
        svg_list_view.setModel(svg_model)
        svg_list_view.setItemDelegate(svg_delegate)
        svg_list_view.clicked.connect(
            lambda index: self._onSvgIconClicked(index, loader)
        )
        # 存句柄给上面的加载回调用（此时列表还没建，回调里可能还是 None）
        self._svgModel = svg_model
        self._svgView = svg_list_view
        svg_search_edit = ElaLineEdit(self)
        svg_search_edit.setPlaceholderText("搜索图标")
        svg_search_edit.setFixedSize(300, 35)
        svg_search_edit.textEdited.connect(
            lambda text: self._onSvgSearchEditTextEdit(text, svg_model, svg_list_view)
        )
        parent_layout.addWidget(svg_search_edit)
        parent_layout.addWidget(svg_list_view)

    def _onSvgIconClicked(self, index: QModelIndex, _loader):
        icon_name = index.data()
        if not icon_name:
            return

        QApplication.clipboard().setText(icon_name)
        ElaMessageBar.success(
            ElaMessageBarType.PositionPolicy.Top,
            "复制完成",
            f"{icon_name}已被复制到剪贴板",
            1000,
            self,
        )

    def _onSvgSearchEditTextEdit(self, searchText: str, model, view):
        if not searchText:
            model.setIsSearchMode(False)
            model.setSearchKeyList([])
            view.clearSelection()
            view.viewport().update()
            return
        loader = self._getSvgLoader()
        all_icon_names = loader.iconNames()
        search_key_list = []
        for name in all_icon_names:
            if searchText.lower() in name.lower():
                search_key_list.append(name)
        model.setIsSearchMode(True)
        model.setSearchKeyList(search_key_list)
        view.clearSelection()
        view.scrollTo(model.index(0, 0))
        view.viewport().update()

    def _demoSvgFunctions(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "04. ela_ext - svg_to_icon / svg_to_pixmap / svg_icon_loader",
                self._demoSvgFunctions,
            )
        )
        self._addInfoText(
            "把 SVG 源码转成 QIcon/QPixmap（首参是源码字符串，不是图标名、\n"
            "也不是文件路径），以及取全局图标加载器。注意 svg_icon_loader()\n"
            "不再自动加载任何图标包 —— 共 0 个图标是正常的，宿主自己加载。",
            parent_layout,
        )
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(15)

        icon_btn = ElaPushButton("svg_to_icon", self)
        icon_btn.setFixedWidth(120)
        icon_btn.clicked.connect(self._onDemoSvgToIcon)
        btn_layout.addWidget(icon_btn)

        pixmap_btn = ElaPushButton("svg_to_pixmap", self)
        pixmap_btn.setFixedWidth(120)
        pixmap_btn.clicked.connect(self._onDemoSvgToPixmap)
        btn_layout.addWidget(pixmap_btn)

        loader_btn = ElaPushButton("svg_icon_loader", self)
        loader_btn.setFixedWidth(120)
        loader_btn.clicked.connect(self._onDemoSvgLoader)
        btn_layout.addWidget(loader_btn)

        btn_layout.addStretch()
        parent_layout.addLayout(btn_layout)
        parent_layout.addSpacing(20)

    def _onDemoSvgToIcon(self):
        try:
            loader = self._getSvgLoader()
            names = loader.iconNames()
            if names:
                # 首参是 **SVG 源码**，不是图标名 —— 直接喂名字会渲染出空图
                # （QSvgRenderer 解析失败且不报错），这坑 README 的 API 表记着
                icon = svg_to_icon(loader.getSvgData(names[0]), size=48)
                from PyQt6ElaWidgetTools import ElaMessageBar, ElaMessageBarType

                ElaMessageBar.success(
                    ElaMessageBarType.PositionPolicy.Top,
                    "svg_to_icon",
                    f"已将 '{names[0]}' 转换为 QIcon（48x48，空图={icon.isNull()}）",
                    3000,
                    self,
                )
        except Exception as e:
            from PyQt6ElaWidgetTools import ElaMessageBar, ElaMessageBarType

            ElaMessageBar.error(
                ElaMessageBarType.PositionPolicy.Top,
                "svg_to_icon",
                f"失败: {e}",
                3000,
                self,
            )

    def _onDemoSvgToPixmap(self):
        try:
            loader = self._getSvgLoader()
            names = loader.iconNames()
            if names:
                pixmap = svg_to_pixmap(loader.getSvgData(names[0]), size=48)
                from PyQt6ElaWidgetTools import ElaMessageBar, ElaMessageBarType

                ElaMessageBar.success(
                    ElaMessageBarType.PositionPolicy.Top,
                    "svg_to_pixmap",
                    f"已将 '{names[0]}' 转换为 QPixmap（{pixmap.width()}x{pixmap.height()}）",
                    3000,
                    self,
                )
        except Exception as e:
            from PyQt6ElaWidgetTools import ElaMessageBar, ElaMessageBarType

            ElaMessageBar.error(
                ElaMessageBarType.PositionPolicy.Top,
                "svg_to_pixmap",
                f"失败: {e}",
                3000,
                self,
            )

    def _onDemoSvgLoader(self):
        loader = svg_icon_loader()
        count = len(loader)
        from PyQt6ElaWidgetTools import ElaMessageBar, ElaMessageBarType

        ElaMessageBar.success(
            ElaMessageBarType.PositionPolicy.Top,
            "svg_icon_loader",
            f"全局图标加载器已获取，共 {count} 个图标"
            + (
                "（本库不自带图标集，用 loadFromFile / loadFromPackage 加载）"
                if count == 0
                else ""
            ),
            3000,
            self,
        )
