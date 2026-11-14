# opencode 真实长会话性能记录

环境：Windows 10 26300 / Python 3.11.9 / 窗口 1400×900 / 默认主题。

数据源：`ses_e734295a1ffeFEIRdCrlNDpg9f`（stress）

- bundle：16.87 MB
- 父消息：1420，渲染 1377
- 子代理：9 个，1680 条子消息
- 工具分段：3238（含子代理内部工具）
- reasoning：1102 段
- 统计徽标：1353 个

## 结果

| 预设 | 导入 | RSS 增量 | 滚动 avg | 滚动 p95 | 滚动 max | 导入后控件 |
|---|---:|---:|---:|---:|---:|---:|
| default | 0.07 s | +14 MB | 34.8 ms | 23.8 ms | **1137 ms** | 5 tool / 0 subagent |
| low-threshold | 0.08 s | +14 MB | 37.3 ms | 23.8 ms | 1243 ms | 5 tool / 0 subagent |
| collapsed-tools | 0.07 s | +15 MB | 38.3 ms | 22.7 ms | 1171 ms | 5 tool / 0 subagent |
| no-virtual | 16.9 s | **+1419 MB** | 8.9 ms | 35.7 ms | 55 ms | 2947 tool / 9 subagent |
| 对照：无子代理会话 default | 0.06 s | +14 MB | 19.0 ms | 22.5 ms | 74 ms | 0 tool / 0 subagent |

优化前滚动结束后 default 已物化：1761 个 `ToolCallCard`、9 个 `SubagentCard`、3 个 `ElaMarkdownViewer`。

## 关键发现

1. **主瓶颈不是长历史本身，而是“单个气泡里一次物化几百个子工具卡”。**
   两个 spike 在滚动 step 77/78：

   | bundle 消息下标 | 子代理数 | 子工具数 | 总工具数 |
   |---:|---:|---:|---:|
   | 1340 | 4 | 949 | 953 |
   | 1352 | 5 | 808 | 813 |

   对应当前 `SubagentCard.addChild()` 会立即为每个子工具创建 `ToolCallCard`，
   即使子代理卡默认收起。一次事件循环里创建约 950 个控件，产生 1.1 s / 0.8 s 卡顿。

2. **关闭虚拟化不可取。**
   全量物化把 RSS 从 135 MB 拉到 1.55 GB，导入 16.9 s；虽然滚动平滑，
   但启动和内存代价不可接受。

3. **降低虚拟化阈值 / 工具默认收起没有解决 spike。**
   卡顿来自子代理卡内部，不是消息级虚拟化阈值；`setToolDefaultOpen(False)`
   也不会跳过子控件创建。

4. **无子代理的长会话滚动明显更稳。**
   1541 条消息、1602 个工具调用，avg 19 ms / max 74 ms，说明子代理嵌套是主要差异。

5. **搜索和 resize 在 default 下可接受。**
   搜索 18 条命中约 52 ms；resize 1200/900/1400 约 30/7/6 ms。

## 已做优化

1. **`SubagentCard` 子卡延迟物化**
   - 父卡收起时只保存 child calls，不创建 `ToolCallCard` / 嵌套 `SubagentCard`。
   - 首次展开时创建一页（`_CHILD_PAGE_SIZE = 16`），其余显示「显示其余 N 个工具」。
   - 点击后按 16 个/页交给 0ms 定时器异步补齐，单帧不会创建几百张卡。
   - 子调用结果更新仍走父卡的 pending 数据，不会因为未物化而丢结果。

2. **停止子工具逐个挪统计徽标**
   - 子工具卡在子代理内部，不再对每个 child 调 `_move_step_stats_to_end`。

3. **统计标签合并刷新**
   - 子卡批量登记时用 0 ms 单次定时器统一刷新 header 计数，避免 950 次
     `_sync_stats()`。

4. **大消息变更汇总轻量解析**
   - 工具分段超过 64 个时先只算文件路径 / 增删行，不解析完整 diff；
     展开汇总时再补完整 diff。

