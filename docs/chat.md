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
- **模块分工（`chat/`）** — `widget*.py`：宿主组装 / 队列 / 插话 / 回合；`input*.py`：输入区（`input_parts` 内部控件、`input_completion` 补全 / 命令、`input_attachments` 附件 / 拖放、`input_history` 历史草稿、`input_toolbar` 工具栏 / 占用环；选择器是独立组件 `selector.py`）；`view*.py`：消息列表 / 虚拟化 / 搜索；`bubble*.py`：单条消息；`blocks/`：可复用块；`message` / `store` / `timeline`：数据层；`binder` / `worker` / `journal`：后端接入。
- **工具结果富渲染（`registerToolRenderer`）** — 宿主按工具名注册渲染器，库只
  替换工具卡的**内容区**（头部 / 折叠 / 错误竖线 / 忙碌环 / 展开策略仍由
  `ToolCallCard` 负责，故现有工具卡回归行为不变）：
  `registerToolRenderer(name, factory, *, subtitle=None, groupable=None)`；
  工厂签名 `(ToolRenderContext) -> QWidget`，返回 `None` 落回默认纯文本；
  可选实现 `updateToolResult(result, status)` 接收结果推送。
  `subtitle(arguments) -> (键, 值)` 的键会自动从参数摘要排除（防「3 个文件
  files=[...]」重复）；给上下文工具（read / glob / grep / list）注册默认退出
  分组（否则被分组卡绕过）。库内提供**可选**内置渲染器（见下「可选内置工具
  渲染器」），宿主仍可全部自行实现。**渲染器里的每个 `ColorText` 都要显式
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
    - **批准型**（`questions` 为空）：允许一次（实心强调色）/ 始终允许（描边、
      **`ElaLongPressButton`：要按住 700ms 才生效** —— 持久授权的误触代价比
      「允许一次」高一个量级）/ 拒绝…（危险色）—— **按重要性分档**，不是三个
      等权重文字按钮；可带反馈；长按期间按钮面被主题主色填满、文字自动换对比色；
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
  空数组会被模型读成「用户答了『一个都不选』」）、**自定义答案与候选项单选互斥、
  多选共存**（多选里自定义只是额外一项，勾选它不会取消其它选项）。
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
- **会话统计（`view.sessionStats(contextWindow=0)` → `ElaChatSessionStats`）** —
  计数（总 / 用户 / 助手）、当前上下文的四路词元（输入 / 输出 / 推理 /
  缓存读 + 写）与合计、使用率（给了 `contextWindow` 时）、会话累计成本、最后活动时间；
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
  形状 `setAvatarShape`（默认圆形 / `rounded` 8px 圆角 / `square` 4px 圆角）；
  免责提示文案 / 显隐 `setDisclaimer(text)` / `setDisclaimerVisible(on)`
  （默认 `DISCLAIMER_TEXT`，只作用于助手消息，空文案自动隐藏）；
  阅读列默认 768px 居中（`setContentMaxWidth()`，`0` 恢复全宽），
  用户气泡 / 助手正文 / 工具卡共用同一条列；输入区与 dock 同宽居中
  （只钉最大宽，不向宿主贡献固定下限）
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
  `attachmentsChanged` 信号 / 提交时 `messageSubmittedFull(text, attachments)`；
  `clear()` 清空整份草稿（文本 / @ 引用 / 附件），`ElaChatWidget.clear()` 只清会话、
  不碰输入区草稿
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
  `setAvatarShape` 可切 8px / 4px 圆角方形）、
  内容分段（按加入顺序组成时间线：`ElaChatPart` 的
  reasoning / text / tool / stats 四类，正文段可多段；另有 `Permission`（审批 / 问答向导）、`Compaction`
   （压缩分隔）、`Synthetic`（steer 回执）三种「非正文段」—— **它们的 `text`
   都不并入 `message.text`**：插话是旁注、摘要是历史的替代物，并进去等于算两遍）、思考段
  （`ReasoningBlock` 折叠块，或 `setReasoningStyle("inline")` 内联
  + `ThinkingRow` 思考行，逐段跟随位置）、每步工具面板（外层
  `ToolGroupPanel`「工具调用 (N)」，运行中显示 `(已完成/总数)`；**折叠态
  标题带一行摘要**：单调用「工具调用：工具名 · 关键参数」，多调用
  「工具调用 (N) · 名称计数」，过长按宽度省略、悬停由库内 `ElaToolTip` 显示全文（`set_tooltip`，与整库提示样式一致）；单卡标题 / 参数摘要同样只在真正被省略时绑提示；
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
  `example/chat_playground_page.py`：懒建页面 / 切页不中止生成 / 归档恢复 /
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

