# 划词助手（Windows 全局）

- **ElaSelectionAssistant** — 全局划词助手（`selection_assistant/`，纯 ctypes
  无 pywin32 依赖，Win7+）：`ElaMouseMonitor` 采用**轮询式**全局鼠标监视
  （`GetAsyncKeyState` + `GetCursorPos`，主线程 QTimer 默认 15ms，**不使用
  `WH_MOUSE_LL` 全局钩子**——钩子回调阻塞会拖死整机鼠标输入）；拖选松开 /
  双击选词后模拟 `Ctrl+C` 读取选中文本（**不预先改动剪贴板**，成功后按需
  恢复原文本），在落点附近弹出动作条；信号 `selectionCaptured(text, pos)` /
  `actionTriggered(actionId, text, pos)` / `popupShown` / `popupHidden` /
  `enabledChanged` / `captureBlocked` / `errorOccurred`；**动作条菜单项完全由宿主定义**
  （`setActions` 传 `ElaMenuItem` 列表，可启用 / 禁用 / 排序，
  组件不内置任何动作，未定义时只发 `selectionCaptured` 不弹窗）、
  `setMinSelectionLength`、`setDragThreshold`、`setDoubleClickMs`；
  `setCaptureFilter(predicate(down, up))` 在注入 `Ctrl+C` 前给宿主一个闸门
  （过滤器异常按拦截处理）；外观（紧凑模式 / 偏移）走 `popup()`，
  取词参数（剪贴板恢复 / 各类延迟）走 `capture()`；
  `setEnabled(True)` 启动监视，失败发 `errorOccurred` 并保持禁用

  > **取词闸门（默认行为）**：拖选与「拖窗口 / 拖滚动条 / 拖文件」在鼠标
  > 层面无法区分，而取词要**向前台窗口注入 `Ctrl+C`** —— 在终端 / 控制台里
  > 注入的 `Ctrl+C` 就是**中断信号**（实测：终端里拖一下 scrollbar 会把正在
  > 跑的命令 SIGINT 掉）。因此未设 `setCaptureFilter` 时**拖选默认不取词**
  > （双击选词仍可用），被拦时发 `captureBlocked(reason)`。要开拖选取词用内置
  > 启发式过滤器 `setCaptureFilter(ElaSelectionAssistant.builtinDragFilter())`
  > （跨窗口 / 按在窗口边框 / 超长拖拽一律拒掉），或
  > `setRequireFilterForDrag(False)` 彻底放开（不建议）。
- **ElaSelectionPopup** — 动作条浮窗（`Tool | 无边框 | 置顶 | 不接受焦点`，
  `WA_ShowWithoutActivating` 不抢源应用焦点）：`popupAt(pos)` 以落点为锚、
  越界自动翻转并收敛到屏幕工作区；点击动作后自动隐藏并发出
  `actionTriggered(actionId)`；按钮悬停提示走库内 `ElaToolTip` 并显示在
  动作条**下方**（不遮挡上方选中文字，也不使用原生 `QToolTip`）；可独立复用
- **ElaSelectionResultDialog** — 结果对话框（点「翻译 / 解释 / 总结」这类要跑
  模型的动作后弹出，实时显示流式 Markdown；参照 Cherry Studio 的 selection action
  window）。基类是上游 **`ElaWidget`** 而非自绘 `QWidget`：ElaWidget 自带 ElaAppBar
  （图标 + 标题 + 窗口按钮）、窗口阴影（`QEvent::Show` 时补
  `WS_THICKFRAME`，Win7 另加 `CS_DROPSHADOW`）、拖动、边缘缩放、Mica 背景与主题
  适配，所以本组件零 QSS、零 `paintEvent` 自绘、零阴影边距常量；窗口按钮只留
  「置顶 + 关闭」（`StayTopButtonHint` 上游画的是图钉，就是这种面板该有的 pin）。
  **抢焦点**（与 Cherry 的 action window 一致，Esc / Ctrl+C 与按钮点击都需要它），
  代价是源应用选区高亮消失 —— 所以正文上方常驻一行划词原文预览。
  `openFor(actionId, title, selectedText, anchor, icon)` 定位并弹出（水平居中于
  落点、下方放不下翻上方、夹回工作区；**`anchor=None` 表示复用当前位置** ——
  「重新生成」是同一次划词的重跑，重跑该直接调 `beginStream()`，别走
  `openFor`，否则窗子会被抽回划词落点）；**只管显示不碰网络**，内容由宿主用
  `beginStream()` / `appendMarkdown(chunk, turn)` / `endStream(turn)` 推进
  （`turn` 是 turn token，被中止回合的迟到分片会被丢弃），另有 `setResult()` /
  `setError()`；信号 `finished` / `closed` / **`stopRequested`** /
  `regenerateRequested` / `copied` / `plainCopied`。取消走 `stopRequested` —— **宿主必须在那里
  abort 自己的后端**（Cherry Studio 缺这一步：停止按钮点了不真停，只靠 renderer
  进程死亡顺带杀掉 fetch）；关窗 / 停止 / 流式中 Esc 三条路径都发它，且被中止的
  半句话**不算结果**（`finished` 不发、复制保持禁用）。Esc 分流：流式中=停止、
  空闲=关闭；**`Ctrl+C` 复制纯文本**（渲染后文本，去掉 Markdown 标记 —— 默认行为），
  原始 Markdown 源走「复制 Markdown」按钮 / `Ctrl+Shift+C`。划词原文预览单行按宽度省略，一次划几百万字也不卡
  （省略只在前 400 字上算：实测全文 64 万字 `elidedText` 要 153ms/次，截断后
  0.086ms/次），要原文取 `selectedText()`；悬浮提示折行有界（最长 400 字、
  宽 480px），不会拉成横贯屏幕的单行条
