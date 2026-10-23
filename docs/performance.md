# 性能：成本模型与宿主配方

> 当前维护线：**PyQt6 6.8.1 + Qt 6.8.2（Win7 交付线为自编译 Qt 6.8.4）**。
> 下文的 PySide6 / PyQt5 数据是迁移期对照，保留作历史参考；当前栈的组件成本与
> 聊天 / Markdown 滚动基线见 `tools/perf/` 与本文「聊天组件自测」。
>
> 面向**使用本库的宿主应用**。数字来自 2026-10-13 实测：Win11 主机（CPU 同档）+ Win7 虚拟机，
> 运行时 = `PySide6 6.8.3` + 自编译 Qt 6.8.4（Win7 套件）；对照组 `PyQt5 5.15.2` / `PyQt6 6.8.1 + Qt 6.8.2` / `PyQt6 6.11`。
> 背景与逐项归因见 `docs/pyside6-migration.md` 第九节；本页只讲**宿主该怎么做**。

## 一页摘要

| 你会遇到的 | 原因（量级） | 你要做的 |
|---|---|---|
| 启动比 PyQt5 版慢 30–40% | 每个 Python 侧控件贵 5.5×（shiboken 包装）+ Qt6 内核 1.25–1.6× | 重页面**惰性构建 + 启动后后台预热**（配方 ②）；别在构造路径里调 `QFont().defaultFamily()`（配方 ①） |
| 某一页莫名其妙多 ~190ms | Qt6 首次解析系统默认字体（**一次性**） | 配方 ①（用 `ElaSplashScreen` 的话已自动处理） |
| 第一次出现代码块时卡 ~200ms | 首次 `ElaIcon.getElaIcon`（图标字体 ~216ms，字体引擎已热时 ~29ms）+ Pygments 导入（~35ms） | 配方 ①（splash 已一并预热；预热后首块代码 219ms → 3.5ms） |
| 主窗口「闪一下」/ 弹两次 | 给**已显示**的窗口挂原生子窗口（GL 视口）→ Windows/Qt 重建顶层 HWND | 配方 ③（默认就是软件视口；启用 GL 就必须在 `show()` 之前建画布） |
| 侧边栏收缩 / 拖动窗口时掉帧 | 每帧 resize 中央页 → 整页 invalidated → 上百子控件各画一遍 | 配方 ④（连续 resize 期间钉尺寸 + 防抖） |
| 主题切换卡一下 | 与绑定无关：Ela/C++ 对**可见控件**全量重绘（∝ 可见控件数） | 无法根治；控制同时可见的控件数 |

## 成本模型（同机实测，ms/次）

> 下表保留迁移期对照：**当前维护线只看 PyQt6 列**，PyQt5 / PySide6 两列用于理解历史差异。

| 操作 | PyQt5<br>sip+Qt5.15 | PyQt6<br>sip+Qt6.8 | PySide6<br>shiboken+Qt6.8 | 结论 |
|---|---|---|---|---|
| `QWidget()` | 0.0008 | 0.0012 | **0.0066** | **绑定 5.5×**；Qt6 内核只 1.5× |
| `QLabel('x')` | 0.0020 | 0.0025 | 0.0093 | 同上 |
| `QColor().red()`（值类型） | 0.0004 | 0.0004 | 0.0004 | 无差异 |
| `QListWidget.addItem`（纯 C++） | — | — | ≈1.0× | 无差异 |
| `Signal.connect` | 0.0031 | 0.0038 | **0.0020** | PySide6 反而快 2× |
| `QFontMetrics.horizontalAdvance` | 0.0013 | **0.0020** | 0.0024 | **Qt6 内核 1.6×**（DirectWrite；字体密集 UI 的固定税） |
| `grab()`（绘制+渲染） | 0.0053 | 0.0064 | 0.0092 | 绘制只 1.4× |

三条要点：

