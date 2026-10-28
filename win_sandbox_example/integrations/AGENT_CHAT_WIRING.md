# 把 win_sandbox 接进 agent_chat（按行号的清单）

以 `E:\python_project\agent_chat` 为参照；你的项目把 `app.*` 换成自己的包名即可。

## 1. 新增 `app/sandbox_runtime.py`

把 sandbox 做成进程级单例，`agent` 创建前就完成注册：

```python
from integrations.agent_chat_example import (
    DEFAULT_SANDBOX_WORKSPACE,
    install_for_agent_chat,
)

SANDBOX_WORKSPACE = DEFAULT_SANDBOX_WORKSPACE   # runtime/agent_workspace
sandbox, enabled = install_for_agent_chat(SANDBOX_WORKSPACE)
```

`enabled` = `get_registered_tools("build")`，包含沙箱版 4 个工具。

## 2. `app/start_main.py`

在 `create_async_agent` 之前 import 单例（`chat.py` 也会 import，但显式一层更清楚）：

```python
import atexit
from app.sandbox_runtime import sandbox
atexit.register(sandbox.close)
```

- 第 41 行 `create_async_agent(enabled_tools=get_registered_tools("plan"))` **不用改**：
  `AgentChat.__init__` 第 60 行 `apply_mode(self.agent, "plan")` 会立刻把工具集换成 plan。
- 用户切到 build 时，`_toggle_mode` 会调 `get_registered_tools("build")`，
  这时才包含沙箱版 `shell`。
- 如果你希望默认就是 build（编码 agent），把第 60 行的 `"plan"` 改成 `"build"`，
  第 42 行改成 `enabled_tools=enabled`。

## 3. `app/components/chat.py`

### 3.1 import

```python
from app.sandbox_runtime import SANDBOX_WORKSPACE, sandbox
```

### 3.2 所有「取消流」的点都要加 `cancel_foreground()`

`self._cancel_event.set()` 只让 `async for` 跳出，**不会中断 `to_thread` 里的命令**。
加一个 helper：

```python
def _cancel_stream(self):
    self._cancel_event.set()
    sandbox.cancel_foreground()
```

替换这几处：

| 函数 | 行（参考） | 原代码 |
|---|---|---|
| `_toggle_mode` | 65 | `self._cancel_event.set()` |
| `_clear_chat` | 271 | `self._cancel_event.set()` + `clear()` |
| `_stop_chat` | 285 | `self._cancel_event.set()` |
| `_switch_session_guard` | 484 | `self._cancel_event.set()` |
| `_undo_message` | 644 | `self._cancel_event.set()` |

`_clear_chat` 变成：

```python
self._cancel_stream()
self._cancel_event.clear()
```

### 3.3 话题目录挪进沙箱工作区

`_new_topic_workdir`（第 490-495 行）：

```python
d = SANDBOX_WORKSPACE / ".topics" / session_id
```

`_start_chat` 第 153 行 fallback：

```python
topic_wd_path = SANDBOX_WORKSPACE
```

`_open_work_dir` 第 78-79 行 fallback：

```python
or str(SANDBOX_WORKSPACE)
```

`_del_topic` 第 600 行：

```python
if wd.parent == SANDBOX_WORKSPACE / ".topics":
```

`_start_chat` 第 182 行 `set_work_dir(topic_wd_path)` **不用改**：
`install(..., get_work_dir=get_work_dir)` 会让 `shell` / `write_file` 的相对路径
跟随当前话题目录，同时仍要求落在 `SANDBOX_WORKSPACE` 内。

### 3.4 文件 / 读类工具

`install_for_agent_chat()` 已经传了 `file_tools`、`grep_tool` 和
`get_work_dir`，会自动覆盖：

| 工具 | 收口方式 |
|---|---|
| `read_file` / `write_file` / `edit_file` | 同名覆盖：先 `box.resolve` 再调用原函数 |
| `glob_file` | 重写：只接受相对 pattern，`..` / 绝对路径直接拒绝 |
| `read_image` | 包装原函数，先把路径 `box.resolve` 再读 |
| `grep_file` | 包装原函数，把搜索目录 `box.resolve` 后交给 `rg` |

相对路径都跟随当前话题目录（`get_work_dir`），但最终必须落在
`SANDBOX_WORKSPACE` 内。`grep_file` / `read_file` / `write_file` 的外部路径
会抛 `PolicyDenied`（带可解释消息），`glob_file` 的绝对 pattern 返回错误字符串。