- **ElaMouseMonitor / ElaClipboardCapture** — 监视与取词后端（可注入假实现，
  测试无需真实输入）；`ElaMouseMonitor` 尊重系统主 / 次键互换
  （`SM_SWAPBUTTON`）；`ElaClipboardCapture` 通过「基准文本 + 轮询变化」
  取词，失败时剪贴板从未被改动；恢复剪贴板有**三道校验**，任一不过就跳过并
  发 `restoreSkipped`（原因见 `lastRestoreSkipReason()`，取值 `user-copied` /
  `clipboard-changed` / `non-text-baseline`）：文本与注入那份不同、**剪贴板序列号
  变了**（哪怕文本相同 —— 用户又复制了一遍同样的内容，原实现只看文本会把用户
  这次复制覆盖回旧值）、基准剪贴板含图片 / 文件 / HTML 等**无法还原**的内容
  （此时宁可留着注入进来的文本，也绝不 `clear()` 掉用户复制的东西）；
  `send_copy()` 另有**注入侧两道闸门**：修饰键（Shift / Ctrl / Alt）按下不注入
  （否则发出去的是 `Ctrl+Shift+C` 之类）、距上次注入不足 200ms 不连发
  （`force=True` 可跳过）；包内另导出 `foreground_pid()` / `window_pid_at()` /
  `window_rect_at()` 查询（供 `setCaptureFilter` 与内置过滤器使用）
- **不拦截键盘**：划词助手**不安装任何键盘钩子**（无 `SetWindowsHookEx`，
  键盘状态只用 `GetAsyncKeyState` 只读），不会吞掉或改写用户自己按下 / 松开的
  `Ctrl+C` / `Ctrl+V`；动作条浮窗也不接受焦点（`WA_ShowWithoutActivating`），
  弹窗出现后按键仍发给源应用

```python
from PyQt6.QtWidgets import QApplication
from PyQt6ElaWidgetTools import ElaIconType
from pyqt6_ela_pro import ElaMenuItem, ElaSelectionAssistant

assistant = ElaSelectionAssistant(parent)
assistant.setActions([                              # 菜单项由宿主定义
    ElaMenuItem("copy", "复制", ElaIconType.IconName.Copy),
    ElaMenuItem("search", "搜索", ElaIconType.IconName.MagnifyingGlass),
])
assistant.actionTriggered.connect(on_action)        # (actionId, text, pos)

def on_action(actionId, text, pos):
    if actionId == "copy":
        QApplication.clipboard().setText(text)      # 行为全由宿主实现

# 拖选取词要向前台注入 Ctrl+C（终端里等于 SIGINT），默认闸门不放行：
# 挂上内置启发式过滤器，把跨窗口 / 窗口边框 / 超长拖拽挡掉
assistant.setCaptureFilter(ElaSelectionAssistant.builtinDragFilter())
assistant.setEnabled(True)
```

> 限制：终端 / 受保护程序可能取不到词；若选中文本与剪贴板原内容完全相同
> **且剪贴板序列号不可用**，无法与「未复制」区分；剪贴板恢复**只还原文本** ——
> 基准剪贴板含图片 / 文件等非文本内容时会跳过恢复而不是还原（原因见
> `capture().lastRestoreSkipReason()`），可由宿主在 `restoreSkipped` 后自行
> 补回原内容；轮询式监视（默认 15ms）可能漏检极快点击，且无法检测滚轮
> （动作条改由下一次点击 / 新划词隐藏）；启用后鼠标拖拽在**通过闸门**时才会
> 向前台应用注入一次 `Ctrl+C`（在资源管理器里会把当前选中文件复制进剪贴板，
> 所以务必配过滤器）；注入前若用户正按着 `Shift` / `Ctrl` / `Alt`，本次注入
> 会被跳过（发出 `captureBlocked`），连续划词在 200ms 内也只注入一次。

要跑模型的动作接结果对话框（`copy` / `search` 这类不走对话框）：

```python
from pyqt6_ela_pro import ElaSelectionResultDialog

dialog = ElaSelectionResultDialog()
dialog.stopRequested.connect(backend.abort)             # ★ 必须接：关窗即中止
dialog.regenerateRequested.connect(lambda aid: run(aid))

def on_action(actionId, text, pos):
    if actionId == "translate":
        dialog.openFor(actionId, "翻译", text, pos)    # 定位并弹出
        turn = dialog.beginStream()                    # 开始流式回合
        for chunk in backend.stream():                 # 宿主自己的网络
            dialog.appendMarkdown(chunk, turn)         # 传 turn 挡掉迟到分片
        dialog.endStream(turn)
```


---

**可运行示例**：`example/selection_page.py`（事件日志 / 宿主动作实现）。
