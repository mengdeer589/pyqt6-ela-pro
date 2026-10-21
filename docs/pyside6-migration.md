# PyQt5 → PySide6 迁移：踩坑与经验

> **历史文档**：本文件记录 PyQt5 → PySide6 迁移期的经验。当前仓库**只维护 PyQt6 线**
> （`pyqt6_ela_pro`，PyQt6 6.8.1 + Qt 6.8.2 / Win7 自编译 6.8.4）；本文保留用于理解
> 跨绑定差异，新的约束与现状以 `README.md` / `AGENTS.md` 为准。

本文是 `pyqt5_ela_pro` → `pyside6_ela_pro`（PySide6 6.8.3 + PySide6ElaWidgetTools 0.13.0）
这次迁移的**经验沉淀**：哪些 PySide6 / shiboken 行为会咬人、报错为什么误导、怎么定位、怎么把它变成守卫。

- 权威约束清单在 `AGENTS.md`（库内硬规则，逐条可执行）；本文给**症状 → 根因 → 修法 → 守卫**的叙事与判据。
- 轮子相关（混版、绑定生成器 bug、镜像）见 git 历史（原 `WHEEL_ISSUES.md` 已删除）；`MIGRATION.md` 是本地过程记录（gitignore，含更早一轮 6.6.2 的实测）。
- 迁移规模与结果：**372 个文件 / +3979 −3555**；全量测试 **0 failed**（官方 6.8.3：5603 passed / 39 skipped；pyside6-win7 运行时：5610 passed / 35 skipped）。

---

## 0. TL;DR：三个成本中心

| 成本中心 | 量级 | 为什么难 |
|---|---|---|
| 上游绑定的**枚举参数**只收枚举成员 | 一次迁移里 **296 处测试失败** | 报错是完全误导的 `NameError: name 'ElaWidgetTools' is not defined` |
| **静默崩溃**（`0xC0000409` / `0xC0000005`，无 traceback） | 每个都是独立根因 | 异常穿出 Qt 回调 / 悬空指针 / 无主定时器 —— try/except 与 faulthandler 都抓不到 |
| **环境与轮子** | 卡住整条命令 | 混版轮、镜像 403、path wheel 哈希、绑定生成器 bug —— 与代码无关但更致命 |

一个总原则：**PyQt5 的宽松掩盖了真 bug，PySide6 把它们变成崩溃**。方向上是好事，代价是迁移成本集中在「当年图省事写下的代码」上。

---

## 1. 致命坑：静态检查抓不到、报错还误导

### 1.1 上游枚举参数只收枚举成员（最贵）

```python
eTheme.getThemeColor(mode, 13)          # PyQt5：可以
eTheme.getThemeColor(mode, 13)          # PySide6：
# NameError: Error evaluating `ElaWidgetTools.ElaTheme.getThemeColor`:
#            name 'ElaWidgetTools' is not defined
```

**不要相信这条报错** —— 它和「模块名」毫无关系，真实原因是 shiboken 类型匹配失败后把内部求值错误原样抛出。

实测只收枚举成员的上游方法（写死清单见下），传 `int` 一律炸：

| 方法 | 说明 |
|---|---|
| `eTheme.getThemeColor(mode, slot)` / `setThemeColor(mode, slot, color)` | 前两个参数都要枚举成员 |
| `eTheme.setThemeMode(mode)` | |
| `ElaNavigationBar.setDisplayMode(mode, isAnimation)` | 第 2 参是 `bool`（合法） |
| `ElaWindow` / `ElaAppBar` / `ElaWidget.setWindowButtonFlags(flags)` | `A \| B` 可直接传 |
| `ElaText.setTextStyle(style)` | |
| `ElaIcon.getInstance().getElaIcon(icon, color)` | `color=None` 更狠：**access violation** |
| `addElaIconAction(None, text)` | 同上，不得传 `None` |

反例（**不是**枚举坑）：`QTextBlockFormat.setLineHeight(height, heightType)` 第 2 参要**裸 int**，传枚举成员反而要 `.value`。