- **时间线通知（`ElaChatNotice`）** — `view.addNotice(messageId, noticeType, text, detail)`
  在消息时间线里追加一条弱化分隔行（模型 / agent / 目录切换、中断、指令更新、
  重启）。`noticeType` 取 `ElaChatNoticeType`，文案由宿主提供；通知的 `text`
  **不并入** `message.text`。
- **自动重试（`ElaChatRetryCard`）** — `view.setRetry(messageId, attempt, message,
  nextAt)` / `clearRetry` / `retryState`：显示「第 N 次重试 · Ns 后」+ 立即重试 /
  取消；`nextAt` 是 epoch 毫秒（0 = 无倒计时）。`ElaChatStreamBinder.retry(...)`
  是后端退避的快捷入口；`error()` / `finish()` 自动清重试态。
- **运行态活动行（`ElaChatWorkingRow`）** — `view.setActivity("正在运行命令…")`
  在时间线底部显示呼吸点 + 文案（空串隐藏）。`binder.setAutoActivity(True)`
  会在回合开始 / 工具调用 / 首字时自动维护；`setActivityProvider(fn)` 可覆盖文案。
- **时间线密度（`ElaChatTimelineDetail`）** — `view.setTimelineDetail(detail)`：
  thinking / shell / edit / subagents / notices / tools 六个分区，每个分区
  `placement`（hidden / collapsed / expanded）+ `details`（collapsed / expanded）。
  密度直接改变已存在控件的可见性与默认开合，**不重建文档**；hidden 工具仍保留
  在数据与导出里，只是不占视线。`view.setPartExpanded(partId, on)` 记录逐分段
  的手动披露状态，二者随 `exportSession` 的 `view` 段持久化。
- **会话内搜索（`ElaChatSearchBar` / `ElaChatSearchHit`）** —
  `view.searchText(query, caseSensitive=False)` 搜索助手正文 + 用户文本，
  `searchNext` / `searchPrev` 循环跳转并高亮；`view.showSearchBar()` /
  `hideSearchBar()`，`ElaChatWidget` 的 `Ctrl+F` 走同一入口。
- **Diff / 文件变更** — 顶层 `ElaDiffView`（基于 `ElaPlainTextEdit` +
  `editBorderlessStyle()`，继承 ElaScrollBar / ElaMenu；统一 diff：双行号、
  +/- 底色、Pygments 着色、折叠上下文、大 diff 上限），`ElaChatFileChanges` 是工具 body
  用的文件列表（每文件懒建 diff）；纯模型在 `pyqt6_ela_pro/_diff.py`
  （`parseUnifiedDiff` / `diffLines` / `filesFromMetadata`）。
  `ElaChatToolCall.metadata` 由宿主填写，约定：
  `{"files": [{"file", "patch" | "before" + "after", "additions", "deletions",
  "status"}], "diagnostics": ..., "shell": ...}`。
- **可选内置工具渲染器** — `installBuiltinToolRenderers()` 注册
  `shell` / `bash` / `execute`（复用 `ElaTerminalView`：ANSI 色彩 / 行数上限 /
  右键复制）、`edit` / `write` / `patch` / `apply_patch`（文件变更 + diff），
  以及 `read` / `view` / `cat`、`glob` / `list` / `ls`、`grep` / `search` /
  `find`、`fetch` / `webfetch` / `web` / `curl`、`mcp`、`todowrite` /
  `todo_write` / `update_todo_list`（只读 checklist）。**默认不注册**，
  同名宿主渲染器优先，`uninstallBuiltinToolRenderers()` 可整体摘掉。
  文本 body 统一走 `ElaTerminalView.setEmbedded`（去自带边框、12px、raised
  表面），图片预览走 `ElaImageCard`（保持比例、不放大）；`glob` / `list` /
  `ls` 与 `mcp` 的高度上限 420，其它文本 320，shell 仍为 260。JSON 结果会
  缩进展示（超过 256KB 跳过多余序列化）。
