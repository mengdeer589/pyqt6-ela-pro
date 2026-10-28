# AI 对话（chat）

> 组件位于 `pyqt6_ela_pro/chat/`；应用内接入指南（含 `llm_test` 全文快照）见
> `example/chat_guide_page.py`。
>
> 交互对齐 opencode 会话 UI，实现件优先复用 Ela 原生组件
> （`ElaFlowLayout` / `ElaIconButton` / `ElaDropDownButton` / `ElaMenu` /
> `ElaListView` / `ElaScrollPageArea` / `ElaProgressRing` / `ElaToggleButton`）。

- **ElaChatWidget** — ChatGPT 风格聊天组件（自研，`pyqt6_ela_pro.chat`）：
  可选头部（标题 / 清空）+ 消息列表 + 分层输入区 + 排队 dock + 输入区
  dock + 审批 dock（`chatView()` / `chatInput()` / `toolBar()` /
  `queueDock()` / `inputDock()` / `permissionDock()` 取各部件句柄）；
  命令式回合 API（`sendUserMessage` → `beginAssistantMessage` →
  `endAssistantMessage`，`stopGeneration` 停止并保留已输出内容）——
  **分段时间线操作不在 widget 上**：`beginStep` / `beginText` / `appendText` /
  `beginReasoning` / `addToolCall` / `setStepStats` / `setMessageDuration`
  等一律经 `chatView()`（或 `view.bubble(id)`）调用；widget **不转发**
  view 的同名方法（两套签名会把消息 id 落到别的参数上）；
  宿主操作 `undoMessage`（撤回用户消息：删除该条及其后 + 原文 / 附件回填，
  **只对用户消息生效**）/ `undoLastUserMessage`（撤回最后一条用户消息 ——
  「撤回最后一条」的正确入口）/
  `regenerateFrom`（重生准备：删除原回答并返回前置用户消息）/
  `retryMessage`（重试准备：清错误并把状态落成 `stopped`、**保留消息位置**，同参数重发）；
  排队 `sendNextQueued` / `setAutoSendQueue`（回合结束自动续发队首，默认开）；
  steer 插话 `steerMessage` / `drainSteer` / `setSteerEnabled`（生成中把新
  指令送进这一轮，在 `beginStep` 安全边界投递，而非等整轮跑完）；
  消息内容操作（`messages()` 只读快照 / `updateMessage` / `count` /
  `toolCalls` / 头像 / 外观）都在 `chatView()` 上，`messageUpdated` 信号
  同步快照变化；
  信号 `messageSubmitted` / `messageSubmittedFull` / `stopRequested` /
  `generationStarted` / `generationFinished` / `messageUpdated` /
  `copyRequested` / `undoRequested` / `regenerateRequested` / `retryRequested` /
  `messageActionTriggered` / `attachmentClicked` / `permissionRequested` /
  `permissionReplied` / `steerReady` / `steerChanged` / `attachmentsChanged` /
  `queueChanged` / `mentionSelected` / `imagePasted` / `filesAdded` /
  `clearRequested` / `newTopicRequested` / `cleared` / `sessionChanged` /
  `batchRenderFinished` / `suggestionClicked`
- **工具结果富渲染（`registerToolRenderer`）** — 宿主按工具名注册渲染器，库只
  替换工具卡的**内容区**（头部 / 折叠 / 错误竖线 / 忙碌环 / 展开策略仍由
  `ToolCallCard` 负责，故现有工具卡回归行为不变）：
  `registerToolRenderer(name, factory, *, subtitle=None, groupable=None)`；
  工厂签名 `(ToolRenderContext) -> QWidget`，返回 `None` 落回默认纯文本；
  可选实现 `updateToolResult(result, status)` 接收结果推送。
  `subtitle(arguments) -> (键, 值)` 的键会自动从参数摘要排除（防「3 个文件
  files=[...]」重复）；给上下文工具（read / glob / grep / list）注册默认退出
  分组（否则被分组卡绕过）。库内**不内置**任何具体渲染器 —— diff / 图片 /
  终端输出都由宿主实现。**渲染器里的每个 `ColorText` 都要显式
  `setTextPixelSize`** —— 不设就是 `ElaText` 的默认字号（实测 **28px**），比
  chat 的 11-14px 标尺大一大截，整张卡的比例会崩