守卫：`tests/regression/test_pyside6_migration_isms.py`（AST 扫「枚举方法收到 int 字面量」）。

### 1.2 Qt 回调里的 Python 异常 = 进程静默 abort

任何 Qt 回调（`eventFilter` / 信号槽 / `paintEvent`）里抛出的 Python 异常会穿过 C++ 边界导致
**0xC0000409（无 traceback，faulthandler 也没输出）**。三个连带结论：

1. **`try/except` 包住 `emit()` 毫无作用** —— 槽内未捕获异常直接 `abort()`，不会把异常传回调用方。唯一有效防线是**连接时把槽包起来**（库内 `selection_assistant._native.safe_connect`，`charts` 事件分发层自己 try/except）。
2. **类级 monkeypatch 拦不住 shiboken 方法**：`type(menu).exec = spy` 之后 `menu.exec(...)` 仍解析到 C++ 方法（要拦就拦自己的包装层 `_internal.execElaMenu`）。
3. `QTimer.singleShot(ms, callable)` 是**无主定时器**：不随任何控件销毁，回调里摸已释放的包装器 = 同样静默终止。用 `_internal.single_shot_on(ctx, ms, slot)`（定时器做成 `ctx` 的子对象）；**会反复重发**的两处（`table_view._retire_poll_timer`、`charts/core._schedule_lazy_option`）改用懒建的常驻子定时器 + `start()`。

**定位手法**（实测唯一可靠）：分段 `print(..., flush=True)` 逼近崩溃事件，并且**加 `-s`** 跑
（否则 pytest 的 stdout 捕获来不及刷出，会误以为探针没生效）。

守卫：`tests/regression/test_ownerless_timers.py`、`tests/regression/test_qt_callback_abort_guards.py`、`tests/example/test_markdown_page_timers.py`。

### 1.3 动画的 parent 不能是它自己动的那个对象

```python
QPropertyAnimation(target, b"geometry", target)   # ✗
```

目标销毁时 Qt 连带删掉仍在 Running 的动画，`finished` 收尾槽随后跑在一半销毁的对象图上 =
**0xC0000005**（无 traceback，常崩在 fixture teardown）。**改删除策略 / 加 `is_deleted` 守卫都挡不住**
（销毁由 parent-child 驱动）。`ela_avatar` 的 `shake_window` 配 `tests/ela_avatar/` 是确定性复现。

守卫：`tests/regression/test_animation_parenting.py`（AST 扫全库）。

### 1.4 析构期跨对象访问已释放的 C++ 对象

```python
# ✗ current_parent.layout() 那一层 C++ 对象可能已析构
current_parent = widget.parentWidget()
current_parent.layout().removeWidget(widget)

# ✓ 只碰自己持有的、验证过存活的引用；Qt 会自己把 widget 从旧布局摘出去
if widget is None or not shiboken6.isValid(widget):
    return
widget.setParent(self._stats_host)
```

`chat/bubble.py::_dock_step_stats_to_footer` 就是这么崩的（跑在析构信号链上）。
**跨对象取指针是析构期崩溃的头号来源**。

### 1.5 PySide6 生命周期四条（全库都踩过）

- **绑定到自身的 `destroyed` 槽不会被调用**：`self.destroyed.connect(self._cleanup)` = 清理从未发生。
  正确形状：`destroyed` 上挂**模块级函数**（`functools.partial(obj)`）+ 槽自身 `is_deleted()` 自愈兜底。
- **判存活一律 `_internal.is_deleted(x)`**：它把 `None` 也算已销毁 —— `shiboken6.isValid(None)` 返回 **True**，
  照抄 `not isValid(x)` 会放行 `None`。
- **`shiboken6.isValid(任意 Python 对象)` 也返回 True**：旧代码靠 `sip.isdeleted(object())` 抛 TypeError 兜住的
  「非控件输入」路径要显式 `isinstance` 判断。
- **`QObject.receivers()` 在 PySide6 不可用**（所有信号都拿不到数）：断言「没叠连接」改为**数真实回调次数**。

