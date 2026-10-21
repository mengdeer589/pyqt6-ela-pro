## 上游修复方案：Win7 文本渲染问题——三条性能 + 一条确定性崩溃

Win7 物理机实测发现的三条文本渲染性能问题（§2~§4），各附根因数据与已验证的修复方案。第 1 条与第 3 条经隔离实验重新归因后是同一根机制的两种表现，根因在 Qt/Win7 字体引擎层，用原生 Qt 控件（QPlainTextEdit / QTextBrowser）即可复现，与 ela 组件实现无关；ela 的角色只是「默认字体选择」把宿主带上了这条慢路径。 

另有第 4 条为正确性问题（确定性崩溃，§5）：ElaMarkdownViewer setMarkdown 后处理管线的编辑块时序缺陷，定位链与修复方案见 §5。 

## 0. 环境与测量约定

- Windows 7 SP1 物理机（唯一可复现环境；虚拟机无法复现）。 

Qt 6.8 是最后一个支持 Win7 的大版本——无法用更新版 Qt 验证是否已修，全部结论在 6.8 上完成。 

- 测量：真实平台 + WA_DontShowOnScreen 离屏渲染，程序化滚动（40px/步）或全幅 viewport().repaint() 计时，中位数。 

• A/B 对比一律独立进程：Win7 存在进程级 shaping 毒化（§3）， 

- 绝对值受 DWM/GPU 合成状态影响（同一份代码上午 15.5ms、下午 1.3ms 均有实测）；CPU 侧 shaping 成本（CJK fallback ~3ms/行）跨时段稳定。
本文结论以「比率 + 同会话 A/B」为准。 

## 1. 共同根因（最优先看这条）

Qt 的 Win7 DirectWrite 字体引擎有两条慢 shaping 路径——① 主字体缺对应字形（逐字形 fallback）；② 多族字体列表（逐字形族匹配，与各族是否CJK 无关）——两个缺陷都在这两条路径上： 

1. 无跨 paint 缓存：CJK shaping ~3ms/行；CJK 原生字体 ~0.15ms/行（~20×）。每次全幅重绘都把可见区整体重新 shaping。 

2. 进程级毒化：进程内只要走过一次 fallback 路径，其后任何字体、 

1.6→17.8ms/step；纯 ASCII 1.1→275ms/step），持续至进程结束。 

触发需真实 paint——只做 headless 文档排布、不上屏，不毒化。 

两条缺陷均可用原生 Qt 控件复现，ela C++ 组件层贡献 ~0（§2 隔离数据）： 

- 第1条（终端）与第3条（进程毒化）是同一根机制：#1 = fallback 

- 第2条（圆角透明底）独立，属DWM透明合成层，与shaping无关。 

## 2. 问题 1：终端 CJK 内容全幅重绘 ~90ms → 修复：默认字体 CJK 感知

## 2.1 现象

ElaTerminalView 显示 CJK 日志（1500 行、680×500）时，任何全幅重绘（窗口 resize、滚动、追加日志、切主题）实测 ~85-110ms/次（上屏测量）。成本与总行数无关（~3ms/可见行，可见 ~30 行）——每次全付的是可见区的 shaping，1500 行终端与 30 行终端重绘同价。 

2.2 归因数据（1500 行 CJK、纯 setPlainText 无 char format、 

全视口重绘、各独立进程） 

<table><tr><td>控件原生 QPlainTextEdit</td><td>字体 雅黑(系统默认)</td><td>成本 5.0ms</td></tr><tr><td>C++ ElaPlainTextEdit</td><td>雅黑(系统默认)</td><td>4.0ms</td></tr><tr><td>原生 QPlainTextEdit</td><td>Consolas</td><td>88.9ms</td></tr><tr><td>C++ ElaPlainTextEdit</td><td>Consolas</td><td>92.2ms</td></tr></table>

C++ 组件层贡献 ~0（4.0 vs 5.0、92.2 vs 88.9，均在噪声内）。 

成本全在「Consolas +CJK 逐字形 fallback shaping」——QPlainTextEdit 本身如此，与 ela 的样式 / 自绘背景无关。 

逐行 char format 亦排除：同一终端对「每 span 显式写格式 / 默认 span 写空 QTextCharFormat / 完全不写格式参数」三变体 A/B，85.9 / 85.7 / 83.7ms 无差异。 