- **工具审批（`beginPermission` / `resolvePermission`）** — **交互与记录分离**
  （对齐 opencode 的 `session-question-dock`）：
  - 等待用户操作 → `ElaChatPermissionDock`（**输入区上方**，输入区照常可用，
    不顶替它）；答完 → 时间线上该 part 的**原位**留下一张
    `PermissionRecord`，**默认折叠成一行**（与 `工具调用 (N)` 同一套折叠交互）。
    两者是**不同的 widget** —— 交互是大控件，记录是一行摘要，排版需求正好相反。
  - 一次只放一张；后到的**排队**（「还有 N 个待答复」），不顶掉用户正在答的那张。
    排队的卡**从未被 show 过**（建卡时无 parent，卡片自己不 show，显示时机只归
    dock —— 否则 Qt 会把无父控件当顶层窗口弹出来，用户看到「小窗一闪」）。
  - **两种形态由 `permission.questions` 是否为空决定**（**这就是判据，勿另设
    标志位**）：
    - **批准型**（`questions` 为空）：允许一次（实心强调色）/ 始终允许（描边）/
      拒绝…（危险色）—— **按重要性分档**，不是三个等权重的文字按钮；可带反馈；
    - **问答型**（`questions` 非空）：**逐题向导** —— 标题行（「需要你回答 ·
      短标签」+ 右侧「N / M」+ 可点的进度段胶囊，**仅多题时出现**），题面
      （14px 主文本色），候选卡（每项**两行**：标题 + 说明，
      `ElaChatOption{label, description}`；单选 = `ElaRadioButton` 圆点、
      多选 = `ElaCheckBox` 方框，**标记是真控件不是自绘**），末行是「输入自己的
      答案」（**点标记 / 点整行 / `Space` = 选中它 + 展开输入框**；单选下是
      radio、再点标记不取消，多选下再点标记 = 取消并收起；空文本勾上不算答案），
      页脚 忽略 / 上一步 / 下一步|提交（**都是 `ElaButton`**，不印快捷键
      提示但快捷键照常生效；点它们会先把输入框里的文字落定）。大量 diff 按
      「行数 + 单行长度」双上限折叠。
      键盘：`1`–`9` 选中对应行（与焦点在哪一行无关）、`Space` 切换（多选）、
      `↑↓←→` / `Home` / `End` 移焦点、`Ctrl+⏎` 下一步 / 提交、`Alt+←` 上一步、
      `Esc` 忽略。
    - **选项区是普通容器，不封顶也不滚动**：`QScrollArea.sizeHint()` 是个无意义
      的小值，会把内容压扁（实测 166px 压到 69px、第二个选项切掉半截），而内层
      滚动区滚到头后事件会冒泡到外层（滚选项会连消息区一起动）。候选行是普通
      控件、行高固定，容器的 `sizeHint` 就是内容高度。

  **组件只画卡 + 收集回复 + 发信号，绝不阻塞**（Qt 里挂起等用户点按钮会卡死
  事件循环）：宿主收 `permissionRequested` 自行挂起后端，收 `permissionReplied`
  自行恢复；「始终允许」的规则持久化也归宿主（`resources` 模式串原样交出）。
  未答复的审批在回合中止 / 消息删除时自动作废，不留死卡。
  `beginPermission` 收到**已经是落定态**的 request（宿主重放后端历史）时直接落
  成记录卡：不进 dock、不发 `permissionRequested`。

  问答型的 `answer` 是 `json.dumps({key: str | [str, ...]})`：**单选塌缩成标量**、
  **多选发整个数组**、**未答题整条不进 payload**（不是空串也不是空数组 ——
  空数组会被模型读成「用户答了『一个都不选』」）、**自定义答案与候选项互斥**。
  读未塌缩的原始分组形式用 `view.permissionAnswers(messageId, requestId)`
  （「答到一半还没提交」时看进度）。取还在 dock 里等回复的卡用
  `view.interactivePermissionCard(messageId, requestId)`（`permissionCard` 只返回
  时间线上的**记录卡**，等待期间是 `None`）。
  强调色取自 `eTheme` 主题令牌，**不硬编码 opencode 的品牌色**（本库可换肤）
