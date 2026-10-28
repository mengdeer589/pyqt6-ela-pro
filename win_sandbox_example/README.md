# win_sandbox_example — Win7 免管理员 agent 沙箱

OpenShell 在 Windows 上要求 WSL2 + Docker，而 Win7 交付线两者都没有。这个示例用
Win7 自带的用户态机制做它的最小子集：

| 机制 | 挡住什么 | 需要管理员 |
|---|---|---|
| Job Object（`KILL_ON_JOB_CLOSE` + 资源 / UI 限制） | 进程泄漏、弹窗、改系统设置 | 否 |
| 子进程令牌降到 Low Integrity | 写用户目录 / 注册表 / Program Files | 否 |
| 工作区目录打 Low 标签（`icacls`） | 让 Low 子进程只在这个目录里可写 | 否 |

**定位是「防误操作」，不是对抗性沙箱。** 不做网络强制（防火墙 / WFP 都要管理员），
不做读隔离（低完整性只拦写），不防刻意逃逸（Win7 没有 AppContainer）。

## 目录

```
win_sandbox_example/
├─ win_sandbox/            # 核：零 agent 依赖（stdlib + ctypes）
│  ├─ proc.py              # CreateProcess + 低完整性 + Job
│  ├─ shells.py            # bash / cmd 探测
│  ├─ sandbox.py           # Sandbox 门面 + SandboxTask + 服务 / 审批 / 审计
│  ├─ audit.py             # JSONL 审计事件
│  ├─ approval.py          # 能力申请 / 审批数据结构
│  ├─ errors.py            # PolicyDenied（可解释拒绝）
│  ├─ identity.py          # shell 可执行文件 SHA256 baseline
│  ├─ import_workspace.py  # 导入目录（尊重 .gitignore）
│  ├─ services.py          # 后台任务端口 / URL 注册表
│  ├─ templates.py         # 模板 + 保留 / 一次性工作区
│  └─ probe.py             # 能力自检
├─ agent_adapter/          # 适配层示例（自建注册表）
│  ├─ registry.py          # 极简装饰器注册表（替换成你的）
│  ├─ tools.py             # shell / background_run / check_background / cancel_background
│  └─ file_guard.py        # read_file / write_file / edit_file / glob_file
├─ integrations/           # 接具体 agent 框架
│  ├─ toolmanager.py       # @ToolManager.register 风格（agent_chat / llm_test 同源）
│  ├─ agent_chat_example.py
│  ├─ AGENT_CHAT_WIRING.md # agent 层（工具注册）的按行号清单
│  └─ PYQT_WIRING.md       # PyQt6 + pyqt6-ela-pro 的界面接线
├─ qt_approval.py          # ElaConfirmDialog 审批框适配
├─ pyqt_demo.py            # PyQt6 沙箱控制台（前台 / 后台 / 停止 / 审批）
├─ demo.py                 # CLI：probe / run / scenario / repl
├─ demo_agent.py           # 脚本化工具调用序列
├─ selftest.py             # 基础自动验收
└─ conformance.py          # 一致性验收（审计 / 审批 / 模板 / 服务 / 身份）
```

## 环境

- Windows 7 SP1 及以上（Win10/11 同样可用）
- Python 3.8+（用到了 `Path.unlink(missing_ok=True)`）
- Git for Windows（可选；没有就自动退回 `cmd.exe`）
- **不需要管理员**

## 快速开始

```powershell
cd E:\python_project\elawidgettools\win_sandbox_example

python demo.py probe        # 4 项能力探测
python selftest.py          # 基础自动验收
python conformance.py       # 一致性验收（审计 / 审批 / 模板 / 服务 / 身份）
python pyqt_demo.py --smoke # PyQt 控制台（构造冒烟；需要 pyqt6-ela-pro）
python demo.py scenario     # 完整场景：写工作区 / 越界 / 后台任务 / 取消
python demo.py repl         # 交互式
```

`demo.py run` 演示「点停止」：

```powershell
python demo.py run --cancel-after 2 "ping -n 60 127.0.0.1"
```

2 秒后调用 `cancel_foreground()`，整棵进程树被杀，不会残留 `PING.EXE`。

## 核 API

```python
from win_sandbox import Sandbox, SandboxPolicy

box = Sandbox(
    workspace=r"C:\Users\Test\AppData\Local\YourAgent\workspace",
    policy=SandboxPolicy(
        low_integrity=True,
        max_processes=64,
        memory_mb=2048,
        default_timeout=120,
    ),
)
box.prepare()                 # 建目录 + 打 Low 标签 + 构造子进程环境

result = box.run("pytest -q", timeout=300)
# result.exit_code / stdout / stderr / timed_out / cancelled

task = box.start("python -m http.server 8000")   # 独立 Job，立即返回
task.status()                 # running / done / failed / cancelled
task.tail()                   # 最近 3000 字符
task.cancel()

box.check(task.id)            # 状态 + 尾部输出
box.cancel_task(task.id)
box.cancel_foreground()       # UI 停止：只杀前台命令
box.close()                   # 退出：杀所有任务
box.resolve("../..")          # 文件工具路径收口，越界抛 ValueError
```