字体矩阵（ElaTerminalView + 1500 行 CJK、全幅重绘、各独立进程）： 

<table><tr><td>字体</td><td>成本</td></tr><tr><td>Consolas (当前默认 _DEFAULT_FONT_FAMILY)</td><td>110ms</td></tr><tr><td>Arial</td><td>93ms</td></tr><tr><td>[Consolas, YaHei]</td><td>87ms</td></tr><tr><td>[YaHei, Consolas]</td><td>87ms</td></tr><tr><td>Microsoft YaHei</td><td>9.0ms</td></tr><tr><td>SimSun</td><td>7.9ms</td></tr><tr><td>KaiTi</td><td>6.1ms</td></tr><tr><td>MS Gothic (CJK 等宽)</td><td>112ms (同样慢, 排除)</td></tr></table>

多族字体列表本身就是慢路径（与列表内容无关，见 §3.2 数据）——Win7 上「等宽主字体 +CJK 后备」的族列表方案不可行；想要快，必须单一CJK 兼容字体。 

## 2.3 修复方案

1. 库侧（建议主项，纯 Python，已验证 10~15×）： 

pyqt6_ela_pro/terminal_view.py 的默认字体做 CJK 感知——系统为 CJK locale（或探测到 CJK 字体）时默认 "Microsoft YaHei"，非 CJK 系统保持 Consolas。实测 90→9ms。 

代价：雅黑 Latin 部分非等宽，日志对齐略降；等宽 MS Gothic 实测同样慢（112ms），不可用。setFontFamilies() 已公开，宿主也可自行覆盖。 

2. Qt 侧（根因）: fallback shaping 跨 paint 缓存，见 §6 素材。 

3. 问题 3：进程走过 fallback shaping 后，其后任何文本渲染慢 10~250× 

## 3.1 现象

同一进程内只要出现过经 fallback 路径 shaping 的文本（主字体缺 CJK 字形 / 字体族列表含纯 Latin 字体），其后任何字体、任何脚本的文本 paint 成本放大 10~250×，持续至进程结束： 

- 纯 ASCII 文档（13K 字符）：全新进程 1.1ms/step（~160fps）→有过 fallback 史后 11~283ms/step（~4fps）； 

```txt
(1.6→17.8ms/step)——与问题1的「同进程后续重绘变慢」同源。 
```

- 其后纯 CJK 字体渲染的 CJK 文档同样被毒化 

新建 QTextBrowser / QTextDocument 实例都无法摆脱 → app 级状态，在字体引擎 / shaping 缓存层。原生控件即复现，与 ela 无关。 

## 3.2 触发机制（各独立进程实测）

<table><tr><td>前置</td><td>其后纯 Latin / ASCII 成本</td></tr><tr><td>CJK 文档 headless 排布(无 widget、无 paint)</td><td>1.1ms(干净)</td></tr><tr><td>CJK paint·系统默认字体(雅黑)</td><td>1.1ms(干净)</td></tr><tr><td>CJK paint·显式雅黑</td><td>1.1ms(干净)</td></tr><tr><td>CJK paint·显式 Consolas</td><td>11.6ms(毒化~10×)</td></tr><tr><td>viewer 文档含 [Consolas, 雅黑UI, 雅黑] 代码字符格式</td><td>其后纯 ASCII 275~283ms(~250×)</td></tr><tr><td>同上</td><td>其后纯雅黑 CJK 文档 17.8ms(干净态 1.6ms, 11×)</td></tr><tr><td>全程单一CJK 字体(两文档同进程)</td><td>1.6/1.6ms, 零毒化</td></tr></table>

多字体族列表 A/B（同文档、同 widget，仅字符格式字体族不同）： 

```txt
- font-family: 'Microsoft YaHei' → 1.6ms/step
- font-family: 'Consolas', 'Microsoft YaHei UI', 'Microsoft YaHei' → 16.5ms/step (10×)
- font-family: 'Microsoft YaHei', 'Microsoft YaHei UI', 'Microsoft YaHei' (全CJK三族) → 17.4ms/step (仍10×慢)
- font-family: 'SimSun', 'KaiTi' (两族均在系统、均CJK) → 18.5ms/step (仍10×慢) 
```

```txt
且 Microsoft YaHei UI 在 Win7 中文系统上未安装（Qt 将其解析为
Tahoma，纯 Latin）——库内硬编码的 [code font, "Microsoft YaHei UI", "Microsoft YaHei"] 列表在任何 CJK
Win7 机器上都是双慢：多族列表+
列表内含解析失败的纯 Latin 字体。 
```

