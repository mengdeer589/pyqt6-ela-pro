# 性能：成本模型与宿主配方

> 面向**使用本库的宿主应用**。数字来自 2026-10-13 实测：Win11 主机（CPU 同档）+ Win7 虚拟机，
> 运行时 = `PySide6 6.8.3` + 自编译 Qt 6.8.4（Win7 套件）；对照组 `PyQt5 5.15.2` / `PyQt6 6.8.1 + Qt 6.8.2` / `PyQt6 6.11`。
> 背景与逐项归因见 `docs/pyside6-migration.md` 第九节；本页只讲**宿主该怎么做**。

## 一页摘要

| 你会遇到的 | 原因（量级） | 你要做的 |
|---|---|---|
| 启动比 PyQt5 版慢 30–40% | 每个 Python 侧控件贵 5.5×（shiboken 包装）+ Qt6 内核 1.25–1.6× | 重页面**惰性构建 + 启动后后台预热**（配方 ②）；别在构造路径里调 `QFont().defaultFamily()`（配方 ①） |
| 某一页莫名其妙多 ~190ms | Qt6 首次解析系统默认字体（**一次性**） | 配方 ①（用 `ElaSplashScreen` 的话已自动处理） |
| 主窗口「闪一下」/ 弹两次 | 给**已显示**的窗口挂原生子窗口（GL 视口）→ Windows/Qt 重建顶层 HWND | 配方 ③（默认就是软件视口；启用 GL 就必须在 `show()` 之前建画布） |
| 侧边栏收缩 / 拖动窗口时掉帧 | 每帧 resize 中央页 → 整页 invalidated → 上百子控件各画一遍 | 配方 ④（连续 resize 期间钉尺寸 + 防抖） |
| 主题切换卡一下 | 与绑定无关：Ela/C++ 对**可见控件**全量重绘（∝ 可见控件数） | 无法根治；控制同时可见的控件数 |

## 成本模型（同机实测，ms/次）

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
3. **Qt 版本有关**：Qt 6.11 已把 `QWidget()` 造回来（≈1.0µs，接近 Qt5），字体度量也降了 —— 升级 PySide6 是同一个绑定下最便宜的提速手段（Win7 线需要重新打补丁）。

## 宿主配方

### ① 启动时预热一次性字体（~190ms，一次）

用本库的 splash 就**已经自动做掉**（`ElaSplashScreen.show()` 之后的首个事件循环里预热，
见 `splash_screen._warmTextStack`）。不用 splash 的话自己在启动阶段加一行：

```python
from PySide6.QtGui import QFont
QFont().defaultFamily()        # Qt6 首次 ~190ms；之后再调是 0.0x ms
```

**不要**把它留在页面构造 / 首次绘制路径里（否则某一页会莫名多 190ms —— 我们就踩过：
某个无关演示节从 4ms 变成 194ms）。守卫：`tests/regression/test_font_warmup_trap.py`。

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

本库示例（`pyside6_ela_pro/example/…`）就是这么做的：启动 1943ms → **510ms**，24 页在
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
from pyside6_ela_pro import setResizeReflowDeferred

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
`pyside6_ela_pro/example/base_page.py`（实测单帧 8.6ms → **0.0ms**）。

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
- **透明文本视口（Win7）**：`QTextBrowser` 系在 palette `Base` 透明 + 视口不自填充时走慢速重绘路径（滚动实测 ×8）。本库查看器默认已改用不透明同色底
  （`ElaMarkdownViewer.setViewportBackground`，bugs #14）；宿主自绘文本控件同理。
- **CJK 字体 shaping（Win7）**：进程内渲染过 CJK 后，纯 Latin 文档重绘成本可放大 ~20–40×（Qt/DirectWrite 层，与库无关，bugs #15）；终端可用
  `ElaTerminalView.setFontFamilies()` 指定含中文字形的等宽族，规避逐字形回退（bugs #12 的另一半）。

## 自测

最小探针（粘到你的项目里跑）——「同一个操作，PyQt5 与 PySide6 各跑一遍」：

```python
import time
from PySide6.QtWidgets import QApplication, QWidget      # PyQt5 侧改成 PyQt5.*
app = QApplication([])
def bench(label, fn, n=5000):
    fn(); t = time.perf_counter()
    for _ in range(n): fn()
    print("%-24s %.4f ms" % (label, (time.perf_counter() - t) * 1000 / n))
bench("QWidget()", lambda: QWidget())
```

判读：`QWidget()` 在 PyQt5 上 ≈0.001ms、PySide6 ≈0.007ms 属正常（绑定差异）；若你的
某项比这还大一两个数量级，那才是代码问题，不是绑定。

更完整的对照工具：

- **随库分发**（`tools/perf/`）：
  `bench_micro.py`（底层原语：对象创建 / 虚调用 / 参数转换，PyQt5/PyQt6/PySide6 都能跑）、
  `bench_components.py`（本库组件的构造成本表）；
- 本仓库开发时用的宿主级 harness（仓库外）：`bench_example.py` / `bench_lazy.py`（启动与
  首访）、`bench_anim.py`（侧边栏动画帧间隔）、`bench_theme_icons.py`（主题切换 + 图标
  视图）、`probe_win7_kernel.py`（目标机开关探针）、`watch_windows.py`（窗口出现 / 消失
  时间线，排查「窗口闪 / 弹两次」）。