5. **恢复工具分段跳过线性查找**
   - `_restore_one_part` 直接取刚追加的末尾分段，避免 950 次 `_find_part` 扫描。

## 优化后

同一份 stress bundle、同一窗口：

| 指标 | 优化前 | 优化后 |
|---|---:|---:|
| 滚动 avg | 34.8 ms | **16.2 ms** |
| 滚动 max | 1137 ms | **38.1 ms** |
| 导入后 RSS 增量 | 14.4 MB | 14.6 MB |
| 导入耗时 | 0.073 s | 0.072 s |
| 滚动后物化工具卡 | 1761 | 8（未展开子代理不建子卡） |
| 子代理展开第一批 | ~950 卡 / 约 1.1 s | 16 卡 / 26 ms |
| 展开后加载全部 | — | 342 卡 / 483 ms（分 22 批，无单帧长阻塞） |

`no-virtual` 仍然不可取：15.7 s 导入、+1163 MB；默认虚拟化 + 子卡懒物化是当前最优组合。

## 运行轨迹面板（瀑布时间轴重做）

同一份 stress bundle、1000×720 窗口、真实桌面渲染。旧面板 = 300 行逐行
`QWidget` + 归一化耗时条；新面板 = 单画布时间轴 + 按轮只读流程图。

| 指标 | 旧面板 | 新面板 |
|---|---:|---:|
| `refresh()`（模型 + 重建） | 275–385 ms | 106.4 ms avg / 117.7 ms p95 |
| 首次绘制 | 44.7 ms | **1.6 ms** |
| 滚动 p95 | ~4 ms | **3.4 ms** |
| hover 整幅重绘 p95 | — | 4.5 ms（实际脏区更小） |
| 回放帧 p95 / max | — | 3.8 ms / 4.0 ms |
| 切流程图（22 节点） | — | 46.6 ms |
| RSS 增量 | +85.4 MB | **+9.3 MB** |
| 时间轴控件数 | 1813 | **36** |
| 轨迹行数 | 300（截断） | **7071（22 轮 / 1354 响应，全量只画可视区）** |

- 模型 `buildTraceRows`：79.8 ms avg / 101.9 ms p95（22 轮 / 1354 响应 /
  3238 次工具 / 7071 行）。
- 异常耗时裁剪：`clip_ms=52.6s`，108 个 span 被裁剪；单轮 7.6h 的 `write`
  显示跨度被压到 68.1s，真实值保留在 hover 与轮头。
- 聊天主视图回归：`bench_chat.py --preset default` 滚动 avg 17.2 / p95 21.1 /
  max 25.7 ms（改前 17.6 / 21.9 / 26.7 ms），无回退。
- `--effects off` 主要省装饰绘制；滚动 / 回放差异在 0.3 ms 内，说明性能
  瓶颈已不在发光效果。

复现：

```powershell
uv run python benchmarks/opencode_chat_replay/bench_trace.py --effects on --steps 30
uv run python benchmarks/opencode_chat_replay/bench_trace.py --effects off --steps 30
uv run python benchmarks/opencode_chat_replay/bench_chat.py --preset default --steps 40
```

## 后续可选项

- 如果 Win7 上 16 张卡仍偏重，可把 `_CHILD_PAGE_SIZE` 调到 8~12。
- 如需进一步降低单条 parent 消息的 38 ms 峰值，可在适配层限制每个 subagent
  的首屏 child 数（只保留摘要，展开时再拉完整子工具）。

## 复现

```powershell
uv run python benchmarks/opencode_chat_replay/extract_opencode.py --mode stress
uv run python benchmarks/opencode_chat_replay/bench_chat.py --preset default --steps 100
uv run python benchmarks/opencode_chat_replay/bench_chat.py --preset no-virtual --steps 50
```

原始 JSON 在 `out/bench_*.json`，截图在 `out/bench_default.png`、
`out/replay_subagents.png`、`out/replay_subagent_card.png`。
