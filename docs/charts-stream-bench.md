# 流式图表基准

`tools/perf/bench_charts_stream.py` 测 `pushData` / `setDataWindow` / 绘制的单次耗时，用于回答「1 kHz / 10 万点能不能扛」。

## 跑法

```powershell
uv run python tools/perf/bench_charts_stream.py --points 100000 --window 10000 --batch 16 --calls 1000 --frames 10
uv run python tools/perf/bench_charts_stream.py --json bench.json
```

- `--points`：初始 `setOption` 的点数。
- `--window`：`maxPoints` 窗口大小。
- `--batch`：每次 `pushData` 追加的点数。
- `--calls`：`pushData` 次数（不 sleep，测吞吐上限）。
- `--frames`：稳态绘制采样帧数。
- `--json`：把结果写到文件。

输出为 p50 / p95 / max / mean（毫秒）与进程峰值内存（MB，Windows 走 `psapi`，其它平台需要 `psutil`）。

## 本机基线

环境：Windows / AMD Ryzen 7 7700 / Python 3.11.9 / PyQt6 6.8.1 + Qt 6.8.2 / `line` + `sampling: "lttb"` / 900×520。

参数：`--points 100000 --window 10000 --batch 16 --calls 1000 --frames 10`。

| 指标 | 结果 |
|---|---|
| 初始 `setOption`（10 万点） | 126 ms |
| 首帧绘制 | 12.9 ms |
| `pushData` p50 | 0.73 ms |
| `pushData` p95 | 0.85 ms |
| `pushData` max | 32.2 ms（含布局 / GC 抖动） |
| `setDataWindow`（10 万点 → 1 万点窗口） | 4.4 ms |
| 稳态绘制 p50 | 1.6 ms |
| 稳态绘制 p95 | 4.7 ms |
| 进程峰值内存 | 171 MB |

单次 `pushData` 的中位耗时约 0.73 ms，1 kHz 推送（每毫秒一次）仍有约 0.27 ms 余量；p95 也低于 1 ms。`max` 的 30 ms 级尖峰来自偶发全量布局与 GC，不是稳态成本。

## 说明

- 这是单机基线，不是 CI 阈值；不同 CPU / Qt 版本差异明显。
- `pushData` 不做全量重建：只更新 `DataRing`、坐标轴范围与 dataZoom 窗口。
- 高频推送若在业务侧一次只推 1 点，建议按帧合并成小批量再调用，避免每点触发一次布局。
