# Markdown 查看器（ElaMarkdownViewer）

主题自适应的 Markdown 渲染控件，面向 AI 对话场景（流式追加，聊天助手消息复用它
的嵌入模式）。本页是能力清单；API 细节见 `pyqt6_ela_pro/markdown_viewer/viewer.py`
的类 docstring，可运行示例见 `example/markdown_page.py`。示例页是长文阅读器：
正文由单个查看器占满页面，主题 / 行号 / 折叠 / 缩放 / 搜索 / 流式重放收在右上角
「阅读设置」`ElaDrawer` 中（`setMaskEnabled(False)`，无遮罩、不挡正文操作）。

## 排版

- Bear / Ink 骨架：标题 1.5/1.3/1.15/1.05/1/1 阶梯、Medium/DemiBold 字重、
  1.65 倍行高、标题上间距大于下间距、无 h1/h2 分隔线；
- 引用块 3px 竖线 + muted 正文（不斜体、无底色）；表格浅 1px 网格、表头不加底色；
- 代码卡浅 surface + 1px 边框 + 4px 圆角；行内代码浅底、无边框；图片居中；
- 表格斑马纹（默认关闭）与列宽设置；
- 任务列表可点击勾选；
- `<details>` 折叠块；
- YAML front matter 自动剥离；
- `[toc]` 目录与标题锚点（锚点跳转可返回上一位置）。

## 缺字形兜底（Win7）

中文系统默认对主字体（`Microsoft YaHei`；GDI 中文系统登记为「微软雅黑」）没有的字符（LLM 输出里的 `↔` / `⇒` / `✓` 等）
套单族符号字体（`Segoe UI Symbol` / `Cambria Math`）——只改 `QTextCharFormat` 的字体族，
**不改文本**，复制 / 导出仍保真；没有候选字体覆盖的字符保持原样，不会静默替换成 `?`。

```python
viewer.setMissingGlyphFallbackEnabled(False)   # 关闭（默认：中文系统开启）
viewer.missingGlyphFallbackEnabled()           # 查询
```

库自产标记（任务 `□`/`■`、折叠 `+`/`−`）本身就在雅黑 cmap 内，不走兜底。
`ElaTerminalView` 也已默认接入（`setMissingGlyphFallbackEnabled(False)` 可关）；
其它 `QTextDocument` 组件可复用
`pyqt6_ela_pro._internal.applyMissingGlyphFonts(document, family)`。

## 主题（配色 + 排版）

内置 10 套主题，按当前浅 / 深主题自动取对应变体；每套含 `semantic`
（8 个语义键）、`syntax`（代码高亮）与可选的 `layout` 排版覆盖。主题不仅换色，
也会切换标题阶梯 / 字重 / 间距 / 引用 / 表格 / 代码样式；未写的 layout token
继承 Bear / Ink 默认。

| 主题 | 特征 |
|---|---|
| `bear` | 默认；墨色纸面、单一蓝链接、柔和排版 |
| `lark` | 飞书文档；蓝色单强调、8px 节奏、2px 引用线 |
| `typo` | Typo.css；细标题、青绿链接、1.8 行高、链接下划线 |
| `vue` | Vue 文档；绿色强调、H2 下边框、表格斑马纹、橙色行内代码 |
| `ayu` | 暖纸色 / 橙色强调；深色为 Ayu Mirage |
| `solarized` | 经典 Solarized Light / Dark |
| `indigo` | 紫蓝强调；H1/H2 左侧 6px + 底部边框、淡蓝引用底 |
| `paper` | 暖纸底 + 衬线正文；820px 阅读列、12px 段距 |
| `github` | GitHub Primer；980px、H1/H2 底边线、表头底色 |
| `nord` | Nord 冷灰配色；不限宽、深色下更适合长时间代码阅读 |

排版 token 除了标题 / 正文行高 / 引用 / 表格 / 代码外，还支持：

- `body_font_family`：`""` 继承控件默认，`"serif"` 在中文系统优先宋体系、
  其它系统回退 Georgia 等衬线字体，也可以直接写字体族名；实例 / 进程级
  `setBodyFontFamily` 优先于主题设置（见下）；
- `content_max_width`：独立查看器的最大正文宽度（px，`0` = 不限）；居中留白，
  嵌入聊天模式忽略，由聊天列控制；
- `surface`：`{"light": ..., "dark": ...}`，覆盖查看器页面底色（`None` =
  跟随 eTheme 的 `BasicPress`）；`paper` 用它实现暖纸底。

