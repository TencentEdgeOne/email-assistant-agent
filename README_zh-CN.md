# 邮件处理助手

基于 LangGraph + CrewAI (Python) 的 EdgeOne Makers Agent 全栈项目模板。演示多 Agent 协作、人机协作 (HITL) 审批流程，以及三栏式 SaaS UI 的实时 SSE 流式交互。

## 功能

- **多 Agent 协作** — CrewAI 三角色流水线（过滤 / 撰写 / 润色）生成邮件回复草稿
- **人机协作 (HITL)** — LangGraph `interrupt()` 在审批节点暂停，用户可通过/编辑/驳回/重写/跳过每封草稿
- **SSE 流式输出** — 逐 token 显示草稿撰写过程 + 逐节点进度播报
- **IMAP 邮箱集成** — 配置环境变量即可连接真实 Gmail/Outlook/QQ 邮箱
- **会话记忆** — 通过 `context.store.langgraph_checkpointer` 实现 LangGraph 状态持久化
- **三栏布局 UI** — 邮件分类树（左）+ 对话时间线（中）+ 流水线可视化（右）
- **停止与恢复** — 三层中断保障（客户端 abort + 服务端 stop + localStorage 标记）

## 目录结构

```text
email-assistant/
├── agents/                        # Python 后端（EdgeOne Makers Functions）
│   └── email/
│       ├── run.py                # POST /email/run — SSE 流式主入口
│       ├── review.py             # POST /email/review — HITL 恢复
│       ├── history.py            # POST /email/history — 会话列表/详情/删除
│       ├── stop.py               # POST /email/stop — 中断运行
│       ├── scheduled.py          # POST /email/scheduled — 定时触发
│       ├── health.py             # POST /email/health — 探活
│       ├── _graph.py             # LangGraph StateGraph 定义
│       ├── _nodes.py             # 8 个图节点（拉取/分类/排序/起草/审批/执行/总结/中止）
│       ├── _crew.py              # CrewAI 子流水线装配
│       ├── _agents.py            # 3 个 CrewAI Agent 构建器
│       ├── _tasks.py             # 3 个 CrewAI Task
│       ├── _tools.py             # CrewAI 工具（语气/模板/线程上下文）
│       ├── _models.py            # Pydantic v2 数据模型
│       ├── _providers.py         # 邮件 Provider（Mock + IMAP）
│       ├── _llm.py               # AI Gateway LLM 工厂
│       ├── _events.py            # CrewAI → LangGraph 事件桥接
│       ├── _sse_utils.py         # SSE 序列化工具
│       ├── _state.py             # LangGraph 状态 TypedDict
│       ├── _routing.py           # 条件边函数
│       ├── _skill_loader.py      # SKILL.md 解析器
│       ├── fixtures/             # 10 封示例 .eml 文件 + user_rules.json
│       ├── skills/               # email-tone + email-templates
│       └── prompts/              # classifier.md / prioritizer.md / summarizer.md
├── src/                           # React 前端（Vite + TypeScript）
│   ├── App.tsx                   # 主状态机（约 1500 行）
│   ├── api.ts                    # SSE 解析 + 会话 CRUD
│   ├── types.ts                  # 类型定义
│   ├── design-tokens.ts          # 设计系统 token
│   ├── historyStorage.ts         # localStorage 会话索引
│   ├── icons.tsx                 # Lucide SVG 图标
│   ├── index.css                 # 全局样式 + 关键帧动画
│   └── components/
│       ├── ChatLayout.tsx        # 三栏响应式布局 + 历史抽屉
│       ├── EmailInboxTree.tsx    # 左栏 — 邮件分类树
│       ├── ConversationStream.tsx # 中栏 — 消息时间线
│       ├── DraftReviewCard.tsx   # HITL 审批卡（通过/编辑/驳回/重写/跳过）
│       ├── EmailDetailDrawer.tsx # 滑出式邮件详情面板
│       ├── NodeFlowVisualizer.tsx # 右栏 — 流水线节点状态
│       └── HistorySidebar.tsx    # 历史会话侧栏（localStorage 驱动）
├── index.html                    # 入口 HTML（Inter + JetBrains Mono 字体）
├── edgeone.json                  # EdgeOne 项目配置
├── package.json                  # 前端依赖
├── requirements.txt              # Python 依赖
├── vite.config.ts                # Vite 配置
├── tsconfig.json                 # TypeScript 配置
└── .env.example                  # 环境变量参考
```

> 以 `_` 开头的文件是私有模块，不会被 EdgeOne 映射为公开路由。

## 环境变量

