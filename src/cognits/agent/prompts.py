"""Port of internal/agent/prompts.go."""

from cognits.agent.agent_loader import load_agent_prompt

DIRECTORY_READER_SYSTEM_PROMPT = load_agent_prompt("directory_reader")
DOCUMENTALIST_SYSTEM_PROMPT = load_agent_prompt("documentalist")
EVALUATOR_SYSTEM_PROMPT = load_agent_prompt("evaluator")
RESEARCHER_SYSTEM_PROMPT = load_agent_prompt("web_researcher")
SESSION_NAMER_SYSTEM_PROMPT = load_agent_prompt("session_namer")
SESSION_ANALYZER_SYSTEM_PROMPT = load_agent_prompt("session_analyzer")
SKILL_PLANNER_SYSTEM_PROMPT = load_agent_prompt("skill_planner")
STUDY_PLANNER_SYSTEM_PROMPT = load_agent_prompt("study_planner")
TEACHER_SYSTEM_PROMPT = load_agent_prompt("maestro")

DEFAULT_AGENT_ID = "orchestrator"

ORCHESTRATOR_SYSTEM_PROMPT = load_agent_prompt("orchestrator")
SYSTEM_SUPPORT_PROMPT = load_agent_prompt("system_support")

# DEFAULT_AGENTS maps agent IDs to their system prompts for the default

DEFAULT_AGENTS = [
    {
        "id": "orchestrator",
        "systemPrompt": ORCHESTRATOR_SYSTEM_PROMPT,
    },
    {
        "id": "web_researcher",
        "systemPrompt": RESEARCHER_SYSTEM_PROMPT,
    },
    {
        "id": "documentalist",
        "systemPrompt": DOCUMENTALIST_SYSTEM_PROMPT,
    },
    {
        "id": "session_namer",
        "systemPrompt": SESSION_NAMER_SYSTEM_PROMPT,
    },
    {
        "id": "session_analyzer",
        "systemPrompt": SESSION_ANALYZER_SYSTEM_PROMPT,
    },
    {
        "id": "directory_reader",
        "systemPrompt": DIRECTORY_READER_SYSTEM_PROMPT,
    },
    {
        "id": "skill_planner",
        "systemPrompt": SKILL_PLANNER_SYSTEM_PROMPT,
    },
    {
        "id": "study_planner",
        "systemPrompt": STUDY_PLANNER_SYSTEM_PROMPT,
    },
    {
        "id": "evaluator",
        "systemPrompt": EVALUATOR_SYSTEM_PROMPT,
    },
    {
        "id": "maestro",
        "systemPrompt": TEACHER_SYSTEM_PROMPT,
    },
    {
        "id": "system_support",
        "systemPrompt": SYSTEM_SUPPORT_PROMPT,
    },
]

def default_agent_prompt(agent_id: str) -> str:
    for a in DEFAULT_AGENTS:
        if a["id"] == agent_id:
            return a["systemPrompt"]
    return ORCHESTRATOR_SYSTEM_PROMPT