`grep_file` 的返回仍是 `rg` 的绝对路径；模型把它交给 `read_file` 时，
`box.resolve` 会再校验一次。

## 4. 审计 / 审批 / 服务

在 `sandbox_runtime.py` 里把 audit / approval 一起传进去：

```python
from pathlib import Path
from integrations.agent_chat_example import DEFAULT_SANDBOX_WORKSPACE, install_for_agent_chat
from win_sandbox import ApprovalMode, JsonlAudit, SandboxPolicy

audit = JsonlAudit(Path("runtime") / "audit.jsonl")
sandbox, enabled = install_for_agent_chat(
    DEFAULT_SANDBOX_WORKSPACE,
    audit=audit,
    approval=my_approval_handler,     # Dash 用 modal；Qt 用 qt_approval.py
    policy=SandboxPolicy(approval_mode=ApprovalMode.ASK),
)
```

- **审计**：`read_file` / `write_file` / `edit_file` / `glob_file` /
  `read_image` / `grep_file` 每次调用都会发 `tool_start` / `tool_end`；
  `shell` / `background_run` 发 `run` / `start`；越界发 `deny`；
  审批发 `approval`。审计文件必须在工作区**外**，构造 `Sandbox` 时会检查。
- **拒绝理由**：模型看到的是
  `[denied] write_file: C:\... (outside the sandbox workspace)` + 建议，
  不是裸 `ValueError`。
- **audit 模式**：`SandboxPolicy(guard_mode=GuardMode.AUDIT)` 先只记录不拦，
  看一周日志再切 `ENFORCE`。
- **审批**：默认只放行本次，不记住目录；每分钟最多 5 次
  （`approval_rate_limit`）。
- **后台服务**：`background_run(wait=False)` 起服务后，宿主调
  `sandbox.expose(task.id, port, "web")` 拿 `http://127.0.0.1:port/`；
  任务取消 / 结束 URL 自动失效。

## 5. 导入 / 模板 / 身份

- **导入项目**：`import_tree(src, sandbox.workspace)` 会按 `.gitignore` 过滤，
  并默认跳过 `.env` / `*.pem` / `id_rsa` 等凭据文件（清单在
  `ImportResult.blocked`）。
- **模板**：`create_sandbox("runtime", "python")` / `"node"` / `"ephemeral"`；
  `ephemeral` 在 `close()` 时删除工作区。
- **可执行文件身份**：`prepare()` 记录 shell 的 SHA256 到
  `%LOCALAPPDATA%\WinSandbox\shell_identity.json`；默认每条命令前重新校验，
  变化时审计 `high`；`SandboxPolicy(strict_binary=True)` 变化 / 读取失败都拒绝。
- **输出上限**：前台命令超过 200KB 只读尾部；后台任务超过 50MB 自动取消
  （`max_task_output_bytes`）。
- **conformance**：目标机上跑
  `python conformance.py --json report.json`，把结果贴回来。

## 6. 已有话题的迁移

旧话题的 `work_dir` 存在 `<AgentsConfig.work_dir>/.topics/<id>`，新目录是
`<SANDBOX_WORKSPACE>/.topics/<id>`。升级后旧话题的相对路径会落在沙箱外，
`box.resolve()` 会拒绝。两种处理：

1. **简单**：清空旧话题的 `work_dir`（或删掉旧话题），让它们回落到
   `SANDBOX_WORKSPACE`。
2. **保留文件**：把旧 `.topics/<id>` 整个目录移动到新 base，再更新
   `chat_session.work_dir` 字段。

新装环境不受影响。

## 7. 验收清单

```powershell
# 1) 能力探测 / 一致性验收
python -m win_sandbox.probe
python conformance.py --json report.json

# 2) 启动 app，切到 build 模式，让 agent：
#    - 在当前目录建 a.txt          -> 出现在 runtime/agent_workspace/.topics/<id>/
#    - 写 C:\Users\<你>\test.txt   -> 弹出审批框；拒绝则失败，允许则写入
#    - 跑 ping -n 60 127.0.0.1     -> 点停止后 1 秒内进程消失
#    - 起一个 python -m http.server 8000（background_run wait=False）
#        点停止 -> 服务仍在；关窗口 -> 服务消失
#    - 查 runtime/audit.jsonl      -> 能看到 tool_start / tool_end / deny / approval
```