```txt
结论：慢路径的触发条件 = ① 主字体缺对应字形（逐字形 fallback），或 ② 多族字体列表本身（逐字形族匹配，与各族是否 CJK 无关）。两者均无跨 paint 缓存、且触发进程级毒化。触发源不是「渲染过 CJK」，而是「有文本经慢路径 shaping」。纯单族 CJK 字体渲染 CJK 不毒化。库内的触发点是 ela_markdown_viewer.py 的代码字符格式
_code_format / _code_text_format
([code font, "Microsoft YaHei UI", "Microsoft YaHei"], 约 L3195 / L3209)与终端默认字体 Consolas——宿主文档里凡含 CJK 的代码块 / 行内码都会踩上，进而毒化整个进程（宿主应用自己其后打开的任何文档、任何文本控件全慢）。 
```

## 3.3 修复方案

1. 库侧（建议主项，纯 Python，已验证）：CJK 系统下代码字符格式用单一 CJK 字体——[code_font, "Microsoft YaHei UI", "Microsoft YaHei"] 改 "Microsoft YaHei"（或代码字体本身选 CJK 兼容字体）；非 CJK locale 保持现状。实测 16.5→1.6ms/step，且同进程不再毒化。
注意必须收成单族：全 CJK 的多族列表实测仍 10× 慢（§3.2），保留任何后备族都不行。配合 §2 的终端默认字体 CJK 化，库可控范围内的慢路径触发点全部消除。 

2. Qt 侧（根因）：进程级 shaping 毒化，报 bug 素材见 §6。 

4. 问题 2：圆角 / 嵌入形态的透明 Base 视口使文本 paint 成本 ×8 → 

```txt
ElaMarkdownViewer.setMarkdown 渲染「<details> 折叠块内容里含 markdown 表格 + 其后还有另一张表格」的文档时，进程确定性崩溃：Qt6Gui.dll + 0x2fa705 + c0000005（PE 导出表定位在 QTextDocumentPrivate::scan_frames 内，函数起点 0x2fa570、崩点 +0x195；个别崩溃另见 Qt6Core+0xe1ea5 qt_static_metacall 二次）。Win7 SP1 + Qt 6.8.1 / PyQt6 6.8.1。 
```

```txt
修复：不透明 Base + 圆角 mask（已验证） 
```

## 4.1 现象

ElaMarkdownViewer 圆角（setBorderRadius(r>0)）与嵌入（聊天气泡等）形态自动切透明 Base + 关自填充（_apply_viewport_base：显式底色 > 嵌入 / 圆角透明 > 不透明 BasicPress），文本 paint 成本放大 5~8×（同会话 A/B：透明 Base 7~9ms/step vs 不透明 1.3ms/step；上午同代码 119 vs 15.5ms/step，绝对值随 DWM 状态漂移，机制独立于 §1）。 

原生 QTextBrowser 做同款透明处理同价（112ms）→ 成本在「透明 Base + 视口不自填充」本身，属 DWM/GPU 透明合成层行为。 

## 4.2 修复验证（同 CJK 文档、1000×700、同会话 A/B）

```txt
变体 成本
现状：setBorderRadius(6) 透明 Base 9.1ms/step
修复：Base=BasicPress 不透明 + 文本 browser 圆角 QRegion mask 1.7ms/step (5.4×) 
```

外观逐像素一致：宿主背景设红色做标记，左上 $10 \times 10$ 角落区两变体各6个宿主色像素（ $\approx$ 理论7.7）——四角透出外层自绘圆角背景，与现状无差别（半径6下多边形近似圆弧无可见锯齿）。 

## 4.3 实现要点

- setBorderRadius(r>0)：不再切透明 Base，保持不透明 BasicPress（与外层自绘圆角背景同色，快 paint 路径）； 

```txt
- 文本 browser 加圆角 QRegion mask:
    QPainterPath().addRoundedRect(rect, r, r) → toSubpathPolygons()[0] → QPolygon (QPoint 列表) → QRegion(poly) → setMask,
    resizeEvent 时重建； 
```

- 四角被 mask 裁掉 $\rightarrow$ 外层圆角背景透出 $\rightarrow$ 外观与现状一致； 

