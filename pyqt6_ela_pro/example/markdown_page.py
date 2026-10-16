"""
[pyqt6_ela_pro] ElaMarkdownViewer Markdown 渲染页面

按类别分块展示（每块一个独立查看器）：

1. **文本与排版**：标题锚点 / 行内样式 / 列表任务 / 表格 / 引用提示块 /
   折叠 / 图片 / 脚注，附工具栏（搜索、缩放、导出 PDF）；
2. **代码块**：语言标签、行号、超长折叠、悬停复制、``diff`` 行级着色；
3. **数学公式**：矩阵 / 环境 / ``\\boxed`` / 极限算子 / 宏展开 / 容错；
4. **Mermaid 图**：flowchart / sequenceDiagram（可选依赖 mermaidx）；
5. **流式渲染**：以上四块拼接后用 ``appendMarkdown`` 逐 token 输出
   （空态占位、打字光标、未闭合围栏预览、贴底自动跟随），
   ``endStream`` 后与静态渲染结果一致。
"""

import os
import tempfile

from PyQt6.QtCore import QElapsedTimer, Qt, QTimer, QUrl
from PyQt6.QtGui import (
    QColor,
    QDesktopServices,
    QFont,
    QImage,
    QLinearGradient,
    QPainter,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
)

from PyQt6ElaWidgetTools import ElaLineEdit, ElaProgressBar, ElaText
from pyqt6_ela_pro import ElaButton, ElaDialogBase, ElaMarkdownViewer
from .base_page import ExamplePage

#: 文本与排版样例（标题 / 行内 / 列表任务 / 表格 / 引用 / 折叠 / 图片 / 脚注）
_MARKDOWN_TEXT = r"""# 文本与排版

本分块展示文本类能力：标题层级与锚点、行内样式、列表与任务、表格、
引用与提示块、推理块 / details 折叠、图片与脚注；`[toc]` 自动生成目录。

[toc]

## 1. 标题与锚点

支持 `#` 至 `######` 六级标题；标题自动生成锚点，
`[toc]` 目录与脚注回跳都依赖这些锚点。

### 三级标题

#### 四级标题

##### 五级标题

###### 六级标题

## 2. 行内样式

**加粗**、*斜体*、~~删除线~~、`inline_code(x)`、H~2~O 下标、x^2^ 上标、
==高亮文本==、emoji :rocket: :fire: :check:、
[外部链接](https://example.com)（点击会二次确认）、
裸链接 https://example.com 自动识别。

## 3. 列表与任务

- 无序列表
  - 嵌套子项 A
  - 嵌套子项 B

1. 有序列表第一步
2. 有序列表第二步

任务列表（可直接点击勾选，源 Markdown 同步更新）：

- [x] 已完成：行内样式与列表
- [ ] 待办：点击这行试试
- [ ] 待办：再点一次取消勾选

## 4. 表格

| 能力 | API | 说明 |
|:-----|:----|-----:|
| 搜索高亮 | searchText | 高亮全部匹配并跳转 |
| 缩放 | setZoomFactor | 同步缩放公式尺寸 |
| 复制全文 | toPlainText | 纯文本导出 |
| PDF 导出 | exportPdf | 一键生成 PDF |

## 5. 引用与提示块

> 普通引用块使用次级文字色，可跨越多行。

> [!NOTE]
> 蓝色备注：用于补充说明。

> [!TIP]
> 绿色技巧：代码卡片悬停右上角可复制。

> [!IMPORTANT]
> 紫色重要：关键结论与注意事项。

> [!WARNING]
> 橙色警告：操作前请确认。

> [!CAUTION]
> 红色注意：高风险操作，请谨慎执行。

## 6. 推理折叠 / 元信息

模型推理内容可用 `<think>…</think>` 包裹，默认折叠为一行标签（点击标签展开/收起，
流式输出未闭合时标签显示「思考中…」）；`<details>` 同样支持折叠：

<think>
我先分析需求，再决定实现路径：这里展示的是默认折叠的推理内容，
点击上方的「思考过程」标签即可展开查看。
</think>

<details>
<summary>点击查看实现细节</summary>
详情内容默认隐藏，适合放置补充说明或折叠的长篇内容。
</details>



文档开头的 YAML front matter（`---` 包围）在渲染时自动剥离，不占用版面。

## 7. 图片

本地宽图自动缩放到视口宽度（点击可弹窗预览）：

![1600 × 520 本地示例图](ela_markdown_demo.png)

远程图片默认拦截并显示占位（安全默认，可用 `setRemoteImagesEnabled(True)` 放开）：

![远程图片默认被拦截](https://example.com/demo.png)

## 8. 脚注

设计说明见脚注[^design]，交互说明见脚注[^interact]。

[^design]: 脚注定义行自动收集到文末，点击上标编号跳转。
[^interact]: 任务勾选、图片点击、折叠/展开等交互都会回写源文本或发出信号。

"""