**前台和后台用不同 Job**：`cancel_foreground()` 不会误杀后台服务；
`close()` 才全部收掉。

## 审计 / 拒绝 / 审批 / 服务 / 模板

```python
from win_sandbox import (
    ApprovalDecision, ApprovalMode, GuardMode, JsonlAudit, PolicyDenied,
    Sandbox, SandboxPolicy, create_sandbox, import_tree, read_events,
)

audit = JsonlAudit("runtime/audit.jsonl")

box = Sandbox(
    workspace,
    audit=audit,
    approval=my_approval_handler,          # 可选；配合 ApprovalMode.ASK
    policy=SandboxPolicy(
        guard_mode=GuardMode.ENFORCE,      # AUDIT = 只记日志不拦
        approval_mode=ApprovalMode.ASK,    # DENY = 直接拒绝
        retain_workspace=True,             # False = close() 删除工作区
    ),
)
box.prepare()

# 越界：enforce 抛 PolicyDenied（消息可解释）；audit 只记录
try:
    box.resolve(r"C:\Users\Test\x.txt", tool="write_file", operation="write")
except PolicyDenied as exc:
    print(exc.to_message())

# 服务暴露：后台任务监听 127.0.0.1，登记一个可点 URL
task = box.start("python -m http.server 8000 --bind 127.0.0.1")
service = box.expose(task.id, 8000, "web")     # service.url
box.cancel_task(task.id)                       # URL 自动失效

# 导入项目（尊重 .gitignore）
import_tree(r"C:\work\project", box.workspace)

# 模板：generic / python / node / ephemeral
box2 = create_sandbox("runtime", "ephemeral")  # close() 删除工作区

# 审计读取
for event in read_events("runtime/audit.jsonl"):
    print(event["event"], event.get("tool"))
```

### 审批框（pyqt6-ela-pro）

```python
from qt_approval import QtApprovalHandler

approval = QtApprovalHandler(main_window)   # 必须在 GUI 线程创建
box = Sandbox(workspace, approval=approval, policy=SandboxPolicy(approval_mode=ApprovalMode.ASK))
```

工具线程会通过 `BlockingQueuedConnection` 把请求投到 GUI 线程，弹
`ElaConfirmDialog.show(parent, "沙箱权限申请", ...)`；确认后**只放行本次**，
不会记住目录、也不会扩大范围。审批默认每分钟最多 5 次（`approval_rate_limit`），
防止模型刷屏。

### 审计事件

`prepare` / `run` / `start` / `cancel` / `deny` / `approval` / `tool_start` /
`tool_end` / `service_expose` / `binary_identity` / `close`。命令只记
`command_preview` + `command_sha256`，不记完整命令。

### 加固默认值（P0/P1）

- **审计文件不能在工作区内**：`Sandbox(...)` 构造时直接拒绝（Low 子进程能写工作区，会篡改审计）。
- **`import_tree` 默认跳过凭据文件**：`.env` / `.env.*` / `*.pem` / `*.key` / `id_rsa` 等，跳过清单在 `ImportResult.blocked`。
- **输出上限**：前台命令超过 `max_output_bytes`（200KB）只读尾部 + 截断标记；后台任务超过 `max_task_output_bytes`（50MB）自动取消并记 `output_limit`。
- **`find_bash` 默认不信任 cwd**：随项目携带的 `git-for-windows` 要显式 `prefer_bundled=True`（`agent_chat_example` 已默认开启）。
- **每条命令前重新校验 shell SHA256**（`recheck_binary=True`）；`strict_binary=True` 时变化 / 读取失败都拒绝启动。
- **审批默认每分钟最多 5 次**（`approval_rate_limit`），且只放行本次，不记住目录。

> `ephemeral` 模板会在 `close()` 时删除工作区；审计文件请放在工作区外
> （如 `runtime/audit.jsonl`），否则会跟着一起删掉。

## 接 agent_chat / `@ToolManager.register` 风格

> 你的 UI 是 **PyQt6 + pyqt6-ela-pro**：工具层照这一节接，界面部分看
> `integrations/PYQT_WIRING.md` 和 `pyqt_demo.py`。`AGENT_CHAT_WIRING.md`
> 里的 Dash callback（`stop_btn` / `_cancel_event`）只作为 agent 层参考，
> 不是你的界面接法。

你的 agent 如果和 `agent_chat/app/agents` 同源（`@ToolManager.register` +
`get_registered_tools` / `set_tool_mode`），直接用 `integrations/toolmanager.py`：

