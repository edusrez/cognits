/** SSE event contract between backend (routes_stream.py) and frontend.

Each event type mirrors the backend's wire format exactly.
Named events use 'event:' line; token frames use no event line (default).

@see AGENTS.md "SSE wire format" for the full specification.
@see src/cognits/server/routes_stream.py for the backend implementation.
*/

// --- Named events ---

export interface HistoryEvent {
  messages: MessageRow[];
  toolStatus: string;
  liveContent: string;
  liveReasoning: string;
  liveReports: { reportId: string; reportTitle: string }[];
  agentActive: boolean;
}

export interface ReasoningEvent {
  content: string;
}

export interface ErrorEvent {
  message: string;
}

export interface ToolStartEvent {
  name: string;
  [key: string]: unknown;
}

export interface ToolEndEvent {
  name: string;
  [key: string]: unknown;
}

export interface ToolProgressEvent {
  message: string;
  agent: string;
  favicons?: string[];
}

export interface SubagentEndEvent {
  reportId: string;
  title: string;
  summary: string;
}

export interface UsageEvent {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  prompt_cache_hit_tokens?: number;
  prompt_cache_miss_tokens?: number;
  source?: string;
}

export interface SessionRenamedEvent {
  name: string;
}

export interface UiActionEvent {
  action: string;
  [key: string]: unknown;
}

export interface SetupCompleteEvent {
  // Empty payload
}

export interface CreateLearningSessionEvent {
  skillName: string;
  skillId: string;
}

export interface DoneEvent {
  // Empty object {} for snapshot, null for live
}

// --- Token frame (no event: line, default handler) ---

export interface TokenFrame {
  choices: [
    {
      delta: {
        content?: string;
        reasoning_content?: string;
      };
      finish_reason?: string;
    },
  ];
  usage?: UsageEvent;
}

// --- Union type ---

export type SSEEvent =
  | { type: "history"; data: HistoryEvent }
  | { type: "done"; data: DoneEvent | null }
  | { type: "reasoning"; data: string }
  | { type: "error"; data: string }
  | { type: "tool_start"; data: ToolStartEvent }
  | { type: "tool_end"; data: ToolEndEvent }
  | { type: "tool_progress"; data: ToolProgressEvent }
  | { type: "subagent_end"; data: SubagentEndEvent }
  | { type: "usage"; data: UsageEvent }
  | { type: "session_renamed"; data: SessionRenamedEvent }
  | { type: "ui_action"; data: UiActionEvent }
  | { type: "setup_complete"; data: SetupCompleteEvent }
  | { type: "create_learning_session"; data: CreateLearningSessionEvent }
  | { type: "token"; data: string };

// --- Shared types ---

export interface MessageRow {
  id: number;
  sessionId: string;
  role: "user" | "assistant" | "system" | "tool";
  content: string;
  reasoning?: string;
  reports?: { reportId: string; reportTitle: string }[];
  createdAt: string;
}
