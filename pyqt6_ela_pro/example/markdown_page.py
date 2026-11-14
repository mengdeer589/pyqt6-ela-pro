"""[pyqt6_ela_pro] ElaMarkdownViewer Markdown 渲染页面。"""

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
    QVBoxLayout,
    QWidget,
)

from PyQt6ElaWidgetTools import (
    ElaComboBox,
    ElaIconType,
    ElaLineEdit,
    ElaProgressBar,
    ElaScrollArea,
    ElaText,
    ElaToggleSwitch,
)
from pyqt6_ela_pro import (
    ElaButton,
    ElaDialogBase,
    ElaDrawer,
    ElaDrawerPositionType,
    ElaMarkdownViewer,
    ElaThemeWidget,
    defaultMarkdownTheme,
    markdownThemes,
)
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

> 以上内容由一次 `setMarkdown()` 渲染；右侧「阅读设置」抽屉提供搜索高亮、
> 缩放、主题切换与流式重放。"""

_MARKDOWN_ALL = "\n\n".join(
    (_MARKDOWN_TEXT, _MARKDOWN_CODE, _MARKDOWN_MATH, _MARKDOWN_MERMAID)
)

_READER_INTRO = r"""# 大文档渲染长文

> 这是一篇用于观察**大文档渲染**的长文示例：标题、正文、代码卡、表格、公式与
> Mermaid 连续排布。页面只保留阅读内容；主题、行号、折叠、缩放、搜索与流式重放
> 都收在右上角「阅读设置」抽屉里，一键唤出。

阅读器关注的是连续滚动时的排版稳定性：标题阶梯与段距不跳动，代码卡边缘对齐，
表格不溢出视口，图片按宽度自适应；切换主题后整篇文档重新排版，但阅读位置保持。

```python
from pyqt6_ela_pro import ElaMarkdownViewer

viewer = ElaMarkdownViewer()
viewer.setLineNumbersEnabled(True)  # 右侧「阅读设置」可随时开关
viewer.setMarkdown("正文里的代码卡片会自动预留行号槽")
```
"""

_READER_APPENDIX = r"""
## 9. 长文滚动与排版节奏

连续滚动时，标题间距、正文行高、列表缩进和代码卡边缘都应保持稳定。下面这段文字
刻意写长一些，用来观察滚动过程中的重绘成本与视觉节奏。中文正文与 English terms
混排时，行高由主题的 `body_line_height` 统一控制，不会因为字体回退而忽高忽低。

长文阅读的另一个重点是「位置感」：当读者从代码卡滚动到公式，再滚动到表格时，
每一屏都应该有清晰的层级。标题的上间距大于下间距，段落之间保持统一的呼吸感，
引用块的竖线不越出正文列，代码卡与表格的左右边缘对齐到同一条基线。

### 9.1 中英文混排

