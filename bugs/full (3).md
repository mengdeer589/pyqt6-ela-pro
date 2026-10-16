#10 非主屏最大化时 isFullScreen() 误报 → 标题栏拖抽失效 ( ElaAppBar NCHITTEST 闸门)

• PyQt6 复测 (2026-10-16): 复现——probes/probe\_fullscreen\_state.py: 副屏最大化后无边 QWidget isFullScreen=True 且 isMaximized=False (比原记录更重——原记录仅 isFullScre 误报、isMaximized 仍 True), ElaWindow 副屏 isMaximized=True isFullScreen=True; 主两者均正确。probe\_maximize\_discriminate.py: 副屏最大化后 maximize 按钮位仍回 HTZOOM (库 NCHITTEST handler 在跑), 标题栏 y=12 x 扫描全 HTCLIENT (主屏同扫描为 HTCPTION) — caption 分支仍被误报中断, 副屏最大化后 标题栏拖不动。

库/组件：根因在 Qt 5.15 Win7 平台插件的 fullscreen 状态推断（无 Qt 源码现场，机制为推断）；表现层
PyQt5ElaWidgets C++ ElaAppBar::takeOverNativeEvent 的 MM\_NCHITTEST
( ElaWidgets/ElaAppBar.cpp \~L644 )。

\- 现象：窗口（无边框 / 自绘边框）在无任务栏的副屏上最大化后，标题栏（appbar）命中测试整条返回 HTCLIENT（而非 HTCPTION）→最大化状态下从标题栏拖不动窗口（Windows 原生语义本应是「还 + 拖动」）。主屏（带任务栏）最大化正常。非最大化状态两屏均正常。

\- 根因链（2026-10-12 本机实测，Win7 SP1，双 1920×1080 并排，任务栏仅主屏底部；探针 probes/probe\_fullscreen\_state.py / probes/probe\_maximize\_drag2.py / probes/probe\_maximize\_discriminate.py）：

1. QWindow::isFullScreen() 误报：三方对照（最大化后续状态）——原生边框 QWidget 副屏 isFullScreen=False √；Qt::FramelessWindowHint QWidget 副屏 isFullScreen=True；ElaWindow 副屏 isFullScreen=True x；三者主屏均 False √（isMaximized() 两屏正确为 True）。

2. 机制（推断）：主屏底部 40px 任务栏使最大化窗口高 1040 ≠ 屏高 1080；副屏无任务栏，无边框窗最大化后恰好铺满副屏完整几何（(1920,0,1920×1080)）→ 平台插件把「无边框 + 恰好铺满整屏」推断为 fullscreen（Qt 的 showFullScreen 在 Win 上正是这样实现几何的），该推断不区分窗口实际处于 maximized 原生状态。

3. 表现：ElaAppBar.cpp NCHITTEST 的 caption 闸门 if (d->\_containsCursorToItem(this && !window()->isFullScreen()) → 误报的 isFullScreen 直接指断整条标题栏。判别证据：副屏最大化后标题栏 x 扫描 (y=12) 全 HTCLIENT（主屏同扫描 HTCAPTION），而 maximize 按钮位置仍返回 HTZOOM (=9) ——库 handler 在跑，只有 caption 分支被指；Qt 侧几何无偏移 (appba mapToGlobal 正确。 QCursor::pos() 与 appbar 矩形包含关系实测为真）。

期望行为：

\- Qt侧：窗口处于原生 maximized 状态时 isFullScreen() 必须为 False (fullscreen 状态只应反映显式 showFullScreen() 请求)。

• 库侧（表现层）：NCHITTEST caption 闸门改为 !isFullScreen() || isMaximized()（或自行跟踪「用户是否显式请求全屏」）——最大化时标题栏按 Windows 语义应给 HTCAPTION，支持还原 + 填动