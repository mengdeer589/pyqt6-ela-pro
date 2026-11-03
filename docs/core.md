# 核心机制（动效 / 主题 / 配色 / 所有权）

本页说明 `pyqt6_ela_pro` 的基础设施模块。组件级 API 见各模块 docstring 与
`README.md`。

## 动效策略（`_motion.py`）

`pyqt6_ela_pro.motion` 提供三档全局偏好，组件通过它决定「这次动效播不播、
播多久」：

| 模式 | 状态过渡 | 持续动效 |
|---|---|---|
| `Full` | 正常全时长 | 正常播放 |
| `Reduced` | 压到 50ms 以内 | 停掉 |
| `Disabled` | 同步落终值（不占一帧） | 停掉 |

默认跟随系统（`SPI_GETCLIENTAREAANIMATION`，Win7 起可用），首次查询探测一次并
缓存。宿主/测试可以：

```python
from pyqt6_ela_pro import ElaMotionModeType, motion

motion.setMode(ElaMotionModeType.Full)   # 强制指定
motion.setOverrideSystem(True)           # 固定住，不再跟随系统
```

组件侧入口：

- `start_transition(anim, full_ms, on_complete=...)`：`QPropertyAnimation` 过渡，
  也是 `finished` 收尾的唯一注册点；调用点不要再自己连 `anim.finished`。
- `start_transition_timer(timer)`：给手搓插值的 `QTimer` 过渡用。
- `start_idle_loop(timer, interval_ms, on_stop=...)`：持续动效（转圈 / 呼吸 /
  流动）。`Reduced` / `Disabled` 下是**停掉**而不是放慢；相位类动效必须通过
  `on_stop` 摆到静态基态。

`Disabled` 下不使用 `setDuration(0)`：时长为 0 时 `QAbstractAnimation.start()`
会同步发 `finished`，收尾可能在调用方栈未铺好时执行。实现改为先 `start()` 进入
Running，再 `setCurrentTime(duration())` 跳到终点，终值仍经过真实 Qt 路径。

`charts` 的 `ChartAnimation` 是例外：它不挂 `QAbstractAnimation.finished`，自带
`complete()`，不适用 `start_transition`。

## 语义令牌与主题（`_theme.py`）

上游 `eTheme.getThemeColor(mode, index)` 给的是颜色槽位（`BasicText` / `WindowBase` /
`PrimaryNormal` …），不是语义。`_theme` 做两件事：

1. 把槽位翻译成「这层表面 / 这级文字 / 这条边」的可读角色；
2. 补齐上游缺的语义，例如 Success / Warning 状态色与 charts 调色板。

常用入口：`currentMode()`、`surface()`、`text()`、`textMuted()`、`border()`、
`statusColor(mode, role)`、`chartPalette()`、`setAccentColor()` / `resetAccentColor()`。

## 配色（`_colors.py`）

颜色字符串的唯一入口是 `_colors.parse_color`：`QColor("rgb(...)")` 会得到无效色、
绘制成纯黑且零报错。色板提供 `accent` / `accentHover` / `accentActive` / `accentBg` /
`textColor`，实心按钮另有 `solid` / `solidHover` / `solidText` 等派生色。

`primary` / `blue` 的强调色取 `eTheme` 实时值（跟随 `setAccentColor`）；其余色系是
库自带的固定色板。

## 样式原语（`_styles.py`）

全库禁用 QSS。需要非主题色文字 / 纯色底 / 文本视口底 / 1px 框 / 圆角卡片 /
透明图标按钮 / 无外观行时，用：

- `ColorText`：显式文字色版本（每个实例必须显式 `setTextPixelSize`，默认 28px 过大）；
- `setSolidBackground` / `setTextBaseColor` / `setPlainFrame`；
- `paintRoundedCard` / `FlatIconButton` / `BareButton`。

`ElaText.paintEvent` 会把 palette 重置回主题色，硬塞的 `QColor` 在绘制时会被丢掉；
`ColorText` 用 `QLabel::paintEvent` 绕开这一点。显式色是快照，主题切换时由组件重新
调用 `setTextColor`。

## 内容控件所有权（`_ownership.py`）

容器通过 `setXxxWidget(w)` 接收宿主提供的内容控件，释放时按策略处理：

| 策略 | 行为 |
|---|---|
| `Borrowed`（默认） | 容器持强引用，释放时 `setParent(None)` 交还调用方 |
| `Reparented` | 释放时放回挂载前的 parent |
| `Owned` | 释放时由容器 `deleteLater()` |

`ContentSlot` 封装了挂载 / 取回 / 释放的全部记账。它**刻意不是** host 的 QObject
子对象：宿主析构会连带析构槽，而 Python 包装器还活着，GC 时会 delete 已释放的
C++ 对象（0xC0000005）。

## 工具提示（`tooltips.py`）

提供 `ElaToolTip`（8 种显示位置）与 `ElaStateToolTip`（加载 / 完成状态卡片）。
`set_tooltip(widget, text, position)` 会复用已有提示框、只更新配置；绑定后吞掉
`QEvent.ToolTip`，避免原生 `QToolTip` 与自定义提示同时弹出。

长文本用 `maxWidth` + `wordWrap` 控制折行；`contentWidget` 给定时用它替代文本。

## 表格（`table_view.py`）

`ElaDataTable` 在 `ElaTableView` 之上封装 `QStandardItemModel`：同步 / 异步设置数据、
按列索引或表头名设置列宽、单元格样式、行底色、插入删除行。表头排序默认关闭，需要
`setSortingEnabled(True)`。

数值排序把空值 / 非数值 / `nan` / `inf` 统一排到最后，避免比较不成立导致顺序不稳定。

## 分段控件（`ela_selector_bar.py`）

一排互斥选项 + 会「压扁 - 移动 - 绽开」的高亮指示器；动画只在选中项变化时跑，
`valueChanged` 只连接一次。

## 任务栏进度（`taskbar_progress.py`）

Qt6 没有 `QtWinExtras`，组件直接调 COM `ITaskbarList3` / `ITaskbarList4`，在任务栏
图标上展示进度（正常 / 暂停 / 错误 / 不确定 / 隐藏）。接口按系统版本回退：优先
`ITaskbarList4`（Win8+），失败再用 `ITaskbarList3`（Win7）。

## Parquet 表格（`parquet_table.py`）

`ElaParquetTable` 基于 `ElaDataTable`，用 `polars` 分页读取 Parquet。依赖是可选安装：

```bash
pip install pyqt6-ela-pro[parquet]
```

列统计按「整列」精确计算，成本随行数线性增长，但按列名缓存后每列只付一次：

| 行数 | 文件大小 | 本列 min+max+last |
|---:|---:|---:|
| 2,000 万 | 284 MiB | 22.6 ms |
| 1 亿 | 1.45 GiB | 112 ms |
| 5 亿 | 7.71 GiB | 586 ms |

统计在 `clicked` 槽里同步跑，主线程会被占住；要彻底解决需要把统计挪到工作线程。