Markdown 的渲染结果最终要落到 `QTextDocument` 上，Qt 的排版引擎会按片段拆分文本，
再逐段计算行高与换行点。对于包含 `inline_code`、**加粗强调**、[链接](#) 与
~~删除线~~ 的段落，片段数量会明显增加；阅读器需要在保证语义颜色的同时，避免
每个片段都触发一次昂贵的格式合并。

在 Win7 交付环境中，字体回退是比排版算法更敏感的因素。CJK 字符必须落在单一字体族
内，Latin 等宽字体只用于纯 ASCII 代码；这条约束在长文中尤其重要，因为一次错误的
字体回退会污染后续所有文本绘制。

### 9.2 列表与层级

- 一级列表：用于并列的阅读要点；
  - 二级列表：用于补充说明与边界条件；
    - 三级列表：用于极少数需要展开的细节。
- 列表项内的行内代码 `viewer.setMarkdown(source)` 与正文保持同一行高。
- 有序列表可以表达步骤：

1. 准备 Markdown 源文本；
2. 调用 `setMarkdown()` 完成一次全量渲染；
3. 滚动阅读，观察标题、代码卡与表格的对齐；
4. 打开「阅读设置」切换主题，确认阅读位置不丢失。

## 10. 宽表格与信息密度

| 场景 | 推荐设置 | 说明 |
|:-----|:---------|:-----|
| 长文阅读 | 行号关闭 | 减少代码卡左侧的视觉噪音 |
| 代码审阅 | 行号开启 | 便于引用具体行 |
| 超长代码 | 折叠 12 / 24 行 | 保留上下文，避免单块占满视口 |
| 主题对比 | bear / vue / solarized | 观察标题线与代码底色的差异 |
| 数学公式 | 保持默认字号 | 缩放时公式会同步调整 |

表格在窄视口下会按列宽重新分配空间；如果内容仍然过宽，查看器保持表格自身的最小宽度，
由外层横向滚动承接，而不是把文字压成无法阅读的窄列。

## 11. 代码阅读

```python
from dataclasses import dataclass


@dataclass
class ReaderState:
    theme: str = "bear"
    line_numbers: bool = False
    collapse_lines: int = 0

    def describe(self) -> str:
        mode = "on" if self.line_numbers else "off"
        return f"{self.theme}: line numbers {mode}, collapse {self.collapse_lines}"
```

```diff
@@ -1,4 +1,4 @@
-旧的主题切换按钮常驻在页面上
+主题切换收进右侧阅读设置抽屉
  正文区域只保留阅读内容
  滚动位置在切换主题后保持
```

```bash
uv run python -m pyqt6_ela_pro.example
```

## 12. 公式与长文中的数学

行内公式 $E = mc^2$ 与正文共享行高；块级公式单独居中，并在缩放时同步调整尺寸。

$$
\begin{aligned}
\nabla \cdot \mathbf{E} &= \frac{\rho}{\varepsilon_0} \\
\nabla \times \mathbf{B} &= \mu_0 \mathbf{J}
\end{aligned}
$$

$$
\boxed{\sum_{k=1}^{n} k = \frac{n(n+1)}{2}}
$$

## 13. Mermaid 长图

```mermaid
flowchart TB
    A[打开阅读器] --> B{需要调整?}
    B -->|主题| C[打开阅读设置]
    B -->|排版| C
    C --> D[切换主题 / 行号 / 折叠]
    D --> E[继续阅读]
    E --> B
```

## 14. 引用与脚注

> [!NOTE]
> 长文中的提示块用于打断大段正文，帮助读者快速定位重点。

> [!WARNING]
> 示例中的「重新播放」会临时接管正文；播放结束后恢复静态渲染与阅读位置。

脚注把补充信息移出正文，避免打断阅读节奏[^reader]。点击上标编号可以跳转到文末，
再点击编号返回原位置。

[^reader]: 阅读设置抽屉里的所有操作都对应 `ElaMarkdownViewer` 的公开 API。
"""

_MARKDOWN_READER = "\n\n".join((_READER_INTRO, _MARKDOWN_ALL, _READER_APPENDIX))

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
    """生成超宽演示图片（1600×520），返回所在目录。"""
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
    """ElaMarkdownViewer 长文阅读：正文占满页面，设置收进无遮罩 ElaDrawer。"""

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
        self._reader_view = None
        self._settings_drawer = None
        self._md_theme_combo = None
        self._line_numbers_switch = None
        self._collapse_combo = None
        self._collapse_lines = (0, 12, 24)
        self._zoom_label = None
        self._search_edit = None
        self._search_count = None
        self._reader_status = None
        super().__init__(parent)

    def _setupUI(self):
        """阅读器布局：不套外层滚动区，正文查看器自己滚动。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._mainLayout = QVBoxLayout()
        self._mainLayout.setContentsMargins(0, 0, 0, 0)
        self._mainLayout.setSpacing(0)
        layout.addLayout(self._mainLayout, 1)

    def buildDemoContent(self):
        if self._demo_built:
            return
        self._demo_built = True
        self._addDemoContent(self._mainLayout)

    def _addDemoContent(self, main_layout):
        """创建阅读器正文，并把全部演示开关收进右侧 ElaDrawer。"""
        header = QWidget(self)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(28, 14, 20, 12)
        header_layout.setSpacing(12)

        title_column = QVBoxLayout()
        title_column.setSpacing(2)
        title = ElaText("Markdown 阅读器", header)
        title.setTextPixelSize(20)
        title_font = QFont()
        title_font.setPixelSize(20)
        title_font.setBold(True)
        title.setFont(title_font)
        title_column.addWidget(title)
        subtitle = ElaText(
            "大文档阅读 · 主题 / 排版 / 搜索收进右上角「阅读设置」",
            header,
        )
        subtitle.setTextPixelSize(13)
        subtitle.setWordWrap(True)
        title_column.addWidget(subtitle)
        header_layout.addLayout(title_column, 1)

        code_btn = ElaButton("</> 代码", variant="text", color="primary", parent=header)
        code_btn.setFixedWidth(85)
        code_btn.clicked.connect(lambda: self._show_code(self._addDemoContent))
        header_layout.addWidget(code_btn)

        settings_btn = ElaButton(
            "阅读设置",
            icon=ElaIconType.IconName.Sliders,
            variant="outlined",
            parent=header,
        )
        settings_btn.setFixedWidth(118)
        settings_btn.clicked.connect(self._toggle_settings_drawer)
        header_layout.addWidget(settings_btn)
        main_layout.addWidget(header)

        viewer = ElaMarkdownViewer(parent=self)
        viewer.setOpenExternalLinks(False)
        viewer.setBaseUrl(_ensure_demo_image())
        viewer.setStickToBottom(False)
        viewer.setLineNumbersEnabled(False)
        viewer.setMarkdown(_MARKDOWN_READER)
        viewer.codeCopied.connect(
            lambda text: self._set_reader_status(f"已复制代码（{len(text)} 字符）")
        )
        viewer.selectionQuoted.connect(
            lambda text: self._set_reader_status(
                f"已复制引用为 Markdown（{len(text)} 字符）"
            )
        )
        viewer.taskToggled.connect(
            lambda index, checked: self._set_reader_status(
                f"任务 #{index} 已{'勾选' if checked else '取消勾选'}"
            )
        )
        viewer.imageClicked.connect(self._preview_image)
        viewer.linkActivated.connect(self._on_link_activated)
        main_layout.addWidget(viewer, 1)

        self._reader_view = viewer
        self._stream_view = viewer
        self._create_settings_drawer()

    def _create_settings_drawer(self):
        """把主题、行号、折叠、缩放、搜索和流式演示收进右侧无遮罩抽屉。"""
        drawer = ElaDrawer(
            position=ElaDrawerPositionType.Right,
            drawer_size=360,
            parent=self,
        )
        drawer.setMaskEnabled(False)
        content = ElaThemeWidget()
        outer = QVBoxLayout(content)
        outer.setContentsMargins(18, 16, 18, 16)
        outer.setSpacing(12)

        head = QHBoxLayout()
        title = ElaText("阅读设置", content)
        title.setTextPixelSize(18)
        title_font = QFont()
        title_font.setPixelSize(18)
        title_font.setBold(True)
        title.setFont(title_font)
        head.addWidget(title)
        head.addStretch()
        code_btn = ElaButton(
            "</> 代码", variant="text", color="primary", parent=content
        )
        code_btn.setFixedWidth(85)
        code_btn.clicked.connect(lambda: self._show_code(self._create_settings_drawer))
        head.addWidget(code_btn)
        outer.addLayout(head)

        scroll = ElaScrollArea(content)
        scroll.setWidgetResizable(True)
        inner = ElaThemeWidget()
        form = QVBoxLayout(inner)
        form.setContentsMargins(0, 0, 6, 0)
        form.setSpacing(10)

        def section(text):
            label = ElaText(text, inner)
            label.setTextPixelSize(13)
            font = QFont()
            font.setPixelSize(13)
            font.setBold(True)
            label.setFont(font)
            form.addWidget(label)

        section("主题")
        self._md_theme_combo = ElaComboBox(inner)
        for name in markdownThemes():
            self._md_theme_combo.addItem(name)
        index = self._md_theme_combo.findText(defaultMarkdownTheme())
        self._md_theme_combo.setCurrentIndex(max(0, index))
        self._md_theme_combo.currentIndexChanged.connect(self._on_md_theme_changed)
        form.addWidget(self._md_theme_combo)

        section("排版")
        line_row = QHBoxLayout()
        line_label = ElaText("代码行号", inner)
        line_label.setTextPixelSize(13)
        line_row.addWidget(line_label)
        line_row.addStretch()
        self._line_numbers_switch = ElaToggleSwitch(inner)
        self._line_numbers_switch.setIsToggled(self._reader_view.lineNumbersEnabled())
        self._line_numbers_switch.toggled.connect(self._on_line_numbers_toggled)
        line_row.addWidget(self._line_numbers_switch)
        form.addLayout(line_row)

        collapse_row = QHBoxLayout()
        collapse_label = ElaText("长代码", inner)
        collapse_label.setTextPixelSize(13)
        collapse_row.addWidget(collapse_label)
        collapse_row.addStretch()
        self._collapse_combo = ElaComboBox(inner)
        for text in ("不折叠", "折叠 12 行", "折叠 24 行"):
            self._collapse_combo.addItem(text)
        current = self._reader_view.codeBlockCollapseLines()
        self._collapse_combo.setCurrentIndex(
            self._collapse_lines.index(current)
            if current in self._collapse_lines
            else 0
        )
        self._collapse_combo.currentIndexChanged.connect(self._on_collapse_changed)
        self._collapse_combo.setFixedWidth(128)
        collapse_row.addWidget(self._collapse_combo)
        form.addLayout(collapse_row)

        zoom_row = QHBoxLayout()
        zoom_out = ElaButton("−", variant="outlined", parent=inner)
        zoom_reset = ElaButton("100%", variant="outlined", parent=inner)
        zoom_in = ElaButton("+", variant="outlined", parent=inner)
        for button in (zoom_out, zoom_reset, zoom_in):
            button.setFixedWidth(64)
        self._zoom_label = zoom_reset
        zoom_out.clicked.connect(self._on_zoom_out)
        zoom_in.clicked.connect(self._on_zoom_in)
        zoom_reset.clicked.connect(self._on_zoom_reset)
        zoom_row.addWidget(zoom_out)
        zoom_row.addWidget(zoom_reset)
        zoom_row.addWidget(zoom_in)
        zoom_row.addStretch()
        form.addLayout(zoom_row)

        section("搜索")
        self._search_edit = ElaLineEdit(inner)
        self._search_edit.setPlaceholderText("输入关键词，回车定位")
        self._search_edit.textChanged.connect(self._on_search_changed)
        self._search_edit.returnPressed.connect(self._on_find_next)
        form.addWidget(self._search_edit)
        search_row = QHBoxLayout()
        self._search_count = ElaText("", inner)
        self._search_count.setTextPixelSize(12)
        self._search_count.setFixedWidth(60)
        prev_btn = ElaButton("上一个", variant="outlined", parent=inner)
        next_btn = ElaButton("下一个", variant="outlined", parent=inner)
        clear_btn = ElaButton("清除", variant="outlined", parent=inner)
        for button in (prev_btn, next_btn, clear_btn):
            button.setFixedWidth(72)
        prev_btn.clicked.connect(self._on_find_prev)
        next_btn.clicked.connect(self._on_find_next)
        clear_btn.clicked.connect(self._on_clear_search)
        search_row.addWidget(self._search_count)
        search_row.addWidget(prev_btn)
        search_row.addWidget(next_btn)
        search_row.addWidget(clear_btn)
        search_row.addStretch()
        form.addLayout(search_row)

        section("流式演示")
        stream_hint = ElaText(
            "以流式方式重放整篇文档，观察稳定段提交与打字光标。", inner
        )
        stream_hint.setTextPixelSize(12)
        form.addWidget(stream_hint)
        stream_row = QHBoxLayout()
        self._replay_btn = ElaButton(
            "重新播放", variant="solid", color="primary", parent=inner
        )
        self._pause_btn = ElaButton("暂停", variant="outlined", parent=inner)
        self._finish_btn = ElaButton("立即完成", variant="outlined", parent=inner)
        for button in (self._replay_btn, self._pause_btn, self._finish_btn):
            button.setFixedWidth(96)
        self._pause_btn.setEnabled(False)
        self._finish_btn.setEnabled(False)
        self._replay_btn.clicked.connect(self._restartStream)
        self._pause_btn.clicked.connect(self._togglePauseStream)
        self._finish_btn.clicked.connect(self._finishStream)
        self._stream_elapsed = QElapsedTimer()
        self._stream_timer = QTimer(self._reader_view)
        self._stream_timer.setInterval(35)
        self._stream_timer.timeout.connect(self._onStreamTick)
        self._reader_view.streamFinished.connect(
            self._onStreamFinished, type=Qt.ConnectionType.QueuedConnection
        )
        stream_row.addWidget(self._replay_btn)
        stream_row.addWidget(self._pause_btn)
        stream_row.addWidget(self._finish_btn)
        stream_row.addStretch()
        form.addLayout(stream_row)

        self._speed_btn = ElaButton("速度 x1", variant="outlined", parent=inner)
        self._speed_btn.setFixedWidth(96)
        self._speed_btn.clicked.connect(self._cycleStreamSpeed)
        speed_row = QHBoxLayout()
        speed_row.addWidget(self._speed_btn)
        speed_row.addStretch()
        form.addLayout(speed_row)

        self._progress = ElaProgressBar(inner)
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(10)
        form.addWidget(self._progress)

        self._stream_status = ElaText(
            "等待开始：点击「重新播放」可在正文中观察流式输出。", inner
        )
        self._stream_status.setTextPixelSize(12)
        self._stream_status.setWordWrap(True)
        form.addWidget(self._stream_status)
        form.addStretch()
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)

        footer = QHBoxLayout()
        self._reader_status = ElaText("最近操作：—", content)
        self._reader_status.setTextPixelSize(12)
        self._reader_status.setWordWrap(True)
        footer.addWidget(self._reader_status, 1)
        close_btn = ElaButton("关闭", variant="outlined", parent=content)
        close_btn.setFixedWidth(72)
        close_btn.clicked.connect(drawer.closeDrawer)
        footer.addWidget(close_btn)
        outer.addLayout(footer)

        drawer.setContentWidget(content)
        self._settings_drawer = drawer

    def hideEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        if self._settings_drawer is not None and self._settings_drawer.isOpened():
            self._settings_drawer.closeDrawer()
        super().hideEvent(event)

    def _toggle_settings_drawer(self) -> None:
        if self._settings_drawer is not None:
            self._settings_drawer.toggleDrawer()

    def _set_reader_status(self, text: str) -> None:
        if self._reader_status is not None:
            self._reader_status.setText(f"最近操作：{text}")

    def _on_md_theme_changed(self, _index: int) -> None:
        """把下拉框当前主题应用到页面内所有演示查看器。"""
        name = self._md_theme_combo.currentText()
        for viewer in self.findChildren(ElaMarkdownViewer):
            viewer.setMarkdownTheme(name)
        self._set_reader_status(f"主题已切换：{name}")

    def _on_line_numbers_toggled(self, enabled: bool) -> None:
        if self._reader_view is not None:
            self._reader_view.setLineNumbersEnabled(enabled)
        self._set_reader_status("代码行号已" + ("开启" if enabled else "关闭"))

    def _on_collapse_changed(self, index: int) -> None:
        if self._reader_view is None or not 0 <= index < len(self._collapse_lines):
            return
        lines = self._collapse_lines[index]
        self._reader_view.setCodeBlockCollapseLines(lines)
        self._set_reader_status(
            "长代码" + ("不折叠" if not lines else f"折叠 {lines} 行")
        )

    def _sync_zoom_label(self) -> None:
        if self._reader_view is not None:
            self._zoom_label.setText(f"{self._reader_view.zoomFactor() * 100:.0f}%")

    def _on_zoom_in(self) -> None:
        if self._reader_view is not None:
            self._reader_view.zoomIn(0.1)
        self._sync_zoom_label()

    def _on_zoom_out(self) -> None:
        if self._reader_view is not None:
            self._reader_view.zoomOut(0.1)
        self._sync_zoom_label()

    def _on_zoom_reset(self) -> None:
        if self._reader_view is not None:
            self._reader_view.setZoomFactor(1.0)
        self._sync_zoom_label()

    def _on_search_changed(self, text: str) -> None:
        if self._reader_view is None:
            return
        if not text:
            self._reader_view.clearSearch()
            self._search_count.setText("")
            return
        total = self._reader_view.searchText(text)
        self._search_count.setText(f"{total} 处")
        self._set_reader_status(f"搜索「{text}」：{total} 处")

    def _on_find_next(self) -> None:
        if self._reader_view is not None:
            self._reader_view.findNext()

    def _on_find_prev(self) -> None:
        if self._reader_view is not None:
            self._reader_view.findNext(backward=True)

    def _on_clear_search(self) -> None:
        if self._reader_view is not None:
            self._reader_view.clearSearch()
        if self._search_edit is not None:
            self._search_edit.clear()
        if self._search_count is not None:
            self._search_count.setText("")

    def _on_link_activated(self, url: str) -> None:
        self._set_reader_status(f"链接：{url}")
        if not url.startswith(("http://", "https://")):
            return
        answer = QMessageBox.question(
            self,
            "打开外部链接",
            f"是否使用系统浏览器打开？\n{url}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            QDesktopServices.openUrl(QUrl(url))

    def _preview_image(self, url: str) -> None:
        """图片点击预览（本地图片弹窗，远程链接交给系统浏览器）。"""
        self._set_reader_status(f"图片：{url}")
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
        """重新播放：在正文中流式重放整篇文档。"""
        self._start_stream(self._build_stream_chunks(_MARKDOWN_READER, 48))

    def _start_stream(self, chunks: list, prefix: str = "") -> None:
        """启动一次流式输出（``prefix`` 非空时先呈现提问再续写）。"""
        self._stream_timer.stop()
        self._stream_chunks[:] = list(chunks)
        self._stream_total = len(self._stream_chunks)
        self._stream_done = 0
        self._stream_view.setLineNumbersEnabled(False)
        self._stream_view.setStickToBottom(True)
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
        self._line_numbers_switch.setEnabled(False)
        self._collapse_combo.setEnabled(False)
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
        """流式收尾：恢复阅读模式与抽屉里的排版开关。"""
        self._stream_view.setStickToBottom(False)
        self._stream_view.setLineNumbersEnabled(
            self._line_numbers_switch.getIsToggled()
        )
        self._line_numbers_switch.setEnabled(True)
        self._collapse_combo.setEnabled(True)
        self._progress.setValue(100)
        elapsed = self._stream_elapsed.elapsed() / 1000.0
        self._stream_status.setText(
            f"已完成：{self._stream_total} 段 / {elapsed:.1f}s，可继续阅读或重新播放"
        )
        self._pause_btn.setText("暂停")
        self._pause_btn.setEnabled(False)
        self._finish_btn.setEnabled(False)
        self._replay_btn.setText("重新播放")
        self._replay_btn.setEnabled(True)