| 变量 | 必填 | 说明 |
|------|------|------|
| `AI_GATEWAY_API_KEY` | 是 | LLM API 密钥（平台自动注入） |
| `AI_GATEWAY_BASE_URL` | 是 | LLM API 地址（OpenAI 兼容） |
| `EMAIL_PROVIDER` | 否 | `mock`（默认）或 `imap` |
| `IMAP_HOST` | imap 时必填 | IMAP 服务器地址（如 `imap.gmail.com`） |
| `IMAP_USER` | imap 时必填 | 邮箱地址 |
| `IMAP_APP_PASSWORD` | imap 时必填 | 应用专用密码 |
| `IMAP_PORT` | 否 | 默认 `993` |
| `IMAP_USE_SSL` | 否 | 默认 `true` |

### 连接真实 Gmail 邮箱（IMAP）

按照以下步骤将你的 Gmail 接入模板：

1. **开启两步验证**
   - 打开 [Google 账号安全设置](https://myaccount.google.com/security)
   - 在「登录 Google 的方式」中，启用**两步验证**

2. **生成应用专用密码**
   - 打开 [应用专用密码](https://myaccount.google.com/apppasswords)
   - 选择应用："邮件"，选择设备："其他（自定义名称）" → 输入 "Email Assistant"
   - 点击**生成** → 复制生成的 16 位密码（格式如 `abcd efgh ijkl mnop`）

3. **配置环境变量**
   ```bash
   EMAIL_PROVIDER=imap
   IMAP_HOST=imap.gmail.com
   IMAP_USER=yourname@gmail.com
   IMAP_APP_PASSWORD=abcdefghijklmnop   # 去掉空格填入
   ```

4. **部署或重启** — 下次运行将从你的真实收件箱拉取邮件。

> **其他邮箱说明：** 其他支持 IMAP 的邮箱（Outlook、QQ 邮箱、163 等）配置方式类似，只需修改 `IMAP_HOST` 并使用对应的授权码：
> - Outlook：`IMAP_HOST=outlook.office365.com`
> - QQ 邮箱：`IMAP_HOST=imap.qq.com`（在 QQ 邮箱设置中生成授权码）
> - 163 邮箱：`IMAP_HOST=imap.163.com`（在 163 设置中开启 IMAP 并获取授权码）

## API 接口

| 端点 | 方法 | 说明 |
|------|------|------|
| `/email/run` | POST | SSE 流式运行，Header 带 `makers-conversation-id` |
| `/email/review` | POST | 从 HITL 中断恢复，Header 带 `makers-conversation-id` |
| `/email/history` | POST | 会话列表/详情/删除，Body 传 `{ "action": "list" \| "get" \| "delete" }` |
| `/email/stop` | POST | 中断正在执行的运行，Header 带 `makers-conversation-id` |
| `/email/scheduled` | POST | 定时触发的每日摘要 |
| `/email/health` | POST | 探活检查 |

### SSE 事件

```
event: session              data: {"type":"session","conversationId":"...","task":"daily_digest"}
event: state_update         data: {"classify":{"classified":[...]}}
event: progress             data: {"phase":"draft","stage":"started","message":"正在起草..."}
event: human_review_required data: {"draft":{...},"remaining":2}
event: done                 data: {"summary":"..."}
event: error_message        data: {"error":"..."}
data: [PAUSED]              # 运行暂停（等待审批）
data: [DONE]                # 运行完成
data: [CANCELLED]           # 运行被取消
```

## 架构

### 后端（`agents/email/`）

1. **LangGraph StateGraph** — 8 个节点编排完整的邮件处理流水线
2. **CrewAI 子流水线** — 三 Agent 草稿生成（过滤 → 撰写 → 润色）
3. **HITL `interrupt()`** — 图在 `review` 节点暂停，通过 `/email/review` 恢复
4. **双流模式** — `stream_mode=["updates","custom"]` 同时输出状态变更和进度播报
5. **邮件 Provider 抽象** — MockProvider（示例数据）/ IMAPProvider（真实邮箱），通过 `EMAIL_PROVIDER` 环境变量切换

### 前端（`src/`）

- `App.tsx` — SSE 状态机 + pipeline reducer + HITL 流程编排
- `api.ts` — SSE 解析 + 会话历史 CRUD + 模块级缓存
- `historyStorage.ts` — localStorage 会话索引（侧栏即时渲染，0ms 首屏）
- `components/ChatLayout.tsx` — 三栏响应式网格 + 历史抽屉覆盖层
- `components/ConversationStream.tsx` — 消息时间线 + 骨架屏加载态
- `components/DraftReviewCard.tsx` — 行内 HITL 卡片（通过 / 编辑 / 驳回 / 重写 / 跳过）
- `components/EmailInboxTree.tsx` — 分类收件箱 + 优先级徽标 + 操作按钮

## 本地开发

```bash
# 安装前端依赖
npm install

# 启动 EdgeOne 本地开发（前后端同时启动）
edgeone pages dev
```

## 许可证

MIT