1. **主要是「每个对象/每次跨边界调用」的固定成本**，不是算法慢。一个 2900 控件的界面 ≈ 十几万次跨边界调用 → 累计数百毫秒；控件少的窗口几乎无感。
2. **绑定税在慢机上被放大**：同一支探针在 Win7 VM 上是 `QWidget()` **10.5µs vs 0.7µs（15×）**。所以「老机器更卡」是预期行为。
3. **Qt 版本有关**：Qt 6.11 已把 `QWidget()` 造回来（≈1.0µs，接近 Qt5），字体度量也降了 —— 升级 PyQt6 / Qt 是当前线最便宜的提速手段（Win7 线需用自编译 Qt 重新打补丁）。

## 宿主配方

### ① 启动时预热一次性字体 / 图标字体 / 语法高亮（~250ms，一次）

用本库的 splash 就**已经自动做掉**（`ElaSplashScreen.show()` 之后的首个事件循环里预热，
见 `splash_screen._warmTextStack`）：系统默认字体（~190ms）→ 首个 `ElaIcon.getElaIcon`
（图标字体，字体引擎已热时 ~29ms）→ Pygments 导入与首个词法器（~35ms）。不用 splash
的话自己在启动阶段加这三步：

```python
from PyQt6.QtGui import QFont, QColor
from PyQt6ElaWidgetTools import ElaIcon, ElaIconType
QFont().defaultFamily()        # Qt6 首次 ~190ms；之后再调是 0.0x ms
ElaIcon.getInstance().getElaIcon(ElaIconType.IconName.Copy, QColor(0, 0, 0))
from pygments.lexers import get_lexer_by_name
get_lexer_by_name("python", stripnl=False, ensurenl=False)
```

**不要**把它留在页面构造 / 首次绘制路径里（否则某一页会莫名多 190ms —— 我们就踩过：
某个无关演示节从 4ms 变成 194ms）。图标字体与 Pygments 没预热时，这两笔会落在
**第一个代码块渲染**上：实测首块代码 219ms → 预热后 3.5ms。守卫：
`tests/regression/test_font_warmup_trap.py`、`tests/splash_screen/test_splash_screen.py::TestWarmTextStack`。

### ② 重页面惰性构建 + 启动后后台预热

启动期只建「脚手架 + 首屏那页」，其余页在事件循环起来后**每 tick 建一页**：

```python
# 页面基类：内容惰性化（首次显示时构建），并暴露幂等的构建入口
class MyPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._built = False
        self._build_scaffold()          # 只搭壳（滚动区 + 空布局）

    def ensureContent(self):
        if self._built:
            return
        self._built = True
        self._build_content()           # 重活都在这里

    def showEvent(self, event):
        self.ensureContent()
        super().showEvent(event)


# 启动后：每 tick 一页（定时器挂窗口上，随窗口销毁）
pages = [p for p in window.findChildren(MyPage)]
cursor = [0]

def warm_next():
    while cursor[0] < len(pages):
        page = pages[cursor[0]]; cursor[0] += 1
        if page.isVisible() or page._built:
            continue
        page.ensureContent()
        timer.start(16)                 # 一页一个节拍，避免长阻塞
        return

timer = QTimer(window); timer.setSingleShot(True); timer.timeout.connect(warm_next)
timer.start(250)
```

本库示例（`pyqt6_ela_pro/example/…`）就是这么做的：启动 1943ms → **510ms**，24 页在
后台约 1s 内全部预热完。

### ③ `show()` 之前构建「会挂原生子窗口」的组件

`ElaBlueprintCanvas` 的 GL 视口是 `QOpenGLWidget`（原生子窗口）。窗口已显示之后再挂上
去，Windows/Qt 会**重建顶层 HWND** —— 用户看到主窗口闪一下（类名 `QWindowIcon` →
`QWindowOwnDCIcon`，实测触发点在建好画布那一刻）。