### 1.6 `QPainter(device)` 不接管所有权

传临时 `QPixmap(...)` / `QImage(...)` 会在构造完立刻被 GC，painter 随后握着悬空指针 = 0xC0000005。
测试里造 painter 必须把位图存成局部变量持有引用；`render(painter)` 抛错会让 painter 悬空 → 后续用例 abort。

### 1.7 QThread 未结束就析构

PyQt5 只打印告警，PySide6 直接崩，而且**崩点在下一个测试的事件循环里**，极难关联回元凶。
`QThread` 子类必须在析构前 `wait()`（测试里用 autouse fixture 统一收尾）。

---

## 2. Qt5 → Qt6 API 差异速查表

**前提：以绑定版本实测为准，不照抄 Qt 文档。** 两个反例（都是照文档改完又打回）：

| API | 照文档改的结果 | 实际 |
|---|---|---|
| `QTextBlockFormat.setLineHeight` | 改单参 → `expected 2 arguments` | PySide6 6.8 仍是 **2 参** |
| `QObject.receivers()` | 以为只是自定义信号不准 | **全部信号都不可用** |

| 差异点 | PyQt5 / Qt5 | PySide6 / Qt6 | 处理 |
|---|---|---|---|
| 枚举写法 | `Qt.AlignCenter` / `Qt.WA_*` / `Qt.Key_Space` | scoped：`Qt.AlignmentFlag.AlignCenter` … | 全部改 scoped（PySide6 仍留旧别名，不会报错） |
| `QAction` / `QShortcut` / `QActionGroup` | `QtWidgets` | **`QtGui`** | |
| `QOpenGLWidget` | `QtWidgets` | **`QtOpenGLWidgets`** | |
| `QWIDGETSIZE_MAX` | 有 | **不导出** | `_internal.WIDGET_SIZE_MAX = 16777215` |
| `QVariant` | 有 | **不存在** | `data()` 直接返回 Python 对象，取不到是 `None` |
| `QWheelEvent` 构造 | 8 参（含 `scrollType`） | `(pos, globalPos, pixelDelta, angleDelta, buttons, modifiers, phase, inverted)`，**`inverted` 无默认值** | 少一个参数 = access violation |
| `QWheelEvent.pos()` | 有 | 无 | `event.position()`（要点用 `.toPoint()`） |
| 滚轮事件的投递 | 发给滚动区即可 | 真实事件投给 **viewport** | `sendEvent(scroll_area)` 不进 `wheelEvent` |
| `QWheelEvent.isAccepted()` | 初值 `False` | **初值 `True`** | 里层不消费要显式 `ignore()` |
| `QEnterEvent` | `QEvent(Type.Enter)` | 需要 3 个坐标 | `QEnterEvent(p, p, p)` |
| `QPainter.drawPolyline` | varargs | **只接受单个 `QPolygonF`** | `drawPolyline(QPolygonF([...]))` |
| `QWidget.render(..., flags=)` | `flags` | `renderFlags=`；`render(painter)` 需要 `targetOffset` | |
| `QRect.adjusted(float)` | 抛 TypeError | **静默取整** | 半像素先转 `QRectF` |
| `QTextTableFormat().property(未设置)` | `""` | **`None`** | 断言 `not prop` |
| `Qt.BrushStyle.NoBrush` | `== 0` 为 True | 是 `enum.Flag`，`== 0` 为 **False** | 与枚举成员比较 |
| 上游枚举参数 | `int` 可用 | 只收枚举成员 | 见 §1.1 |
| `Signal.connect(slot, enum)` | 可用 | **`TypeError`**；两位置参是 `connect(上下文QObject, 槽)` | 带额外实参用 `lambda _checked=False, m=mode: …` |
| `QFont.Monospace` | 实例属性 | 已移除 | `QFont.StyleHint.Monospace` |
| `AA_EnableHighDpiScaling` / `AA_UseHighDpiPixmaps` | 有 | 无 | 删除 |
| matplotlib 后端 | `backend_qt5agg` | `backend_qtagg` | |
| `QtWinExtras`（任务栏进度） | 随 PyQt5 提供 | **不存在** | comtypes 调 `ITaskbarList3`（`taskbar_progress.py`） |
| `QAxContainer`（ActiveX） | 随 PyQt5 提供 | **不存在** | `office_viewer.py` 整块移除 |
| Win7 支持 | 有补丁 | **没有**（Qt 6.8 不支持） | `__init__.py` 的 Win7 DirectWrite 补丁已删 |
| 存活判断 / 同步销毁 | `sip.isdeleted` / `sip.delete` | `shiboken6.isValid` / `shiboken6.delete` | **`PySide6.Shiboken` 6.7+ 才有**，用 `import shiboken6` |
| `QAbstractNativeEventFilter.nativeEventFilter` | `message` 是 `sip.voidptr` | 是 **`int`** | |

