export interface FileNode {
  name: string
  path: string
  isDir: boolean
  children?: FileNode[]
}

export interface AgentDef {
  id: string
  name: string
  systemPrompt: string
}

export interface ChatUsage {
  prompt_tokens: number
  completion_tokens: number
  prompt_cache_hit_tokens: number
  prompt_cache_miss_tokens: number
  total_tokens?: number
}

export interface SubagentConfig {
  model: string
  reasoning: string
  maxSteps: number
}

export interface SessionConfig {
  provider: string
  model: string
  reasoning: string
  agentId: string
}

export interface LLMConfig {
  llmProvider: "deepseek" | ""
  llmAgentId: string
  llmApiKey: string
  llmModel: "deepseek-v4-pro" | "deepseek-v4-flash" | ""
  llmReasoning: "disabled" | "high" | "max" | ""
  agentOverrides: Record<string, string>
  chatFontSize: number
  typewriterSpeed: number
  tinyfishApiKey: string
  tinyfishTier: string
  subagentConfig: Record<string, SubagentConfig>
  userName: string
  userLocation: string
  defaultLearnitViewport: string
  writeLangs: string[]
}