选中文字的高亮底色 / 文字色固定跟随 Markdown 主题（主题强调色混入页面底色），
不取系统 `Highlight` —— Win7 / Win11、窗口失焦前后观感一致；高亮文字沿用正文色，
加粗 / 链接等自带前景色的片段仍保留自身颜色。

颜色值接受 `#rgb` / `#rrggbb` / 具名色 / `rgb()` / `rgba()`（`setCodeTokenColors` 与
`registerMarkdownTheme` 的自定义色同样支持）—— 库内统一过 `_colors.parse_color`。
正文片段不写显式前景色（颜色由控件 palette 的 `Text` 提供、随主题切换）；
导出 HTML / PDF 时正文走默认文字色（深色主题下导出不会出现「白字白纸」）。

```python
from pyqt6_ela_pro import registerMarkdownTheme, setDefaultMarkdownTheme

viewer.setMarkdownTheme("lark")              # 切换当前实例
registerMarkdownTheme("mine", light=..., dark=..., layout=...)   # 注册自定义
setDefaultMarkdownTheme("typo")              # 改「之后新建实例」的默认主题
```

### 正文字体族

库**不内置字体**。用户系统里装了字体时直接指定：

```python
from pyqt6_ela_pro import isFontFamilyAvailable

viewer.setBodyFontFamily("LXGW WenKai")   # 单族；"" 恢复主题默认
viewer.bodyFontFamily()                    # 当前实际生效的族名
isFontFamilyAvailable("LXGW WenKai")       # 设置界面可用它判断是否安装
```

宿主应用自带 TTF 时，先注册再指定（不需要用户安装）：

```python
from PyQt6.QtGui import QFontDatabase

font_id = QFontDatabase.addApplicationFont(r"assets\LXGWWenKai-Regular.ttf")
family = QFontDatabase.applicationFontFamilies(font_id)[0]  # "LXGW WenKai"
viewer.setBodyFontFamily(family)
```

宿主随包分发字体时请遵守字体的 OFL 许可（附带 `OFL.txt`，不得单独售卖字体文件）。

规则：

- 单族；传 `"A, B"` 只取第一个并告警（Win7 多族是慢 shaping 路径）；
- 只影响正文和标题；代码块仍走 `setCodeFontFamily()`，公式走 `math_lite`；
- 字体不存在时实际回退到可用字体（进程默认 → 主题字体），`bodyFontFamily()`
  返回回退后的族名；
- `setDefaultMarkdownBodyFontFamily("LXGW WenKai")` 只影响**之后新建**的实例
  （chat 气泡在创建时读取），已有实例用 `setBodyFontFamily()`；
- 切换 Markdown 主题不会覆盖显式指定的正文字体。

## GFM 与扩展语法

- GFM：表格 / 任务列表（含引用块内的任务列表）/ 删除线；
- GitHub Alert 提示块（`> [!NOTE]` / `[!TIP]` / `[!WARNING]` 等）；
- 脚注：跳转与回跳，编号按**首次引用顺序**（不是定义顺序）；
- 行内高亮 `==text==`；上下标 `~x~` `^x^`（**内容限字母数字**：`H~2~O`、`x^2^`；
  正文里的其它 `~`（如范围值 `1~23、45~67`）按字面渲染）；emoji 短代码；
  链接目标 / 裸 URL / HTML 标签内的这些字符按字面保留，不参与行内转换；
- 推理块（`think` 围栏）：折叠展示，流式未闭合时标签显示「思考中…」，
  可用 `setReasoningTag` / `setReasoningLabel` 修改或关闭；
- 裸 HTML 标签守卫：未配对的开 / 闭标签按字面文本渲染；`<br>` / `<img>` 等
  void 开标签自动补成自闭合，避免 Qt 导入器吞掉后续正文；成对标签、自闭合
  标签、autolink、围栏 / 行内 / 缩进代码块不受影响；
- `diff` 围栏行级着色；链接悬浮显示地址；
- Callout 的 warning / caution 与 diff 增删色走 Ela 状态色，语法 token 仍由 Markdown 主题决定。

## 代码块

- 语法高亮与语言标签（可选依赖 `pygments`，缺失自动降级为纯文本）；
- 高亮缓存分两层：与主题无关的词法 token（主题切换不重新 lex）+
  最终字符格式（`setHighlightCacheSize()` 控条数，`0` 同时关闭两层）；
- 悬停复制按钮；超长折叠（**导出 / 打印 / 复制全文会临时展开**，
  `toPlainText()` 仍返回当前视图，折叠内容不在其中）；