```python
from app.agents import ToolManager, get_registered_tools, set_tool_mode
from app.agents.tools import file_tools, grep_tool
from integrations.toolmanager import install

box = install(
    workspace,
    tool_manager=ToolManager,
    set_tool_mode=set_tool_mode,
    file_tools=file_tools,        # read/write/edit + glob_file + read_image
    grep_tool=grep_tool,          # grep_file
    get_work_dir=get_work_dir,
    audit=JsonlAudit("runtime/audit.jsonl"),   # 可选
    approval=my_approval_handler,              # 可选；配合 ApprovalMode.ASK
    policy=SandboxPolicy(approval_mode=ApprovalMode.ASK),  # 可选
)
enabled = get_registered_tools("build")   # 传给 create_async_agent
```

- 执行工具用**同名覆盖**（`ToolManager.register` 是直接赋值），模型侧调用方式不变。
- `read_file` / `write_file` / `edit_file` / `glob_file` / `read_image` /
  `grep_file` 全部用同名覆盖：路径先过 `box.resolve`，并各自发
  `tool_start` / `tool_end` 审计。
- 这是宿主层补丁；正式修法（`_resolve` 校验、绝对路径拒绝）应落在上游。
- 停止按钮：`box.cancel_foreground()`；退出：`box.close()`。

`integrations/agent_chat_example.py` 是具体 import 路径的示例，复制后改 import 即可。

> 已在 `agent_chat` 的真实 `ToolManager` 上验证：4 个执行工具 + 6 个文件类工具
> 注册/覆盖、shell 写工作区、越界拒绝、审批框回调、后台任务 start/check/cancel 全部通过。

## 接进自己的 agent（自建注册表）

适配层就是 `agent_adapter/tools.py`。复制到你 agent 的 `tools/` 目录后：

1. 把 `from .registry import register_tool` 换成你的装饰器。
2. 把 `SHELL_PARAMS` / `BACKGROUND_RUN_PARAMS` 换成你的 schema 格式。
3. 启动时 `install_sandbox(workspace)`。
4. 停止按钮调 `box.cancel_foreground()`。
5. 退出调 `box.close()`。
6. 文件工具改走 `box.resolve()`（参考 `file_guard.py`）。

四个工具的函数体**不用改**：

```python
@register_tool("shell", description=..., parameters=...)
def shell(command, workdir="", timeout=120, description=""):
    result = box.run(command, workdir=workdir, timeout=timeout)
    return format_result(result, description or command[:60], box)

@register_tool("background_run", ...)
def background_run(command, wait=True, workdir=""):
    if wait:
        return format_result(box.run(command, workdir=workdir, timeout=600), command[:60], box)
    task = box.start(command, workdir=workdir)
    return f"后台任务 {task.id} 已启动"

@register_tool("check_background", ...)
def check_background(task_id=None):
    return box.check(task_id)

@register_tool("cancel_background", ...)
def cancel_background(task_id):
    return box.cancel_task(task_id)
```

## Win7 上必须注意

1. **工作区标签是递归的**（`icacls /T`）：已有文件是 Medium，不递归低完整性子进程
   改不了。大目录会慢；示例的单测工作区很小。
2. **`TEMP` / `TMP` / `HOME` / `USERPROFILE` 已重定向**到工作区内的 `.sandbox/`；
   否则 pip / git / python 写临时文件会失败。
3. **父进程在 Job 里**：Win7 不支持嵌套 Job。正常从 Explorer 启动不会遇到；
   从某些终端 / IDE 启动可能。`probe.py` 会报 `Parent in job: yes`。
4. 长路径：Win7 不支持长路径，工作区太深会被 260 截断。
5. `cmd` 模式会把命令写进 `.sandbox\cmd_*.bat` 再执行 —— 命令行里嵌套引号
   （`echo x > "C:\path"`）会被 cmd 解析坏。
6. **`usr/bin/bash.exe` 在低完整性下会打印一行无害告警**
   （`cygheap_user::init: NtSetInformationToken (TokenDefaultDacl), 0xC0000022`）。
   `win_sandbox` 已经在 `RunResult.stderr` 和 `task.tail()` 里自动过滤，不需要宿主处理。

## 已知缺口

- **网络**：免管理员 Win7 无法做内核级拦截；离线场景默认没有网络工具。
- **读隔离**：低完整性只拦写，`.ssh` 等仍可读；要真正隔离只能上专用低权限账户
  （需要安装时一次管理员）。`agent_chat` 适配器里的 `read_file` / `glob_file` /
  `read_image` / `grep_file` 已经限制在沙箱内，但 **shell 仍可 `cat` 工作区外文件**。
- **对抗性逃逸**：没有 AppContainer（Win8+）/ 内核原语，只承诺防误操作。
