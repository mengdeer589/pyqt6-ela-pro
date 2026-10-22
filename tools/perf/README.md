# 性能探针（随库分发）

本目录是**宿主可直接跑**的性能探针，用来分辨「这笔开销是我的代码、是 Qt 版本、是绑定
（sip vs shiboken），还是 Win7 字体引擎」。判读方法、实测基线与宿主配方见
[`docs/performance.md`](../../docs/performance.md)。

| 脚本 | 用途 |
|---|---|
| `bench_micro.py` | 底层原语：对象创建 / C++→Python 虚调用 / 方法调用 / 信号（跨绑定可跑） |
| `bench_components.py` | 本库组件的构造成本表（per-instance + 是否原生子窗口） |
| `bench_chat.py` | 聊天栈：构造 / 流式 / 历史导入 / resize / 滚动 / 主题切换 |
| `bench_charts.py` | `ElaChartWidget`：大数据的 ingest / layout / paint / hover / zoom |
| `bench_markdown_paint.py` | Markdown 滚动绘制：原生浏览器 vs 查看器，CJK / ASCII / mixed |
| `bench_font_engine.py` | Win7 字体引擎 A/B：DirectWrite vs GDI（bug #15） |

```powershell
python tools/perf/bench_micro.py
python tools/perf/bench_components.py
uv run python tools/perf/bench_chat.py
uv run python tools/perf/bench_charts.py
uv run python tools/perf/bench_markdown_paint.py --doc cjk --target viewer
uv run python tools/perf/bench_font_engine.py
```

## `bench_micro.py`：把绑定与 Qt 版本分开

同一个脚本可在三种环境里跑，对比出两块：

| 对比 | 差反映的是 |
|---|---|
| PyQt5（sip + Qt5）↔ PyQt6（sip + Qt6） | **Qt 版本**内核差异（实测 `QWidget()` ≈1.5×、字体度量 1.6×） |
| PyQt6（sip + Qt6）↔ PySide6（shiboken + Qt6） | **绑定**差异（实测 `QWidget()` **5.5×**、`QLabel` 3.7×；`Signal.connect` 反而快 2×） |

关键判读（2026-10 实测，Win11）：凡是不碰 QWidget 构造的操作（值类型、纯 C++ 调用、
无参 getter）两栈基本持平；**凡是要造控件的都会跳 5~7 倍**。慢机上放大更狠（Win7 VM 上
同一探针是 **15×**），所以「老机器更卡」是预期行为。

## `bench_components.py`：组件构造成本

按「单实例构造 + `deleteLater()`」的中位值给出 ms/实例（含子控件数、是否创建原生子窗口），
用来判断「哪些组件适合大量实例化、哪些要在启动期少建」。示例结论（Qt 6.8.4）：
`ColorText` 0.033ms / `ElaButton` 0.067ms 可以按需大量建；`ElaField` 0.42ms、
`ElaMarkdownViewer` 0.73ms、`ElaChatView` 1.50ms、`ElaTerminalView` 4.27ms 属重组件，
启动期只建可见的那几个。

## `bench_chat.py`：聊天栈

```powershell
uv run python tools/perf/bench_chat.py
uv run python tools/perf/bench_chat.py --messages 300 --json out.json
uv run python tools/perf/bench_chat.py --offscreen   # 无桌面环境；绘制数字不代表实屏
```

输出环境 / 默认字体 / CJK 单族判定，以及构造、流式、`importSession` 历史导入、
resize（冻结 / 放开）、滚动与深浅主题切换。Win7 上先看两件事：① 默认字体是否单族
（命中 shaping 毒化时所有文字慢一个量级）；② 滚动一屏的耗时（`QTextBrowser` 的
字体 shaping 路径是主成本）。

## `bench_charts.py`：图表大数据

```powershell
uv run python tools/perf/bench_charts.py
uv run python tools/perf/bench_charts.py --json out.json
```

按 `ingest` / `layout` / `paint` / `frame` 分阶段，另测 `hover`、`zoom`、`zoom新窗口`
（真实重采样）与 `缩回全景`（采样 LRU 命中）。基线与「别拿更快但不重采样的曲线当基线」
等纪律见脚本 docstring 与 [`docs/performance.md`](../../docs/performance.md)。

## `bench_markdown_paint.py`：滚动绘制分项

```powershell
uv run python tools/perf/bench_markdown_paint.py --doc cjk --target viewer
uv run python tools/perf/bench_markdown_paint.py --doc ascii --target native
uv run python tools/perf/bench_markdown_paint.py --doc mixed --target viewer --styled
```

**一次进程只测一种文档**：Win7 上先测的那份可能毒化后测的那份。`native` vs `viewer`
可把「Qt 的文本绘制」与「查看器自绘装饰层」分开。

## `bench_font_engine.py`：Win7 字体引擎 A/B（#15）

背景：`bugs/未处理项.md` #15——Win7 上出现过 CJK shaping 后纯 Latin 文本慢 10~40×
的进程级毒化。`crystalidea/qt6windows7#63` 指出 Qt 6.8.4 的 DirectWrite 路径在 Win7
上异常，workaround 是切到 GDI 字体引擎。

同一台机器跑两次，只改平台插件参数：

```powershell
uv run python tools/perf/bench_font_engine.py
$env:QT_QPA_PLATFORM = 'windows:nodirectwrite'
uv run python tools/perf/bench_font_engine.py
```

输出 `ascii_before` / `cjk` / `ascii_after` 的 repaint 中位数。判读：

- `ascii_after / ascii_before` ≈ 1：正常；
- 默认引擎 10~40×、GDI 回到 ≈1：命中 #15，宿主可在 `QApplication` 之前设置
  `QT_QPA_PLATFORM=windows:nodirectwrite`（或 `-platform windows:nodirectwrite`）；
- GDI 也慢：慢路径在 GDI 侧，需要 Qt 源补丁，不是换引擎能解决的。

GDI 会改变整进程字体渲染（ClearType / 彩色字体 / 字体度量），属于**宿主级开关**，
不进库默认。Win10 本机对照：默认 5.1/5.2ms、GDI 3.9/3.8ms，均无毒性；Win7 需实机验证。