- 行号是**绘制层**：代码卡左侧预留行号槽，`setLineNumbersEnabled()` 只重绘，
  不重渲染文档；行号不进入复制、搜索、`toPlainText()`、HTML 或 PDF；
- 纯 ASCII 代码（行内 / 围栏）用 Consolas 一类 Latin 等宽字体；
  含 CJK 的代码优先 `NSimSun`（单族 CJK 等宽，Win7 中文版自带），
  没有时回退当前 CJK 字体。`setCodeFontFamily()` 可强制覆盖两者；
  `codeFontFamily()` / `codeLatinFontFamily()` 分别查 CJK 安全字体与 ASCII 字体。

## 数学公式

零依赖 `math_lite` 渲染（不需要 LaTeX 环境）：

- 支持矩阵 / `align` / `gather` / `cases` / `\binom` / `\substack` / `\mathbb`；
- `\boxed` / `\overbrace` / `\xrightarrow` / `\boldsymbol` / `\textcolor` / `\cancel`；
- 公式编号 `\tag` / `\tag*`（编号右对齐在公式末尾，`\tag*` 不补括号）；
- 极限算子自动堆叠；`\newcommand` / `\def` 宏展开；中文按系统字体回退；
- 容错：未收录命令原样显示为字面文本，只有结构性错误才回退源码。

## Mermaid 图

可选依赖 `mermaidx`（无浏览器渲染；缺失时回退代码卡片）：

- 按视口距离优先渲染可见图；
- 主题切换时先用旧主题的图顶替；
- `themeVariables` 默认跟随 Ela 主题（Light/Dark），仍可用 `setThemeVariables` 覆盖；
- 光栅化倍率随显示宽度自适应；
- 可选引擎预热 `setMermaidPrewarm(True)`。

## 图片与媒体

- 图片基准路径与超宽缩放；
- 远程图片默认拦截（需要时由宿主放开；放开后按阅读列宽缩放）；
- 图片点击信号与预览；本地图片右键另存为；
- 公式 / Mermaid / 外链悬浮显示源码或 URL（`install_document_tooltips`
  + 库内 `ElaToolTip`，不弹原生 QToolTip），点击或右键复制。

## 搜索 / 导出 / 打印

- 文档内搜索与缩放；整篇重渲染（缩放 / 换主题 / 换内容）后搜索高亮自动重建；
- `exportPdf(path, *, pageSize, orientation, marginsMm, fontPointSize, lineSpacing,
  pageNumbers, title, creator)`：字号 / 行距 / 方向 / 页边距 / 页码 / 元数据只影响
  导出，不改屏幕；`fontPointSize=None` 表示沿用当前正文等效字号；
- `printDocument()`；
- `toHtml(embedImages=True)` 单文件导出（图片内嵌 data URI）。

## 引用回复与流式

- `markdownSelection()` / `selectionQuoted`：把选中内容还原为 Markdown 源（引用回复用）；
- 滚动语义：`setStickToBottom(True)`（默认，聊天 / 流式）贴底时自动跟随；
  `setStickToBottom(False)`（阅读器）让 `setMarkdown` 换新内容后回到顶部，同内容
  重渲（切主题 / 表格样式 / 字号）保留当前位置。内容可以在控件首次显示前设置
  （宿主 `show()` 前预载），首次显示仍从顶部开始；大文档分块渲染遵循同一语义；
- 流式追加：`appendMarkdown` / `endStream`，贴底自动跟随、末尾打字光标；
- 嵌入模式 `setEmbeddedMode(True)`：透明背景、隐藏滚动条、高度随文档自适应
  （聊天正文 / 内联思考默认启用，`setEmbeddedTrimBottom(True)` 让文末段距不计入高度）；
- `renderIssues()` 返回渲染降级记录（格式有问题时不会静默丢内容）。

## 长文档与性能

- **分块渐进渲染**：超过 64KB 的文档自动分块（每块 16KB，**只在围栏 / 公式 /
  details / 推理块之外的空行切**，表格与长段落不会被拆开）、按时间片
  逐块提交，首屏很快出现、UI 不冻结；`isRendering()` 查询状态，`renderingProgress` /
  `renderingFinished` 回报进度，渲染途中再调 `setMarkdown` 会取消在途分块；
- **无图片文档不做图片扫描**：布局刷新只在「processed 文本含 `![` / `<img>`，或本文档
  有 Mermaid 块」时遍历文档（`_image_candidates`），否则整趟跳过 —— 那是「块 × 片段」
  的 Python 遍历，235KB 文档三趟实测 ~16ms；
