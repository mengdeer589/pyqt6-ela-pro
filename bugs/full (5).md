f13 pyqt6\_ela\_pro ElaChatView.setResizeReflowDeferred：内置延迟重排失效（冻结值=新
定=不省重排）

PyQt6 复测（2026-10-16）：复现——probes/recheck\_chat\_reflow\_deferred.py（40条 DIAG6 同型短消息、minMessages=10、真实平台 + WA\_DontShowOnScreen；子类 resizeEvent 在 super() 之后捕获 \_resize\_frozen\_width / \_content.width() 快照，无定时器时序歧义）：680→780 resize 事件时刻冻结值 = 770 = 新内容宽（视口 780 - 10 边距），逐帧重排成本 195.7 ms，与 deferred=off 的 194.4 ms 无差（原记录 \~189ms/帧 同量级）——「停手后一次性重排」仍未生效。库内 view.py::on\_view\_resized 仍在 super().resizeEvent() 之后读 self.\_content.width()（布局 pass 已同步拉到新宽）。

库/组件：pyqt6\_ela\_pro/chat/view.py ElaChatView (\_on\_view\_resized/\_resize\_reflow\_\* 一族)。

\- 现象：setResizeReflowDeferred(True, minMessages=N) 开启后，窗口拖拽 / 视图 resize 期间全部消息的逐帧重排成本不变（40 条消息离屏实测 \~189ms/帧，与未启用同量级；上屏口径即宿主窗口拖拽 190260ms/帧）——「停手后一次性重排」设计未生效，重排仍逐帧发生。

\- 根因：resizeEvent → \_on\_view\_resized(event.size().width()) 用 self.\_content.width() 作冻结值，但 Qt6 事件时序下视图的布局 pass 先于其自身 resizeEvent 处函数（滚动区内容被同步拉到新视口宽），读到冻结值时已是新宽 → setFixedWidth(新宽) = 无 letterbox = 不省重排。DIAG6 探针实测：事件时刻 content=770（新视口宽）、 \_resize\_frozen\_width=770。

\- 复现: 独立 ElaChatView + zminMessages 条消息 + setResizeReflowDeferred(True, minMessages=10), 测 resize(w+100,h) + processEvents 成本 = 每次 \~190ms, 同时 \_resize\_frozen\_width = 新视口宽。

\- 期望行为：冻结值取 resize 前的内容宽度（旧宽）；或在布局 pass 之前 就持有内容宽（上一轮结算 / sh时预钉）。

\- 项目侧是否有临时规避及移除条件：宿主侧接法 = 交互 resize 重排守卫钉
view.\_content, on\_settle 调库 \_sync\_content\_width 把内容拉回视口芯 (widgetResizable)
内容只在滚动区 自身 resize 时重算)，并 setResizeReflowDeferred(False) 禁用库内置延迟（其
120ms 释放循环会清掉守卫钉宽）。库修复后可移除守卫、恢复库 API
(setResizeReflowDeferred(True, minMessages=10))。

14 ElaMarkdownViewer : 透明 Base 视口 ( setTransparentTextBase ) 使文本 paint 成本 x8—Win7/Qt6 下滚动密集中文文档 112\~118ms/帧

\- PyQt6 复测 (2026-10-16) : 复现——probes/md\_scroll\_perf14.py 重跑: P1 完整 viewer (透