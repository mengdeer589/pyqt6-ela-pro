# 未解决 bug 记录

> 本文件只保留未解决问题；已解决条目已从本目录移除。

## #19 PyQt6ElaWidgetTools（编译 pyd）：eTheme / eApp 单例包装 __getattr__ → C++ getInstance() 链访问违规，进程死亡（app 空闲时偶发）

- 库/组件：PyQt6ElaWidgetTools 0.13.0（2026-10-21 内网镜像构建，ElaWidgetTools.pyd 6.6 MB）单例访问链：`__init__.py` 的 `__wrapsingleton` 包装类 `__getattr__`（`eTheme.<attr>` / `eApp.<attr>` 均经此路径）→ C++ `ElaTheme.getInstance()` / `ElaApplication.getInstance()`（或其返回对象上的属性访问）。

- 现象（2026-10-22 首现，`~/.wenjian/logs/crash.log` pid=20008 段，约 15:18~15:36 间）：主 GUI 线程执行模块级单例属性查找时 Windows fatal exception: access violation——faulthandler 主线程唯一残帧
  `PyQt6ElaWidgetTools\__init__.py in __getattr__`（行号 235933970 是 pyd 行表映射伪影，对应 `__wrapsingleton` 包装类）；其余线程全空闲（两话题 worker asyncio 循环停在 `windows_events._poll`、broker / 页面加载器停在 `queue.get()`）。进程直接死亡（dump 写入中途截断、无 Python 回溯、无 excepthook 记录——纯 C 层终止）。

- 复现：暂不可复现（首现；无最小复现，无法定位命中异常单例状态的具体控件 / 主题令牌调用；后续再发时 crash_diagnostics 的全线程栈可辅助定位）。

- 期望行为：`getInstance()` 类单例访问器在应用空闲期不应 AV；至少 C++ 侧对单例状态（未初始化 / 已析构）有判空保护，异常时抛出 Python 异常而非原生崩溃。

- 我方核实（2026-10-22，Win10 + PyQt6 6.8.1 + 交付线 Qt 6.8.4）：
  - `__wrapsingleton.__getattr__` 代码路径存在，但 `ElaSingletonMacro.h` 的 `getInstance()` 是 `static auto instance = new Class(); return instance;`（永不为空、永不析构）；`del` + `gc.collect()` 后 `sip.isdeleted(ElaTheme.getInstance())` 仍为 `False`，sip 没有把单例所有权交给 Python；
  - `ElaTheme` 78 个成员 + `ElaApplication` 84 个成员逐个 `getattr` 均正常；
  - 报告里的行号是 pyd 行表伪影，不能证明 AV 发生在 `__getattr__`；「单例判空」不会命中任何分支，不能作为修复。
  - 已做防御性收口：`PyElaWidgetTools/scripts/wheel/__init__.py` 的 `__wrapsingleton` 改为首次访问时缓存 `getInstance()` 的 wrapper 并持有强引用；`tests/regression/test_binding_singleton_proxy.py` 守护缓存逻辑，`tests/regression/test_binding_singleton_lifetime.py` 守护已装轮子的非 Python 所有权。**该模板改动需重编 / 重打包 `pyqt6-elawidgettools` 轮子后才在运行时生效。**
  - 仍需下游提供：下次复现的 faulting module + offset（WER `Get-WinEvent -FilterHashtable @{LogName='Application'; Id=1000}`）、pyd 编译时 Qt 版本与运行时 DLL 是否一致。没有 offset 不能定位真正的 C++ 路径。取证步骤与一键收集脚本见 [`docs/crash-diagnostics.md`](../docs/crash-diagnostics.md)。

- 项目侧临时规避及移除条件：无（空闲期偶发、宿主侧无法规避；crash_diagnostics 保底取证）。若稳定复现某控件 / 某操作路径，再评估项目侧绕行。
