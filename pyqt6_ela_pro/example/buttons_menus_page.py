"""按钮与菜单

所有「点一下会做事」的控件。

原「增强按钮」页第 01 节是 ElaTagLineEdit（输入框），页名与内容
不符，已挪到「输入与选择」。原生 ElaPushButton / ElaToolButton /
ElaIconButton 从「基础控件」并到这里 —— 它们和 ElaButton 是同一族，
拆两页等于逼用户自己判断「该用哪个」。
"""

from functools import partial

from PyQt6.QtCore import QPoint, QTimer, Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication, QGridLayout, QHBoxLayout
from PyQt6ElaWidgetTools import (
    ElaIconButton,
    ElaIconType,
    ElaMenu,
    ElaMenuBar,
    ElaMessageBar,
    ElaMessageBarType,
    ElaPushButton,
    ElaText,
    ElaThemeType,
    ElaToggleButton,
    ElaToolButton,
    eTheme,
)
from .base_page import ExamplePage
from pyqt6_ela_pro import (
    ElaButton,
    ElaDropDownButton,
    ElaLongPressButton,
    ElaProgressButton,
    ElaSplitButton,
    accent,
    resetAccentColor,
    setAccentColor,
)
from pyqt6_ela_pro.svg_icon import svg_icon_loader

#: 演示用的内联 SVG（24x24 描边风格）。
#: ``<<<COLOR_CODE>>>`` 会被 :meth:`ElaButton.setSvgIcon` 替换成**当前主题文字色**
#: —— 这就是 SVG 图标能跟随深浅色主题与禁用态的原理：宿主不用为两套主题各画一份。
_SVG_BODY = {
    "search": '<circle cx="11" cy="11" r="7"/><path d="M16 16l4 4"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "download": '<path d="M12 4v11M7 11l5 5 5-5M5 20h14"/>',
    "close": '<path d="M6 6l12 12M18 6L6 18"/>',
}


def _stroke_svg(body: str) -> str:
    """把一段描边路径包成 24x24 的 SVG 源码（带主题色占位符）。"""
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"'
        ' stroke="<<<COLOR_CODE>>>" stroke-width="2" stroke-linecap="round"'
        f' stroke-linejoin="round">{body}</svg>'
    )


#: 强调色预设。第一个是上游出厂值，其余用来演示「换色后 hover/press 跟着变」。
_ACCENT_PRESETS = [
    ("出厂蓝", "#0067c0"),
    ("赤陶红", "#c0392b"),
    ("松石绿", "#16a085"),
    ("紫罗兰", "#8e44ad"),
    ("琥珀橙", "#d35400"),
]


