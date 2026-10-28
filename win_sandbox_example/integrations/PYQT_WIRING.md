# 把 win_sandbox 接进 PyQt6 + pyqt6-ela-pro

`AGENT_CHAT_WIRING.md` 只讲「工具层」怎么接（`@ToolManager.register` 那套），
和 UI 框架无关。你的界面是 PyQt6，这里只讲界面接线；工具层仍然可以复用
`integrations/toolmanager.py`。

## 1. 创建顺序

```python
app = QApplication(["your-agent"])
eApp.init()

# ① 审批框（必须在 GUI 线程创建；窗口可以稍后才有）
approval = QtApprovalHandler(lambda: window)

# ② 沙箱 + 工具（必须早于 agent / worker 创建）
sandbox, enabled = install_for_agent_chat(
    Path.cwd() / "runtime" / "agent_workspace",
    audit=JsonlAudit(Path.cwd() / "runtime" / "audit.jsonl"),
    approval=approval,
    policy=SandboxPolicy(approval_mode=ApprovalMode.ASK),
)

# ③ agent / worker（enabled 传给 create_async_agent）
window = MainWindow(enabled_tools=enabled)
window.show()

app.aboutToQuit.connect(sandbox.close)
```

如果 `MainWindow.__init__` 里就 `worker.start()`，把 ② 放到 `window = ...`
**之前**，`QtApprovalHandler(lambda: window)` 的 lambda 会延迟到弹框时才取窗口。

## 2. 停止 / 关闭

```python
chat.stopRequested.connect(on_stop)

def on_stop():
    sandbox.cancel_foreground()   # 先杀沙箱里的进程树
    binder.cancel()               # 再收消息状态
    worker.cancel()               # 最后取消流式任务

app.aboutToQuit.connect(sandbox.close)
```

顺序很重要：`worker.cancel()` 只置标记，不会中断 `asyncio.to_thread` 里的命令；
不先 `cancel_foreground()`，`ping -n 60` 会继续跑到超时。

## 3. 审批框

```python
from qt_approval import QtApprovalHandler

approval = QtApprovalHandler(window)          # 或 lambda: window
```

- 工具线程调用 `approval(request)` 时，`BlockingQueuedConnection` 把请求投到
  GUI 线程，弹 `ElaConfirmDialog.show(parent, "沙箱权限申请", content, "top")`。
- 用户点确认 → **只放行本次**；点取消 → 抛 `PolicyDenied`，模型看到
  `[denied] ... (user denied access)` 和建议。
- 默认每分钟最多 5 次审批（`approval_rate_limit`），防止模型刷屏。
  如果随项目带 `git-for-windows`，在 `install_for_agent_chat(..., prefer_bundled=True)`。

## 4. 工作区 / 话题

- **专用工作区**：`runtime/agent_workspace`；`install_for_agent_chat()` 会
  `prepare()`（建目录 + 打 Low 标签）。
- **每话题子目录**：`workspace/.topics/<session_id>`；
  `agents.set_work_dir(topic_dir)` 后：
  - `shell` / `background_run` 不传 `workdir` 时默认用当前话题目录；
  - `read_file` / `write_file` / `edit_file` 的相对路径也跟随话题目录；
  - 最终都过 `box.resolve()`，必须落在工作区内。
- **旧话题在外部**：`_current_workdir()` 会退回工作区根，不弹审批（那是宿主
  配置问题，不应该问用户）。

## 5. 后台任务 / 服务

```python
task = sandbox.start("python -m http.server 8000 --bind 127.0.0.1")
self._task_id = task.id
self._poll.start()          # QTimer 500ms

def _poll_task(self):
    info = sandbox.check(self._task_id)
    self._status.setText(info.splitlines()[0])
    if "running" not in info:
        self._poll.stop()
        self._task_id = None

service = sandbox.expose(task.id, 8000, "web")
QDesktopServices.openUrl(QUrl(service.url))
```

- 停止按钮只杀前台命令；后台服务继续跑。
- 关窗口 `sandbox.close()` 才杀后台任务。
- 任务取消 / 结束后 `services()` 自动剔除对应 URL。

## 6. 审计

```python
audit = JsonlAudit(Path.cwd() / "runtime" / "audit.jsonl")
```

放在工作区**外**：`ephemeral` 模板会在 `close()` 时删除工作区。

事件：`prepare` / `run` / `start` / `cancel` / `deny` / `approval` /
`tool_start` / `tool_end` / `service_expose` / `binary_identity` / `close`。
命令只记 `command_preview` + `command_sha256`。

## 7. 和你现有的 `ElaChatWidget` 接线

和 `llm_test/README.md` 的「宿主接入四步」完全一样，只多三处：

```python
chat = ElaChatWidget(parent)
worker = MyAgentWorker()
binder = ElaChatStreamBinder(chat, worker=worker)
binder.shutdownOnClose(window)

chat.messageSubmitted.connect(on_ask)
chat.stopRequested.connect(on_stop)      # ← on_stop 第一行 cancel_foreground

def on_stop():
    sandbox.cancel_foreground()
    binder.cancel()
    worker.cancel()

app.aboutToQuit.connect(sandbox.close)   # ← 多这一行
```

另外：

- 启动前 `install_for_agent_chat(..., approval=QtApprovalHandler(window))`；
- `create_async_agent(enabled_tools=enabled)` 用返回的 build 工具集；
- 文件工具不需要额外处理，适配器已经同名覆盖。

## 8. 验收

```powershell
python pyqt_demo.py --smoke        # 构造 + 0.8s 退出
python conformance.py              # 9 项一致性验收
python -m win_sandbox.probe        # 4 项能力探测

# 手工：
# - 前台跑 ping -n 60 127.0.0.1，点停止 → 1 秒内进程消失
# - 后台跑 python -m http.server 8000，点停止 → 服务仍在
# - 关窗口 → 服务消失
# - 「测试越界写」→ ElaConfirmDialog；拒绝后模型拿到 [denied] 消息
```