**默认是软件视口**（`ELABLUEPRINT_GL` 未设 / `off`），所以开箱不会踩这个雷。要 GPU
加速才显式启用，并且必须**先建画布再 `show()` 窗口**：

```python
# 方式 A（推荐）：默认软件视口，什么都不用做
canvas = ElaBlueprintCanvas(graph, parent=window)

# 方式 B：要 GL 加速 —— 必须在 window.show() 之前构建画布
os.environ["ELABLUEPRINT_GL"] = "on"        # 需在首次探测前设置
canvas = ElaBlueprintCanvas(graph, parent=window)
window.show()
```

启用 GL 又在「已显示窗口」上创建时，组件会打 `logger.warning` 提醒
（`blueprint/viewport.py`），守卫 `tests/ela_blueprint/test_viewport_attach_contract.py`。

### ④ 连续 resize（侧边栏动画 / 拖动窗口）期间钉尺寸

动画/拖窗时每帧都会 resize 内容页 → 整页 invalidated → 上百个子控件各自重绘（实测单帧
8.6ms；慢机按 2–5× 放大）。**库已提供公开工具**，宿主挂一次即可：

```python
from pyqt6_ela_pro import setResizeReflowDeferred

class MyPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        ...
        setResizeReflowDeferred(self)      # 连续 resize 钉住，静止 120ms 后一次性放开
```

- 只作用于**页面 / 面板**这一级（顶层窗口的尺寸归窗口管理器，挂上会被忽略并记 WARNING）；
- 放开时按控件**原有的 min/max 约束**恢复（宿主自己设的固定尺寸不会被吃掉）；
- `setResizeReflowDeferred(page, on=False)` 可随时关掉；`delayMs` 调防抖时长；
- `ElaChatView` 另有同口径的 `setResizeReflowDeferred`（聊天场景带会话级参数）。

内部实现（不想用工具时照抄）：连续 resize（间隔 < 60ms）时 `setFixedSize(当前尺寸)` 钉住，
静止 120ms 后恢复 min/max 并让父布局 invalidate + activate 一次。

本库的 chat 组件已有同类开关（`ElaChatView.setResizeReflowDeferred`）。示例里的实现见
`pyqt6_ela_pro/example/base_page.py`（实测单帧 8.6ms → **0.0ms**）。

### 聊天历史：延迟分段物化

`ElaChatView.importSession` / `restoreMessages` 在批量模式下只给首屏附近的消息建
工具卡 / 思考块，其余消息只保存 `parts` 数据（`bubble.partsDeferred()`），滚动到附近
时按页物化；超过 24 步的超长消息只物化末尾 12 步（`partsWindowed()`），其余折叠成
「展开全部」按钮。`parts()` / `messages()` / 导出始终是全量数据。

实测 102 条消息 / 1309 step / 1428 次工具调用的 opencode 历史（1400×900 窗口）：

| 指标 | 全量物化 | 延迟物化 |
|---|---|---|
| `importSession` | ~4.6 s | **~20 ms** |
| 内存 | ~678 MB | **~210 MB** |
| 控件数 | ~32k | **~450** |
| 拖动 resize（冻结后） | ~190 ms/帧 | **~4 ms/帧** |

超长历史（合成数据）的 spacer 虚拟列表（≥200 条自动启用）：

| 规模 | 旧逐条占位 | spacer 虚拟列表 |
|---|---:|---:|
| 1,000 条 | 1,589 控件 / 148 MB | **249 控件 / 102 MB** |
| 10,000 条 | 10,243 控件 / 231 MB | **197 控件 / 124 MB** |
| 10,000 条滚到顶部 | ~492 ms | **~42 ms** |

需要逐控件断言的测试可 `view.setVirtualPartsEnabled(False)` 关闭分段延迟物化；
批量超过 80 条时连气泡壳也延迟（`setShellVirtualizationEnabled` 可控），
`bubble(id)` 对未物化消息返回 `None`，数据用 `message()` 快照读。滚远后已物化
消息会收回等高占位（保留快照与实测高度），因此滚完整个历史内存不会随消息数
线性增长。

