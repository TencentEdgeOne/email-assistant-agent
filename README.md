# Email Assistant

A full-stack EdgeOne Makers Agent template powered by LangGraph + CrewAI (Python). Demonstrates multi-agent collaboration, human-in-the-loop (HITL) approval workflows, and real-time SSE streaming with a three-column SaaS UI.

## deploy
[![Deploy to EdgeOne Makers](https://cdnstatic.tencentcs.com/edgeone/pages/deploy.svg)](https://edgeone.ai/makers/new?template=email-assistant-agent&from=within&fromAgent=1&agentLang=python)

## Features

- **Multi-Agent Collaboration** — CrewAI three-role pipeline (filter / writer / polisher) generates email drafts
- **Human-in-the-Loop** — LangGraph `interrupt()` pauses at the review node; user approves / edits / rejects / regenerates / skips each draft
- **SSE Streaming** — Token-by-token draft writing + per-node progress narration in real time
- **IMAP Integration** — Connect a real Gmail/Outlook/QQ mailbox via environment variables
- **Session Memory** — LangGraph checkpointer via `context.store.langgraph_checkpointer`
- **Three-Column UI** — Inbox tree (left) + conversation timeline (center) + pipeline visualizer (right)
- **Stop & Resume** — Triple-layer cancellation (client abort + server stop + localStorage flag)

## Directory Structure

```text
email-assistant/
├── agents/                        # Python backend (EdgeOne Makers Functions)
│   └── email/
│       ├── run.py                # POST /email/run — SSE streaming main entry
│       ├── review.py             # POST /email/review — HITL resume
│       ├── history.py            # POST /email/history — conversation list/get/delete
│       ├── stop.py               # POST /email/stop — abort active run
│       ├── scheduled.py          # POST /email/scheduled — cron trigger
│       ├── health.py             # POST /email/health — health check
│       ├── _graph.py             # LangGraph StateGraph definition
│       ├── _nodes.py             # 8 graph nodes (fetch/classify/prioritize/draft/review/apply/summarize/abort)
│       ├── _crew.py              # CrewAI sub-pipeline assembly
│       ├── _agents.py            # 3 CrewAI Agent builders
│       ├── _tasks.py             # 3 CrewAI Tasks
│       ├── _tools.py             # CrewAI tools (tone/template/thread-context)
│       ├── _models.py            # Pydantic v2 data models
│       ├── _providers.py         # Email providers (Mock + IMAP)
│       ├── _llm.py               # AI Gateway LLM factory
│       ├── _events.py            # CrewAI → LangGraph event bridge
│       ├── _sse_utils.py         # SSE serialization utilities
│       ├── _state.py             # LangGraph state TypedDict
│       ├── _routing.py           # Conditional edge functions
│       ├── _skill_loader.py      # SKILL.md parser
│       ├── fixtures/             # 10 sample .eml files + user_rules.json
│       ├── skills/               # email-tone + email-templates
│       └── prompts/              # classifier.md / prioritizer.md / summarizer.md
├── src/                           # React frontend (Vite + TypeScript)
│   ├── App.tsx                   # Main state machine (~1500 lines)
│   ├── api.ts                    # SSE parsing + history CRUD
│   ├── types.ts                  # Type definitions
│   ├── design-tokens.ts          # Design system tokens
│   ├── historyStorage.ts         # localStorage conversation index
│   ├── icons.tsx                 # Lucide SVG icons
│   ├── index.css                 # Global styles + keyframes
│   └── components/
│       ├── ChatLayout.tsx        # Three-column responsive shell + history drawer
│       ├── EmailInboxTree.tsx    # Left column — classified inbox tree
│       ├── ConversationStream.tsx # Center column — message timeline
│       ├── DraftReviewCard.tsx   # HITL approval card (approve/edit/reject/regenerate/skip)
│       ├── EmailDetailDrawer.tsx # Slide-out email detail panel
│       ├── NodeFlowVisualizer.tsx # Right column — pipeline node status
│       └── HistorySidebar.tsx    # History sidebar (localStorage-backed)
├── index.html                    # Entry HTML (Inter + JetBrains Mono fonts)
├── edgeone.json                  # EdgeOne project config
├── package.json                  # Frontend dependencies
├── requirements.txt              # Python dependencies
├── vite.config.ts                # Vite config
├── tsconfig.json                 # TypeScript config
└── .env.example                  # Environment variable reference
```

> Files prefixed with `_` are private modules — not mapped as public routes by EdgeOne.

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `AI_GATEWAY_API_KEY` | Yes | LLM API key (injected by platform) |
| `AI_GATEWAY_BASE_URL` | Yes | LLM API base URL (OpenAI-compatible) |
| `EMAIL_PROVIDER` | No | `mock` (default) or `imap` |
| `IMAP_HOST` | When `imap` | IMAP server host (e.g. `imap.gmail.com`) |
| `IMAP_USER` | When `imap` | Email address |
| `IMAP_APP_PASSWORD` | When `imap` | App-specific password |
| `IMAP_PORT` | No | Default `993` |
| `IMAP_USE_SSL` | No | Default `true` |

### Connecting a Real Gmail Mailbox (IMAP)

Follow these steps to connect your Gmail account:

1. **Enable 2-Step Verification**
   - Go to [Google Account Security](https://myaccount.google.com/security)
   - Under "How you sign in to Google", enable **2-Step Verification**

2. **Generate an App Password**
   - Go to [App Passwords](https://myaccount.google.com/apppasswords)
   - Select app: "Mail", select device: "Other (Custom name)" → enter "Email Assistant"
   - Click **Generate** → copy the 16-character password (e.g. `abcd efgh ijkl mnop`)

3. **Set Environment Variables**
   ```bash
   EMAIL_PROVIDER=imap
   IMAP_HOST=imap.gmail.com
   IMAP_USER=yourname@gmail.com
   IMAP_APP_PASSWORD=abcdefghijklmnop   # remove spaces from the generated password
   ```

4. **Deploy or restart** — the next run will fetch real emails from your inbox.

> **Note:** Other IMAP-compatible providers (Outlook, QQ Mail, 163, etc.) follow a similar pattern — just change `IMAP_HOST` and use the corresponding app password mechanism. For example:
> - Outlook: `IMAP_HOST=outlook.office365.com`
> - QQ Mail: `IMAP_HOST=imap.qq.com` (use authorization code from QQ Mail settings)
> - 163 Mail: `IMAP_HOST=imap.163.com` (use authorization code from 163 settings)

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/email/run` | POST | SSE streaming run. Header: `makers-conversation-id` |
| `/email/review` | POST | Resume from HITL interrupt. Header: `makers-conversation-id` |
| `/email/history` | POST | Conversation list/get/delete. Body: `{ "action": "list" \| "get" \| "delete" }` |
| `/email/stop` | POST | Abort active run. Header: `makers-conversation-id` |
| `/email/scheduled` | POST | Cron-triggered daily digest |
| `/email/health` | POST | Health check |

### SSE Events

```
event: session              data: {"type":"session","conversationId":"...","task":"daily_digest"}
event: state_update         data: {"classify":{"classified":[...]}}
event: progress             data: {"phase":"draft","stage":"started","message":"正在起草..."}
event: human_review_required data: {"draft":{...},"remaining":2}
event: done                 data: {"summary":"..."}
event: error_message        data: {"error":"..."}
data: [PAUSED]              # Run paused (waiting for review)
data: [DONE]                # Run completed
data: [CANCELLED]           # Run cancelled
```

## Architecture

### Backend (`agents/email/`)

1. **LangGraph StateGraph** — 8 nodes orchestrating the full email processing pipeline
2. **CrewAI Sub-pipeline** — Three-agent draft generation (filter → writer → polisher)
3. **HITL via `interrupt()`** — Graph pauses at `review` node, resumes via `/email/review`
4. **Dual streaming** — `stream_mode=["updates","custom"]` for both state diffs and progress narration
5. **Email Provider abstraction** — MockProvider (fixtures) / IMAPProvider (real mailbox) via `EMAIL_PROVIDER` env

### Frontend (`src/`)

- `App.tsx` — SSE state machine + pipeline reducer + HITL flow orchestration
- `api.ts` — SSE parser + conversation history CRUD + module-level cache
- `historyStorage.ts` — localStorage-backed conversation index (instant sidebar rendering)
- `components/ChatLayout.tsx` — Three-column responsive grid + history drawer overlay
- `components/ConversationStream.tsx` — Message timeline with skeleton loading states
- `components/DraftReviewCard.tsx` — Inline HITL card (approve / edit / reject / regenerate / skip)
- `components/EmailInboxTree.tsx` — Categorized inbox with priority badges and action buttons

## Local Development

```bash
# Install frontend dependencies
npm install

# Start EdgeOne local dev (frontend + backend)
edgeone pages dev
```

## License

MIT
