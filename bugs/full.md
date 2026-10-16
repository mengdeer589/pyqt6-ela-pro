#2 ElaMenu : 菜单含 checkable 项时，addElaIconAction 的项图标不渲染（被勾选列整列替代）
• PyQt6 复测（2026-10-16）：复现——像素判别探针 probes/recheck\_menu\_checkable\_iqon.py （直接驱动 C++ ElaMenuStyle 的 drawControl(CE\_MenuItem)，项几何经真实 show 后 actionGeometry 取，画布 painter.translate(-rect.x(), -rect.y()) 对齐项原点）：非 checkable 分支图标列 145px 墨色、checkable 未勾选图标列 0px（项图标被勾选列整列替代）、勾选时该列画 Check 字形（60px）。源级 ElaMenuStyle.cpp:93 if (mopt->menuHasCheckableItems) 分支仍在（C++ 组件 0.13.0 同版）。

库/组件：PyQt5ElaWidgets C++ ElaMenu / ElaMenuStyle
( ElaWidgets/Development/ElaMenuStyle.cpp 的 drawControl(CE\_MenuItem) )。

现象：只要菜单里存在任意一个 checkable 项，QStyleOptionMenuItem. menuHasCheckableItems 为真，C++ 样式走 if/else 的 checkable 分支：图标列位置 统一改画 Check（勾）/ None（空）字形，addElaIconAction(icon, text) 传入的 ElaIconType 图标（action 属性 ElaIconType）与 QIcon 全部不绘制。图标列与勾选列二选一，无法共存。

\- 复现（2026-10-12 本机实测，当前安装 pyd）：

1. 源级：ElaMenuStyle::drawControl 中 if (mopt->menuHasCheckableItems) 分支只 drawText(..., mopt->checked ? Check : None), else 分支才读 action->property("ElaIconType") 圆图标。

2. 行为级（探针 probes/probe\_menuitem\_style.py）：ElaMenu 两项均
setCheckable(True) + addElaIconAction(Hammer/DiagramProject, ...), 直接驱动
menu.style()（构造时 setStyle 装入的 C++ ElaMenuStyle）的
drawControl(CE\_MenuItem, opt, painter, menu), opt.rect 取 actionGeometry 真
实 item 几何：
• opt.menuHasCheckableItems=True → 只出勾选，无图标；

\- opt.menuHasCheckableItems=False → 正常出图标。（离屏 show() + grab() 截图不可用：offscreen 平台不渲染字体字形，截图全黑，只能走 style 直绘。）

\- 期望行为：checkable 项与项图标互不排斥——勾选标记与图标应分列共存（如「图标列 + 勾选列」，或勾选叠加在文本侧），addElaIconAction 的图标在 checkable 菜单里照常渲染。

\- 项目侧是否有临时规避及移除条件：无规避（按约定不做绕开，如「状态写进文案 + 换图标」那类变通不采用）。受影响处：宿主应用的 plan/build 双项 checkable 模式菜单（项上分别传 DiagramProject / Hammer 图标——库修复后即生效，当前仅勾选列渲染）；宿主应用托盘「划词助手：开/关」状态项（刻意不传图标，状态写进文案 + 换图标）。库修复（checkable 分支也绘制项图标）后，宿主侧「库缺陷#2」注释可删、模式菜单项图标自然出现；托盘项可评估恢复图标。

#10 ElaContentDialog / ElaMessageDialog : 替换内容区后窗口高度不重新适配，多行正文被裁切