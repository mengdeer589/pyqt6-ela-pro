# 轮子问题诊断报告

> 诊断对象：PyElaWidgetTools 周边的两个轮子
> —— 本地 `wheels/` 的 **PySide6 6.8.3** 套件（实为 Win7 交付线混入的开发源，见第二节修订），与 `dist/` 的 **pyside6_elawidgettools 0.13.0**。
>
> 结论先说：这是**两个互相独立的问题**，一个在 PySide6 轮子里（Win7 交付线的混版轮被误用），一个在绑定生成器里。
> 用 aliyun 干净 PySide6 6.8.3 可以修掉第一个；第二个已定位为 `gen_xml.py` 枚举索引越界并修复（第六节）。

---

## 一、TL;DR

| # | 问题 | 归属 | 症状 | 已证实的修法 |
|---|---|---|---|---|
| 1 | `wheels/` 里的 PySide6 轮子是**混版 DLL**（6.8.4 与 6.8.3 混装） | PySide6 轮子 | `QSvgRenderer()` / `QPrinter()` / `QWebSocket()` **构造即 0xC0000409** | 用 aliyun 干净 `PySide6==6.8.3`（已实测通过） |
| 2 | 绑定轮的**导航 API 崩溃**（与 PySide6 轮子无关） | **绑定生成器（gen_xml.py）** | `addExpanderNode`/`addFooterNode` 100% 崩；其余调用点漂移的"偶发"多数来自被污染环境 | **已修复**：枚举索引越界（见第六节）；干净 6.8.3 全量验证通过 |

对照关系（关键证据链）：

| 组合 | Addons 类构造 | `ElaWindow` | `addPageNode` | `addCategoryNode` | `addExpanderNode` |
|---|---|---|---|---|---|
| **PyQt5 轮** + PyQt5 5.15.2 | — | OK | OK | OK | **OK**（返回 `(0, key)`） |
| 绑定轮 + 本地混版 PySide6 6.8.3 | **崩** | OK | 偶发崩 | 偶发崩 | 崩 |
| 绑定轮 + aliyun 干净 PySide6 6.8.3 | OK | 偶发崩 | 偶发崩 | 偶发崩 | 崩 |
| 绑定轮 + aliyun 干净 PySide6 6.9.3 | OK | 偶发崩 | 偶发崩 | 偶发崩 | 崩 |

> 「偶发崩」= 同一段脚本多次运行，崩溃点会在不同调用之间漂移（构造 / category / page / expander）。
> 这是**堆破坏**特征，不是单点逻辑错 —— 定位时不要只盯某一个 API。

---

## 二、问题 1：本地 PySide6 轮子混版（已定性）

### 症状

在本地轮子装出的环境里，**只要实例化 QtSvg / QtPrintSupport / QtWebSockets 的类就崩**：

```python
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtWebSockets import QWebSocket

QSvgRenderer()   # ← 0xC0000409（STATUS_STACK_BUFFER_OVERRUN），无 traceback
QPrinter()       # ← 同上
QWebSocket()     # ← 同上
```

而 `QWidget()` / `QNetworkAccessManager()` 正常 —— 说明不是「整个 Qt 坏了」，是**部分 DLL 与其它 DLL 不匹配**。

### 证据（与官方轮逐文件对拍，可复现）

```powershell
# 1) 拉官方轮
python -m pip download --no-deps -q -i https://mirrors.aliyun.com/pypi/simple/ ^
    -d %TEMP%\officialwheel "PySide6-Essentials==6.8.3"
# 2) 逐 DLL 比 hash + FileVersion（脚本见 %TEMP%\opencode\cmp_wheels.py）
python %TEMP%\opencode\cmp_wheels.py
```

实测结果：

```
local dll count=179  official dll count=179
Qt6Core.dll          DIFF local=6165504/2ce534186e6c/6.8.4.0  official=6159496/6965720757c8/6.8.3.0
Qt6Gui.dll           DIFF local=9342976/382c1b9effd3/6.8.4.0  official=9285768/428e11074a37/6.8.3.0
Qt6Widgets.dll       DIFF local=6480896/b575af17f703/6.8.4.0  official=6500488/85023696a1f0/6.8.3.0
Qt6PrintSupport.dll  DIFF local= 391680/fe2575cb1119/6.8.4.0  official= 404104/d0cb3f3385c1/6.8.3.0
Qt6OpenGLWidgets.dll DIFF local=  52224/01e72339488c/6.8.4.0  official=  64136/fbc014e70e43/6.8.3.0
different dlls: 80 / 179
```

