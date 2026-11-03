# 终端输出视图（ElaTerminalView）

只读终端输出组件：宿主把 `subprocess` / `QProcess` / 日志文件 / 工具调用拿到的原始
文本（可含 ANSI 转义）喂进来，组件负责解析、排版与交互。**组件不执行任何命令。**

## 数据模型

- `_lines`（`TerminalLine` 列表）是唯一真相，`QTextDocument` 只是派生渲染。
- 过滤 = 按模型重建；导出 = 拼接模型；行数上限 = 淘汰模型头部。
- ANSI 解析器只产出颜色索引，不碰具体颜色，切换调色板无需重新解析。
- `append` 按帧合并提交，避免逐片重排的 O(n²)。

## 用法

```python
from pyqt6_ela_pro import ElaTerminalView

view = ElaTerminalView(maxLines=5000, paletteName="opencode")
view.append("\x1b[32mok\x1b[0m\n")
view.setLineNumbersVisible(True)
view.setFilter("error")
view.findNext()
view.saveTo("output.log")
```

常用 API：`append` / `appendLine` / `clear` / `setMaxLines` / `setFilter` /
`findNext` / `findPrevious` / `setAutoScroll` / `setLineNumbersVisible` /
`setWordWrap` / `saveTo` / `copyAll` / `copySelection`。

## 配色主题

内置主题用 `terminalThemes()` 查询，`registerTerminalTheme(name, light, dark)` 注册
自定义主题，`setDefaultTerminalTheme(name)` 改后续实例的默认值。

## CJK 与缺字形

中文系统默认开启缺字形兜底（`setMissingGlyphFallbackEnabled(False)` 可关）：只改
`QTextCharFormat` 的字体族，不改文本，复制 / 导出保真。

主字体是比例字体：做进度条不要混用缺字形字符（如 `░`）与主字体覆盖的 `█` ——
前者会走符号字体兜底、字宽不同，条会随填充变短。用同一字符配颜色，或背景色空格。