- **工具模型扩展** — `ElaChatToolCall` 增加 `kind`（`ElaChatToolKindType`，
  对齐 ACP：read / edit / delete / move / search / execute / think / fetch /
  switch_mode / subagent / other，空值按工具名推导）、`title`、`locations`
  （`ElaChatToolLocation{path, line}`）、`parent_id`（子代理嵌套）、
  `started_at` / `duration_ms`。`view.addToolCall(..., kind=, title=,
  locations=, parentId=, startedAt=, durationMs=)` 可直接传；`ToolRenderContext` 同步暴露这些字段。
- **计划 / 待办（`Plan` 分段）** — `view.setPlan(messageId, plan, partId=None)`
  接受 `ElaChatPlan` / dict / list / Markdown（`- [ ]` / `- [x]` / `- [>]`）；
  默认复用消息最后一张计划卡，反复上报不会堆卡。折叠态显示「当前项 + n/m」，
  展开是 checklist；随 `exportSession` / journal 持久化。读：
  `view.plan(messageId)` / `view.planPart(messageId)`，清空 `view.clearPlan`。
- **子代理嵌套** — 子调用 `parentId` 指向父工具（`task` / `subagent` / `agent` /
  `delegate_task`），父卡用 `SubagentCard`：头部任务 / 状态 / 统计，主体挂子
  `ToolCallCard` 与最终结果。父卡收起时子工具只登记数据、不建卡；首次展开按
  16 个一页物化，其余走「显示其余 N 个工具」，点击后按页异步补齐。`childCard()`
  会按需物化（兼容入口），`childCalls()` 返回全部快照。组头只统计顶层工具；
  `estimate_parts_height` 跳过子分段；删除 / 清空有 `is_deleted` 守卫。
- **回合变更汇总** — `view.turnChanges(messageId)` 从 `metadata["files"]`
  （参数兜底）按路径合并；回合结束后气泡底部自动显示
  「N 个文件变更 +x −y」，展开复用 `ElaChatFileChanges` /
  `ElaDiffView`。开关 `view.setChangeSummaryEnabled(on)`；汇总**不落库**，
  恢复时从工具 metadata 重新派生。
- **运行轨迹（`ElaChatTracePanel`）** — 独立面板（宿主放进 `ElaDialogBase` /
  `ElaContentDialog` 或 `QSplitter`；**别用裸 `QDialog`**，否则标题栏与底色都不跟主题）：
  `buildTraceRows(messages)` 按 **用户提问 → 助手响应 → 步骤 → 工具 /
  reasoning / plan / permission / compaction** 整理成树：一条用户消息开启一轮，
  其后的全部助手消息作为该轮的「响应」子节点。行带 `start_ms` / `span_ms` /
  `clipped` / `estimated` / `error_below` / `stats`。
  主视图**每轮一条响应密度条、每个响应独立局部时间标尺**（7071 行也只画可视区，
  不再逐行建控件）；异常耗时按全局 p99×2 裁剪、响应内空闲间隔压缩，真实值留在
  ElaToolTip 与轮头统计里。分类色只用 Ela 的 accent / status / muted（不走
  ECharts 分类色板），浅色 / 深色和宿主 `setAccentColor` 都会跟随。
  「流程图」页复用**只读** `ElaBlueprintCanvas`（`use_gl=False`，只画当前轮，
  120 节点上限；双击节点回跳消息）。视图 / 筛选用 `ElaPivot`，hover 详情用
  `ElaToolTip`，倍速用 `ElaDropDownButton` + `ElaMenu`。底部会话轨道按轮次画
  工具密度 / token 分层 / 上下文压力（`setContextWindow()` 给 70% / 90% 阈值线）；
  时间轴与 86px 趋势条是**性能例外的自绘视图**：Ela 没有 7000 行树形瀑布，
  3 个 `ElaChartWidget` 的原型 `setOption` 约 20ms 且丢失共享游标 / 点击跳转。
  `ElaChatTraceOptions(view/effects/replay/tracks)` + `setOptions()` /
  `setOption()` 热切换；`effects=False` 走纯平色无动画，适合弱机 / Win7。
  回放按**响应**从当前可见位置连续播到末尾（跨轮 / 跨响应自动推进、自动滚动跟随）：
  `startReplay()` / `stopReplay()` / `setReplaySpeed()` / `cycleReplaySpeed()`，
  速度 0.5×–20×；playhead 只重绘当前响应条带。`refresh()` 手动触发（流式分片不自动重建）；
  `rowActivated(messageId)` / `partActivated(messageId, partId)` 供宿主
  `scrollToMessage`；`turnChanged(index)` 给侧栏 / 外部导航。工具计时可经
  `view.addToolCall(..., startedAt=, durationMs=)` 传入。性能口径见
  `benchmarks/opencode_chat_replay/bench_trace.py` 与 `PERFORMANCE.md`。