- **上下文压缩表达（`beginCompaction` / `appendCompactionSummary` /
  `endCompaction`）** — 时间线上的分隔卡：**折叠态就露出摘要首行**（自己按
  字符数截断），点开看全文；`endCompaction(..., historyCount=N)` 给了条数才写
  「已压缩 N 条历史」，**没给就说「已压缩历史」**（`0` 的含义是「不知道」，不是
  「压了 0 条」）。**库不实现压缩算法**（摘要模板 / 收缩循环 / 词元估算都依赖
  provider 侧），只负责「能表达 + 能持久化」；压不压、压哪段由宿主决定
- **上下文占用指示器（`chatInput().setContextUsage(used, window, costUsd)`）** —
  输入区底部工具栏里的小圆环（与「清空上下文」同排的**默认组件**，无数据时
  画空底环、`window<=0` 按 0%；非进度条：
  占用是标量不是过程），三档配色（<60% 弱化 / 60~85% 警示 / >85% 危险），
  hover 显示花费 / 百分比 / 词元数，**可点击**（发 `contextUsageClicked`，弹面板归宿主），
  `setContextUsageVisible(on)` 控显隐。
  数据全由宿主
  提供，**不进 `ElaChatStats`**（那个字段的 `merge()` 是各步求和语义，上下文
  占用是当前值）
- **会话统计（`view.sessionStats(limit=0)` → `ElaChatSessionStats`）** —
  计数（总 / 用户 / 助手）、当前上下文的四路词元（输入 / 输出 / 推理 /
  缓存读 + 写）与合计、使用率（给了 `limit` 时）、会话累计成本、最后活动时间；
  以及**工具调用统计**：`tool_calls`（总次数）、`tool_rounds`（轮数 = 有工具
  调用的步骤数，消息内按 `step` 去重）、`tool_errors` / `tool_aborted` /
  `tool_unsettled`（按状态分档，`unsettled` = pending + running）、
  `tool_counts`（工具名小写归一 -> 次数）、`reasoning_ms`（思考耗时合计）。
  口径对齐 opencode `getSessionContext`（取**最后一条有 tokens 的助手消息的
  最后一步**，不是全会话求和）。**四路词元互不重叠：输入只含未命中缓存的
  部分** —— OpenAI / DeepSeek 的 `prompt_tokens` 包含缓存命中，`binder` /
  `journal` 落库前会扣掉（`chat/_usage.py`），Anthropic 的 `input_tokens`
  本身不含、原样使用；直接构造 `ElaChatStats` 时也要按这个口径填。四路和用
  `ElaChatStats.contextTokens()`（reasoning 不重复加；服务端缺 `total_tokens`
  时用量徽标的「总计」也回退到它）。省事可以
  直接把 `total_tokens` / `total_cost_usd` 喂给上面的上下文圆环
- **成本（`ElaChatStats.cost_usd` / `ModelPricing` / `stats_cost`）** —
  定价表不烤进库（价格会变、还分上下文长度阶梯），库只提供换算纯函数：
  `output` 与 `reasoning` 同价、按输入侧总量选阶梯档、最后除以 1e6。
  宿主也可以自己算好直接填 `cost_usd`
- **ElaChatView** — 消息列表：用户气泡右对齐（可选中纯文本、最大宽度可调）、
  助手消息按步骤化分段组织（思考段 → 正文段（可多段）→ 每步工具面板 →
  步骤用量徽标），正文复用 `ElaMarkdownViewer` **嵌入模式**（透明背景 /
  隐藏滚动条 / 高度贴合内容（文末空白不计入高度），公式 / Mermaid /
  代码高亮能力一致）、
  系统消息居中弱化；
  贴底自动跟随（10px 判定）+ 上滚暂停 + 离底 >400px 才显示「回到底部」
  （浮动按钮为**实心强调色**底 + 对比色箭头，悬停 / 按下走 `PrimaryHover` /
  `PrimaryPress` 槽位，跟随 `eTheme` 强调色与深浅主题）；
  展开 / 收起工具卡时暂停跟随（`holdFollow`），视口保持不动不跳动；
  嵌套滚动区（Markdown / 工具输出）防脱离；turn 间隔节奏；空态标题 /
  副标题 / 建议按钮列表；多步骤流式 API（`beginStep` / `beginText` /
  `appendText` / `endText` / `setStepStats`）与消息动作透传（均带消息 id）；
  错误类型单独存字段（`setMessageError(id, msg, errorType)` /
  `messageError(id)`），错误卡据此决定是否点亮「重试」（限流 / 超时 / 网络
  类可重试，参数错误 / 鉴权失败 / 内容过滤不点）；
  上下文占用圆环 `setContextUsage(used, window, costUsd)`；
  头像自定义 `setUserAvatar` / `setAssistantAvatar`（SVG / 路径 / `QPixmap` 等）、
  形状 `setAvatarShape`（默认圆形 / `rounded` / `square`）；
  免责提示文案 / 显隐 `setDisclaimer(text)` / `setDisclaimerVisible(on)`
  （默认 `DISCLAIMER_TEXT`，只作用于助手消息，空文案自动隐藏）