### 2.1 `QEvent` 钩子签名差异（迁移期成片失败）

- `QEvent.Type.HoverEnter/Leave` 在 `event()` 里要判 `QEvent.Type.*`；
- 主题钩子 `_onThemeChanged` 是**协作式**（MRO 决定成败）：钩子 mixin 排在 `_ThemeAwareMixin` 之后会被空桩遮蔽 ——
  信号照收、槽照调、什么都不干、**零报错**。带钩子的 mixin 必须排在前面并 `super()._onThemeChanged(mode)` 下传；
- `connect_theme_signal` 有幂等守卫：子类 init 里**不能再传自定义槽名**（第二次调用被静默吞掉）。

---

## 3. 上游绑定（shiboken）层的差异

- **出参重载**：C++ 的 `QString&` 出参在绑定层被删掉、改由**返回值**给出 ——
  `addExpanderNode` / `addFooterNode` 返回 `(NodeResult, key)`；`addCategoryNode` 运行时要求 **≥2 参**。
  **`.pyi` 不可当契约**（pyi 与 .pyd 是两条生成管线，历史上不同步）。
- **注册失败一律返回非零、绝不抛异常**：验注册要**逐条断言 `NodeResult`**（否则节点建了但 key 空，页面全挂不上）。
- **kwargs 构造**：旧 sip 绑定「位置参数没填满 + `**kwargs`」会 access violation；
  本地构建的 shiboken 轮实测四种调用全可用（`WidgetFactory` 仍只在 kwargs 非空时透传，保守兼容官方轮）。
- **绑定生成器 bug**（本轮真凶）：定制注入代码用**旧命名索引**去索引**新数组**，越界读到垃圾 `PyTypeObject*` →
  `addExpanderNode` 100% 崩（`0xC0000005`）；重建绑定后修好。详见 `WHEEL_ISSUES.md` 第六节。

---

## 4. 测试体系怎么改（最容易被低估）

| 坑 | 症状 | 做法 |
|---|---|---|
| 断言绑定层实现细节 | `receivers()`、`QRect.adjusted(float)` 必须抛错……迁移后必然失效 | 改断言**可观测结果 / 意图色**（如数真实回调次数） |
| offscreen **不渲染文字** | `grab()` / `render()` 的像素比对拿不到文字 | 像素级断言先探测再 skip（`tests/_pixels.py::skip_if_no_pixels`）；要看真实渲染就跑示例应用 |
| 字体度量平台相关 | windows 候选行 43px、offscreen 36px | **不写死像素**，钉不变量（`height() == sizeHint().height()`、内边距预算） |
| `@pytest.mark.parametrize` 里构造 `QPixmap`/`QImage`/`QFont` | collection 期无 `QApplication` → **静默崩掉整个进程（零输出）** | 传工厂（`lambda: QPixmap()`）在测试体内调用 |
| 事件模拟 | `QTest` 在 offscreen 命中路由不可靠 | `QApplication.sendEvent(widget, QMouseEvent(...))` 直达目标控件 |
| 弹层残留 | `activePopupWidget()` 非空会吞掉后续用例的鼠标 / 滚轮 | 弹过 popup 必须 `hidePopup()` / `close()` + `processEvents()` |
| 阻塞式菜单（`QMenu.exec`） | CI 卡死（类级 monkeypatch 又拦不住） | 放一个**挂在被测控件上**的 `QTimer` 轮询 `activePopupWidget()` 并 `close()` |
| 剪贴板时序不确定 | 真实剪贴板的读回 / 序列号时序不定 → 偶发假红 | 改成**确定性剪贴板桩**；集群用例统一 `_qthelpers.wait_for_clipboard` |
| 控件销毁 | 手写 `deleteLater()` 常常漏 `processEvents()` | 一律 `make(...)` fixture（autouse `qt_cleanup` 逆序销毁 + 冲刷事件循环） |
| 跨测试污染 | 崩在测试 A 的事件循环，元凶是测试 B 留下的活线程 | 逐目录 / 文件**叠加二分**最小崩溃组合；崩溃类一律 `-X faulthandler` |
| 示例页逐页构造 | 同进程连建 20+ 顶层 `ElaThemeWidget` 撞 Qt 清理竞态（0xC0000409） | **一进程一页**；别把已知噪声当页面坏了 |
| 大消息量 / 视口 | 迁移期新增了合帧、挂起、批量渲染等开关 | 这些是**性能开关**不是业务接口，测试要按语义断言 |

