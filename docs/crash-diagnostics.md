# 原生崩溃取证（PyQt6 / Win7）

本文给**下游**用：应用出现原生 access violation、进程静默退出、或 GUI 卡死时，如何取到
`faulting module + offset`、异常码、调用栈和 Python 线程上下文。适用于 bug #19 这类
「`eTheme` / `eApp` 单例访问 AV」的取证；也适用于其它 Qt / pyd 原生崩溃。

> 关键：`fault offset` 是**模块内偏移**（相对于模块基址），不是绝对地址。回传时不要
> 自己加 image base；也不要只发「崩在 Qt6Core.dll」——同一个 DLL 的不同 offset 是
> 完全不同的代码路径。

## 1. 先取最小信息：事件日志

Windows 会把崩溃记到 **Application 日志、Event ID 1000**；挂起（AppHang）是 **1002**。

```powershell
Get-WinEvent -FilterHashtable @{LogName='Application'; Id=1000} -MaxEvents 10 |
  Format-List TimeCreated, Id, Message
```

不用 PowerShell：

```cmd
wevtutil qe Application /q:"*[System[(EventID=1000)]]" /f:text /c:10
```

如果机器是 PowerShell 2（Win7 默认）且 `Get-WinEvent` 不可用：

```powershell
Get-EventLog -LogName Application -Newest 500 |
  Where-Object { $_.EventID -eq 1000 } | Select-Object -First 10 |
  Format-List TimeGenerated, EventID, Message
```

GUI：`eventvwr.msc` → Windows Logs → Application → 筛选 Event ID `1000`（或 `1002`）。

事件正文里要抄下：

- `Faulting application path` / PID
- `Faulting module name`（如 `ElaWidgetTools.pyd` / `Qt6Core.dll`）
- `Faulting module version` / timestamp
- `Exception code`（AV = `0xc0000005`；fail-fast = `0xc0000409`）
- `Fault offset`（模块内偏移）
- `Faulting application start time`（对齐日志时间）

> 这一步不需要安装任何工具；即使不抓 dump，module + offset 也已经能先判断是 pyd、
> Qt DLL，还是别的模块。

## 2. 事件日志被清过：WER 报告

Win7 的 WER 报告在：

```powershell
Get-ChildItem "$env:LOCALAPPDATA\Microsoft\Windows\WER" -Recurse -Filter Report.wer |
  Sort-Object LastWriteTime -Descending | Select-Object -First 10 FullName
```

打开最新的 `Report.wer`，搜：

```powershell
Select-String -Path <Report.wer> -Pattern 'Sig\[|FaultingModule|ExceptionCode|FaultOffset'
```

常见字段：

- `Sig[3]`：faulting module
- `Sig[4]`：模块版本 / 时间戳
- `Sig[6]`：exception code
- `Sig[7]`：fault offset

## 3. 抓 dump（需要调用栈时）

### 方式 A：ProcDump（推荐）

Sysinternals `procdump64.exe`（选能在 Win7 运行的版本）：

```powershell
:: 等 python.exe 启动，捕获未处理异常
procdump64.exe -accepteula -ma -e -w python.exe C:\dumps

:: 或对已经运行的进程直接抓
procdump64.exe -accepteula -ma <PID> C:\dumps\python.dmp
```

参数：

- `-e`：未处理异常时抓
- `-ma`：full dump（栈 / 堆最全，体积大）
- `-mm`：mini dump（只要栈时更小）
- `-w`：等待进程启动

### 方式 B：WER LocalDumps（自动抓，需管理员）

```powershell
$k = "HKLM:\SOFTWARE\Microsoft\Windows\Windows Error Reporting\LocalDumps"
New-Item $k -Force
New-ItemProperty $k -Name DumpFolder -Value "C:\dumps" -PropertyType ExpandString -Force
New-ItemProperty $k -Name DumpType   -Value 2 -PropertyType DWord -Force   # 1=mini, 2=full
New-ItemProperty $k -Name DumpCount  -Value 10 -PropertyType DWord -Force
```

复现后到 `C:\dumps` 取 `.dmp`，定位完删除这些注册表项。

> 32 位 Python 在 64 位系统上，路径通常是
> `HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\Windows Error Reporting\LocalDumps`。

## 4. 分析 dump：WinDbg / cdb

```text
windbg -z C:\dumps\python.dmp
.symfix
.reload
!analyze -v
.ecxr
kb
lmvm ElaWidgetTools
lmvm Qt6Core
```

- `!analyze -v`：直接给 `FAULTING_MODULE` / `FAULTING_IP` / exception code
- `.ecxr`：切到异常上下文
- `kb`：调用栈
- `lmvm <module>`：模块 base / size / version / timestamp
- `ln <address>`：最近符号（需要 PDB）

Win7 上请选能在 Win7 运行的调试器（例如 Windows SDK 7.1A 的 cdb/WinDbg，或较老的
WinDbg 版本）；新版本 WinDbg 未必支持 Win7。

