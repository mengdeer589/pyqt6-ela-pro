# Markdown 查看器（ElaMarkdownViewer）

主题自适应的 Markdown 渲染控件，面向 AI 对话场景（流式追加，聊天助手消息复用它
的嵌入模式）。本页是能力清单；API 细节见 `pyside6_ela_pro/ela_markdown_viewer.py`
的类 docstring，可运行示例见 `example/markdown_page.py`。

## 排版

- 对齐 Typora 结构：标题层级字号阶梯、1.6 倍行高、引用块浅底色、无边框代码卡片、图片居中；
- 表格斑马纹与列宽设置；
- 任务列表可点击勾选；
- `<details>` 折叠块；
- YAML front matter 自动剥离；
- `[toc]` 目录与标题锚点（锚点跳转可返回上一位置）。

## 缺字形兜底（Win7）

中文系统默认对主字体（`Microsoft YaHei`）没有的字符（LLM 输出里的 `↔` / `⇒` / `✓` 等）
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

## 配色主题

内置 4 套配色：`opencode`（默认）/ `github` / `solarized` / `dracula`，
按当前浅 / 深主题自动取对应变体；每套含 `semantic`（8 个语义键）与 `syntax`（代码高亮）。
正文片段不写显式前景色（颜色由控件 palette 的 `Text` 提供、随主题切换）；
导出 HTML / PDF 时正文走默认文字色（深色主题下导出不会出现「白字白纸」）。

```python
from pyside6_ela_pro import registerMarkdownTheme, setDefaultMarkdownTheme

viewer.setMarkdownTheme("github")            # 切换当前实例
registerMarkdownTheme("mine", light=..., dark=...)   # 注册自定义（同名覆盖）
setDefaultMarkdownTheme("github")            # 改「之后新建实例」的默认主题
```

## GFM 与扩展语法

- GFM：表格 / 任务列表 / 删除线；
- GitHub Alert 提示块（`> [!NOTE]` / `[!TIP]` / `[!WARNING]` 等）；
- 脚注：跳转与回跳；
- 行内高亮 `==text==`；上下标 `~x~` `^x^`（**内容限字母数字**：`H~2~O`、`x^2^`；
  正文里的其它 `~`（如范围值 `1~23、45~67`）按字面渲染）；emoji 短代码；
- 推理块（`think` 围栏）：折叠展示，流式未闭合时标签显示「思考中…」，
  可用 `setReasoningTag` / `setReasoningLabel` 修改或关闭；
- `diff` 围栏行级着色；链接悬浮显示地址。

## 代码块

- 语法高亮与语言标签（可选依赖 `pygments`，缺失自动降级为纯文本）；
- 悬停复制按钮；行号与超长折叠。

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
- 光栅化倍率随显示宽度自适应；
- 可选引擎预热 `setMermaidPrewarm(True)`。

## 图片与媒体

- 图片基准路径与超宽缩放；
- 远程图片默认拦截（需要时由宿主放开）；
- 图片点击信号与预览；本地图片右键另存为；
- 公式 / Mermaid 悬浮显示源码，点击或右键复制。

## 搜索 / 导出 / 打印

- 文档内搜索与缩放；
- `exportPdf(path, pageSize, marginsMm)` 与 `printDocument()`；
- `toHtml(embedImages=True)` 单文件导出（图片内嵌 data URI）。

## 引用回复与流式

- `markdownSelection()` / `selectionQuoted`：把选中内容还原为 Markdown 源（引用回复用）；
- 流式追加：`appendMarkdown` / `endStream`，贴底自动跟随、末尾打字光标；
- 嵌入模式 `setEmbeddedMode(True)`：透明背景、隐藏滚动条、高度随文档自适应
  （聊天正文 / 内联思考默认启用，`setEmbeddedTrimBottom(True)` 让文末段距不计入高度）；
- `renderIssues()` 返回渲染降级记录（格式有问题时不会静默丢内容）。

## 长文档与性能

- **分块渐进渲染**：超过 64KB 的文档自动分块（每块 16KB，按空行边界切）、按时间片
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