- **ElaChatInput** — 单卡片输入区（对齐 opencode：附件条 / 多行输入 / 工具栏
  同在一个圆角卡片内——`inputSurface()`；聚焦时边框转强调色，空草稿时发送
  按钮置灰）；卡片上方是补全浮层（`@` 引用，provider 接口）；
  附件条（`ElaChip` / 图片缩略卡，拖放 + 粘贴图片 + 去重；粘贴图片的**图像**
  随附件对象流转 —— 消息气泡与撤回回填都有缩略图，**不序列化**，落库 /
  恢复历史后回退为文件 chip）；
  多行输入（默认 3–8 行，`Enter` 发送 / `Shift+Enter` 换行，IME 安全）；
  工具栏左组 = 新建话题 + 添加文件（`Ctrl+U`，回形针）+ 清空上下文，右组 =
  发送 / 停止；三个左组按钮各自可隐（`setNewTopicVisible` /
  `setAddFileVisible` / `setClearVisible`，文件选择走 `setFilePicker`）；
  **发送 / 停止同按钮**：流式中草稿为空才显示「停止」，有草稿仍为「发送」
  （默认交由宿主排队，`setQueueEnabled` 可关）；`Esc` / `Ctrl+G` 停止；
  文件进入输入区的通道：`attachments()` 快照（含 `path`）/ `attachmentPaths()` 路径列表 /
  `attachmentsChanged` 信号 / 提交时 `messageSubmittedFull(text, attachments)`
- **ElaChatToolBar / ElaChatToolButton** — 可复用水平工具栏：
  `leading` / `trailing` 两段，追加 `addButton` / `addWidget` /
  `addSeparator` 与插入版 `insertButton` / `insertWidget` /
  `insertSeparator(before)`（落在参照项所在分区），动态状态
  `setItemVisible` / `setItemEnabled`（按钮 / 控件 / 分隔线都接受句柄），
  移除 `removeItem`（销毁控件；分隔线也可）/ `removeSeparator`（单独移除
  一条分隔线，分隔线无 key、只能给句柄）/ `clear(zone)`（分段清空；zone
  非法值抛 `ValueError`），事件
  `toolTriggered(key)` / `toolToggled(key, checked)`；图标按钮为
  `ElaIconButton`（原生方形 / `IsSelected`），文字按钮为 `ElaButton`；
  `compact` 模式供消息底部操作栏复用
- **ElaChatBubble** — 步骤化消息气泡（可独立复用）：头部（头像 + 名称 +
  时间 / 状态；头像支持内置图标与自定义图 `setAvatarImage`——SVG 数据 /
  SVG 或位图路径 / `bytes` / `QPixmap` / `QImage` / `QIcon`，默认圆形裁切，
  `setAvatarShape` 可切圆角方形 / 直角方形）、
  内容分段（按加入顺序组成时间线：`ElaChatPart` 的
  reasoning / text / tool / stats 四类，正文段可多段；另有 `Permission`（审批 / 问答向导）、`Compaction`
   （压缩分隔）、`Synthetic`（steer 回执）三种「非正文段」—— **它们的 `text`
   都不并入 `message.text`**：插话是旁注、摘要是历史的替代物，并进去等于算两遍）、思考段
  （`ReasoningBlock` 折叠块，或 `setReasoningStyle("inline")` 内联
  + `ThinkingRow` 思考行，逐段跟随位置）、每步工具面板（外层
  `ToolGroupPanel`「工具调用 (N)」，运行中显示 `(已完成/总数)`；**折叠态
  标题带一行摘要**：单调用「工具调用：工具名 · 关键参数」，多调用
  「工具调用 (N) · 名称计数」，过长按宽度省略、悬停看全文；
  内部 `ToolCallCard` 默认折叠、pending 锁定、参数摘要、失败转错误卡；
  `ContextToolGroupCard` 自动归并 read/glob/grep/list 并显示计数）、
  步骤用量（`setStepStats` 追加 `StatsBadge`）、附件条
  （`AttachmentStrip`）、底部（`MessageMeta` 整轮耗时 +
  `MessageActions` 悬停显现的复制 / 撤回 / 重新生成，占位用
  `RetainSizeWhenHidden` 保留、消息区不跳动，按钮带 ElaToolTip 提示；
  未悬停时 `actions().isVisibleTo(...)` 为 False 属预期，判断可用性看
  `actions()` 是否存在 + `isEnabled()`；复制落定弹 `ElaMessageBar`
  确认，默认开、`setCopyNotificationEnabled` 可关）；助手流式
  `beginStream` / `appendText` / `endStream`（`streamFinished` 信号），
  **等待首个 token（TTFT）期间默认在气泡内显示 `ElaShimmer` 文本骨架** ——
  它不是 `ElaChatPart`，不进 `parts` / 导出 / journal；收到首个正文 / 思考 /
  工具 / 审批 / 统计即隐藏，`setWaitingPlaceholderEnabled(False)` 可关；
  `parts()` 返回当前分段快照；免责提示可单条改
  （`setDisclaimer` / `setDisclaimerVisible`，用户气泡恒不显示）