#: 代码块样例（语言标签 / 行号 / 折叠 / 复制 / diff 着色）
_MARKDOWN_CODE = r"""# 代码块

代码卡片：语言标签、行号（示例开启）、超长折叠（超过 12 行）、悬停右上角复制按钮；
`diff` 围栏按行着色（新增绿 / 删除红 / 位置行蓝）；未收录语言按纯文本渲染。

```python
from dataclasses import dataclass, field


@dataclass
class ChatMessage:
    role: str
    content: str
    meta: dict = field(default_factory=dict)


class ChatSession:
    def __init__(self, model: str = "deepseek"):
        self.model = model
        self.messages: list[ChatMessage] = []

    def add(self, role: str, content: str) -> ChatMessage:
        message = ChatMessage(role=role, content=content)
        self.messages.append(message)
        return message

    def history(self) -> list[dict]:
        return [
            {"role": item.role, "content": item.content}
            for item in self.messages
        ]

    def clear(self) -> None:
        self.messages.clear()


if __name__ == "__main__":
    session = ChatSession()
    session.add("system", "你是一个乐于助人的助手。")
    session.add("user", "用一句话解释相对论。")
    for item in session.history():
        print(item["role"], ":", item["content"])
```

```json
{"model": "deepseek", "stream": true, "temperature": 0.7}
```

```bash
uv run python -m pyqt6_ela_pro.example
```

```
[INFO] server started on :8080
[WARN] cache miss for key "user:42"
[ERROR] upstream timeout after 30s
```

```diff
@@ -1,3 +1,3 @@
-旧的实现方式
+新的实现方式
 未变化的上下文
```
"""

#: 数学公式样例（行内 / 矩阵 / 环境 / boxed / 极限算子 / 宏 / 容错）
_MARKDOWN_MATH = r"""# 数学公式

行内：质能方程 $E=mc^2$、欧拉恒等式 $e^{i\pi}+1=0$、
希腊字母 $\alpha, \beta, \Gamma, \Omega$；悬浮公式可查看 LaTeX 源码。

矩阵与线性变换（`pmatrix`）：

$$
\begin{pmatrix} a & b \\ c & d \end{pmatrix}
\begin{pmatrix} x \\ y \end{pmatrix}
=
\begin{pmatrix} ax + by \\ cx + dy \end{pmatrix}
$$

组合数与字母表（`\binom` / `\mathbb` / `\mathcal`）：

$$
\binom{n}{k} = \frac{n!}{k!(n-k)!}, \quad \mathbb{R}^n,\ \mathcal{L}(V)
$$

分段函数（`cases`）：

$$
f(x) = \begin{cases} x^2 & x \ge 0 \\ -x & x < 0 \end{cases}
$$

多行对齐（`align`）、多行下标（`\substack`）与 `array` 列格式：

$$
\begin{align}
(a+b)^2 &= a^2 + 2ab + b^2 \\
(a-b)^2 &= a^2 - 2ab + b^2
\end{align}
$$

$$
\sum_{\substack{1 \le i \le n \\ i \ne j}} a_{ij},
\quad
\begin{array}{lcr} 1 & 2 & 3 \\ x & y & z \end{array}
$$

结果高亮（`\boxed`）、下花括号（`\underbrace`）与极限算子（`\limsup`）：

$$
\boxed{\lim_{n \to \infty} \left(1 + \frac{1}{n}\right)^n = e}
\qquad
\underbrace{x + x + \cdots + x}_{n\ \text{个}} = nx
$$

$$
\limsup_{n \to \infty} a_n \le \max_{x \in X} f(x) \le \gcd(p, q)
$$

宏定义（`\newcommand`）与文本转义（`\text{中文 50\%}`）：

$$
\newcommand{\R}{\mathbb{R}}
\R^n \to \R^m, \quad \text{增长 50\%}
$$

未收录的命令不会让整条公式降级——容错渲染为字面文本（如
$\unknowncmd$），结构性错误（如缺少 `\right`）才回退源码。
"""

