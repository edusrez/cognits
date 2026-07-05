"""Centralized constants: model names, limits, thresholds, labels.

All duplicated literals across the codebase resolve to a single source here.
"""

# --- LLM model names ---
DEFAULT_MODEL = "deepseek-v4-pro"
DEFAULT_FLASH_MODEL = "deepseek-v4-flash"
DEFAULT_PROVIDER = "deepseek"

# model_id -> provider capabilities
MODEL_REGISTRY: dict[str, dict] = {
    "deepseek-v4-pro": {
        "provider": "deepseek",
        "context_window": 1_048_576,
        "supports_thinking": True,
    },
    "deepseek-v4-flash": {
        "provider": "deepseek",
        "context_window": 1_048_576,
        "supports_thinking": True,
    },
}


def parse_model(model_str: str) -> tuple[str, str]:
    """Parse 'provider/model-id' or bare 'model-id' → (provider, model_id).

    Bare IDs default to DEFAULT_PROVIDER.
    """
    if "/" in model_str:
        provider, model_id = model_str.split("/", 1)
        return provider, model_id
    return DEFAULT_PROVIDER, model_str


def get_context_window(model_str: str) -> int:
    """Look up context window from MODEL_REGISTRY. Falls back to MODEL_CONTEXT_WINDOW."""
    _, model_id = parse_model(model_str)
    entry = MODEL_REGISTRY.get(model_id)
    if entry and "context_window" in entry:
        return entry["context_window"]
    return MODEL_CONTEXT_WINDOW

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

# --- Server ---
DEFAULT_PORT = 5173
VITE_PORT = 5174
MAX_TOKENS_LIMIT = 384000
MAX_TEXT_BYTES = 5 * 1024 * 1024  # 5 MB
MAX_NAME_LENGTH = 120
MAX_SESSION_NAME_LENGTH = 80

TREE_SKIP_DIRS = {"node_modules", "dist", "vendor", "__pycache__", ".git", ".cognits"}
CODE_SKIP_DIRS = {"__pycache__", ".git", ".cognits", ".learnit", ".venv", "node_modules", "dist", "vendor", "build", "chroma_db", "frontend_dist"}

# --- LLM client ---
LLM_CONNECT_TIMEOUT = 10.0
LLM_READ_TIMEOUT = 120.0
LLM_WRITE_TIMEOUT = 30.0
LLM_POOL_TIMEOUT = 10.0
LLM_BASE_URL = "https://api.deepseek.com/chat/completions"
LLM_ERROR_BODY_MAX_BYTES = 8192

VALID_REASONING = ("disabled", "enabled", "max")

# --- TinyFish ---
TINYFISH_SEARCH_URL = "https://api.search.tinyfish.ai"
TINYFISH_FETCH_URL = "https://api.fetch.tinyfish.ai"
TINYFISH_TIMEOUT = 150.0

# --- Misc ---
FAVICON_URL_TEMPLATE = "https://icons.duckduckgo.com/ip3/{domain}.ico"

# --- Agent subagent defaults ---
EVALUATOR_MAX_STEPS = 100
STUDY_PLANNER_DEFAULT_STEPS = 10
DOCUMENTALIST_MAX_STEPS = 50
REFLECTION_REVISION_MAX_STEPS = 10

# --- RAG ---
EMBEDDING_MODEL = "BAAI/bge-m3"
EMBEDDING_DIM = 1024
EMBEDDING_BATCH_SIZE = 32
RAG_COLLECTION_NAME = "reports"
RAG_DISTANCE_METRIC = "cosine"
RAG_DEFAULT_MAX_RESULTS = 10
RAG_WARM_TIMEOUT_S = 300
RAG_WORKER_RLIMIT_GB = 3

# --- Learner model ---
MASTERY_THRESHOLD = 0.95

# BKT parameters
BKT_PRIOR_ALPHA = 1.0
BKT_PRIOR_BETA = 1.0
BKT_LAMBDA_HINT = 0.15
BKT_LAMBDA_TIME = 0.10
BKT_EVIDENCE_THRESHOLD = 4.0

# Mastery level thresholds
MASTERY_EXPLORING_P = 0.60
MASTERY_PRACTICING_MIN_REPS = 3
MASTERY_PROFICIENT_P = 0.80
MASTERY_PROFICIENT_CONFIDENCE = 8.0
MASTERY_MASTERED_CONFIDENCE = 12.0
MASTERY_MASTERED_RETENTION = 0.90
MASTERY_DECAY_OVERDUE_FACTOR = 1.5

# Skill defaults
DEFAULT_SKILL_DIFFICULTY = 0.5
SEEDING_CORRECTNESS = 0.85

# --- Tool caps ---
REPORT_TITLE_MAX_CHARS = 80
REPORT_SUMMARY_MAX_CHARS = 200
CHANGELOG_VALUE_MAX_CHARS = 200
STUDY_PLAN_MAX_ITEMS = 50

# --- Session namer ---
SESSION_NAMER_MAX_TOKENS = 20
SESSION_NAMER_TEMPERATURE = 0.3

# --- Context compaction ---
MODEL_CONTEXT_WINDOW = 1_048_576  # DeepSeek V4 Pro/Flash 1M tokens
COMPACTION_TRIGGER = 0.6          # force compaction at 600K
COMPACTION_PRESERVE_TURNS = 3     # keep last N user/assistant turns

# --- Reflection loop ---
REFLECTION_MAX_ITERATIONS = 2

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