- **ElaChatQueueDock / ElaChatInputDock / ElaChatPermissionDock** — 输入区
  上方的三个 dock：排队消息（N 条 + 预览 + 立即发送 / 编辑 / 移除，
  `enqueueMessage` / `sendQueuedNow` / `editQueuedMessage`）；通用**替换
  输入区**的 dock（宿主自定义卡片，`setDockWidget`）；审批交互卡（等待回复
  时停在输入区上方，答完落成时间线上的折叠记录卡 —— 两者不是同一个
  widget，详见上面的「工具审批」）
- **ElaChatStreamBinder** — 流式事件 → 组件映射器（宿主接入推荐入口）：
  构造传 `worker` 即**自动接线**（`llmStarted` / `chunkReceived` /
  `toolStarted` / `toolEnded` / `statsReady` / `emptyTurn`，也可稍后
  `connectWorker(worker)`）；`startTurn(prompt, regenerate=False,
  attachments=None)` 返回**回合 token**，把它交给
  `finish(turn, status=None)` 闭环回合（建助手消息 + `beginTurn` + 驱动后端，
  后端未就绪返回 `None` 且不建空消息；**认不出的迟到收尾直接丢弃并返回
  `None`** —— 后端 `cancel()` 是异步的，旧回合的 `turnFinished` 可能在新回合
  开起来之后才到；**重新生成要把
  `message.attachments` 一起传**，否则模型看不见用户上传的文件）；
  `shutdownOnClose(window)`
  在窗口关闭 / 销毁时自动 `worker.shutdown()`（宿主免写 `closeEvent`）；
  细粒度 API：`beginTurn` /
  `beginRound`（第 2 轮起自动分步）、`reasoning` / `answer` /
  `stream(chunk)`（同一轮思考复用一块、正文自动结束思考段）；
  `toolStart(callId, name, arguments)` / `toolEnd(callId, result, ok=None)`
  （`ok=None` 按 `"Error:"` 前缀推断失败）与便捷方法
  `toolCallStarted(toolCall)` / `toolCallEnded(toolCall, result)`
  （直接接 OpenAI 风格 `tool_call` dict 信号）；`stats(usage, ttftMs, tps)`
  （兼容 OpenAI `usage` / `ElaChatStats`）、`error` / `emptyTurn`；
  `cancel()` 记录停止（收尾思考段），此后 `finish(turn)` 自动按
  `Stopped` / `Done` 收尾（显式传参优先）；`finish(turn, status=None)`（补整轮耗时、
  结束消息、返回 `ElaChatTurnSummary` 摘要：状态 / 是否输出过正文 /
  `finish_reason` / 耗时；同一 token 二次调用属陈旧收尾，返回 `None`）