- **流式收尾的大文档分帧**：`endStream` 仍是全量重渲染（提交边界上的列表 / 表格 /
  脚注只有全量渲染才对），但**不可见的后台查看器**（后台标签页）走分块渲染，
  收尾不再阻塞 100~300ms；`streamFinished` 仍立即发出，`isRendering()` 为真、
  `renderingFinished` 在结束时发出；`toPlainText` / `toHtml` / `markdownSelection` /
  `exportPdf` / `printDocument` 会先补完在途渲染，读到的一定是最终内容；
- **可见文档整趟只重排一次**：渲染管线分段编辑，但挂在已显示控件上的文档只在最后
  `markContentsDirty` 一次（宿主仍会收到一次 `contentsChanged`）。实测 60KB
  `setMarkdown` 77→60ms、117KB 主题切换 141→104ms、长消息 `endStream` 72→59ms；
- 绘制只算**本次暴露的区域**：行内代码底面按「暴露矩形 + 块内可见行二分」绘制
  （嵌入模式下查看器视口等于全文高度，按它算等于每帧给全文算一遍：单个上千行的
  长块实测 120ms/帧 → 6ms/帧），标题分隔线 / hr / 引用竖线 / 代码卡圆角同样按
  暴露区间、只画相交的块与表；
- **代码复制按钮按需创建**：`_code_buttons` 与代码表按下标对齐、离屏项是 `None`，
  只为可见带内的表建控件（73KB / 1200 块：`setMarkdown` 421 → 326ms，按钮
  1200 → 4 个）；可见表用 `firstPosition()` 二分定位，几何只对它们计算
  （嵌入模式的可见区间取外层滚动区视口映射，`viewport()` 在那里拿不到真实可见范围）；
- **主题切换只重渲染屏幕上的查看器**：滚出视口的消息仍然 `isVisible()`，按它判断
  等于每次切主题重渲染整段会话；现在按可见带懒做、被绘制时自动补齐（100 条 4KB
  会话实测 431 → 66ms）；
- Mermaid 按视口距离优先渲染（离屏图排在后面）；
- **视口底色默认不透明**（`setViewportBackground`）：非嵌入查看器一律用与自绘背景同色的
  不透明底色，圆角形态配视口圆角 mask 裁出四角 —— 外观逐像素等价，但避开透明视口在
  Win7 上的慢速重绘路径；嵌入模式保持透明、底色归宿主（宿主应传自己的背景色作不透明
  底色，聊天已传消息区色），需要显式指定或严格透明时用该 API（`None` = 恢复自动，
  `QColor(0, 0, 0, 0)` = 透明）；
- **图片在渲染期加载**：本地图片渲染时解码并按显示宽度缩放（图片多时这部分
  开销与图片总量成正比）；
- **不做按视口懒渲染**：滚动范围、文档内搜索、导出 / 打印、锚点跳转都依赖完整
  文档模型，屏幕外内容仍需进文档。要「离屏不保留」请走宿主层：聊天用
  `ElaChatView.setViewportSuspension`（默认开，视口外 ±2 屏的消息查看器整个
  挂起、滚动回来重渲染）；独立长文档用分块渲染 + `renderingProgress` 进度指示。

## 渲染管线（实现说明）

1. **预处理**：围栏代码 / 行内代码 / 公式 / Mermaid / 折叠块 / 脚注 / Callout /
   `[toc]` 替换为唯一占位符（U+E000 私有区字符），解析后按占位符精确回填。不要按
   渲染后的文本 `find()` 反推位置：同一串文本在更早处以非代码形式出现过就会整体错位。
2. **Qt Markdown 导入器**解析预处理后的文本。
3. **后处理**：字符格式（链接 / 加粗 / 斜体 / 删除线）、表格样式、任务标记、公式 /
   图片 / Mermaid 嵌入、标题锚点、脚注与 Callout。
4. **可见文档整趟只布局一次**：渲染期间屏蔽 `QTextDocument` 信号，结束后
   `markContentsDirty` 一次并补发一次 `contentsChanged`。
5. **后处理分三段编辑块**；折叠删除必须单独成段 —— 折叠区间可能包含刚解析出的表格
   单元块，在第一段编辑块内删除会改坏尚未物化的 frame 树，后续布局扫描会解引用坏
   指针。屏蔽信号不影响帧树物化（那是编辑块收尾做的）。
