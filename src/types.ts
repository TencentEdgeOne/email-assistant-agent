/**
 * SSE event contract — keep in sync with backend handlers
 * (``run.py`` / ``review.py`` / ``scheduled.py``).
 *
 * Event types:
 *   - ``session``               — first frame of every stream; carries conversationId
 *   - ``state_update``          — LangGraph stream_mode="updates" payload
 *   - ``progress``              — node-level narration from stream_mode="custom"
 *                                 (e.g. "🧠 LLM 正在分类 10 封邮件…")
 *   - ``human_review_required`` — interrupt() payload from the review node
 *   - ``paused``                — sentinel "[PAUSED]" string
 *   - ``cancelled``             — sentinel "[CANCELLED]" string
 *   - ``error_message``         — backend-side error
 *   - ``done``                  — final summary payload
 *   - ``end``                   — sentinel "[DONE]" string
 */

// ─── Domain types (mirror agents/email/_models.py) ─────────────────────────

export type EmailCategory =
  | 'urgent_customer'
  | 'meeting'
  | 'internal'
  | 'marketing'
  | 'notification'
  | 'followup'
  | 'spam'
  | 'billing'
  | 'other';

export type Tone =
  | 'formal'
  | 'friendly_professional'
  | 'apologetic'
  | 'urgent'
  | 'concise';

export type ReviewAction =
  | 'approve'
  | 'edit'
  | 'reject'
  | 'regenerate'
  | 'skip';

export interface Email {
  id: string;
  /** Pydantic field name (default serialization) */
  sender?: string;
  /** Pydantic alias — only present if serialized with by_alias=True */
  from_?: string;
  /** Legacy fallback */
  from?: string;
  to: string[];
  subject: string;
  body_text?: string;
  body_html?: string;
  received_at: string;
  thread_id: string | null;
  has_ics?: boolean;
}

export interface ClassifiedEmail {
  email: Email;
  category: EmailCategory;
  needs_reply: boolean;
  priority: number;
  reason: string;
}

export interface DraftItem {
  email_id: string;
  to: string[];
  subject: string;
  body: string;
  tone: Tone;
  template_used: string | null;
  confidence: number;
  rationale: string;
}

export interface ReviewDecisionInput {
  action: ReviewAction;
  edited_body?: string;
  feedback?: string;
}

export type RunTask = 'daily_digest' | 'triage_only' | 'single_reply';

// ─── SSE frames ────────────────────────────────────────────────────────────

export interface SSEFrame {
  event?: string;
  data: unknown;
}

export interface SessionPayload {
  type: 'session';
  conversationId: string;
  task?: string;
  resumed?: boolean;
  decision?: ReviewAction;
}

/** LangGraph stream_mode="updates" payload — keys are node names. */
export type StateUpdatePayload = Record<string, Record<string, unknown>>;

/** Custom-stream narration emitted by individual nodes via
 * ``langgraph.config.get_stream_writer``. The frontend consumes these
 * to render a live "what's happening right now" pill — most useful during
 * long-running stages (classify ~10s, draft ~20-30s) that previously felt
 * frozen to the user. ``phase`` matches a ``PipelineNode`` so the rendering
 * code can co-locate the chip with the right step in NodeFlowVisualizer. */
export interface ProgressPayload {
  /** Pipeline stage that emitted this event — matches PipelineNode. */
  phase: PipelineNode;
  /** Lifecycle marker. Frontend doesn't need to render every stage; the
   * ``message`` field is the human-readable narration.
   *
   * ``token`` carries an LLM streaming chunk in ``delta`` (not ``message``)
   * — the frontend accumulates these into a "live writing" bubble rather
   * than swapping the progress chip text. */
  stage:
    | 'started'
    | 'completed'
    | 'skipped'
    | 'error'
    | 'agent_start'
    | 'task_start'
    | 'task_complete'
    | 'token';
  /** Human-readable line — already pre-formatted with emoji + Chinese.
   * Empty when ``stage === 'token'`` (use ``delta`` instead). */
  message?: string;
  /** Token chunk text — only set when ``stage === 'token'``. */
  delta?: string;
  /** Set on draft-stage events only — CrewAI agent role string. */
  agent?: string;
  /** Set on draft-stage events tied to a specific email — used by the
   * frontend to highlight the correct row in the inbox tree. */
  email_id?: string;
  /** Set on draft-stage task_start / task_complete events — the CrewAI
   * Task name (analyze_task / draft_task / polish_task). */
  task?: string;
}

export interface HumanReviewPayload {
  type: 'human_review_required';
  interrupt_id: string;
  email_id: string;
  draft: DraftItem;
  options: ReviewAction[];
  remaining: number;
}

export interface DonePayload {
  summary: string;
}

export interface ErrorPayload {
  error: string;
}

// ─── Pipeline node taxonomy ────────────────────────────────────────────────

/** Order matters — left-to-right in the NodeFlowVisualizer. */
export const PIPELINE_NODES = [
  'fetch',
  'classify',
  'prioritize',
  'draft',
  'review',
  'apply',
  'summarize',
] as const;

export type PipelineNode = (typeof PIPELINE_NODES)[number];

export type NodeStatus =
  | 'pending'   // not visited yet
  | 'active'    // in progress
  | 'paused'    // hit interrupt() (only review)
  | 'done'      // finished
  | 'error';    // crashed