class ButtonsMenusPage(ExamplePage):
    """按钮与菜单示例页。"""

    PAGE_TITLE = "按钮与菜单"

    def __init__(self, parent=None):
        self._nameEdit = None
        self._passwordEdit = None
        self._longPressBtn = None
        self._accentInfo = None
        super().__init__(parent)

    def _addDemoContent(self, main_layout):
        self._demoPushButton(main_layout)
        self._demoToolButton(main_layout)
        self._demoIconButton(main_layout)
        self._demoToggleButton(main_layout)
        self._demoPrimaryButton(main_layout)
        self._demoLongPressButton(main_layout)
        self._demoProgressButton(main_layout)
        self._demoSvgIcon(main_layout)
        self._demoElaButton(main_layout)
        self._demoDropDownButton(main_layout)
        self._demoSplitButton(main_layout)
        self._demoElaMenu(main_layout)
        self._demoMenuBar(main_layout)
        self._demoAccentColor(main_layout)

    def _demoAccentColor(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "99. pyqt6_ela_pro - setAccentColor 强调色换色",
                self._demoAccentColor,
            )
        )
        self._addInfoText(
            "换强调色时 hover / press / 开关圆点会一并派生写入 —— 只改基础色的话，\n"
            "按钮本体是新色、悬停又跳回出厂蓝。派生规则是从出厂值反解的，所以\n"
            "「换色再换回来」是逐值一致的。注意 eTheme 没有换色通知，需要自行重绘。",
            parent_layout,
        )
        row = QHBoxLayout()
        row.setSpacing(12)
        for name, hexColor in _ACCENT_PRESETS:
            btn = ElaPushButton(name, self)
            btn.setFixedWidth(110)
            # 用 partial 而不是 lambda：后者在循环里会闭包捕获循环变量，
            # 且 PyQt6 的 connect(slot, arg) 不是有效重载。
            btn.clicked.connect(partial(self._onAccentPreset, hexColor))
            row.addWidget(btn)
        reset_btn = ElaPushButton("还原", self)
        reset_btn.setFixedWidth(90)
        reset_btn.clicked.connect(self._onAccentReset)
        row.addWidget(reset_btn)
        row.addStretch()
        parent_layout.addLayout(row)
        self._accentInfo = ElaText("", self)
        self._accentInfo.setTextPixelSize(14)
        parent_layout.addWidget(self._accentInfo)
        self._refreshAccentInfo()
        parent_layout.addSpacing(20)

    def _refreshAccentInfo(self):
        if self._accentInfo is None:
            return
        light = accent(ElaThemeType.ThemeMode.Light)
        dark = accent(ElaThemeType.ThemeMode.Dark)
        hover = eTheme.getThemeColor(
            ElaThemeType.ThemeMode.Light, ElaThemeType.ThemeColor.PrimaryHover
        )
        self._accentInfo.setText(
            f"当前强调色  Light {light.name()}   Dark {dark.name()}   "
            f"派生 hover {hover.name()}"
        )

    def _repaint_all(self):
        """``eTheme.setThemeColor`` 没有 NOTIFY 信号，换完色得自己让界面重画。"""
        app = QApplication.instance()
        if app is None:
            return
        for widget in app.topLevelWidgets():
            if not widget.isHidden():
                widget.update()

    def _onAccentPreset(self, hexColor):
        setAccentColor(QColor(hexColor))
        self._repaint_all()
        self._refreshAccentInfo()

    def _onAccentReset(self):
        resetAccentColor()
        self._repaint_all()
        self._refreshAccentInfo()

    def _demoPushButton(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "05. PyQt6ElaWidgetTools - ElaPushButton 按钮", self._demoPushButton
            )
        )
        self._addInfoText("按钮组件", parent_layout)
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(15)
        push_btn = ElaPushButton("按钮", self)
        push_btn.setFixedWidth(100)
        btn_layout.addWidget(push_btn)
        push_btn_disabled = ElaPushButton("禁用", self)
        push_btn_disabled.setFixedWidth(100)
        push_btn_disabled.setEnabled(False)
        btn_layout.addWidget(push_btn_disabled)
        btn_layout.addStretch()
        parent_layout.addLayout(btn_layout)
        parent_layout.addSpacing(20)

    def _demoToolButton(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "06. PyQt6ElaWidgetTools - ElaToolButton 工具按钮", self._demoToolButton
            )
        )
        self._addInfoText("工具按钮组件，用于展示图标", parent_layout)
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(15)
        tool_btn = ElaToolButton(self)
        tool_btn.setElaIcon(ElaIconType.IconName.Plus)
        btn_layout.addWidget(tool_btn)
        tool_btn_disabled = ElaToolButton(self)
        tool_btn_disabled.setElaIcon(ElaIconType.IconName.Minus)
        tool_btn_disabled.setEnabled(False)
        btn_layout.addWidget(tool_btn_disabled)
        btn_layout.addStretch()
        parent_layout.addLayout(btn_layout)
        parent_layout.addSpacing(20)

    def _demoIconButton(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "07. PyQt6ElaWidgetTools - ElaIconButton 图标按钮", self._demoIconButton
            )
        )
        self._addInfoText("图标按钮组件", parent_layout)
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(15)
        icon_btn1 = ElaIconButton(ElaIconType.IconName.Plus, 16, self)
        btn_layout.addWidget(icon_btn1)
        icon_btn2 = ElaIconButton(ElaIconType.IconName.Minus, 16, self)
        btn_layout.addWidget(icon_btn2)
        icon_btn_disabled = ElaIconButton(ElaIconType.IconName.Copy, 16, self)
        icon_btn_disabled.setEnabled(False)
        btn_layout.addWidget(icon_btn_disabled)
        btn_layout.addStretch()
        parent_layout.addLayout(btn_layout)
        parent_layout.addSpacing(20)

    def _demoToggleButton(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "07a. PyQt6ElaWidgetTools - ElaToggleButton 切换按钮",
                self._demoToggleButton,
            )
        )
        self._addInfoText(
            "带文字的开关式按钮，状态变化发 toggled（区别于 ElaToggleSwitch："
            "那是纯开关，这个看起来仍是按钮）",
            parent_layout,
        )
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(15)

        toggle = ElaToggleButton("静音", self)
        toggle.setFixedWidth(110)
        toggle.setIsToggled(False)
        toggle.toggled.connect(
            lambda state: print(f"ElaToggleButton toggled -> {state}")
        )
        btn_layout.addWidget(toggle)

        on_by_default = ElaToggleButton("默认开启", self)
        on_by_default.setFixedWidth(110)
        on_by_default.setIsToggled(True)
        btn_layout.addWidget(on_by_default)

        disabled = ElaToggleButton("禁用", self)
        disabled.setFixedWidth(110)
        disabled.setEnabled(False)
        btn_layout.addWidget(disabled)

        btn_layout.addStretch()
        parent_layout.addLayout(btn_layout)
        parent_layout.addSpacing(20)

    def _demoPrimaryButton(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "02. PyQt6ElaWidgetTools - ElaPushButton 按钮", self._demoPrimaryButton
            )
        )
        self._addInfoText("按钮组件", parent_layout)
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(15)
        primary_btn = ElaPushButton("按钮", self)
        primary_btn.setFixedWidth(120)
        primary_btn.clicked.connect(lambda: print("按钮 clicked"))
        btn_layout.addWidget(primary_btn)
        primary_btn_disabled = ElaPushButton("禁用", self)
        primary_btn_disabled.setFixedWidth(120)
        primary_btn_disabled.setEnabled(False)
        btn_layout.addWidget(primary_btn_disabled)
        btn_layout.addStretch()
        parent_layout.addLayout(btn_layout)
        parent_layout.addSpacing(20)

    def _onLongPressTriggered(self):
        print("长按触发成功！")

    def _setLongPressDuration(self, ms):
        if self._longPressBtn:
            self._longPressBtn.setDuration(ms)
            self._longPressBtn.setText(f"长按 {ms / 1000:.1f} 秒")

    def _demoLongPressButton(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "04. ela_ext - ElaLongPressButton 长按按钮", self._demoLongPressButton
            )
        )
        self._addInfoText(
            "按住按钮一段时间后才触发 longPressed，适合危险操作防误触；"
            "尺寸 / 变体 / 颜色与 ElaButton 共用（size='small' = 22px）",
            parent_layout,
        )
        btn_layout2 = QHBoxLayout()
        btn_layout2.setSpacing(15)
        self._longPressBtn = ElaLongPressButton(duration=800, parent=self)
        self._longPressBtn.setText("长按 0.8 秒")
        self._longPressBtn.setFixedWidth(160)
        self._longPressBtn.longPressed.connect(self._onLongPressTriggered)
        btn_layout2.addWidget(self._longPressBtn)
        small_long_press = ElaLongPressButton(
            "small",
            variant="solid",
            color="primary",
            size="small",
            duration=800,
            parent=self,
        )
        small_long_press.longPressed.connect(self._onLongPressTriggered)
        btn_layout2.addWidget(small_long_press)
        duration_label = ElaText("时长:", self)
        duration_label.setTextPixelSize(14)
        btn_layout2.addWidget(duration_label)
        for ms in [300, 500, 800, 1000]:
            btn = ElaPushButton(f"{ms}ms", self)
            btn.setFixedWidth(60)
            btn.clicked.connect(lambda checked, m=ms: self._setLongPressDuration(m))
            btn_layout2.addWidget(btn)
        btn_layout2.addStretch()
        parent_layout.addLayout(btn_layout2)
        parent_layout.addSpacing(20)

    def _onProgressTimerTick(self):
        current = self._progressBtn.progress()
        if current >= 100:
            self._progressTimer.stop()
            self._progressTimerBtn.setText("启动定时更新")
        else:
            self._progressBtn.setProgress(current + 10)

    def _onProgressTimerToggle(self):
        if self._progressTimer.isActive():
            self._progressTimer.stop()
            self._progressTimerBtn.setText("启动定时更新")
        else:
            self._progressBtn.setProgress(0)
            self._progressTimer.start()
            self._progressTimerBtn.setText("停止定时更新")

    def _demoProgressButton(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "05. pyqt6_ela_pro - ElaProgressButton 进度按钮",
                self._demoProgressButton,
            )
        )
        self._addInfoText(
            "显示进度的按钮组件，通过 setProgress() 设置进度 (0-100)", parent_layout
        )
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(15)
        self._progressBtn = ElaProgressButton(parent=self)
        self._progressBtn.setText("下载")
        self._progressBtn.setFixedWidth(120)
        btn_layout.addWidget(self._progressBtn)
        for percent in [0, 25, 50, 75, 100]:
            btn = ElaPushButton(f"{percent}%", self)
            btn.setFixedWidth(50)
            btn.clicked.connect(
                lambda checked, p=percent: self._progressBtn.setProgress(p)
            )
            btn_layout.addWidget(btn)
        btn_layout.addStretch()
        parent_layout.addLayout(btn_layout)

        auto_layout = QHBoxLayout()
        auto_layout.setSpacing(15)
        self._progressTimerBtn = ElaPushButton("启动定时更新", self)
        self._progressTimerBtn.setFixedWidth(100)
        self._progressTimerBtn.clicked.connect(self._onProgressTimerToggle)
        auto_layout.addWidget(self._progressTimerBtn)
        self._progressTimer = QTimer(self)
        self._progressTimer.setInterval(1000)
        self._progressTimer.timeout.connect(self._onProgressTimerTick)
        auto_layout.addStretch()
        parent_layout.addLayout(auto_layout)
        parent_layout.addSpacing(20)

    def _demoSvgIcon(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "07. ela_ext - ElaButton.setSvgIcon 第三方 SVG 图标", self._demoSvgIcon
            )
        )
        self._addInfoText(
            "setSvgIcon 是本库唯一能在按钮里放非 ElaAwesome 图标的入口 —— 其余按钮\n"
            "（ElaProgressButton / ElaChatToolButton / 上游 ElaPushButton）只认\n"
            "ElaIconType.IconName 枚举。传 SVG 源码就直接渲染；传图标名则去\n"
            "svg_icon_loader 里取，宿主自己 loadFromFile 加载图标包（本库不自带\n"
            "图标集）。SVG 里的 <<<COLOR_CODE>>> 会被替换成当前主题文字色，所以图标\n"
            "自动跟随深浅色主题与禁用态。注意 ElaButton 自绘，QPushButton 的\n"
            "setIcon() 无效（抛 RuntimeError），别在那儿浪费时间。",
            parent_layout,
        )
        parent_layout.addSpacing(10)

        # ① SVG 源码直传 —— 最常见的一次调用搞定
        source_row = QHBoxLayout()
        source_row.setSpacing(15)
        for label, key in (("搜索", "search"), ("添加", "plus"), ("下载", "download")):
            btn = ElaButton(label, variant="outlined", color="primary", parent=self)
            btn.setSvgIcon(_stroke_svg(_SVG_BODY[key]), 16)
            source_row.addWidget(btn)

        # 禁用态也一起演示：图标颜色应与文字一起变灰
        disabled = ElaButton("禁用", variant="outlined", color="primary", parent=self)
        disabled.setSvgIcon(_stroke_svg(_SVG_BODY["search"]), 16)
        disabled.setEnabled(False)
        source_row.addWidget(disabled)

        # 纯图标按钮（无文字）—— 图标单独居中
        icon_only = ElaButton(parent=self)
        icon_only.setSvgIcon(_stroke_svg(_SVG_BODY["close"]), 16)
        icon_only.setToolTip("clearSvgIcon 可退回纯图标状态")
        source_row.addWidget(icon_only)
        source_row.addStretch()
        parent_layout.addLayout(source_row)
        parent_layout.addSpacing(10)

        # ② 图标名形态：先 append 进 loader，再按名字取 —— 适合图标来自
        #    宿主自己的 .icons 图标包的场景
        loader = svg_icon_loader()
        for key in _SVG_BODY:
            loader.append(f"demo_{key}", _stroke_svg(_SVG_BODY[key]))

        name_row = QHBoxLayout()
        name_row.setSpacing(15)
        for label, key in (("按名字", "search"), ("solid 变体", "plus")):
            btn = ElaButton(
                label,
                variant="solid" if key == "plus" else "outlined",
                color="primary",
                parent=self,
            )
            # 返回 False 表示图标包里没这个名字（只画文字并 warn 一次）
            assert btn.setSvgIcon(f"demo_{key}", 16) is True
            name_row.addWidget(btn)

        # 故意演示失败路径：图标名不存在时只画文字 + 警告，不抛异常也不静默
        missing = ElaButton("图标名拼错", variant="outlined", parent=self)
        ok = missing.setSvgIcon("demo_没有这个图标", 16)
        name_row.addWidget(missing)
        assert ok is False
        name_row.addStretch()
        parent_layout.addLayout(name_row)

    def _demoElaButton(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "09. ela_ext - ElaButton 统一按钮", self._demoElaButton
            )
        )
        self._addInfoText(
            "Ant Design 风格按钮 — 6 种变体 × 16 色主题；可见面高度 20/28/36，"
            "键盘 Tab 聚焦有 accent focus ring，setLoading(True) 显示加载指示器",
            parent_layout,
        )
        parent_layout.addSpacing(8)

        variants = ["outlined", "dashed", "solid", "filled", "text", "link"]
        colors = [
            "default",
            "primary",
            "danger",
            "blue",
            "purple",
            "cyan",
            "green",
            "magenta",
            "pink",
            "red",
            "orange",
            "yellow",
            "volcano",
            "geekblue",
            "lime",
            "gold",
        ]
        # Display labels for colors
        color_labels = {
            "default": "Default",
            "primary": "Primary",
            "danger": "Danger",
            "blue": "Blue",
            "purple": "Purple",
            "cyan": "Cyan",
            "green": "Green",
            "magenta": "Magenta",
            "pink": "Pink",
            "red": "Red",
            "orange": "Orange",
            "yellow": "Yellow",
            "volcano": "Volcano",
            "geekblue": "Geekblue",
            "lime": "Lime",
            "gold": "Gold",
        }

        grid = QGridLayout()
        grid.setSpacing(8)

        # Header row
        corner = ElaText("颜色\\变体", self)
        corner.setTextPixelSize(12)
        grid.addWidget(corner, 0, 0, Qt.AlignmentFlag.AlignCenter)
        for j, v in enumerate(variants):
            lbl = ElaText(v.capitalize(), self)
            lbl.setTextPixelSize(12)
            grid.addWidget(lbl, 0, j + 1, Qt.AlignmentFlag.AlignCenter)

        # Data rows
        for i, c in enumerate(colors):
            clbl = ElaText(color_labels[c], self)
            clbl.setTextPixelSize(12)
            grid.addWidget(clbl, i + 1, 0, Qt.AlignmentFlag.AlignCenter)
            for j, v in enumerate(variants):
                btn = ElaButton(color_labels[c], variant=v, color=c, parent=self)
                grid.addWidget(btn, i + 1, j + 1)

        parent_layout.addLayout(grid)
        parent_layout.addSpacing(12)

        # ── Extra: danger, disabled, sizes, icons ──
        row = QHBoxLayout()
        row.setSpacing(12)
        for label, v, c, d in [
            ("危险 Solid", "solid", "default", True),
            ("危险 Outlined", "outlined", "default", True),
        ]:
            b = ElaButton(label, variant=v, danger=d, parent=self)
            row.addWidget(b)
        disabled_s = ElaButton("禁用 Solid", variant="solid", parent=self)
        disabled_s.setEnabled(False)
        row.addWidget(disabled_s)
        disabled_o = ElaButton("禁用 Outlined", variant="outlined", parent=self)
        disabled_o.setEnabled(False)
        row.addWidget(disabled_o)
        for sz in ("small", "middle", "large"):
            b = ElaButton(sz.capitalize(), variant="outlined", size=sz, parent=self)
            row.addWidget(b)
        row.addStretch()
        parent_layout.addLayout(row)
        parent_layout.addSpacing(8)

        # ── Icon buttons ──
        row = QHBoxLayout()
        row.setSpacing(12)
        for text, icon, v, c in [
            ("保存", ElaIconType.IconName.FloppyDisk, "solid", "primary"),
            ("编辑", ElaIconType.IconName.Pencil, "outlined", "default"),
            ("复制", ElaIconType.IconName.Copy, "solid", "danger"),
            ("设置", ElaIconType.IconName.Gear, "dashed", "primary"),
            ("标记", ElaIconType.IconName.BadgeCheck, "filled", "purple"),
            ("旋转", ElaIconType.IconName.ArrowRotateRight, "text", "default"),
        ]:
            row.addWidget(ElaButton(text, icon=icon, variant=v, color=c, parent=self))
        row.addStretch()
        parent_layout.addLayout(row)
        parent_layout.addSpacing(8)

        # ── Loading 态（点「切换加载态」看指示器）──
        row = QHBoxLayout()
        row.setSpacing(12)
        loading_btn = ElaButton("加载中", variant="solid", color="primary", parent=self)
        loading_btn.setLoading(True)
        row.addWidget(loading_btn)
        toggle_btn = ElaButton(
            "切换加载态", variant="outlined", color="primary", parent=self
        )
        toggle_btn.clicked.connect(
            lambda: loading_btn.setLoading(not loading_btn.isLoading())
        )
        row.addWidget(toggle_btn)
        row.addStretch()
        parent_layout.addLayout(row)
        parent_layout.addSpacing(20)

    def _demoDropDownButton(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "09a. pyqt6_ela_pro - ElaDropDownButton 下拉按钮",
                self._demoDropDownButton,
            )
        )
        self._addInfoText(
            "点击展开 ElaMenu 下拉菜单（透明底、无边框，禁用态变灰）", parent_layout
        )
        row = QHBoxLayout()
        row.setSpacing(15)

        btn = ElaDropDownButton(parent=self)
        btn.setText("操作")
        menu = ElaMenu(btn)
        menu.addAction("选项一")
        menu.addAction("选项二")
        menu.addSeparator()
        menu.addAction("选项三")
        btn.setMenu(menu)
        row.addWidget(btn)

        btn2 = ElaDropDownButton(parent=self)
        btn2.setText("设置")
        btn2.setElaIcon(ElaIconType.IconName.Gear)
        menu2 = ElaMenu(btn2)
        menu2.addAction("偏好设置")
        menu2.addAction("账户")
        btn2.setMenu(menu2)
        row.addWidget(btn2)

        disabled = ElaDropDownButton("禁用", parent=self)
        disabled.setEnabled(False)
        row.addWidget(disabled)

        row.addStretch()
        parent_layout.addLayout(row)
        parent_layout.addSpacing(20)

    def _demoSplitButton(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "10. pyqt6_ela_pro - ElaSplitButton 拆分按钮", self._demoSplitButton
            )
        )
        self._addInfoText(
            "左侧点击触发操作，右侧弹出下拉菜单（透明底、无边框）", parent_layout
        )
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(15)

        btn = ElaSplitButton(parent=self)
        btn.setText("保存")
        btn.setElaIcon(ElaIconType.IconName.FloppyDisk)
        btn.clicked.connect(lambda: print("保存 clicked"))
        btn_layout.addWidget(btn)

        menu_btn = ElaSplitButton(parent=self)
        menu_btn.setText("更多")
        menu_btn.setElaIcon(ElaIconType.IconName.Gear)
        menu = ElaMenu(menu_btn)
        menu.addAction("操作一")
        menu.addAction("操作二")
        menu.addSeparator()
        menu.addAction("操作三")
        menu_btn.setMenu(menu)
        menu_btn.clicked.connect(lambda: print("更多 clicked"))
        btn_layout.addWidget(menu_btn)

        no_icon = ElaSplitButton(parent=self)
        no_icon.setText("纯文字")
        menu2 = ElaMenu(no_icon)
        menu2.addAction("选项A")
        menu2.addAction("选项B")
        no_icon.setMenu(menu2)
        no_icon.clicked.connect(lambda: print("纯文字 clicked"))
        btn_layout.addWidget(no_icon)

        disabled = ElaSplitButton(parent=self)
        disabled.setText("禁用")
        disabled.setElaIcon(ElaIconType.IconName.Gear)
        disabled.setEnabled(False)
        btn_layout.addWidget(disabled)

        btn_layout.addStretch()
        parent_layout.addLayout(btn_layout)
        parent_layout.addSpacing(20)

    def _showMenuFeedback(self, action_text: str):
        ElaMessageBar.success(
            ElaMessageBarType.PositionPolicy.Top,
            "菜单反馈",
            f"点击了: {action_text}",
            2000,
        )

    def _demoElaMenu(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "01. PyQt6ElaWidgetTools - ElaMenu 菜单", self._demoElaMenu
            )
        )
        self._addInfoText("点击按钮打开菜单，点击菜单项可看到反馈", parent_layout)
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(15)
        menu_btn = ElaPushButton("菜单", self)
        menu_btn.setFixedWidth(100)
        menu = ElaMenu(self)
        save_action = menu.addAction("保存")
        save_action.triggered.connect(lambda: self._showMenuFeedback("保存"))
        edit_action = menu.addAction("编辑")
        edit_action.triggered.connect(lambda: self._showMenuFeedback("编辑"))
        menu.addSeparator()
        delete_action = menu.addAction("删除")
        delete_action.triggered.connect(lambda: self._showMenuFeedback("删除"))
        menu.addSeparator()
        about_action = menu.addAction("关于")
        about_action.triggered.connect(lambda: self._showMenuFeedback("关于"))
        menu_btn.clicked.connect(
            lambda: menu.popup(menu_btn.mapToGlobal(QPoint(0, menu_btn.height())))
        )
        btn_layout.addWidget(menu_btn)
        btn_layout.addStretch()
        parent_layout.addLayout(btn_layout)
        parent_layout.addSpacing(20)

    def _demoMenuBar(self, parent_layout):
        parent_layout.addLayout(
            self._createHeaderRow(
                "02. PyQt6ElaWidgetTools - ElaMenuBar 菜单栏", self._demoMenuBar
            )
        )
        self._addInfoText("窗口菜单栏组件", parent_layout)
        menu_bar = ElaMenuBar(self)
        file_menu = menu_bar.addMenu("文件(&F)")
        save_action = file_menu.addAction("保存")
        save_action.triggered.connect(lambda: self._showMenuFeedback("文件-保存"))
        file_menu.addAction("另存为")
        file_menu.addSeparator()
        file_menu.addAction("退出")
        edit_menu = menu_bar.addMenu("编辑(&E)")
        edit_menu.addAction("复制")
        edit_menu.addAction("粘贴")
        help_menu = menu_bar.addMenu("帮助(&H)")
        about_action = help_menu.addAction("关于")
        about_action.triggered.connect(lambda: self._showMenuFeedback("帮助-关于"))
        parent_layout.addWidget(menu_bar)
        parent_layout.addSpacing(20)
