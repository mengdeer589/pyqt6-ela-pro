12 PySide6/Qt6 + C++ ElaPlainTextEdit : 终端内容全幅重绘 \~83ms (DirectWrite shaping 无跨 paint 缓存)

PyQt6 复测（2026-10-16）：复现——probes/recheck\_terminal\_repaint.py（真实平台 + WA\_DontShowOnScreen，viewport().repaint() 统一口径，1500 行 CJK 日志 680×500）：ElaTerminalView（Consolas + 逐行 char format）全幅重绘 82.7 / 82.8 / 83.3 ms 中位（与原记录 83ms 相差数毫秒）；同内容裸 QPlainTextEdit 3.8\~5.5 ms（先经 grab() 采样确认对照在真实渲染——QPlainTextEdit 的 widget.repaint() 只付 0.1ms 是口径差异，须用 viewport().repaint()）。

库/组件：PyQt6ElaWidgetTools C++ ElaPlainTextEdit (pro ElaTerminalView 的 C++ 底层；终端默认字体 \_DEFAULT\_FONT\_FAMILY= "Consolas" 与逐行 char format 来自库 pyqt6\_ela\_pro/terminal\_view.py:: \_render\_line ) + Qt 6.8 /DirectWrite 字体 shaping。

\- 现象：全幅重绘（顶层窗口 resize——Windows 顶层 resize 作废整个客户区、滚动、新日志行、切主题，均触发）在真实 1500 行终端内容下实测 \~83ms/次（上屏测量）；同内容裸 QPlainTextEdit 仅 0.2\~8ms。成本与总行数无关（\~2.7ms/可见行，可见约 30 行）——每次全付的是可见区的 shaping，1500 行终端与 30 行终端重绘同价。

\- 归因（2026-10-14 G6/G12/G13 探针，C:\Users\liujie\_rdc\.opencode\plan\perf\_probe\）；探针的视口/可见行数与活终端不同，绝对值高于活机实测、比率可参考）：

1. C++ ElaPlainTextEdit 默认字体全幅 paint 4.2ms (裸 Qt 0.2\~8ms) : 库自身样式 (borderless、自绘背景) 35x;

2. • Consolas 等宽 → 175ms (×42) : Consolas 纯 Latin，终端内 CJK 走 DirectWrite 逐字形 fallback，shaping 结果无跨 paint 缓存，每次 paint 对可见区整体重新 shaping；

3. 逐行 char format (\_render\_line 对每行每个 span 都写 char format，含与默认色相同的 plain 行) → 262ms : char format 把文本切成更多片段，shaping 单位成倍放大；

4. 活终端（Consolas + 逐行格式 + borderless）实测 83ms（G11 两种配置 同星级复现）。

期望行为：

\- 库侧：ElaPlainTextEdit 的 paint 具备跨 paint 的文本 layout / shaping 缓存（对齐 QTextDocument block 缓存语义），局部内容变化走增量更新；

\- terminal\_view.py::\_render\_line 对与默认色相同的 span 不写 char format（减少片段）；

\- 默认字体 Consolas 对 CJK 内容不合理（纯 Latin 字形 + 逐字 fallback），建议重新选择默认字体或提供 CJK 友好默认。

\- 项目侧是否有临时规避及移除条件：无规避（约定：库 / Qt 问题不绕开、如实报告）。宿主应用另有「首事件钉宽、停手结算」的交互 resize 重排守卫，解决的是重排层成本（Qt6 重排为 Qt5 的 25\~30 倍，逐帧 \~180ms）——与本条重绘层相互独立：守卫落地后窗口拖拽仍付 \~83ms/帧的重绘（重排已归零）。库修复 paint 缓存 / 默认字体后本条可关闭。