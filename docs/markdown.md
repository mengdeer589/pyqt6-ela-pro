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

## 配色主题

内置 4 套配色：`opencode`（默认）/ `github` / `solarized` / `dracula`，
按当前浅 / 深主题自动取对应变体；每套含 `semantic`（8 个语义键）与 `syntax`（代码高亮）。

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
- 行内高亮 `==text==`；上下标 `~x~` `^x^`；emoji 短代码；
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

- **分块渐进渲染**：超过 64KB 的文档自动分块、按时间片逐块提交，首屏很快出现、
  UI 不冻结；`isRendering()` 查询状态，`renderingProgress` / `renderingFinished`
  回报进度，渲染途中再调 `setMarkdown` 会取消在途分块；
- 绘制只算可见区域：行内代码底面、标题分隔线 / hr / 引用竖线 / 代码卡圆角只画
  视口内的块；代码复制按钮按表增量复用、几何只对可见代码表计算；
- Mermaid 按视口距离优先渲染（离屏图排在后面）；
- **视口底色默认不透明**（`setViewportBackground`）：非嵌入查看器用与自绘背景同色的
  不透明底色 —— 外观逐像素等价，但避开透明视口在 Win7 上的慢速重绘路径；嵌入模式 /
  圆角形态保持透明（外层容器见圆角透出），需要显式指定或严格透明时用该 API
  （`None` = 恢复自动，`QColor(0, 0, 0, 0)` = 透明）；
- **图片在渲染期加载**：本地图片渲染时解码并按显示宽度缩放（图片多时这部分
  开销与图片总量成正比）；
- **不做按视口懒渲染**：滚动范围、文档内搜索、导出 / 打印、锚点跳转都依赖完整
  文档模型，屏幕外内容仍需进文档。要「离屏不保留」请走宿主层：聊天用
  `ElaChatView.setViewportSuspension`（默认开，视口外 ±2 屏的消息查看器整个
  挂起、滚动回来重渲染）；独立长文档用分块渲染 + `renderingProgress` 进度指示。
