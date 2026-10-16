15 在原生 browser 上同样存在（123ms），viewer 无关；两者叠加时（viewer + 英文文档 + CJK 历史）实测 230ms/帧。Qt 侧修复（或可解释机制并给缓解）后关闭本条。

#16 pyqt6\_eia\_pro combo\_box.py : 顶层无条件 import pypinyin , 包导入即背 \~50 MiB 拼音字典

\- PyQt6 复测 (2026-10-16): 复现——干净子进程 import pyqt6\_ela\_pro 后 pypinyin in sys.modules 为 True; tracemalloc 存活堆 +75.5 MiB (json/decoder 35.3+ pypinyin/seg/mmseg 7.0 + pinyin\_dict 3.6 + 其余), top 分配点全部是 pypinyin 数据文件。

库/组件：pyqt6\_ela\_pro/combo\_box.py ( combo\_box.py:29 from pypinyin import lazy\_pinyin 顶层课 import)。对照 table\_view.py:37 对同一依赖是 try/except 防御式 import + 缺失退回——两处行为不一致。

\- 现象：import pyqt6\_ela\_pro（即任何使用 pro 组件的页面）立即加载 pypinyin，其导入自身要解析 50 万条拼音字典 JSON：tracemallee 实测存活 Python 堆 = 50 MiB（json/decoder 35.4 MiB + pinyin\_dict + constants + seg/mmseg = 14.7 MiB），RSS 增量 = +5055 MiB。无论是否真用拼音排序，字典常驻进程。

\- 复现(2026-10-16本机PyQt6 6.8.1构建实测): import pyqt6\_ela\_pro 后 "pypinyin" in sys.modules 为True; tracemalloc 下import前后Python堆+\~50 MiB,top分配点全部是pypinyin数据文件。

\- 期望行为：pypinyin 悄性到首次调用 lazy\_pinyin 时再 Import（或至少与 table\_view 一致做 try/except 可降级）；import pyqt6\_ela\_pro 不应携带 50 MIB 字典。

项目侧是否有临时规避及移除条件：无规避（项目约定；pypinyin 是声明 依赖，删不得）。影响面：应用启动 Python 堆最大常驻单项（内存剖析 2026-10-16）。库改情性导入后关闭本条。