#: Mermaid 图样例（flowchart / sequence）
_MARKDOWN_MERMAID = r"""# Mermaid 图（可选依赖 mermaidx）

安装 `pyqt6_ela_pro[all]` 后自动渲染为图片；未安装时回退为代码卡片；主题随亮/暗模式切换。

```mermaid
flowchart LR
    A[提出需求] --> B{可行?}
    B -->|是| C[实现并测试]
    B -->|否| D[调整方案]
    D --> B
    C --> E[交付]
```

```mermaid
sequenceDiagram
    participant U as 用户
    participant V as ElaMarkdownViewer
    U->>V: appendMarkdown(chunk)
    V-->>U: 实时渲染
    V->>V: endStream()
```

---

> 以上内容由一次 `setMarkdown()` 渲染；工具栏提供搜索高亮、缩放、
> 复制全文与 PDF 导出。"""

#: 全量静态示例（四块拼接，供示例与流式演示共用）
_MARKDOWN_ALL = "\n\n".join(
    (_MARKDOWN_TEXT, _MARKDOWN_CODE, _MARKDOWN_MATH, _MARKDOWN_MERMAID)
)

#: 聊天式演示的预置回答（覆盖主要块级语法，真实场景可替换为模型输出）
_MARKDOWN_ANSWER = r"""<think>
先拆解问题：流式渲染的关键在于稳定段与增量段的边界处理，
确定思路后再组织回答结构。
</think>

当然可以，下面用一个例子说明 **流式渲染** 的要点。

### 核心流程

1. `beginStream()` 进入流式模式；
2. `appendMarkdown(chunk)` 逐 token 追加；
3. `endStream()` 全量收尾。

> [!TIP]
> 稳定段只提交一次，未闭合的围栏会实时预览。

```python
def answer(view, tokens):
    view.beginStream()
    for token in tokens:
        view.appendMarkdown(token)
    view.endStream()
```

| 阶段 | 行为 |
|------|------|
| 追加中 | 打字光标 + 贴底跟随 |
| 结束后 | 行号 / 折叠自动启用 |

其中时间复杂度为 $O(n)$，矩阵形式：

$$
\begin{pmatrix} 1 & 0 \\ 0 & 1 \end{pmatrix}
$$

更多细节见脚注[^demo]。

[^demo]: 这是预置回答，真实场景可替换为模型输出。
"""


def _ensure_demo_image() -> str:
    """生成超宽演示图片（1600×520），返回所在目录。

    放在临时目录而非仓库内，避免示例产物污染工作区；
    图片宽度大于查看器宽度，可直观看到 ``setBaseUrl()`` 后的自动缩放。
    """
    directory = os.path.join(tempfile.gettempdir(), "pyqt5_ela_md_demo")
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, "ela_markdown_demo.png")
    if not os.path.exists(path):
        image = QImage(1600, 520, QImage.Format.Format_ARGB32)
        painter = QPainter(image)
        gradient = QLinearGradient(0, 0, image.width(), image.height())
        gradient.setColorAt(0.0, QColor("#2563eb"))
        gradient.setColorAt(1.0, QColor("#9333ea"))
        painter.fillRect(image.rect(), gradient)
        painter.setPen(QColor("white"))
        font = QFont()
        font.setPixelSize(44)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(
            image.rect(),
            int(Qt.AlignmentFlag.AlignCenter),
            f"{image.width()} × {image.height()} 本地图片 → 按视口自动缩放",
        )
        painter.end()
        image.save(path)
    return directory