- 嵌入模式（聊天气泡）同机制：宿主把气泡背景色经现有setViewportBackground(color)传入作不透明Base，替代「透明透出下层」——不需要新API，chat/bubble.py传自己那个色即可。 

## 5. 问题 4：setMarkdown 与 _apply_folds 共用编辑块，帧树陈旧窗口内

删表格单元块 $\rightarrow$ scan_frames 确定性崩溃（c0000005） 

正确性问题（非性能）。PyQt6 构建 2026-10-19 实测定位；库版本 pyqt6-ela-pro 2026.10.18。 

## 5.1 现象

文件夹批量解析完成后渲染第一个文件即触发（文件夹OCR必崩根因）。 

```txt
uv run python probes\md_crash_repro.py probes\md_variants\syn_fold_then_table.md (崩 = 进程异常退出、无 SURVIVED 输出；真实内容复现：
uv run python probes\md_crash_repro.py demo1，取
~/.wenjian/ocr/demo1.pdf/vlm/markdown.md)。 
```

## 5.2 触发条件与最小复现

```txt
触发条件（合成用例逐项验证，probes/make_md_variants_syn.py + probes/md_variant_bisect.py，真实平台 + WA_DontShowOnScreen）： 
```

- 折叠块内含 markdown 表且其后再有任意一张表 $\rightarrow$ 崩 

(宽表 / 单行表 / 双折叠均崩)； 

- 表在前、折叠在后 $\rightarrow$ 不崩；折叠内无表（纯文本）+ 外部有表 $\rightarrow$ 不崩； 

- 即必须「折叠内表 + 折叠后表」同文档，缺一不崩。 

最小复现仅 114 字符 (probes/md_variants/syn_fold_then_table.md): 

```txt
<details>
<summary>line</summary>
| a | b |
| --- | --- |
| 1 | 2 |
</details>

| c | d |
| --- | --- |
| 3 | 4 | 
```

## 5.3 归因（探针链，全部真实平台 + WA_DontShowOnScreen）

1. 裸 QTextBrowser.setMarkdown 渲染同款内容不崩
(probes/md_qtext_repro.py) → 崩溃不在 Qt 的 setMarkdown 本身，而在 ela 的 setMarkdown 后处理管线。 

2. 逐步打空 _render_into 的 17 个后处理步骤
(probes/md_step_bisect.py)：仅跳过 _apply_folds 即不崩，其余任一步单独跳过都照崩 → 罪魁 _apply_folds。 

3. 块结构解剖（probes/md_blocks_anatomy.py）：崩溃文档经管线跑完后12个顶层块 = bn0 折叠起始 token、bn1~4 内层表格单元块、bn5 空块、bn6 折叠结束 token、bn7~10 外层表格单元块、bn11 空块；_apply_folds 的删除区间 = bn1~bn6（含4个表格单元块）。 

4. 决定性（probes/md_late2.py）：让管线完整跑完（两段编辑块都闭合、表格 frame 已物化、布局完成）之后，再手工执行与 _apply_folds 完全相同的删除（换起始 token 为标签 + _delete_blocks 逐块删折叠区间）→ 不崩（exit 0）。同一段删除若发生在 setMarkdown 同一编辑块内（真管线）→ 崩。
唯一变量 = 删除时帧树是否已物化。 

5. 机制：_render_into (ela_markdown_viewer.py ~L2823) 把 document.setMarkdown(processed) 与 _apply_folds(document) (~L3650) 塞进同一段 beginEditBlock（库 docstring 自述编辑块内帧树陈旧、rootFrame().childFrames() 看不到新表）。折叠分支经 _delete_blocks (~L3695) 按块号逐块 removeSelectedText() 删除折叠内容——其中含 markdown 表被解析出的表格单元块。在表格 frame 尚未物化的窗口内删除其单元块，frame 树被改坏（悬空 / 失配）；endEditBlock 后布局 scan_frames 遍历 frame 树时解引用坏指针 → AV。 

表在前 / 折叠内无表时，删除区间不构成「表后还有表」的 frame 拓扑，故不触发。 

## 5.4 修复方案

库侧（纯 Python，改 ela_markdown_viewer.py 一处时序）：把 _apply_folds 挪出 setMarkdown 所在的那段编辑块——在第一段 endEditBlock 之后（表格 frame 已物化、布局已跑完）以独立编辑块执行折叠删除；_render_into 的其余后处理步骤不动。§5.3 第 4 条的决定性实验即本方案的验证：同样的删除动作，帧树物化后执行 = 存活，同编辑块内执行 = 崩溃。 