- **ElaChatAsyncWorker** — 异步后端 worker 基类（QThread + asyncio 事件
  循环 + 命令队列 + 取消收尾），信号契约与 `ElaChatMockBackend` 同构；
  子类只需实现 `_setup()`（初始化后端）、`_stream_turn(prompt,
  attachments)`（异步分片迭代器）与可选的 `_rollback_turn(prompt,
  attachments)` / `_after_turn` / `_reset_backend`，
  线程安全命令 `ask(text, attachments=None)` / `regenerate(text,
  attachments=None)` / `reset` / `cancel` / `shutdown`（附件原样透传，
  后端要什么格式由子类决定）。`ask` / `regenerate` 返回**回合 token**
  （未就绪 `None`），`turnFinished` 载荷原样带回 —— 宿主直接
  `worker.turnFinished.connect(binder.finish)` 即可，无需手动转发
- **ElaChatMockBackend** — 模拟后端（QTimer，无线程 / 无模型服务）：
  信号与真实 worker 同构（`ready` / `llmStarted` / `chunkReceived` /
  `toolStarted` / `toolEnded` / `statsReady` / `turnFinished` 等），
  `ask` / `regenerate` / `cancel` / `reset` / `setThinkLevel("off" |
  "normal" | "deep")` / `setReplyProvider(provider)` / `setTickMs`
  （`0` 快进）；两步回合覆盖思考 → 上下文工具 → 统计 → 失败工具 → 正文
- **ElaChatStatusBar** — 宿主状态栏：左侧弱化信息（`setInfo`，
  模型 / 服务地址）+ 右侧状态文本（`setStatus(text, level)`，
  `info` / `busy` / `success` / `error` 四档语义配色），
  `setBusy(True)` 状态前显示 `ElaProgressRing`
- **ElaMarkdownViewer 嵌入模式** — `setEmbeddedMode(True)`：透明背景、
  隐藏滚动条、高度随文档（含流式）自适应、滚轮事件交给外层容器；
  `setEmbeddedExtra(px)` 调整高度余量，`setEmbeddedTrimBottom(True)`
  让高度贴合内容（文末段落下边距不计入，聊天正文 / 内联思考默认启用）
- **持久化 / 会话 bundle** — 消息 / 分段 / 工具 / 用量 / 附件成对
  `toDict()` / `fromDict()`（纯 JSON、容错、带 `SCHEMA_VERSION`）；JSON 文本
  统一走 `jsonDumps` / `jsonLoads` / `jsonBackend`：**装了 `orjson` 自动用
  orjson**（`pip install pyqt6-ela-pro[all]`），否则标准库 json，两套后端
  同为紧凑 UTF-8、`allow_nan=False` 语义一致；读回
  `view.addMessageFromDict()`（保留 id）或 `view.restoreMessages(items,
  preserveIds=True)`（批量渐进渲染：先渲染最新的一屏，更早的消息在滚动到顶部时
  分页补齐；`batchRenderFinished` 在首批排空时发出，未渲染消息的
  `renderDeferred()` 仍为 True，数据用 `message()` 快照读）；无 parts 的旧格式
  助手消息（`stats` / `reasoning` / `tool_calls` 只在消息级）也会原样保留；
  整会话
  `view.exportSession(session, extra)` / `view.importSession(bundle,
  clear=True)`（bundle = session 元数据 + messages + 外观选项，clear 时保留
  原 id）；`ElaChatSessionInfo` 提供会话元数据快照 + `toDict/fromDict`；
  回合中途崩溃用 `ElaChatTurnJournal` 追加写事件流恢复（示例见
  `chat/__init__.py` docstring）；`connectWorker()` 会自动跟随 `llmStarted`
  切步（第 1 轮不切，此时别再手动 `beginStep`），同一步重复上报的用量按
  最新值覆盖，正文 / 思考 / 步骤时长自动记录
- **历史会话虚拟化** — 批量恢复时首屏之外的消息只保存 `parts` 数据、
  不建工具卡 / 思考块 / 查看器（`bubble.partsDeferred()` 为 True）；滚动到
  附近时按页物化，也可显式 `view.materializeMessage(id)` /
  `view.scrollToMessage(id)`。超过 24 步的超长消息只物化末尾 12 步，其余
  折叠成「展开全部」按钮（`bubble.partsWindowed()` / `expandParts()`）；
  完整 `parts` / `messages()` / 导出始终是全量数据。批量超过 80 条时连
  **气泡壳**也延迟（只留等高占位，`bubble(id)` 对未物化消息返回 `None`），
  滚远后已物化的消息会收回占位（`setShellVirtualizationEnabled` 可控）；
  **超过 200 条改用 spacer 虚拟列表**（上下两个 spacer + 只保留视口附近的
  气泡，不再逐条建占位，`setVirtualListEnabled` 可控）。物化按帧进行
  （每帧最多 4 条、离视口最近的先建、窗口始终保持连续），跳转时优先铺满
  视口；未物化区域画轻量骨架条（不建子控件），滚动时不会出现纯空白。
  `view.setVirtualPartsEnabled(False)` 可关闭分段延迟物化（小会话 / 测试
  需要逐控件断言时使用）
