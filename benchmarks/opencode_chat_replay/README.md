# opencode chat replay benchmark

把本机 `opencode.db` 里的真实长会话导出成 `ElaChatView` bundle，再用
`ElaChatWidget` 真实窗口渲染。数据只写本目录 `data/` / `out/`，不修改数据库。

## 环境

```powershell
uv run python benchmarks/opencode_chat_replay/extract_opencode.py --help
```

默认数据库：`%USERPROFILE%\.local\share\opencode\opencode.db`。

## 导出

主压测会话（父会话 + 9 个子代理）：

```powershell
uv run python benchmarks/opencode_chat_replay/extract_opencode.py --mode stress
```

最长单会话对照：

```powershell
uv run python benchmarks/opencode_chat_replay/extract_opencode.py `
  --session ses_e94744fc2ffdnjvewlOj0m9up6 `
  --mode stress `
  --out data/ses_e94744fc2ffdnjvewlOj0m9up6.stress.json
```

`stress` 保留工具全文；`typical` 默认把单段输出截到 16 KB。

## 查看

```powershell
uv run python benchmarks/opencode_chat_replay/replay_chat.py `
  --bundle data/ses_e734295a1ffeFEIRdCrlNDpg9f.stress.json
```

## 性能

```powershell
uv run python benchmarks/opencode_chat_replay/bench_chat.py `
  --bundle data/ses_e734295a1ffeFEIRdCrlNDpg9f.stress.json `
  --preset default `
  --output out/bench_default.json
```

预设：`default` / `no-virtual` / `low-threshold` / `collapsed-tools` / `narrow`。

运行轨迹面板单独基准（时间轴 / 回放 / 流程图 / 效果开关）：

```powershell
uv run python benchmarks/opencode_chat_replay/bench_trace.py `
  --bundle data/ses_e734295a1ffeFEIRdCrlNDpg9f.stress.json `
  --effects on --steps 30 --output out/bench_trace.json
```

首次结果与瓶颈分析见 `PERFORMANCE.md`。

## 映射约定

- `session_message.type=user` → 用户消息
- `assistant.content[]`：
  - `reasoning` → `ElaChatPart(kind=reasoning)`
  - `text` → `ElaChatPart(kind=text)`
  - `tool` → `ElaChatPart(kind=tool)` + `ElaChatToolCall`
  - `subagent` → 子代理工具卡；子会话里的工具调用挂到同一 `parent_id`
- `compaction` → 压缩分段
- `agent-switched` → 系统提示
- `idle` / `system` / `synthetic` 指令内容默认跳过
- 用户内联图片只保留文件名 / MIME / 估算大小，不写 base64