- **输入区增强** — `ElaChatInput` 增加：
  - `setCommandProvider(provider)`：`/` 命令补全（`commandSelected`）；
    `setCommandSubmitMode("signal")` 时提交发 `commandSubmitted(text)` 且不落消息；
  - 下拉选择器：直接实例化 `ElaChatSelector`（模型 / agent / 变体），用
    `chat.toolBar().addWidget(selector, zone="leading")` 放进工具栏；与新建话题 /
    附件 / 清空 / 上下文圆环同排，追加在圆环右侧。`ElaChatSelectorItem(icon=...)`
    的图标同时显示在菜单项与当前项按钮上。组件直接发 `selectionChanged(itemId)`，
    输入区不维护选择器注册表；shell 模式会自动隐藏工具栏里的 `ElaChatSelector`；
  - `setShellMode(True)`：等宽字体、`Esc` 退出、提交走 `shellSubmitted(text)`；
  - `setHistory(ElaChatPromptHistory)`：↑/↓ 浏览提示历史，保留当前草稿；
  - `draftState()` / `setDraftState()` + 300ms `draftChanged`：宿主按会话保存草稿。
- **队列增强** — `ElaChatQueueDock` 增加「插话」（生成中）/ 撤销；
  `setSteerEnabled(False)` 时行按钮置灰、`steerQueued(queueId)` 返回 `False`
  （消息留在队列），`Ctrl+Enter` 回退排队（不受 `setQueueEnabled(False)` 限制）；
  `ElaChatWidget.moveQueued(queueId, toIndex)` / `steerQueued(queueId)` /
  `undoQueueChange()`（快照栈上限 20）。撤销覆盖队列增删改 / 排序 / 转为插话；
  `steerMessage` / `clearSteer` / `dequeueSteer` 不进撤销栈。`steerMessage` 在时间线上
  先建一条「待发送」用户消息，`drainSteer` 结算为已送达；「移到队列 / 删除」动作由
  `pendingUserActionRequested` 交给 widget 处理，回合结束 / 删消息时会同步清理未投递插话。
- **消息身份 / @ 提及** — `ElaChatMessage` 增加 `agent` / `model` /
  `model_variant` / `mentions` / `delivery`；`view.setMessageIdentity(...)` 后
  用户消息头显示 `agent · 模型`，助手底部 meta 显示 `agent · 模型 · 耗时 · 已中断`。
  `ElaChatInput.mentionSpans()` 给出带 id 的 `ElaChatMention` 区间，
  `setMentions()` 按当前文本恢复引用；草稿 / 提示历史 / 撤回 / 队列编辑都会保留
  引用。用户气泡按区间高亮，复制仍取纯文本。

**延伸阅读**：应用内 API 指南见 `pyqt6_ela_pro/example/chat_guide_page.py`；可运行示例是
`example/chat_playground_page.py` 的 **AI 组件实验台**：多话题聊天 + 输入区 + 右侧
`ElaSplitter` 面板。第一个 tab「快速体验」是 6 张引导场景（流式回合 / 批准审批 /
问答审批 / 工具链 / 消息操作 / 输入区），按脚本播放、可重放；后面 7 个 tab 是
API 实验台（基础 / 工具 / Agent / 消息 / 外观 / 输入 / 会话·高级），每项都有内联反馈。
页头「组件画廊」打开独立弹框，直接摆出 PlanPanel / ToolCallCard / PermissionCard /
文件变更 / 状态行 / 附件与队列 dock 等块组件。宿主的撤回 / 重新生成 / 重试 /
停止 / 建议 / 命令 / shell / 上下文占用点击都已接线；旧七工作区页面已移除。
最小接入示例在仓库 `llm_test/`（不入库）。
