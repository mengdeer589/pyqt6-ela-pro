14 ElaMarkdownViewer：透明 Base 视口（setTransparentTextBase）使文本 paint 成本 ×8
——Win7/Qt6 下滚动密集中文文档 112\~118ms/帧

\- PyQt6 复测（2026-10-16）：复现——probes/md\_scroll\_perf14.py 重跑：P1 完整 viewer（透明 Base 视口）117.4 ms/step、P2 恢复 opaque Base + setAutoFillBackground(True) 14.4 (x8.1）、P3 原生 QTextBrowser 同款 透明处理 113.2——与原记录 118 / 14.4 / 112 同量级，透明视口仍为主瓶颈。

库/组件：pyqt6\_ela\_pro ElaMarkdownViewer (\_applyThemeStyle → pyqt6\_ela\_pro/\_styles.py::setTransparentTextBase)：构造/换主题时把内部\_ElaTextBrowser (QTextBrowser 系) 的 palette Base 设为 Qt.GlobalColortransparent 且 viewport().setAutoFillBackground(False)（「等价于 QSS background-color: transparent」，意图是让宿主卡片底色透出）。

\- 现象（2026-10-15 本机实测，Win7 SP1 + PySide6 6.8.3 + pyside6-ela-pro 2026.10.14；1000x700 离屏 WA\_DontShowOnScreen、程序化滚动 40px/步计时；交叉印证：嵌入本组件的应用在真实窗口（非离屏）下滚动 13K 字符 / 284 行 / 约 234 行内码的密集中文文档同样明显卡顿，与离屏探针 71ms/帧（≈14fps 等效帧率）同星级）：

\- 同文档（CJK纯文本13K字符）同宿主层级：viewer默认（透明Base视口）118ms/帧；同一browser实例恢复 Base = opaque + setAutoFillBackground(True) 后14.4ms/帧（×8.2）；

\- 原生 QTextBrowser + 同款 setTransparentTextBase 处理 = 112ms/帧（与 viewer 同价）→ 成
本不在 viewer 管线 / 钩子 / 接线，就在「透明 Base
- 视口不自填充」这一处理本身；

\- 对照组（默认 opaque Base）：原生 QTextBrowser 同文档 12\~15ms/帧；viewer 文档对象被原生
browser setDocument 共享渲染 = 8ms/帧。

\- 归因（探针链 probes/md\_scroll\_perf.py \~ probes/md\_scroll\_perf14.py，逐项排除，全部同文档同层级）：

文档同层级）：
1. 文档内容 / 结构：排除——markdown 全文、纯文本、剥标记版在原生 browser 上均 1245ms；viewer
管线产物（行内码 char format / 显式前景色 / 100% 行高 / 段落距 / 代码表）在原生上逐一复刻均