备选（若时序调整影响其它路径）：折叠内容含表格时改走habilitable
整表删除 / setVisible 隐藏，不做逐单元块 removeSelectedText()。 

宿主侧无规避（项目约定：库问题不绕开、如实报告）。库修复后回归口径：syn_fold_then_table（§5.2 最小复现）与 demo1（真实 OCR 内容）经 probes/md_crash_repro.py 均输出 SURVIVED，且文件夹 OCR 解析两次干净退出。 

## 6. Qt bug 报素材（两条根因缺陷，原生控件即可复现）

建议转提 Qt bug。环境限定 Win7 SP1 + Qt 6.8（最后支持 Win7 的大版本，无法用新版 Qt 验证是否已修——本身也是「问题被 Win7 锁定」的佐证）。 

```txt
1. 慢 shaping 路径无跨 paint 缓存（Win7）：文档经慢路径 shaping （主字体缺 CJK 字形，如 Consolas；或多族字体列表——与各族是否 CJK 无关）时，每次全幅重绘对可见区整体重新 shaping：~3ms/行 vs 单族 CJK 原生字体 ~0.15ms/行（~20×）。最小复现（无第三方依赖）：QPlainTextEdit，字体 Consolas、setPixelSize(13)，setPlainText 灌 1500 行中文日志，viewport().repaint() 计时 → 中位 ~89ms；同脚本改字体为单族 "Microsoft YaHei"（或默认系统字体）→ ~5ms；改字体为 ["SimSun", "KaiTi"] 双族 → 与 Consolas 同价。 
```

2. 进程级 shaping 毒化（Win7）：进程内走过一次 fallback shaping 后，其后任何字体 / 任何脚本的文本 shaping 慢 10~250×，持续至进程结束；触发需真实 paint（headless 排布不触发）；新建文档 / 控件实例无法摆脱。
最小复现：同进程先后两个 QTextBrowser ——第一个 Consolas 字体渲染 CJK 文本并滚动（走完 fallback 路径），第二个任意字体渲染纯 ASCII 并滚动 → ASCII 侧 1.1ms/step（全新进程基线）放大到 11.6ms/step；
重形式：字符格式为 [Consolas，雅黑UI，雅黑] 的 CJK 文档滚动后，同进程第二个纯 ASCII browser 达 275ms/step。 

3.（可选，ela C++ 组件级独立隐患）ElaPlainTextEdit::paintEvent
(ElaPlainTextEdit.cpp ~L143) 每次 paint 自检
palette().color(Text) != BasicText，不等则调 onThemeChanged()
→ setPalette() (private/ElaPlainTextEditPrivate.cpp ~L38)。
宿主若自定义文字色（setPalette 改 Text role），会**每帧改 palette
• 触发文档重算**形成抖动。当前默认场景 palette 一致不触发，但属地雷。
建议改为 themeModeChanged 信号驱动，去掉 paintEvent 内自检。 

## 7. 建议优先级

<table><tr><td>优先级</td><td>项</td><td>类型</td><td>状态</td></tr><tr><td>P0</td><td>问题4折叠删除移出 setMarkdown 编辑块(确定性崩溃)</td><td>库侧Python</td><td>定位完成,方案已验证(§5.3决定性实验)</td></tr><tr><td>P1</td><td>问题1/3字体策略:终端默认字体+viewer代码字符格式CJK化</td><td>库侧Python</td><td>已验证 10~250×</td></tr><tr><td>P1</td><td>问题2圆角/嵌入改「不透明Base + mask /显式底色」</td><td>库侧Python</td><td>已验证 5.4×,像素级外观无损</td></tr><tr><td>P2</td><td>Qt bug 两条(§6)</td><td>Qt 根因</td><td>素材齐,待提</td></tr><tr><td>P3</td><td>C++ ElaPlainTextEdit::paintEvent 自检改信号驱动</td><td>库侧 C++</td><td>隐患,低成本</td></tr></table>


宿主侧在库修复前也可经现有 API 自行缓解：终端 setFontFamilies([ "Microsoft YaHei"]）（实测 90→9ms）；圆角 / 嵌入宿主 



setViewportBackground(不透明底色)。问题 4（§5）无宿主侧缓解 


(项目约定不绕开), 只待库修复。 