---

## 5. 环境与依赖（和代码同样致命）

### 5.1 轮子核验：混版 = 随机崩

`PyElaWidgetTools/wheels/` 里曾放着「官方 6.8.3 Python 层 + 部分 6.8.4 DLL」的混版套件：
**`Qt6Svg` / `Qt6PrintSupport` / `Qt6WebSockets` 一构造就 0xC0000409**。判定法：
逐 DLL 比 `sha256` + `FileVersion`（**179 个 DLL 里 80 个不同，且全是 6.8.4**，而 `Qt6Svg` 还是 6.8.3 —— 「换装做了一半」）。

**同进程混装两个 patch 版本（尤其涉及 private ABI）= 随机崩溃**，别指望「补丁级二进制兼容」。

### 5.2 `uv` 的四个实测坑（本轮卡住命令的直接原因）

1. **环境变量优先级高于项目配置**：终端里的 `UV_DEFAULT_INDEX` / `UV_INDEX_URL` 会**顶掉**
   `pyproject.toml` 的 `[[tool.uv.index]]`；索引一变 uv 判定 lock 失效 → 重新解析。
   **清掉变量不影响已开终端**（进程环境是启动快照），必须新开终端 / 重启 IDE。
2. **uv 不读 `pip.ini`**（实测清空环境变量后直接回退 pypi.org）→ pip 配置文件里的镜像与 uv 无关。
3. **大轮子没有 PEP 658 metadata**：重新解析时 uv 要**下载整只 wheel body** 才能读 METADATA ——
   镜像站 `/packages/...` 一 403 整条命令就失败（实测 `PySide6_Addons` 的 macOS 轮、`quickjs-ng`）。
   对策：PySide6 四件套走**本地 path 源**（完全不碰网络），并用 `[tool.uv] environments` 把解析限死在
   win/AMD64（lock 里不再登记外平台轮子）。
4. **`tool.uv.sources` 只对「直接依赖」生效**：只写在 sources 里会被**静默忽略**（仍去镜像站解析）——
   所以 PySide6 子包要同时列进 `dependencies`。
   另：**path wheel 的哈希 uv 不会自己重算**（`--refresh-package` / `--no-cache` 都不行），
   重编译后要把 `uv.lock` 里的 `hash` 换成文件真实 sha256（或临时改约束触发重解析）。

### 5.3 Win7 交付套件（pyside6-win7）

`PyElaWidgetTools/wheels/pyside6-win7/` = 官方 Python 层 + **自编译 Qt 6.8.4**（132 个 Qt6 DLL 中 112 个自编译，
22 个 QML 专属保持官方），用于 Win7 SP1 离线安装。开发机可刻意用它（与交付运行时一致），
**运行期判别**：`PySide6.QtCore.qVersion()` 返回 **6.8.4**（官方 6.8.3 套件返回 6.8.3）。
切换 = 改 `[tool.uv.sources]` 路径 + `uv lock` + 刷新 sha256。

