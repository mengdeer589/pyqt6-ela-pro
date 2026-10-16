#15 PySide6/Qt6 ( Win7 ) : 进程内出现过 CJK shaping 后 , 其后纯 Latin 文本渲染慢 20\~40x ( app级 shaping 毒化 )

\- PyQt6 复测（2026-10-16）：复现——probes/md\_scroll\_perf5.py 两序各独立进程：cjk\_first 68.0 / 238.0 / 127.5 / 14.0 ms/step (viewer+CJK / viewer+ASCII / 原生+ASCII / 原生+CJK)，ascii\_first 6.2 / 67.4 / 233.3 / 128.5——纯 Latin 从 6.2 放大到 \~233（×38），原生 browser 同样毒化（128），CJK 自身两序恒定 6768。与原记录（71.3/223.7/123.3/14.6 与 6.2/71.4/229.5/127.0）同量级。Qt 6.8.2 未见改善。

库/组件：PySide6 6.8.3 / Qt 6.8 DirectWrite 字体 shaping (Win7 SP1)。纯 QTextBrowser +otenDocument 即复现，与ela无关（新建QTextBrowser / 新建QTextDocument 实例都无法摆脱→app级状态，推断在字体引擎/shaping缓存层）。

\- 现象：同一进程内只要渲染过CJK文本，其后一切纯Latin文档的滚动paint成本放大2040×；纯ASCH文档（13K字符、约100折行）\*\*123127ms/帧\*\*（原生QTextBrowser，\~8fps）；全新进程（无CJK历史）同文档6ms/帧（160fps）。CJK渲染本身不受历史影响（恒1415ms/帧原生口径）。两种顺序均复现且数值稳定：

\- CJK 先行 : viewer+CJK 71.3 → viewer+ASCII 223.7 → 原生新browser+ASCII 123.3 → 原生 +CJK 14.6 ;

\- ASCII 先行: viewer+ASCII 6.2 → viewer+CJK 71.4 → viewer+ASCII (再次) 229.5 → 原生 +ASCII 127.0。

\- 复现（2026-10-15，uv run python probes\md\_scroll\_perf5.py cjk\_first 与 ... ascii\_first；离屏1000x700、40px/步；probes/md\_scroll\_perf4.py m2\~m6为同型状态矩阵）。

• 期望行为：CJK与Latin的shaping/字形缓存相互独立，任一脚本的渲染历史不应劣化另一脚本的后续渲染（至少不跨脚本毒化）。

\- 项目侧是否有临时规避及移除条件：无规避（项目约定）。影响面：以CJK为主的文档不受显性影响（CJK自身不劣化，实测原生15ms/帧含234个行内码token）；受影响的是纯英文/纯Latin文档——宿主进程只要已渲染过CJK（如宿主应用自身UI文案），其后打开纯Latin文档即20×变慢。注意与#14独立：#15在原生browser上同样存在（123ms），viewer无关；两者叠加时（viewer+英文文档+CJK历史）