关键细节：

- **179 个 DLL 里 80 个不同，且全部是 6.8.4 版本**（FileVersion / 大小 / hash 三处都可区分）。
- **`Qt6Svg.dll` 不在差异列表里** —— 说明替换是**做了一半**：Svg / WebSockets 等仍是官方 6.8.3，
  而 Core / Gui / Widgets / Network / PrintSupport / OpenGLWidgets … 已换成 6.8.4。
  这就是「部分类能构造、部分类一构造就 0xC0000409」的完整解释：
  6.8.3 的 `Qt6Svg.dll` 去调 6.8.4 的 `Qt6Core/Gui`，patch 级 private ABI 变化 → 崩溃。
- 安装到 venv 的文件与轮内文件逐字节一致（不是安装损坏，**是轮子本身被改过**）。
- 运行时自证：干净官方轮的 venv 里 `PySide6.QtCore.qVersion()` = `6.8.3`；
  用本地轮时装出的环境里 `qVersion()` 仍是 6.8.3（PySide6 自己的版本号），但 DLL 是 6.8.4 —— 不一致本身就说明被换过。

### 根因（2026-10-12 修订）

**不是**「从 `vendor/Qt/6.8.4` 替换的」。逐字节哈希对拍结果：

- 轮内 6.8.4 DLL 与 `E:\qt6win7\out\qt684\bin`（官方 Qt 6.8.4 源码 + `E:\python_win7\qt6windows7` Win7 适配补丁自编译）**抽样逐字节一致**（Qt6Core/Qt6Gui/Qt6Widgets/Qt6Qml/Qt6QuickTemplates2 等）；
- 与 `vendor/Qt/6.8.4/msvc2022_64/bin`（绑定工程自建 SDK）是**两个不同的构建**（同版本、不同哈希，如 Qt6Core `2ce534186e6c` vs `94f53df478e2`）。

实际形成方式：把自编译 Qt 6.8.4 里**自编译过的模块**（qtbase 系 + Qml/Quick + WebEngine/Pdf/Multimedia，Essentials 轮 80/179 个 DLL，
含 platforms/qmltooling 等插件）替换进官方 PySide6 6.8.3 轮子；**未自编译的模块**（Qt6Svg / WebSockets / Charts /
Bluetooth 等 99 个文件）保持官方 6.8.3。即「官方 Python 层 6.8.3 + 部分 6.8.4 + 部分 6.8.3」。

补充：`vendor/Qt/6.8.4/msvc2022_64/bin` 确实只有 14 个 `Qt6*.dll` —— 所以轮内的 Qml/Quick/WebEngine 等
6.8.4 文件根本不可能来自它；「凑不齐完整覆盖」的说法与事实相反（是选择性替换，不是替换失败）。

这批轮子属于 **Win7 交付线**（`E:\qt6win7\out\README-Win7.md`），不是 PyElaWidgetTools 绑定构建的产物
（`dobuild_local.py` 从不改写 PySide6 轮子；实测 `.venv-pyside6` 与下游 `.venv` 的 PySide6 均为官方 6.8.3）。
它们被拷贝进 `PyElaWidgetTools\wheels\` 并被下游当作开发依赖源使用，才导致 Addons 类构造崩溃。
另注意：即使做「全量 6.8.4 替换」，官方 6.8.3 的 PySide6 `.pyd` 仍在私有 ABI 层面绑定 6.8.3，
Win7 交付线的「补丁级二进制兼容」结论不适用于拿它当通用开发运行时。

**Qt 只在「同一 minor 内向后兼容」**：6.8.3 编译的代码可以在 6.8.4 运行时上跑，
反之不成立；同一进程里混装两个 patch 版本的 DLL（尤其涉及 private ABI 的模块）就会出现随机崩溃。

### 修法

1. **推荐：不用被改过的 PySide6 轮子**。直接用官方/aliyun 的干净 6.8.3。
   本项目已把 `PySide6==6.8.3` 的依赖源从本地 path 改成 **aliyun 索引**（见 `pyproject.toml` 的 `[[tool.uv.index]]`）。
   ⚠️ **从 path 源切回注册源时，uv 的增量更新会留下新旧混装的文件**（本项目实测：切源后
   Addons 类仍崩，直到强制重装）。必须显式重装：

   ```powershell
   uv sync --all-extras --reinstall-package pyside6 --reinstall-package pyside6-essentials `
           --reinstall-package pyside6-addons --reinstall-package shiboken6
   # 验收：
   uv run python -c "from PySide6.QtCore import qVersion; from PySide6.QtSvg import QSvgRenderer; from PySide6.QtPrintSupport import QPrinter; from PySide6.QtWebSockets import QWebSocket; print(qVersion(), QSvgRenderer() is not None, QPrinter() is not None, QWebSocket() is not None)"
   # 期望：6.8.3 True True True
   ```