### 5.4 其他

- `requires-python >=3.11,<3.14`：3.14 没有 numpy 1.x 预编译轮子（`numpy<2` 会让 uv 退回 MinGW 源码编译）。
  **教训：加版本约束必须验证它在所有支持的 Python 版本上可满足**。
- 全量跑建议带 `pytest-timeout`（`--timeout=180 --timeout-method=thread`），否则残留弹层 / 阻塞菜单会卡死整个 run。
- 本库禁用 QSS：`tests/styles/test_qss_free_guard.py` 扫全库（含 `example/`、`llm_test/`）。

---

## 6. 把坑变成守卫（本次新增/沿用的清单）

| 坑 | 守卫 |
|---|---|
| 无主 `singleShot` | `tests/regression/test_ownerless_timers.py` |
| 动画 parent 是动画目标 | `tests/regression/test_animation_parenting.py` |
| 主题信号接线 / 钩子被空桩遮蔽 | `tests/regression/test_theme_signal_wiring.py`、`test_theme_aware_lifetime.py` |
| PyQt5 遗留调用形态（`connect(slot, arg)`、枚举收 int、`exec_`、`QVariant`…） | `tests/regression/test_pyside6_migration_isms.py` |
| 非有限值 / OverflowError 穿出 Qt 槽 | `tests/regression/test_overflow_error_guards.py`、`test_numeric_input_contracts.py` |
| Qt 回调里的异常防护（charts / chat / selection） | `tests/regression/test_qt_callback_abort_guards.py` |
| QSS 复辟 / 源码编码损坏 | `tests/styles/test_qss_free_guard.py`、`test_source_encoding.py` |
| 示例页无主定时器 / 代码围栏 / 文案规范 | `tests/example/test_markdown_page_timers.py`、`test_fenced_code_literals.py`、`test_plain_text_captions.py` |
| 文档与 API 漂移 | `tests/regression/test_docs_api_tables.py`、`tests/example/test_chat_guide_snapshot.py` |
| 轮子状态 | `WHEEL_ISSUES.md`（人读）+ `uv.lock` 哈希 |

**共性与经验**：能静态化的坑就写 **AST 守卫**（扫全库、按形状而不是行号）；不能静态化的（像素、时序、真窗口）
就**改断言语义**（意图色 / 回调次数 / 不变量），并把「怎么定位」写进注释或本文。

---

## 7. 如果重做一次（流程建议）

1. **先对齐版本与轮子**：PySide6 版本 ↔ 绑定轮编译所用 Qt 版本；逐 DLL 核验（`sha256` + `FileVersion`），
   不信任「同版本号」。
2. **探测脚本先行**：上游 API 的参数类型、事件构造签名、可用枚举成员、出参与 `.pyi` 是否一致 —— 实测成表，别边改边撞。
3. **先跑一次全量看失败分布**，按**根因聚类**修（`Get-Content out.txt | Select-String '^E ' | Group-Object ...`），
   不要按文件逐个修。
4. **崩溃类问题用 faulthandler + 分段 `print(..., flush=True)`（`-s`）**，别用测试断言去「修」崩溃。
5. **先重写「断言实现细节」的测试**为断言意图，再动实现；否则你分不清失败是迁移引入的，还是断言本身过时。
6. 每修一类坑就**沉淀一条守卫 + 一条 AGENTS 规则**（本次迁移共沉淀 4 个 AST 守卫：无主定时器 / 动画 parent / 主题接线 / PyQt5 遗留调用形态，外加数十条条目）。
7. 收尾：全量（0 failed）→ **真窗口冒烟**（示例应用逐页，离屏不算）→ 提交里带上环境/轮子说明。

### 迁移清单（可直接照用）

