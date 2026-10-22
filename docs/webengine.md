# QtWebEngine 接入（PyQt6）

本库自身**不依赖** QtWebEngine。宿主如果在同一进程里使用 `QWebEngineView`，需要遵守
PyQt6 的两条硬约束；它们与 `ElaWindow` / `eApp.init()` 无关，也不是 Win7 或镜像构建
独有的问题。

## 1. `QApplication` 必须带程序名

```python
app = QApplication(sys.argv)        # 或 QApplication(["app"])
```

**不要** `QApplication([])`。QtWebEngine 初始化时 Chromium 的
`base::CommandLine` 要求参数表里至少有一个程序名，空 `argc` 会触发 Qt fatal：

```text
Argument list is empty, the program name is not passed to QCoreApplication.
base::CommandLine cannot be properly initialized.
```

随后进程以 `0xC0000409` 静默终止（WER 里通常显示 faulting module 为 `Qt6Core.dll`）。
`QApplication([""])`（argc=1、程序名为空串）可以过，但推荐 `sys.argv` / `["app"]`。

## 2. 惰性 import 前必须打开共享 GL 上下文

PyQt6 的 `QtWebEngineCore` 在 `QApplication` 已存在时直接 `import` 会卡在
`LoadLibraryW(Qt6WebEngineCore.dll)`（实测 >20 s 不返回）。`QtWebEngineWidgets`
会给出明确错误：

```text
ImportError: QtWebEngineWidgets must be imported or
Qt.AA_ShareOpenGLContexts must be set before a QCoreApplication instance is created
```

两种合法接法：

### A. 启动时预导入（简单）

```python
from PyQt6.QtWebEngineWidgets import QWebEngineView  # 必须在 QApplication 之前

app = QApplication(sys.argv)
```

### B. 保留惰性 import（推荐给预览面板这类按需加载）

```python
from PyQt6.QtCore import Qt, QCoreApplication
from pyqt6_ela_pro import prepareWebEngine

# 必须在创建 QApplication 之前调用
prepareWebEngine()          # 等价于 QCoreApplication.setAttribute(AA_ShareOpenGLContexts)
app = QApplication(sys.argv)

# 之后任意时刻都可以安全地惰性导入
from PyQt6.QtWebEngineWidgets import QWebEngineView
```

`prepareWebEngine()` 返回 `False` 表示 `QApplication` 已存在（调用太晚，属性不再生效）。
**不要**在 `QApplication` 之后再设置这个属性：import 看起来不卡了，但创建 view 后
页面加载仍会卡死（实测 >40 s）。

## 常见误判

- **不是 Win7 / 镜像构建问题**：同一套 Qt 6.8.4 DLL 在 PySide6 下，
  `QApplication` 之后 `LoadLibrary` 约 7 ms、惰性 import 约 0.6 s，正常；
  PyQt6 才会卡在 `QtWebEngineCore` 的模块初始化。
- **不是 `eTheme` / `eApp` 的问题**：本库不 import WebEngine，`prepareWebEngine()`
  也只设置 Qt 全局属性，不创建任何窗口。
- **不要把它写进 `pyqt6_ela_pro/__init__.py` 的模块级执行路径**：库无法保证自己
  一定在 `QApplication` 之前被 import；自动改全局 Qt 属性还会影响不用 WebEngine 的宿主。
  统一走显式的 `prepareWebEngine()`。

## 测试约定

- `tests/conftest.py` 的 session `QApplication` 已改为带程序名的
  `QApplication(["pyqt6-ela-pro-tests"])`；以后加真实 WebEngine 用例沿用即可。
- 守卫：`tests/regression/test_webengine_prepare.py`（import 无副作用、app 前返回
  `True`、app 后返回 `False`）。