class MarkdownPage(ExamplePage):
    """ElaMarkdownViewer 两个场景演示：全量静态渲染 + 流式渲染"""

    PAGE_TITLE = "Markdown 渲染"

    def __init__(self, parent=None):
        self._stream_timer = None
        self._stream_chunks: list[str] = []
        self._stream_total = 0
        self._stream_done = 0
        self._stream_speed = 1
        self._stream_elapsed = None
        self._stream_view = None
        self._replay_btn = None
        self._pause_btn = None
        self._finish_btn = None
        self._speed_btn = None
        self._progress = None
        self._stream_status = None
        self._input_edit = None
        self._send_btn = None
        super().__init__(parent)

    def _addDemoContent(self, main_layout):
        self._addInfoText(
            "面向 AI 对话场景的 Markdown 渲染组件：按「文本 / 代码 / 公式 / Mermaid」"
            "四块分别展示，最后是流式渲染演示（逐 token 追加、空态占位、打字光标、"
            "贴底自动跟随）。",
            main_layout,
        )
        self._demoText(main_layout)
        main_layout.addSpacing(24)
        self._demoCode(main_layout)
        main_layout.addSpacing(24)
        self._demoMath(main_layout)
        main_layout.addSpacing(24)
        self._demoMermaid(main_layout)
        main_layout.addSpacing(24)
        self._demoStreaming(main_layout)

    # -- 通用：状态行 ------------------------------------------------------
    #
    # 这里**刻意没有**「创建演示查看器」的 helper：五节各自需要的 setter 只差两三个，
    # 而每节标题的「</> 代码」按钮展示的是该节方法自身的源码 —— 构造一旦抽进
    # helper，读者点开代码就只剩信号接线，看不到查看器是怎么建起来的（第 5 节
    # 流式演示本来就是内联的，现在五节统一）。

    def _createDemoStatus(self, text: str):
        """创建演示状态行（由调用方加入布局，保证位于工具条之后）。"""
        status = ElaText(text, self)
        status.setTextPixelSize(13)
        return status

    # -- 演示 1：文本与排版 ------------------------------------------------

    def _demoText(self, main_layout):
        main_layout.addLayout(self._createHeaderRow("1. 文本与排版", self._demoText))
        self._addInfoText(
            "标题层级与锚点 / `[toc]` 目录、行内样式与 emoji、列表与可点击任务、"
            "表格斑马纹、引用与五种提示块、推理块 / details 折叠、图片缩放与远程拦截、"
            "脚注回跳；工具栏：搜索高亮 / 缩放 / 复制全文 / 导出 PDF；"
            "选中文本右键可「复制为 Markdown」用于引用回复；外链二次确认后打开。",
            main_layout,
        )
        # 查看器构造**就地写出来**（与第 5 节流式演示同款）：每节标题的「</> 代码」
        # 按钮展示的就是本方法的源码，抽到 _createDemoViewer 里等于把读者要学的东西
        # 藏起来了。四节里只有这三个 setter 不同，所以刻意不用 helper。
        viewer = ElaMarkdownViewer(parent=self)
        viewer.setMinimumHeight(620)
        viewer.setOpenExternalLinks(False)
        viewer.setBaseUrl(_ensure_demo_image())
        viewer.setMarkdown(_MARKDOWN_TEXT)
        main_layout.addWidget(viewer)
        status = self._createDemoStatus(
            "最近操作：—（试试点击推理/详情折叠、点击任务勾选、选中文本后右键引用、"
            "点击本地图片预览）"
        )
        viewer.codeCopied.connect(
            lambda text: status.setText(f"已复制内容（{len(text)} 字符）")
        )
        viewer.selectionQuoted.connect(
            lambda text: status.setText(
                f"已复制引用为 Markdown（{len(text)} 字符）：{text.splitlines()[0][:32]}"
            )
        )
        viewer.taskToggled.connect(
            lambda index, checked: status.setText(
                f"任务 #{index} 已{'勾选' if checked else '取消勾选'}，源 Markdown 已同步"
            )
        )
        viewer.imageClicked.connect(self._preview_image)
        self._addViewerToolbar(
            main_layout, viewer, status_label=status, confirm_external=True
        )
        main_layout.addWidget(status)

    # -- 演示 2：代码块 ----------------------------------------------------

    def _demoCode(self, main_layout):
        main_layout.addLayout(self._createHeaderRow("2. 代码块", self._demoCode))
        self._addInfoText(
            "语言标签与语法高亮（Pygments 可选）、行号、超长折叠与「展开其余 N 行」、"
            "悬停右上角复制按钮；`diff` 围栏行级着色（新增绿 / 删除红 / 位置行蓝）。",
            main_layout,
        )
        # 构造就地写出来（见 _demoText 的说明）：行号 + 超长折叠
        viewer = ElaMarkdownViewer(parent=self)
        viewer.setMinimumHeight(560)
        viewer.setOpenExternalLinks(False)
        viewer.setBaseUrl(_ensure_demo_image())
        viewer.setLineNumbersEnabled(True)
        viewer.setCodeBlockCollapseLines(12)
        viewer.setMarkdown(_MARKDOWN_CODE)
        main_layout.addWidget(viewer)
        status = self._createDemoStatus(
            "最近操作：—（悬停代码卡片右上角复制 / 点击「展开其余 N 行」）"
        )
        viewer.codeCopied.connect(
            lambda text: status.setText(f"已复制代码（{len(text)} 字符）")
        )
        main_layout.addWidget(status)

    # -- 演示 3：数学公式 --------------------------------------------------

    def _demoMath(self, main_layout):
        main_layout.addLayout(self._createHeaderRow("3. 数学公式", self._demoMath))
        self._addInfoText(
            "行内 / 块级公式；矩阵、`cases`、`align` / `gather` 环境、`\\boxed`、"
            "极限算子堆叠、`\\newcommand` 宏展开；未收录命令容错为字面文本。"
            "点击公式可复制 LaTeX 源码，悬浮可查看源码。",
            main_layout,
        )
        # 构造就地写出来（见 _demoText 的说明）
        viewer = ElaMarkdownViewer(parent=self)
        viewer.setMinimumHeight(700)
        viewer.setOpenExternalLinks(False)
        viewer.setBaseUrl(_ensure_demo_image())
        viewer.setMarkdown(_MARKDOWN_MATH)
        main_layout.addWidget(viewer)
        status = self._createDemoStatus("最近操作：—（点击任意公式复制 LaTeX 源码）")
        viewer.formulaCopied.connect(
            lambda latex: status.setText(f"已复制公式：{latex[:48]}")
        )
        main_layout.addWidget(status)

    # -- 演示 4：Mermaid 图 ------------------------------------------------

    def _demoMermaid(self, main_layout):
        main_layout.addLayout(self._createHeaderRow("4. Mermaid 图", self._demoMermaid))
        self._addInfoText(
            "flowchart / sequenceDiagram 等图类型由 mermaidx 异步渲染为图片，"
            "主题随亮/暗模式切换；未安装可选依赖时回退为代码卡片；"
            "点击图片可复制 Mermaid 源码。本页开启了引擎预热"
            "（setMermaidPrewarm），并按视口距离优先渲染可见的图。",
            main_layout,
        )
        # 构造就地写出来（见 _demoText 的说明）；引擎预热按视口距离优先渲染可见的图
        viewer = ElaMarkdownViewer(parent=self)
        viewer.setMinimumHeight(520)
        viewer.setOpenExternalLinks(False)
        viewer.setBaseUrl(_ensure_demo_image())
        viewer.setMermaidPrewarm(True)
        viewer.setMarkdown(_MARKDOWN_MERMAID)
        main_layout.addWidget(viewer)
        status = self._createDemoStatus("最近操作：—（点击图可复制 Mermaid 源码）")
        viewer.mermaidCopied.connect(
            lambda code: status.setText(f"已复制 Mermaid 源码（{len(code)} 字符）")
        )
        main_layout.addWidget(status)

    # -- 演示 5：流式渲染 --------------------------------------------------

    def _demoStreaming(self, main_layout):
        main_layout.addLayout(
            self._createHeaderRow(
                "5. 流式渲染（与上方四块内容一致）", self._demoStreaming
            )
        )
        self._addInfoText(
            "支持两种玩法：① 输入问题后回车「发送」——以聊天方式流式输出预置回答；"
            "②「重新播放」——逐 token 输出与上方四块拼接后完全相同的样例。"
            "过程中可暂停/继续、调速、立即完成；空态占位、未闭合围栏/公式实时预览、"
            "推理块未闭合时显示「思考中…」、末尾打字光标、贴底自动跟随；"
            "endStream 后自动开启行号与折叠；本地图片点击可弹窗预览。",
            main_layout,
        )
        viewer = ElaMarkdownViewer(parent=self)
        viewer.setMinimumHeight(560)
        viewer.setOpenExternalLinks(False)
        viewer.setBaseUrl(_ensure_demo_image())
        viewer.setCodeBlockCollapseLines(12)
        viewer.setMermaidPrewarm(True)
        viewer.setPlaceholderText("输入问题后回车，或点击「重新播放」体验流式输出…")
        main_layout.addWidget(viewer)

        question = ElaLineEdit(self)
        question.setPlaceholderText("输入问题后回车发送（演示：统一返回预置回答）")
        send = ElaButton("发送", variant="solid", color="primary", parent=self)
        send.setFixedWidth(96)
        input_row = QHBoxLayout()
        input_row.addWidget(question)
        input_row.addWidget(send)
        main_layout.addLayout(input_row)

        replay = ElaButton("重新播放", variant="solid", color="primary", parent=self)
        pause = ElaButton("暂停", variant="outlined", parent=self)
        finish = ElaButton("立即完成", variant="outlined", parent=self)
        speed = ElaButton("速度 x1", variant="outlined", parent=self)
        for button in (replay, pause, finish, speed):
            button.setFixedWidth(96)
        pause.setEnabled(False)
        finish.setEnabled(False)

        controls = QHBoxLayout()
        controls.addWidget(replay)
        controls.addWidget(pause)
        controls.addWidget(finish)
        controls.addWidget(speed)
        controls.addStretch()
        main_layout.addLayout(controls)

        progress = ElaProgressBar(self)
        progress.setRange(0, 100)
        progress.setValue(0)
        progress.setTextVisible(False)
        progress.setFixedHeight(10)
        main_layout.addWidget(progress)

        status = ElaText(
            "等待开始：点击「重新播放」，可随时暂停 / 调速 / 立即完成。", self
        )
        status.setTextPixelSize(13)
        main_layout.addWidget(status)

        self._stream_view = viewer
        self._replay_btn = replay
        self._pause_btn = pause
        self._finish_btn = finish
        self._speed_btn = speed
        self._progress = progress
        self._stream_status = status
        self._input_edit = question
        self._send_btn = send
        self._stream_elapsed = QElapsedTimer()
        self._stream_timer = QTimer(viewer)
        self._stream_timer.setInterval(35)
        self._stream_timer.timeout.connect(self._onStreamTick)
        replay.clicked.connect(self._restartStream)
        pause.clicked.connect(self._togglePauseStream)
        finish.clicked.connect(self._finishStream)
        speed.clicked.connect(self._cycleStreamSpeed)
        viewer.streamFinished.connect(self._onStreamFinished)
        viewer.imageClicked.connect(self._preview_image)
        question.returnPressed.connect(self._send_message)
        send.clicked.connect(self._send_message)

    def _addViewerToolbar(
        self,
        main_layout,
        viewer,
        status_label=None,
        confirm_external: bool = False,
    ):
        """给查看器叠加交互工具条：搜索高亮、缩放、复制全文、导出 PDF。

        ``status_label`` 为 ``None`` 时自动创建并加入布局；``confirm_external``
        决定外链是否二次确认后打开。
        """
        search = ElaLineEdit(self)
        search.setPlaceholderText("搜索并高亮：输入关键词")
        search.setFixedWidth(220)
        count = ElaText("", self)
        count.setTextPixelSize(13)
        count.setFixedWidth(56)

        prev_btn = ElaButton("上一个", variant="outlined", parent=self)
        next_btn = ElaButton("下一个", variant="outlined", parent=self)
        clear_btn = ElaButton("清除", variant="outlined", parent=self)
        for button in (prev_btn, next_btn, clear_btn):
            button.setFixedWidth(72)
        prev_btn.setEnabled(False)
        next_btn.setEnabled(False)

        def on_search(text: str):
            total = viewer.searchText(text)
            count.setText("" if not text else f"{total} 处")
            prev_btn.setEnabled(total > 0)
            next_btn.setEnabled(total > 0)

        search.textChanged.connect(on_search)
        prev_btn.clicked.connect(lambda: viewer.findNext(backward=True))
        next_btn.clicked.connect(lambda: viewer.findNext())
        clear_btn.clicked.connect(
            lambda: (viewer.clearSearch(), search.clear(), count.setText(""))
        )

        zoom_label = ElaText("100%", self)
        zoom_label.setTextPixelSize(13)
        zoom_label.setFixedWidth(48)
        zoom_out = ElaButton("缩小", variant="outlined", parent=self)
        zoom_in = ElaButton("放大", variant="outlined", parent=self)
        zoom_reset = ElaButton("重置", variant="outlined", parent=self)
        for button in (zoom_out, zoom_in, zoom_reset):
            button.setFixedWidth(72)

        def sync_zoom_label():
            zoom_label.setText(f"{viewer.zoomFactor() * 100:.0f}%")

        zoom_in.clicked.connect(lambda: (viewer.zoomIn(0.1), sync_zoom_label()))
        zoom_out.clicked.connect(lambda: (viewer.zoomOut(0.1), sync_zoom_label()))
        zoom_reset.clicked.connect(
            lambda: (viewer.setZoomFactor(1.0), sync_zoom_label())
        )
        # 原先这里还有「复制全文」和「导出 PDF」两个按钮，**已删除**。
        # 它们靠 ``QTimer.singleShot(1200, lambda: btn.setText(...))`` 把按钮
        # 文案改回去 —— **没给 context 对象**，于是那个定时器是「无主定时器」：
        # 页面销毁后它照样在 T+1200ms 触发，去摸已释放的按钮包装器 →
        # ``RuntimeError`` 穿过 C++ 边界 → 进程 0xC0000409 **静默终止**
        # （无 traceback）。
        #
        # 症状极难定位：这一页构造慢（要建好几个 markdown viewer），只有当
        # 「点按钮 + 1200ms」晚于「页面销毁」时才炸，于是表现为**同一份脚本
        # 偶发崩在不同位置**（实测崩在「截图已存好、准备退出」那一刻）。
        # ``singleShot(ms, ctx, callable)`` 的 context 重载**也不能靠**：实测传了
        # context 照样崩（定时器与 receiver 的连接没有随 wrapper 销毁断开）。
        # 以后要加「点一下改文案、过会儿改回来」的按钮，定时器必须是 ctx 的
        # **子对象**（``QTimer(ctx)``），或回调里 ``_internal.is_deleted(self)`` 自查。

        search_row = QHBoxLayout()
        search_row.addWidget(search)
        search_row.addWidget(count)
        search_row.addWidget(prev_btn)
        search_row.addWidget(next_btn)
        search_row.addWidget(clear_btn)
        search_row.addStretch()
        main_layout.addLayout(search_row)

        zoom_row = QHBoxLayout()
        zoom_row.addWidget(zoom_out)
        zoom_row.addWidget(zoom_label)
        zoom_row.addWidget(zoom_in)
        zoom_row.addWidget(zoom_reset)
        zoom_row.addStretch()
        main_layout.addLayout(zoom_row)

        if status_label is None:
            status_label = ElaText("最近点击链接：—（试试文中的目录或脚注）", self)
            status_label.setTextPixelSize(13)
            main_layout.addWidget(status_label)

        def on_link_activated(url: str):
            status_label.setText(f"最近点击链接：{url}")
            if confirm_external and url.startswith(("http://", "https://")):
                answer = QMessageBox.question(
                    self,
                    "打开外部链接",
                    f"是否使用系统浏览器打开？\n{url}",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer == QMessageBox.StandardButton.Yes:
                    QDesktopServices.openUrl(QUrl(url))

        viewer.linkActivated.connect(on_link_activated)

    def _preview_image(self, url: str) -> None:
        """图片点击预览（本地图片弹窗，远程链接交给系统浏览器）。"""
        local_path = QUrl(url).toLocalFile()
        if local_path and os.path.exists(local_path):
            pixmap = QPixmap(local_path)
            if pixmap.isNull():
                return
            label = QLabel()
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setPixmap(
                pixmap.scaled(
                    min(pixmap.width(), 760),
                    min(pixmap.height(), 480),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            label.setFixedSize(label.pixmap().size())
            dialog = ElaDialogBase(title="图片预览", parent=self.window())
            dialog.setLeftButtonText("关闭")
            for button in dialog.findChildren(QPushButton):
                if button.text() == "确定":
                    button.hide()
                    break
            dialog.setParamWidget(label)
            dialog.adjustSize()
            if dialog.width() < 420:
                dialog.resize(420, dialog.height())
            dialog.exec()
        elif url.startswith(("http://", "https://")):
            QDesktopServices.openUrl(QUrl(url))

    # -- 流式播放控制 ------------------------------------------------------

    @staticmethod
    def _build_stream_chunks(source: str, step: int = 24) -> list[str]:
        """把样例切成逐 token 片段（步长控制节奏）。"""
        return [source[i : i + step] for i in range(0, len(source), step)]

    def _stream_percent(self) -> int:
        if self._stream_total <= 0:
            return 0
        return min(int(self._stream_done * 100 / self._stream_total), 100)

    def _apply_stream_speed(self) -> None:
        """按倍速调整定时器间隔（基准 35ms）。"""
        self._stream_timer.setInterval(max(4, int(35 / self._stream_speed)))

    def _restartStream(self):
        """重新播放：与静态渲染完全相同的样例（逐 token 输出）。"""
        self._start_stream(self._build_stream_chunks(_MARKDOWN_ALL))

    def _send_message(self):
        """聊天式：显示提问并以流式输出预置回答。"""
        text = self._input_edit.text().strip()
        if not text or self._stream_view.isStreaming():
            return
        self._input_edit.clear()
        prefix = f"**你：** {text}\n\n---\n\n"
        self._start_stream(self._build_stream_chunks(_MARKDOWN_ANSWER), prefix=prefix)

    def _start_stream(self, chunks: list, prefix: str = "") -> None:
        """启动一次流式输出（``prefix`` 非空时先呈现提问再续写）。"""
        self._stream_timer.stop()
        self._stream_chunks[:] = list(chunks)
        self._stream_total = len(self._stream_chunks)
        self._stream_done = 0
        self._stream_view.setLineNumbersEnabled(False)
        if prefix:
            self._stream_view.setMarkdown(prefix)
        else:
            self._stream_view.beginStream()
        self._apply_stream_speed()
        self._stream_elapsed.start()
        self._progress.setValue(0)
        self._stream_status.setText("输出中… 0%")
        self._replay_btn.setText("输出中…")
        self._replay_btn.setEnabled(False)
        self._send_btn.setEnabled(False)
        self._input_edit.setEnabled(False)
        self._pause_btn.setText("暂停")
        self._pause_btn.setEnabled(True)
        self._finish_btn.setEnabled(True)
        self._stream_timer.start()

    def _togglePauseStream(self):
        """暂停 / 继续流式输出。"""
        if self._stream_timer.isActive():
            self._stream_timer.stop()
            self._pause_btn.setText("继续")
            self._stream_status.setText(
                f"已暂停（{self._stream_percent()}%，可继续或立即完成）"
            )
        elif self._stream_chunks:
            self._pause_btn.setText("暂停")
            self._stream_status.setText(f"输出中… {self._stream_percent()}%")
            self._stream_timer.start()

    def _finishStream(self):
        """立即完成：一次性补全剩余片段并全量收尾。"""
        self._stream_timer.stop()
        if not self._stream_view.isStreaming():
            return
        while self._stream_chunks:
            self._stream_view.appendMarkdown(self._stream_chunks.pop(0))
        self._stream_done = self._stream_total
        self._progress.setValue(100)
        self._stream_view.endStream()

    def _cycleStreamSpeed(self):
        """循环切换倍速：x1 → x2 → x4 → x1。"""
        sequence = (1, 2, 4)
        self._stream_speed = sequence[(sequence.index(self._stream_speed) + 1) % 3]
        self._speed_btn.setText(f"速度 x{self._stream_speed}")
        self._apply_stream_speed()

    def _onStreamTick(self):
        """逐段喂入流式片段并刷新进度。"""
        if not self._stream_chunks:
            self._stream_timer.stop()
            self._stream_done = self._stream_total
            self._stream_view.endStream()
            return
        self._stream_view.appendMarkdown(self._stream_chunks.pop(0))
        self._stream_done += 1
        percent = self._stream_percent()
        self._progress.setValue(percent)
        self._stream_status.setText(
            f"输出中… {percent}%（{self._stream_elapsed.elapsed() / 1000:.1f}s，"
            f"速度 x{self._stream_speed}）"
        )

    def _onStreamFinished(self):
        """流式收尾：开启行号，使结果与静态渲染一致。"""
        self._stream_view.setLineNumbersEnabled(True)
        self._progress.setValue(100)
        elapsed = self._stream_elapsed.elapsed() / 1000.0
        self._stream_status.setText(
            f"已完成：{self._stream_total} 段 / {elapsed:.1f}s，"
            "行号 / 折叠已启用；可继续输入提问或重新播放"
        )
        self._pause_btn.setText("暂停")
        self._pause_btn.setEnabled(False)
        self._finish_btn.setEnabled(False)
        self._replay_btn.setText("重新播放")
        self._replay_btn.setEnabled(True)
        self._send_btn.setEnabled(True)
        self._input_edit.setEnabled(True)
        self._input_edit.setFocus()
