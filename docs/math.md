# LaTeX 公式轻量渲染（math_lite）

零依赖的 LaTeX 数学子集渲染器：把公式解析为盒模型，用 `QPainter` 画到透明底
`QImage`（2x 超采样，高 DPI 清晰），不引入 matplotlib。用于 Markdown 查看器内嵌公式。

## API

```python
from pyqt6_ela_pro.math_lite import extract_math, render_formula

processed, maths = extract_math(source, "elamath0z{}q")
image = render_formula(latex, color, pt, display=False)   # QImage | None
```

- `extract_math(text, mark, macros=None)`：提取 `$...$` / `$$...$$` / `\[...\]` /
  `\begin{...}`，替换为占位标记；代码围栏内不提取。
- `render_formula(latex, color, pt, display=False)`：返回 `QImage`；不支持的公式返回
  `None`，调用方回退为源码文本。
- `clear_cache()` / `set_cache_capacity(n)`：公式渲染结果按 LRU 缓存。

## 支持范围

- 希腊字母、常用符号、长尾箭头与变体符号；
- 上下标、`\frac` / `\dfrac` / `\tfrac`、`\sqrt[n]`；
- `\sum` / `\prod` / `\int` / `\oint` / `\lim` 等大算子与上下限；`\max` / `\min` /
  `\sup` / `\inf` 等极限算子自动堆叠（`\limits` / `\nolimits` 可覆盖）；
- 直立函数名（`\sin` / `\cos` / `\log` 等）、`\operatorname*`；
- `\boxed` / `\underline` / `\overbrace` / `\underbrace` / 箭头类重音 / `\overset` /
  `\underset` / `\xrightarrow`；
- 字体与颜色：`\text` / `\mathrm` / `\mathbf` / `\boldsymbol` / `\textbf` / `\texttt`
  等，`\textcolor` / `\color`（基础色名或 `#RRGGBB`），`\cancel` 系列；
- 公式编号 `\tag` / `\tag*`；
- 矩阵与多行环境：`matrix` / `pmatrix` / `bmatrix` / `cases` / `align` / `aligned` /
  `gather` / `multline` / `split` / `array` / `smallmatrix` / `dcases` / `rcases`，
  组合数 `\binom`，字母表 `\mathbb` / `\mathcal` / `\mathfrak`；
- 定界符 `\left` / `\right` / `\big` 系列 / `\middle`；
- 宏 `\newcommand` / `\def` / `\DeclareMathOperator`（含参数）；
- 间距与占位 `\quad` / `\hspace` / `\phantom` 系列。

排版对齐 KaTeX：优先 Cambria Math，变量用 Unicode 数学斜体码位，紧凑字形度量，
TeX 风格原子间距，脚本分级缩放，大算子 display 尺寸。

## 容错与限额

- 未知命令按字面文本渲染（`report["degraded"]`）。
- `\left` / `\right` 不闭合时自动配平后重试（`report["repaired"]`）；仍失败才返回
  `None`。
- 单边逻辑像素上限 20000、实际栅格总像素上限 6400 万（超采样倍率 2，按
  `width*2 × height*2` 计算），防止 `\hspace{1000000em}` 之类的输入吃光内存；
  超限按「不支持」处理。
