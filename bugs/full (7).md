\- 归因（探针链 probes/md\_scroll\_pert.py \~ probes/md\_scroll\_pert14.py，逐项排除，全部同文档同层级）：

1. 文档内容 / 结构：排除——markdown 全文、纯文本、剥标记版在原生 browser 上均 1245ms；viewer 管线产物（行内码 char format / 显示前景色 / 160% 行高 / 段潜距 / 代码表）在原生上逐一复刻均 715ms（probes/md\_scroll\_perf12.py M2/M4、probes/md\_scroll\_perf8.py G3）；

2. \_ElaTextBrowser 子类 + ElaThemeWidget 父容器：排除——裸 \_ElaTextBrowser（含theme父）+ 同文档12ms (probes/md\_scroll\_perf10.py 12/13、probes/md\_scroll\_perf9.py H1)；

3. 容器接线 (browser/viewport 事件过滤器、valueChanged→\_on\_view\_scrolled、documentSizeChanged→\_schedule\_layout\_refresh、80ms 布局刷新定时器)：排除——全关后 69.7ms 不变 (probes/md\_scroll\_perf13.py N2);

4. paint 钩子与双 QPainter(viewport()) 结构：排除——类级替换 paintEvent 为原生
QTextBrowser.paintEvent 后 76ms 不变 (probes/md\_scroll\_perf11.py L2);

5. 决定性 (probes/md\_scroll\_perf14.py): 唯一变量 = 透明 Base + 关自填充。P1 viewer 透明视口 118ms → P2 恢复 opaque 14.4ms; P3 原生 browser 同款 透明处理 112ms。

6. 机制（推断，无 Qt 源码现场）：透明背景文本视口走慢速 paint 路径（不透明快路径/滚动 blit 失效、逐帧 alpha 合成叠加），与 #12（Win7 DirectWrite shaping 无跨 paint 缓存）同族——透明背景把每个可见文本行的重绘成本从 \~0.3ms 放大到 \~2.5ms。

7. 注意：上游 2026.10.14 已优化行内码背景绘制（cursorRect 每视觉行一次、共享 pen/brush，替代旧的每标记段一次）——实测该优化在场（行内码钩子总成本 5.3ms → 4.1ms/帧），但它只占全帧成本的 \~6%，不是主瓶颈；主瓶颈是本条的透明视口。

\- 复现（一条命令）：uv run python probes\md\_scroll\_perf14.py （P1 透明 118 / P2 opaque
14.4 / P3 原生同款 112；离屏平台，真实平台 WA\_DontShowOnScreen 同法。完整排除键见
probes/md\_scroll\_perf.py、probes/md\_scroll\_perf12.py、probes/md\_scroll\_perf13.py）。