- [ ] 包名 / 项目名重命名，`requires-python` 钉死，删除 PyQt5 兼容层
- [ ] `sip.*` → `shiboken6.*`；`pyqtSignal/Slot/Property` → `Signal/Slot/Property`
- [ ] 枚举全部 scoped 化；上游枚举参数一律传枚举成员（含示例页）
- [ ] 事件构造函数按**绑定签名**逐一核对（`QWheelEvent` / `QEnterEvent`）
- [ ] `QAction` / `QShortcut` / `QOpenGLWidget` 等迁移模块
- [ ] 生命周期：`destroyed` 模块级槽、`is_deleted(None)`、`QThread.wait()`、动画 parent、`single_shot_on`
- [ ] 测试：`make` fixture、offscreen 断言口径、参数化里不造 `QPixmap`、弹层 / 菜单收尾
- [ ] 环境：轮子核验、uv 源与索引、path wheel 哈希刷新、全量 + 真窗口冒烟
- [ ] 文档：README / docs / AGENTS.md 同步（有守卫就接上）

---

## 8. 本次迁移的提交

| 提交 | 内容 |
|---|---|
| `048c520` | 全库迁移到 PySide6 6.8.3，包重命名为 `pyside6_ela_pro`（372 文件，含 `WHEEL_ISSUES.md`） |
| `ad728ba` | 刷新绑定轮哈希；修示例页两处 PySide6 不兼容调用（`setDisplayMode(0)`、`connect(slot, arg)`）+ 新增 AST 守卫 |
| `f1b172c` | PySide6 四件套改本地 path 源 + 解析限死 win/AMD64（uv 索引陷阱的落地） |
| `7941d28` | 开发机切换到 pyside6-win7 套件（与 Win7 交付运行时一致）+ 全量结果记录 |
| `8a5fc0e` / `9b40dfc` | 下拉按钮族透明底 / 去边框（迁移后按同一套状态层口径收敛的组件级修复） |

---

## 九、启动与交互性能（Win11 主机 + Win7 目标机，2026-10-13）

### 9.1 归因：把「绑定」与「Qt 版本」分开

用 PyQt6（sip + Qt6）当对照组，同机逐项测（每项操作独立进程、3 次中位）：

| 栈 | Qt | 绑定 | `QWidget()` | `QLabel('x')` | `QColor().red()` |
|---|---|---|---|---|---|
| PyQt5 | 5.15.2 | sip | 0.8 µs | 2.0 µs | 0.4 µs |
| PyQt6 | **6.8.2** | sip | **1.2 µs** | 2.5 µs | 0.4 µs |
| PySide6 | **6.8.4** | shiboken | **6.6 µs** | 9.3 µs | 0.4 µs |

- **绑定税（shiboken 对象包装）**：每个 Python 侧创建的 QObject **+~5µs**（`QObject()` 6.5–9×、`QLabel` 3.7–5×）；而纯 C++ 侧开销与 sip 相同（`QListWidget.addItem` 1.0×、值类型 0.9–1.0×），`Signal.connect` 反而快 2×。机制：shiboken 每次创建要建 `SbkObject` + 全局哈希表注册（C++→Python 反查）+ 类型发现 + 所有权记账（`Shiboken::Object::setParent`），每次调用要重载决策 + 参数转换（`pythonToCppConversion`，连 `int` 都现建转换器）+ 过一遍 `shibokensupport/feature.py`。生成代码见 `PyElaWidgetTools/scripts/pyside6/OUTPUTDIR/**/*_wrapper.cpp`。**目标机（Win7 VM）上同一口径放大到 10–15×**（这条路是 CPU 密集的 C++ 工作，慢机放大；sip 侧只有 0.7µs，几乎不放大）。
- **Qt 6.8 内核税**：同 sip 对照下 `QWidget()` 1.5×、`QLabel` 1.25×、**`QFontMetrics.horizontalAdvance` 1.6×**（字体度量是唯一实打实的 Qt6 回归；目标机同样 1.6×）。Qt 6.11 这两项已被改善（`QWidget()` ≈1.0µs）。
- **应用重绘量**：动画每帧 / 主题切换 / 图标页首帧随「可见控件数」线性放大，与绑定只弱相关（`grab()` 1.4×）。

### 9.2 四个热点（实测）