> **当前交付 wheel 没有 pyd / Qt 的 PDB。** 只有 module + offset 也能先定位到模块；
> 要精确到函数，需要用同一份源码重编带 `/MAP` 或 PDB 的 pyd，再对 offset。
> 回传时请附 pyd / Qt DLL 的 SHA256 与版本，确认是不是同一构建。

## 5. 有 Visual Studio：附加调试

- Debug → Attach to Process → 选 `python.exe` → **Attach to: Native code**
- Debug → Windows → Exception Settings → Win32 Exceptions → 勾选 `0xC0000005`
- 复现后看 Call Stack / Modules；`Address - Base` 就是 offset
- 把 Modules 窗口里的模块名、版本、Base、异常地址一起截图/复制

## 6. Python 上下文：faulthandler

`faulthandler` 抓不到原生 AV 的 faulting module，但能给出崩溃前**所有 Python 线程栈**，
帮助确认当时在跑哪个业务路径：

```python
import faulthandler

faulthandler.enable(all_threads=True, file=open("py_fault.log", "w"))
```

或启动时加 `-X faulthandler` / 环境变量 `PYTHONFAULTHANDLER=1`。

卡死类问题还可以：

```python
faulthandler.dump_traceback_later(300, repeat=True)
```

## 7. 需要回传的最小清单

| 项目 | 说明 |
|---|---|
| Event 1000 正文 | faulting module / version / exception code / **fault offset** / PID / 时间 |
| 模块哈希 | `ElaWidgetTools.pyd`、`Qt6Core.dll`、`Qt6Gui.dll` 的 SHA256 + 文件版本 |
| dump | 有就附；没有就附 `!analyze -v` 输出 |
| Python 栈 | `py_fault.log`（faulthandler 全线程） |
| 复现路径 | 当时在做什么（空闲 / 切主题 / 打开会话 / 工具卡渲染…），是否稳定 |

## 8. 一键收集（PowerShell 模板）

把 `$AppDir` 改成应用的 site-packages 目录（含 `PyQt6ElaWidgetTools` / `PyQt6`）：

```powershell
$AppDir = "C:\path\to\site-packages"
$Out = Join-Path $env:USERPROFILE "Desktop\ela-crash-info"
New-Item -ItemType Directory -Force $Out | Out-Null

# Win7 自带 PowerShell 2 没有 Get-FileHash；用 .NET 实现 SHA256
function Get-Sha256([string]$Path) {
  $sha = [System.Security.Cryptography.SHA256]::Create()
  $stream = [System.IO.File]::OpenRead($Path)
  try { ([BitConverter]::ToString($sha.ComputeHash($stream))).Replace("-", "") }
  finally { $stream.Dispose(); $sha.Dispose() }
}

Get-WinEvent -FilterHashtable @{LogName='Application'; Id=1000} -MaxEvents 20 |
  Format-List TimeCreated, Id, Message | Out-File "$Out\event1000.txt" -Encoding utf8
Get-WinEvent -FilterHashtable @{LogName='Application'; Id=1002} -MaxEvents 20 |
  Format-List TimeCreated, Id, Message | Out-File "$Out\event1002.txt" -Encoding utf8

Get-ChildItem "$env:LOCALAPPDATA\Microsoft\Windows\WER" -Recurse -Filter Report.wer -ErrorAction SilentlyContinue |
  Sort-Object LastWriteTime -Descending | Select-Object -First 10 |
  ForEach-Object { Copy-Item $_.FullName "$Out\wer-$($_.Directory.Name).wer" -Force }

Get-ChildItem $AppDir -Recurse -Include ElaWidgetTools.pyd,Qt6Core.dll,Qt6Gui.dll -ErrorAction SilentlyContinue |
  ForEach-Object {
    $hash = Get-Sha256 $_.FullName
    "$hash  $($_.FullName)  $($_.VersionInfo.FileVersion)" |
      Out-File "$Out\modules.txt" -Append -Encoding utf8
  }
```

把 `$Out` 整个目录连同 dump / `py_fault.log` 一起回传。

> 如果 `Get-WinEvent` 不可用（PowerShell 2 环境），把两条事件查询换成前面的
> `Get-EventLog` 版本；如果 `$AppDir` 下没找到 Qt DLL，把路径指到
> `...\site-packages\PyQt6\Qt6\bin`。

## 9. 注意事项

- **offset 是模块内偏移**：WER / 事件日志里的 `Fault offset` 直接可用；用调试器时
  绝对地址 = `模块 base + offset`，`lmvm` 可查 base。ASLR 只改变 base，不改变 offset。
- **异常码**：`0xc0000005` 是 AV；`0xc0000409` 是 fail-fast（Qt fatal / `/GS`）；
  `0xc0000374` 是堆损坏。不同异常码对应不同排查方向。
- **dump 可能含敏感数据**（剪贴板、文档内容、token），只发给可信的维护者。
- **WER 可能被关闭**：如果事件日志没有 1000，先确认 WER 服务/策略；LocalDumps 也不依赖
  WER 弹窗。
- **PDB 不在交付 wheel 里**：module + offset 仍然有价值；需要精确符号时再重编带符号的
  pyd（同一源码 + 同一 Qt）。
