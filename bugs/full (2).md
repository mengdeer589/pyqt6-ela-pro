#10 ElaContentDialog / ElaMessageDialog : 替换内容区后窗口高度不重新适配，多行正文被裁切

\- PyQt6 复测（2026-10-16）：复现——probes/recheck\_messagedialog\_height.py 重跑（offscreen 尺寸协商不受离屏渲染限制）：构造后 400×30 → show 后 400×132（内容 sizeHint 145），label 实际高 15 < heightForWidth(350)=26 → 裁切；规避setMinimumWidth(560)+adjustSize 后 560×145 不裁切；一行短消息与「正文 + ElaLineEdit」形态不受影响——四个场景形态与原记录逐一相同。

库/组件：PyQt5ElaWidgetTools C++ ElaContentDialog ( ElaContentDialog.cpp 构造器 resize(400, height()) + showEvent 不 adjustSize ) + pyqt5\_ela\_pro ElaDialogBase / ElaMessageDialog ( setCentralWidget / Regression 后不改窗口尺寸)。

\- 现象：ElaMessageDialog 的 message 在 400px 宽下换行为 ≥2 行时，正文 ElaText (wordWrap) 被垂直裁切——每行只露上半截，按钮栏正常。库自带默认内容（「退出/确定要退出程序吗」）是一行短文本、最小高 ≈ sizeHint，所以开箱无感；任何经 setCentralWidget 换入更高内容（换行正文、加输入行等）都会踩到。

\- 根因（2026-10-12 探针 probes/recheck\_messagedialog\_height.py 实测）：C++ 构造器 resize(400, height()) 时 height() 还是默认值 30，窗口被定死 400x30；Python 层随后 setCentralWidget 换内容不重算窗口尺寸；show 时 只长到布局最小高 132（内容 sizeHint 为 144）换行 label 分到 15px 而 heightForWidth(350)=25 → 裁切。

\- 复現（离屏，uv run python probes/recheck\_messagedialog\_height.py）：

dlg = ElaMessageDialog(
title="更新技能",
message="技能 ppt-master 最新版本为 v0.4.0（当前 v0.4.0），将下载并更新到最新版本。"
parent=host,

dlg.show() # 窗口 400×132, label 几何 (25,42,350,15), 需要 25 → 裁切

一行短消息与「正文 + E1aLineEdit 输入行」形态（\_KeyCreateDialog）不受影响（label/输入框最小高 = 需要高，布局撑得开窗口）。

\- 期望行为：setCentralWidget / Regression 后窗口按内容 sizeHint 重新适配（如 showEvent 里对「尺寸未经用户设定」的窗口 adjustSize()），多行正文完整显示。

\- 项目侧是否有临时规避及移除条件：有规避——setMinimumWidth(560) + adjustSize() 后再run\_modal（宿主应用共5处：3个既有弹窗助手+技能安装/更新弹窗+删除话题弹窗；后2处2026-10-12同模式补齐）。注意：本条与「不做绕开」约定相悖，但既有3处是既定模式且5处行为须一致，库修复（showEvent自适应内容高度）后5处setMinimumWidth / adjustSize及「库缺陷#9|注释可