2. 如果必须保留 6.8.4 运行时：需要把替换做**完整**（含 `plugins/` 下的平台插件与全部 179 个 DLL），
   且 6.8.4 没有公开 PySide6 轮子 —— 实际上不可行。**结论：不要改 PySide6 轮子**；
   让绑定轮去对齐公开的 Qt（见问题 2 的嫌疑 1）。
3. （2026-10-12 已执行）`PyElaWidgetTools\wheels\` 已清理：混版的 Essentials/Addons 移入
   `wheels\pyside6-win7\`（附 README 说明用途与风险），原位换回从 aliyun 下载的官方 6.8.3；
   四件套 sha256 已与 `uv.lock` 记录逐一比对一致。
   （2026-10-15 更新：工程转入 PyQt6 线后，该官方 6.8.3 四件套已从 `wheels\` 根目录删除；
   需要对照 / 回退时从 aliyun 重下即可——它们本就是未改动的官方轮。）

---

## 三、问题 2 的证据：导航 API 崩溃（绑定轮）

### 最小复现（Python，`%TEMP%\opencode\repro_pyside6_nav.py`）

```python
import sys
from PySide6.QtWidgets import QApplication, QWidget
app = QApplication(sys.argv)
from PySide6ElaWidgetTools import eApp, ElaWindow, ElaIconType
eApp.init()
win = ElaWindow(); win.resize(600, 400)
print("window ok", flush=True)
print("page ->", win.addPageNode("p", QWidget(), ElaIconType.IconName.House), flush=True)
print("cat  ->", win.addCategoryNode("cat", "no-such-key"), flush=True)
print("exp  ->", win.addExpanderNode("t1", ElaIconType.None_), flush=True)   # 1 参也崩
```

干净环境跑法（**必须**用干净 PySide6，否则会被问题 1 干扰）：

```powershell
python -m venv %TEMP%\ps69
%TEMP%\ps69\Scripts\python -m pip install PySide6==6.9.3
%TEMP%\ps69\Scripts\python -m pip install E:\python_project\elawidgettools\PyElaWidgetTools\dist\pyside6_elawidgettools-0.13.0-cp38-abi3-win_amd64.whl
%TEMP%\ps69\Scripts\python %TEMP%\opencode\repro_pyside6_nav.py
```

实测：脚本停在 `window ok` 之前（构造期）、或 `page`/`cat`/`exp` 任一行，每次位置不同；
退出码 `-1073741819`（0xC0000005 access violation）或 `-1073740791`（0xC0000409）。
（2026-10-12 修订：`addExpanderNode` 的必崩已定位为生成器索引越界；其余漂移崩溃多来自被污染环境。修复结果见第六节。）

### 最小复现（C++，加进 example 的 main 即可）

```cpp
#include <QApplication>
#include <QDebug>
#include <QWidget>
#include "ElaApplication.h"
#include "ElaWindow.h"