### 聊天组件自测（2026-10-21）

两个随仓库分发的脚本（Win10/11 与 Win7 交付机通用）：

```powershell
uv run python tools/perf/bench_chat.py --messages 100 --json chat.json
uv run python tools/perf/bench_markdown_paint.py --doc cjk --target viewer --styled
```

`bench_chat.py` 先打印环境与字体（`app_font` / `cjk_single_family` / `mono_font_families`
/ `code_font_family`），再分项测：构造（纯文本 / 富消息）、流式、`importSession`、
resize（冻结 / 放开）、滚动、深浅主题。开发机（Win11，PyQt6 6.8.1 + Qt 6.8.2，
1000×700，每消息含代码块）量级参考：

| 场景 | 结果 |
|---|---|
| 添加 50 条（8KB/条） | ~450ms（9ms/条，32 控件/条） |
| 1 条富消息（思考 + 5 工具） | ~36ms，91 控件 |
| 流式 200 片 / 18KB | 8.6ms + 收尾 21ms |
| `importSession` 50 条 | ~260ms（含首屏渲染；1613 控件） |
| 50 条 resize | 冻结 7.3ms/帧 / 放开 30ms/帧 |
| 50 条滚动 | ~1–3ms/步 |
| 50 条切主题 | ~190ms（代码块密集） |

`bench_markdown_paint.py` 是 Win7 的**分项探针**：同一个文档分别用原生
`QTextBrowser` 与 `ElaMarkdownViewer` 滚动，一步 40px 的耗时差就是查看器自绘
装饰层的成本。**一次进程只测一种文档**（Win7 的字体 shaping 毒化是
进程级的，先测 CJK 会污染后面的 ASCII 数字）。命中字体慢路径时先修字体
（单族 CJK / 缺字形 fallback），再谈控件与绘制优化。

## 组件构造成本参考（ms/实例，Qt 6.8.4）

| 组件 | ms/实例 | 子控件 | 备注 |
|---|---|---|---|
| `ElaText`（上游）/ `ColorText` | 0.031 / 0.033 | 0 | 可大量使用 |
| `ElaAvatar` | 0.041 | 0 | |
| `ElaDropDownButton` / `ElaSplitButton` | 0.048 / 0.052 | 0 | |
| `ElaChip` / `ElaButton` / `ElaShimmer` | 0.053 / 0.067 / 0.072 | 0 | |
| `ElaSelectorBar` | 0.079 | 0 | |
| `ElaBlueprintCanvas` | 0.149 | 1 | GL 时含原生子窗口（见配方 ③） |
| `ElaField` | 0.418 | 8 | 组合壳 |
| `ElaMarkdownViewer` | 0.732 | 6 | 构造便宜，**渲染**才贵（文档布局 / 高亮）；>64KB 自动分块渐进渲染（`isRendering` / `renderingProgress`），不按视口懒渲染（滚动 / 搜索 / 导出依赖完整文档） |
| `ElaChatView` | 1.497 | 11 | 一页一个即可 |
| `ElaTerminalView` | 4.272 | 18 | 最重；别在启动期批量建 |

读法：`0.0x ms` 级可以按需大规模创建；`0.4ms+` 的是「重组件」，启动期只建可见的那几个。
（测量口径：单实例构造 + `deleteLater()` 循环取中位；含子控件。用
`bench_components.py` 可复跑。）

## 已知不可修 / 预期

- **主题切换**的成本 ≈ 可见控件数 × 重绘：实测 272ms / 70–78 次重绘（PyQt5 同量级，**与绑定无关**）。
  减少同时可见的控件数是唯一手段。