- **多话题（架构 B）** — 组件是单话题视图，多话题按「一话题一 widget」放大：
  `ElaTabBar` 做话题列表 + `QStackedWidget` 切页（完整参考实现见
  `example/chat_session_page.py`：懒建页面 / 切页不中止生成 / 归档恢复 /
  外观偏好传播）；组件侧只用 `setCurrentSessionId()` 记一个纯标记，
  会话列表归宿主

**接入真实 AI 后端（推荐：交给 ElaChatStreamBinder）**：

```python
from pyqt6_ela_pro.chat import ElaChatStatusType, ElaChatStreamBinder

binder = ElaChatStreamBinder(chat, worker=worker)     # 自动接机械信号
binder.shutdownOnClose(window)                        # 关窗自动收尾后端

worker.ready.connect(on_ready)                        # UI 状态归宿主
worker.failed.connect(on_failed)
worker.errorOccurred.connect(on_error)
worker.turnFinished.connect(binder.finish)             # 载荷就是回合 token

def on_submit(text, attachments):
    # 建消息 + 重置计时 + ask；附件原样送进后端（要附件就接 messageSubmittedFull）
    if binder.startTurn(text, attachments=attachments) is None:
        status_bar.setStatus("后端未就绪", level="error")
    # startTurn 返回回合 token；worker.turnFinished 原样带回，直接 finish 即可

def on_turn_finished(turn):
    summary = binder.finish(turn)         # cancel 过自动 Stopped，否则 Done
    if summary is None:                    # 认不出的迟到收尾，已被丢弃
        return
    if summary.status == ElaChatStatusType.Stopped:
        status_bar.setStatus("已停止（保留已输出内容）")
    elif summary.isEmptyReply():
        status_bar.setStatus("模型未返回正文", level="error")

def on_stop():                         # chat.stopRequested → 宿主停止
    binder.cancel()                    # 记录停止 + 收尾思考段
    worker.cancel()                    # 中止后端数据流
```

未接后端时可先用 `ElaChatMockBackend` 跑通 UI（信号同构，直接替换
`worker`）；真实异步后端（OpenAI 兼容流式 SDK 等）可继承
`ElaChatAsyncWorker`，只写 `_setup()` / `_stream_turn(prompt,
attachments)` 即可获得线程、
事件循环、命令队列与取消收尾；停止按钮连接 `binder.cancel()` +
`worker.cancel()`（组件只负责 UI 收尾，`binder.finish(turn)` 会自动按
`Stopped` 收尾）。

**宿主侧会话操作**（组件内完成，后端中止 / 历史回滚仍归宿主）：

```python
target = chat.undoMessage(messageId)          # 删该条及其后 + 原文/附件回填
userMessage = chat.regenerateFrom(messageId)  # 删原回答，返回前置用户消息
# 重新生成：附件必须一起带上（快照里就有）
binder.startTurn(
    userMessage.text, attachments=userMessage.attachments, regenerate=True
)
chat.setAutoSendQueue(True)                   # 回合结束自动续发队首（默认开）
chat.sendNextQueued()                         # 或手动触发
```

**参数约定**：`ElaChatView` 层方法以 `messageId` 为首位参数（工厂方法
除外）；`ElaChatWidget` **没有同名转发层**，只保留维护 widget 独占状态的
方法（`clear` / `setMessageError` / `removeMessage` / 排队 / steer / 撤回 /
重生 / 重试等），分段流式与消息内容操作一律经 `chatView()`。

**派生字段**：助手消息以 `parts` 为唯一内容来源，`text` / `reasoning` /
`tool_calls` / `stats` 由 `withParts()` 重算（详见 `ElaChatMessage` docstring）。


---

**延伸阅读**：应用内 API 指南见 `pyqt6_ela_pro/example/chat_guide_page.py`；可运行示例是 `example/` 下的聊天五页（总览 / 输入区能力 / Agent 能力 / 会话管理 / 持久化与性能）；最小接入示例在仓库 `llm_test/`（不入库）。