int main(int argc, char* argv[])
{
    QApplication app(argc, argv);
    ElaApplication::getInstance()->init();

    auto* win = new ElaWindow();
    win->resize(600, 400);
    win->show();

    QString key;
    qDebug() << "page" << int(win->addPageNode("p", new QWidget(), ElaIconType::House));
    qDebug() << "cat " << int(win->addCategoryNode("cat", key));
    qDebug() << "exp " << int(win->addExpanderNode("t1", key, ElaIconType::None));
    return app.exec();
}
```

判读方法：

- C++ 直接跑**也崩** → 问题在 C++/Qt6 编译产物（看第四节嫌疑 1、2）；
- C++ 跑**不崩**、只有 Python 崩 → 问题在 shiboken 绑定生成（看嫌疑 3）。

### 已排除的干扰项

- 不是 PySide6 轮子：干净 6.8.3（全 6.8.3 DLL）与干净 6.9.3 一样崩，而这两个环境里 Addons 类都正常。
  （2026-10-12 修订：当时使用的 `ps683clean` 经哈希核验实为 vendor 6.8.4 换装的实验环境，
  「干净 6.8.3」基准存疑；修复后在全新干净 6.8.3 上不再崩。6.9.3 属不受支持组合。）
- 不是 pytest / 事件循环：独立 `python script.py` 同样崩。
- 不是缺 eApp.init / 窗口未 show：`eApp.init()` 已调，`show()` 前后都试过。
- 不是 Qt5 侧的 C++ 逻辑：同一份源码的 **PyQt5 轮**在 PyQt5 5.15.2 下 `addExpanderNode` 正常返回 `(0, '<key>')`。

---

## 四、问题 2 的嫌疑与建议定位步骤

### 嫌疑 1（最高）：编译 Qt 6.8.4 ≠ 运行 Qt 6.8.3 / 6.9.x

> **2026-10-12 修订**：`addExpanderNode` / `addFooterNode` 的 100% 崩已定位为**生成器索引越界**（见第六节），
> 与本嫌疑无关。本嫌疑仅剩 6.9.x 组合：PySide6 扩展**不支持跨 minor 版本**（6.8 编译的绑定不能在 6.9 运行时使用；
> 注：README 要求版本对齐，但当前 wheel 元数据实际未钉版本，见 6.3 待办），「干净 6.9.3 → `ElaWindow` 构造崩」属预期外组合，不作为绑定缺陷证据。
> 另经哈希实测：`%TEMP%\ps683clean` 实为「官方 6.8.3 + vendor 6.8.4 的 14 个 DLL **全量换装**」的实验环境
> （非干净 6.8.3；探针在其 `QApplication` 创建处即挂起），复核时勿作对照基准。

`ElaWidgetTools.pyd` 的导入表只有三个 Qt 依赖：`Qt6Widgets.dll` / `Qt6Gui.dll` / `Qt6Core.dll`
（用 PE 导入表解析实测）——**它们正是被换版本的三个**。绑定按 6.8.4 头文件/库编译，
而公开可用的 PySide6 只提供 6.8.3（6.8.4 是商业线）或 6.9.x。Qt 的兼容承诺是
「旧编译 → 新运行时」，反向不受支持；混版还直接破坏 patch 级 private ABI。

**建议**：

```powershell
# vendor 里补一份与 PySide6 完全对齐的 Qt 6.8.3
aqt install-qt windows desktop 6.8.3 win64_msvc2022_64 -O PyElaWidgetTools/vendor/Qt
# 改 dobuild_local.py 的 pyside6.qt / qtdir 为 6.8.3，然后
build_offline.bat pyside6 clean env patch ela gen pyside wheel test
```

### 嫌疑 2：`ElaNavigationNode*` 走 `QVariant`（Qt6 下可能变无效值）

> **2026-10-12 修订**：基本不成立。`ElaNavigationNode : public QObject`（`Development/ElaNavigationNode.h:10`），
> 指向 QObject 派生类的指针元类型由 Qt 自动注册（Qt5/Qt6 皆然），无需 `Q_DECLARE_METATYPE`；
> 全库唯一的 `Q_DECLARE_METATYPE` 在日历模型且与此无关。修复后的干净 6.8.3 全 API 探针未复现导航崩，
> 本嫌疑可搁置（指针生命周期问题如有，属独立 C++ 议题）。

`ElaWidgetTools/ElaWidgetTools/private/ElaNavigationBarPrivate.cpp` 成片使用：

```cpp
postData.insert("SelectedNode", QVariant::fromValue(node));          // 多处
ElaNavigationNode* node = index.data(Qt::UserRole).value<ElaNavigationNode*>();   // :166
```

而全库**只有** `Development/ElaCalendarModel.h:35` 声明过 `Q_DECLARE_METATYPE(ElaCalendarData)`，
`ElaNavigationNode*` 没有任何 metatype 声明。Qt5 对这类「QObject 派生类指针」比较宽容，
Qt6 的 `QVariant`/`QMetaType` 收紧后，`fromValue` 可能落成无效 QVariant，
`value<ElaNavigationNode*>()` 拿回 `nullptr` → 后续解引用 = 随机位置的 access violation。

**建议**：给节点指针补 `Q_DECLARE_METATYPE(ElaNavigationNode*)`（头文件处即可）+ 必要时
`qRegisterMetaType<ElaNavigationNode*>()`；或把这类指针交换改成一个明确的载荷类型。
改完务必与嫌疑 1 一起重编再测。

### 嫌疑 3：pyi 与 .pyd 不同代（生成产物不一致）

> **2026-10-12 修订**：判断机制有误 —— 不是 OUTPUTDIR 陈旧，而是**两条生成管线天生不同源**：
> `.pyi` 由 sip 管线生成（出参 `QString&` 并入返回值），`.pyd` 由 shiboken 管线生成（原先未对
> `addCategoryNode` 做特判）。已为 shiboken 侧补齐特判，现在 pyi 与运行时一致（第六节）。

PySide6 绑定的 pyi 与运行时不符，例如：

- pyi：`addCategoryNode(self, categoryTitle: str) -> Tuple[NodeResult, str]`
- 运行时：`TypeError: addCategoryNode expected at least 2 arguments, got 1`（要求 ≥2 参）

说明 `scripts/pyside6/OUTPUTDIR/` 里的 pyi 与实际编译进 `.pyd` 的那一代生成代码不同步。
**重建前先 `clean` 掉 OUTPUTDIR**（`build_offline.bat pyside6 clean ...`），
避免拿着旧 wrapper 编出「pyi 说的和实际跑的不是一回事」的轮子。

### 建议的定位顺序

> （2026-10-12：本节流程已执行完毕，结论见第六节；以下保留为方法论存档。）

1. `clean` + 用 **Qt 6.8.3** 重建绑定轮 → 跑 Python 复现；
2. 若仍崩：跑 C++ 复现判「C++ 还是绑定」；
3. 若判定 C++：按嫌疑 2 补 metatype（这是 Qt6 迁移里最典型的一类静默失效）；
4. 每次重编后固定跑这套探针：`addPageNode` / `addCategoryNode` / `addExpanderNode`（1 参、2 参）
   + `ElaWindow` 连续构造 20 次（暴露堆破坏）。

---

## 五、镜像与版本事实（备查）

| 项 | 事实 |
|---|---|
| aliyun `pyside6` 可用版本 | `6.8.0 ~ 6.8.3`、`6.9.0 ~ 6.9.3`（**没有 6.8.4**） |
| PySide6 6.8.3 的依赖 | `shiboken6==6.8.3` / `PySide6-Essentials==6.8.3` / `PySide6-Addons==6.8.3`（精确等于，无需手工钉） |
| aliyun `pyside6-elawidgettools` | 只有 `0.9.1` 及更早 —— **0.13.0 只在本地 `dist/`**，镜像帮不上忙 |
| 绑定轮 C++ 直接依赖的 Qt DLL | `Qt6Core` / `Qt6Gui` / `Qt6Widgets`（PE 导入表实测） |
| 本库迁移采用的组合 | **aliyun 干净 `PySide6==6.8.3` + 本地 `pyside6_elawidgettools-0.13.0`**（后者按上面步骤修复后再升级） |

---

## 六、修复与验证记录（2026-10-12）

### 6.1 真因：生成器枚举索引越界（`scripts/pyside6/gen_xml.py`）

shiboken 6.8 生成**两套**类型索引：

- 旧命名：`SBK_ELANAVIGATIONTYPE_NODERESULT_IDX = 116`（数组计数 `SBK_ELAWIDGETTOOLS_IDX_COUNT = 214`）
- 新命名：`SBK_ElaNavigationType_NodeResult_IDX = 58`（数组计数 `SBK_ElaWidgetTools_IDX_COUNT = 107`）

定制注入代码（`addExpanderNode` / `addFooterNode`，ElaNavigationBar + ElaWindow 共 4 处）
用**旧索引去索引新数组** `SbkElaWidgetToolsTypeStructs` → 越界约 10 项，读到垃圾 `PyTypeObject*` →
`converter` 为野指针 → `copyToPython` 立即 **0xC0000005**。

- 与「addExpanderNode 100% 必崩、所有参数形状都崩、干净 6.8.3 / 6.9.3 / 混版都崩」完全吻合；
- PyQt5（sip 管线）不走这段代码，故不受影响；
- `gen_xml.py` 里原有一行「自己替换自己」的映射，本以为给 6.8 做了适配，实际是空转。

修复（`scripts/pyside6/gen_xml.py`）：

1. 注入模板统一改用新命名 `SBK_ElaNavigationType_NodeResult_IDX`；
2. `maybeparse` 旧分支（无 `SBK_QString_IDX` 的 shiboken ≤ 6.7）改为**反向降级映射**，不再空转；
3. 补 `addCategoryNode` 两个重载的 shiboken 特判（移除出参 + 返回 `(NodeResult, key)` 元组），与 sip/pyi 对齐。

### 6.2 验证矩阵（修复后重建的 `dist\pyside6_elawidgettools-0.13.0-*.whl`）

| 环境 | PySide6 / Qt | 结果 |
|---|---|---|
| `.venv-pyside6`（构建 venv，官方 6.8.3） | 6.8.3 / 6.8.3 | ✅ 6 次独立运行全通过 |
| `%TEMP%\opencode\ps683verify`（全新 venv，官方 6.8.3） | 6.8.3 / 6.8.3 | ✅ 全 API 通过 |
| `%TEMP%\opencode\pswin7`（**Win7 套件** pyside6-win7：官方 Python 层 + 自编译 Qt 6.8.4） | 6.8.3 / 6.8.4 | ✅ 全 API 通过（绑定轮可直接配套 Win7 套件使用） |
| 转换后的 PySide6 完整示例（临时副本，不动仓库） | 6.8.3 / 6.8.3 | ✅ 启动并持续运行 20s 无异常 |
| `%TEMP%\opencode\ps69clean`（官方 6.9.3） | 6.9.3 / 6.9.3 | ❌ `ElaWindow` 构造崩（跨 minor 不受支持，预期行为） |
| `%TEMP%\opencode\ps683clean`（vendor 6.8.4 换装） | 6.8.3 / 6.8.4 | ❌ `QApplication` 创建处挂起（混装实验床，非有效基准） |

探针覆盖：`ElaWindow` 构造 ×20；`addPageNode` 4 种重载、`addPageNodeKeyPoints` 2 种；
`addCategoryNode` 1/2 参；`addExpanderNode` 1/2/3 参；`addFooterNode` 1/2/3 参。
所有出参方法均返回 `(NodeResult, key)` 元组，与 pyi 一致。

### 6.3 仓库清理

- `PyElaWidgetTools\wheels\`：混版 Essentials/Addons 移入 `wheels\pyside6-win7\`（已补成**自包含四件套**并附 README）；
  原位换回 aliyun 官方 6.8.3；四件套 sha256 与 `uv.lock` 逐一比对一致。
  （2026-10-15：根目录官方 6.8.3 已在磁盘清理中删除；`wheels\` 现只保留 `pyside6-win7\` / `pyqt6-win7\` 两套交付资产。）
- Win7 套件（`pyside6-win7`）2026-10-12 完成**非 QML 全模块补编**：新编 19 个模块（qtsvg / qtwebsockets /
  qtimageformats / qtcharts / qtdatavis3d / qt3d / qtlocation / qttools / qtquicktimeline / qtserialport /
  qtserialbus / qtsensors / qtconnectivity / qtnetworkauth / qthttpserver / qtremoteobjects / qtscxml /
  qtspeech / qtlanguageserver 等），132 个 Qt6 DLL 中 112 个为自编译 6.8.4，仅剩 QML 专属 22 个保持官方；
  46 项全模块矩阵 46/46 通过，Svg / WebSockets / PrintSupport 等混版崩塌已消除。
- 绑定轮 METADATA 实测为 `Requires-Dist: PySide6`（**未钉版本**）——`scripts/wheel/setup.py` 里算好的
  `req`（PySide6==6.8.3 / PyQt5>=5.15.5）未被 `install_requires` 使用，属脚本 bug，待决策是否改为钉版并重出轮子。
- 示例侧顺带记录（非本绑定问题）：`example/beforemain.py` 的绑定切换器未处理
  `pyqtSignal/pyqtSlot/pyqtProperty`，转换后的示例需再补一次（已在临时副本验证通过）。

### 6.4 遗留 / 后续

1. 本轮重建后 wheel 哈希变化（`uv.lock` 中 `2d385fef…` 为旧值，新值 `f8e938e8…`；重编译后会再变，以 dist 文件实际 sha256 为准），下游 `uv sync` 前按既有说明刷新 lock。
2. 6.9.x 不在支持矩阵内；如需支持需按对应版本 shiboken 重新生成/编译。
3. 导入时 `pyside_type_init` 对 `ElaWidgetTools.ElaNavigationType.NodeResult` 等签名串报 UNRECOGNIZED
   （仅影响 `__doc__` 渲染，不影响调用；本次修复前即存在，可另行优化类型系统命名）。
4. Win7 套件已补齐（非 QML 全模块）；建议在 Win7 实机跑 `E:\qt6win7\out\tests\test_all_modules.py`
   （全模块矩阵探针已放入该目录）做最终验收。

---

## 七、开发机运行时切到 Win7 套件（2026-10-12，用户决定）

**决定**：开发机（Win11）的 `uv` 环境改用 **pyside6-win7 套件**（`PyElaWidgetTools/wheels/pyside6-win7/`）。
原先的布置是「开发机只用官方 6.8.3」（第二节修法 1），现改为**与 Win7 交付运行时一致** ——
目的是在开发期就暴露 Qt 6.8.4 / 自编译替换带来的差异。官方 6.8.3（根 `wheels/`）保留作对照 / 回退。

**落地**：`pyproject.toml` 的 `[tool.uv.sources]` 四件套 path 指向 pyside6-win7，`uv.lock` 重锁。
仍是 path 源（PySide6 解析不碰网络）；四件套必须**同时列进 `dependencies`** 才吃到 sources
（uv 只对直接依赖应用 sources，实测）。

**验证（本机，2026-10-12）**：

- venv 内 `Qt6Core / Qt6Gui / Qt6Svg / Qt6Widgets.dll` 与 pyside6-win7 轮内文件**逐字节一致**
  （Core `6165504/2ce534186e6c`、Gui `9342976/382c1b9effd3`、Svg `516096/0cb720c3d994`、
  Widgets `6480896/b575af17f703` —— 即自编译 6.8.4 版）；
- `qVersion()` = **6.8.4**（官方套件下为 6.8.3，可作运行期判别）；
- 当初混版崩塌的 `QSvgRenderer()` / `QPrinter()` / `QWebSocket()` 构造全部正常；
- 绑定轮导航 API（`addPageNode` / `addExpanderNode` / `addCategoryNode`）全部 `Success`；
- 示例应用真实启动 + 事件循环 + 干净退出（冒烟脚本）通过；
- 全量测试：**见下方「八」的补记**。

**回退**：四个 path 改回 `PyElaWidgetTools/wheels/*.whl` → `uv lock`（按 6.4-1 的办法刷新
lock 内 sha256，path wheel 的哈希 uv 不会自己重算）→ `uv sync --all-extras`。

## 八、全量测试补记

pyside6-win7 运行时下的全量测试（2026-10-12，本机）：

```
5610 passed, 35 skipped, 1298 warnings in 347.07s (0:05:47)
```

命令：`uv run --no-sync python -X faulthandler -m pytest tests -q --no-header --timeout=180 --timeout-method=thread`。
对照：切换前的官方 6.8.3 运行时同为 **0 failed**（5603 passed / 39 skipped；总数一致 —— 本轮的
两个新增守卫用例 `tests/regression/test_pyside6_migration_isms.py` 在两边都算，skip 数随运行时探测而变）。