- **Qt6 字体度量 1.6×**（DirectWrite）。字体极密的界面（大量 `QFontMetrics` 计算）会吃到这笔税。
- **绘制 1.4×**：难以避免，但只在每帧重绘很多控件时才可见（配方 ④ 就是为它准备的）。
- **透明文本视口（Win7）**：`QTextBrowser` 系在 palette `Base` 透明 + 视口不自填充时走慢速重绘路径（滚动实测 ×8）。本库查看器对非嵌入 / 圆角形态默认用不透明同色底 +
  圆角 mask（`ElaMarkdownViewer.setViewportBackground`，bugs #14）；嵌入查看器（聊天气泡）保持透明、由宿主传入自己的底色作不透明底（聊天组件已传）；宿主自绘文本控件同理。
- **CJK 字体 shaping（Win7）**：非 CJK 主字体渲染 CJK 内容（逐字形回退）与多族字体列表（逐字形族匹配）都会走慢 shaping，且任一走过一次即**进程级毒化**后续一切文本绘制（10~250×，Qt/DirectWrite 层；Win7 交付线已用 GDI 引擎规避）。
  **第三个触发方向**：主字体是 CJK、但文本含它 cmap 里没有的符号（LLM 输出常带 ↔ / ⇒ / □ / √）同样走逐字形回退并毒化。所以库自产进 `QTextDocument` 的标记只用雅黑 cmap 内的字形：任务勾选 `□`/`■`（U+25A1/U+25A0）、折叠 `+`/`−`（U+002B/U+2212）；不要换回 `☐`/`☑`、`▸`/`▾`（均不在雅黑 cmap）。**查看器默认对缺字字符套单族符号字体**（`_internal.applyMissingGlyphFonts`：Segoe UI Symbol / Cambria Math，只改字体族、不改文本；`ElaMarkdownViewer.setMissingGlyphFallbackEnabled(False)` 可关；`ElaTerminalView` 也已默认接入，同样可关）。终端等其它 `QTextDocument` 组件可复用该工具。
  本库已把可控触发点全部收口：**中文系统**下终端默认字体、查看器代码字符格式 / 默认代码字体、图表文本（`chartFont`）与聊天等宽 / 标题标签均为**单族** `Microsoft YaHei`（其它系统保持原状）；宿主仍可用
  `ElaTerminalView.setFontFamilies()` / `ElaMarkdownViewer.setCodeFontFamily()` 覆盖 —— 要避免逐字形回退请给**单个** CJK 字体，**多族列表（等宽 + CJK 后备）同样慢**（公式渲染是唯一保留多族的例外：数学字形与 CJK 覆盖二选一）。
  **Win7 交付线使用 GDI 引擎**：`crystalidea/qt6windows7#63` 的 DirectWrite 路径在 Win7 上异常；`QT_QPA_PLATFORM=windows:nodirectwrite`（GDI）已由下游实机验证能消除 CJK→Latin 慢路径（必须在 `QApplication` 之前）：
  ```powershell
  $env:QT_QPA_PLATFORM='windows:nodirectwrite'
  # 或 QApplication 参数：-platform windows:nodirectwrite
  ```
  A/B 探针 `tools/perf/bench_font_engine.py` 保留作复测，比较 `ascii_after / ascii_before`（正常 ≈1，10~40× 即命中）。Win10 本机对照：default 5.1/5.2 ms、GDI 3.9/3.8 ms，均无毒性。GDI 会改变整进程字体渲染（ClearType / 彩色字体），属宿主级开关，不进库默认。

## 自测

最小探针（粘到你的项目里跑）—— 当前线用 PyQt6；与 PyQt5 / PySide6 对照时各自替换导入：

```python
import time
from PyQt6.QtWidgets import QApplication, QWidget      # 对照侧换成 PyQt5.* / PySide6.*
app = QApplication([])
def bench(label, fn, n=5000):
    fn(); t = time.perf_counter()
    for _ in range(n): fn()
    print("%-24s %.4f ms" % (label, (time.perf_counter() - t) * 1000 / n))
bench("QWidget()", lambda: QWidget())
```