| 交互 | 修复前 | 修复后 | 机制 |
|---|---|---|---|
| 启动 | 1943 ms（构造 63%） | **510 ms** | 24 页 eager 构造；另有一次性 `QFont().defaultFamily()` 190 ms |
| 侧边栏收缩/展开 | 单帧 8.6 ms | **0.0 ms**（15 帧 137→43ms） | 上游 4 条并发 255 ms 动画 → 每帧 resize 中央页 → 整页 invalidated → 上百子控件重绘 |
| 主题切换 | ~270 ms（70–78 次重绘） | 同量级（主体不可省） | ≈200 ms 是 Ela/C++ 对可见控件的全量重绘；Python 侧 markdown 重建只 ~17 ms |
| 图标展示页 | 首帧 22 ms（稳态 4 ms/帧、滚动 p50 0.02 ms） | 待摊进后台预热 | 首次渲染（视图首布局扫模型），不是逐帧成本 |

### 9.3 已落地的修法

1. 示例页内容**惰性构建** + 启动后**后台逐页预热**（`ExamplePage.buildDemoContent()` / `__main__` 挂在窗口上的单发 `QTimer` 链）→ 启动 1943 → 510 ms。
2. 一次性字体解析**趁 splash 付掉**；页面代码里禁用 `QFont().defaultFamily()`（要默认字体族用 `QApplication.font().family()`，0.01 ms）。
3. 连续 resize（侧边栏动画 / 拖窗口边框）期间**把页面钉在旧尺寸** + 120 ms 防抖恢复 → 单帧 8.6 → 0.0 ms（只冻结布局或冻结重绘都不行：前者无效果，后者页面空白 255 ms）。
4. 守卫适配：`tests/example/conftest.py` 的 `make` 自动补 `buildDemoContent()`；不 `show()` 的守卫显式调用。
5. **带原生子窗口的页在 `show()` 之前建**：`BlueprintPage` 的 GL 视口（`QOpenGLWidget`）挂到**已显示**的顶层窗口上时，Windows/Qt 会重建顶层 HWND（类名 `QWindowIcon` → `QWindowOwnDCIcon`），表现为主窗口「闪一次」（实测在后台预热 T+1.8s）。页面用 `PRE_SHOW_BUILD = True` 声明，`__main__` 在 `window.show()` 前构建它们。

### 9.4 明确**不**做

- **不重编 Qt**：自编译 Win7 套件与官方 6.8.3 逐段 ±1%、同 MSVC；pyside6-win7 与官方轮在 Win11 同速。
- **不为省 ~5µs/对象换绑定栈**：PyQt6 需要第三套 sip 绑定生成器 + 库再迁移一次，而且拿不回重绘类（动画 / 主题 / 图标首帧与绑定弱相关）；PyQt5 会丢掉整个 Qt6 生态。
- 样式（Fusion）/ DWM / 无障碍开关对 Qt6 控件构造没有影响（目标机实测个位数百分比）。

### 9.5 复现工具（`E:\python_project\elawidgettools-perf\`，仓库外）

| 脚本 | 用途 |
|---|---|
| `bench_example.py` | 启动阶段 + 逐页构造 / 首渲染 |
| `bench_lazy.py` | 惰性内容版启动 + 首访成本 |
| `bench_anim.py` | 侧边栏收缩/展开：时长 / 重绘数 / p50·p95 帧间隔（`ELA_FORCE_BINDING` 可强制绑定） |
| `bench_theme_icons.py` | 主题切换 + 图标视图首帧 / 滚动 |
| `bench_reflow.py` / `bench_page_reflow.py` | 单页一次重排（= 动画单帧）成本 |
| `bench_paint_cost.py` | 可见页控件构成 × 各类绘制成本 |
| `bench_micro.py` / `probe_win7_kernel.py` | 底层原语（对象创建 / 虚调用 / 参数转换）与目标机开关探针 |
| `_bench_shim/sitecustomize.py` | 一个 venv 里两套绑定时，用 `ELA_FORCE_BINDING=pyqt5` 强制切换 |
