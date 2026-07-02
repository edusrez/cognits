"""Centralized constants: model names, limits, thresholds, labels.

All duplicated literals across the codebase resolve to a single source here.
"""

# --- LLM model names ---
DEFAULT_MODEL = "deepseek-v4-pro"
DEFAULT_FLASH_MODEL = "deepseek-v4-flash"

# --- Agent limits ---
ORCHESTRATOR_MAX_STEPS = 999
RESEARCHER_MAX_STEPS = 100

# --- Memory pressure thresholds (MB) ---
MEM_WARN = 5000
MEM_HIGH = 6200
MEM_CRITICAL = 6800

# --- Concurrency ---
MAX_CONCURRENT_TOOLS = 4
MAX_CONCURRENT_DEPLOYS = 2
TOOL_SEM_LOW = 1

# --- HTTP client ---
HTTPX_MAX_CONNECTIONS = 10
HTTPX_MAX_KEEPALIVE = 4

# --- RAG chunking ---
CHUNK_SIZE = 1600
CHUNK_OVERLAP = 160

# --- SSE ---
SUBSCRIBER_BUFFER = 1024
KEEPALIVE_SECONDS = 15

# --- Misc ---
TREE_MAX_DEPTH = 6
TREE_MAX_ENTRIES = 2000
BUSY_TIMEOUT_MS = 5000

# --- Agent persona display labels ---
# Canonical mapping: persona ID → user-visible name.
# Serves both the backend (tool_progress banners) and the frontend
# (via /api/agents, already served by routes_misc.py:87).
AGENT_LABELS: dict[str, str] = {
    "web_researcher": "Web Researcher",
    "directory_reader": "Directory Reader",
    "documentalist": "Documentalist",
    "session_analyzer": "Session Analyzer",
    "session_namer": "Session Namer",
    "skill_planner": "Skill Planner",
    "study_planner": "Study Planner",
    "evaluator": "Evaluator",
    "teacher": "Teacher",
    "maestro": "Tutor",
    "system_support": "Support",
}