判读：`QWidget()` 在 PyQt6 上约 **0.0012ms**（PyQt5 同量级；迁移期 PySide6 约 0.007ms 属 shiboken 包装差异）；若你的
某项比这还大一两个数量级，那才是代码问题，不是绑定。

更完整的对照工具：

- **随库分发**（`tools/perf/`）：
  `bench_micro.py`（底层原语：对象创建 / 虚调用 / 参数转换，PyQt5/PyQt6/PySide6 都能跑，历史对照用）、
  `bench_components.py`（本库组件的构造成本表）、`bench_chat.py` / `bench_markdown_paint.py`（聊天与 Markdown 滚动基线）；
- 本仓库开发时用的宿主级 harness（仓库外）：`bench_example.py` / `bench_lazy.py`（启动与
  首访）、`bench_anim.py`（侧边栏动画帧间隔）、`bench_theme_icons.py`（主题切换 + 图标
  视图）、`probe_win7_kernel.py`（目标机开关探针）、`watch_windows.py`（窗口出现 / 消失
  时间线，排查「窗口闪 / 弹两次」）。

---

## 图表（`ElaChartWidget`）折线 / 散点：绘制量上界与实测基线（2026-10）

`tools/perf/bench_charts.py`（离屏 1400×800，可出 JSON）复现下表。

### 基线（帧 = 布局 + 纯光栅化，不含窗口合成）

| 场景 | layout | paint | **frame** | hover | 缩放一步 |
|---|---|---|---|---|---|
| 折线 value 100 万点（默认采样） | 3 | 6 | **12.4ms** | 0.8 | 13 |
| 折线 category 100 万点 | 3 | 6 | **9.4ms** | 0.8 | 22 |
| 折线+点 100 万点 | 3 | 6 | **12.6ms** | — | — |
| 面积 100 万点 | 3 | 9 | **12.6ms** | — | — |
| smooth / step 100 万点 | 3–9 | 6 | **12.6 / 9.4ms** | — | — |
| 散点 50k / 1M | 3 / 6 | 3 | **6.2ms** | 1.6–1.7 | 35–40 |
| 折线 100 万点 `sampling: false` | 1156 | 553 | 1709ms（全量保真的代价） | — | — |

改造前（同一台机）对照：category 轴 100 万点 **11987ms**、散点 50k **296ms**、1M 折线 paint 107ms。

### 三条结论（都在 `AGENTS.md` 的 charts 段有硬规则）

1. **绘制量必须与数据量解耦**：窗口 + 抽稀对所有轴类型生效（此前 category / polar / 非 numpy 全量画），坐标轴标签 / 刻度 / 网格线也按「标签宽度 ÷ 每类目像素」抽稀 —— 1M 类别的 x 轴光标签就要 11.8s。
2. **原语按笔宽选**：宽笔（>1px）+ 自重叠几何会踩 Qt stroker（`drawPolyline`/`QPainterPath` 实测 5s / 1856 段），`drawLines` 批量只要 20ms；细笔三者同级。
3. **点量大走预渲染位图**：5.5k 点 —— 逐点椭圆 14.7ms、合并 `QPainterPath` **204ms**（反直觉陷阱）、`QPixmap` 贴图 3.5ms。

### 对齐 Plotly 的交互能力

`resetView()` / 双击复位、`zoomStep()`、`setDragMode(pan/zoom/select/lasso)`、套索刷选、`tooltip.hitRadius`、`hoveranywhere` / `clickanywhere`、`tooltip.order`、`connectNulls`、SVG 导出、工具箱 6 键（含 zoomIn / zoomOut）—— API 细节见 `docs/charts.md`，契约见 `tests/ela_chart_widget/test_chart_plotly_parity.py`。
