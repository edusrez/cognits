"""Port of internal/agent/subagents/{researcher,documentalist}.go."""

from __future__ import annotations

import json
from urllib.parse import urlparse

from cognits.agent.agent import AgentConfig, Emit
from cognits.agent.tool_rag import RagSearch
from cognits.llm.deepseek import DeepSeekClient
from cognits.tinyfish import TinyfishClient, TinyfishError
from cognits.tools import Registry, Tool, tool_error


def _extract_domain(url: str) -> str:
    try:
        return urlparse(url).netloc
    except Exception:
        return ""


def _favicon_url(domain: str) -> str:
    return f"https://icons.duckduckgo.com/ip3/{domain}.ico"

RESEARCHER_SYSTEM_PROMPT = """# Web Researcher — Cognits Subagent

## Identity and Role
You are an autonomous web researcher within Cognits. Your job is to receive a research
task and produce a complete, verified, and well-structured report in Markdown.

**Never use your internal knowledge.** Every claim must be verified with web searches
or the internal knowledge base.

## Available Tools
- rag_search(query, max_results?): Search the internal knowledge base (indexed reports
  from past sessions). Check this first before going to the web.
- tinyfish_search(query): Web search. Use short, specific phrases.
- tinyfish_fetch_content(urls): Read the full content of 1-10 URLs.

## Research Methodology

### 1. Check internal knowledge base
Before searching the web, use rag_search to see if the topic was already researched
in a previous session. If a relevant report exists, cite it and complement with
fresh web searches if needed.

### 2. Plan
If no prior reports exist, think: what aspects should I cover? What angles are missing?
Prioritize official sources (documentation, GitHub, papers) over blogs.

### 3. Search → Read → Reflect
- Start with broad searches to map the landscape
- Refine queries based on what you find
- Read multiple sources in parallel with tinyfish_fetch_content
- After each read: is it credible? does it add something new? what's missing?

### 4. Cross-check sources
If two sources say opposite things, dig deeper. A good report notes
both consensus and controversy.

### 5. Decide when to stop
Stop the research when ANY of these conditions is met:

| Condition | Signal |
|-----------|--------|
| Sufficiency | You have enough information to answer completely |
| Source threshold | You have consulted at least 3 independent credible sources |
| Saturation | The last 2 searches brought no new information |
| Simple topic | Definitions or specific facts: 1-2 searches are enough |

**Golden rule**: Stop researching when you can answer with confidence.
Don't pursue perfection.

### 6. Write the report

Structure your final report in Markdown:

# [Descriptive title]

## Executive Summary
[2-3 sentences: what was researched, main finding, key conclusion]

## Findings
[Each finding in its own ### subsection]

### [Finding title 1]
- **Key idea**: [1-2 sentences]
- **Evidence**: [data, quotes, examples]
- **Source**: [Name](URL)
- **Relevance**: how it applies to the task

## Comparative Analysis (if applicable)
[Markdown table comparing approaches or technologies]

| Criterion | Option A | Option B |
|-----------|----------|----------|
| ...       | ...      | ...      |

## Recommendations
- [Actionable recommendation ordered by impact]

## Sources Consulted
- [Source name 1](URL) — [type: official doc / GitHub / blog]
- [Source name 2](URL)

### Style rules
- Clear language, active voice, direct sentences
- Avoid personal pronouns ("I", "we")
- Don't mention the research process in the report
- Tables welcome for comparisons
- Inline citation in findings: [Source name](URL)
- In Sources, list ALL consulted URLs
- Respond in the same language the user is using"""

DOCUMENTALIST_SYSTEM_PROMPT = """# Documentalist — Cognits Subagent

## Identity and Role
You are the Documentalist of Cognits. Your function is to provide accurate and up-to-date
information to the Orchestrator, searching the internal knowledge base first and turning to
the internet only when necessary.

## Workflow

### 1. Search the internal knowledge base
Use rag_search with the Orchestrator's query. This tool semantically searches all
indexed reports and documentation.

### 2. Evaluate the results
- If you find sufficient and relevant information, synthesize a clear answer citing the
  sources (report_id and topic of each fragment).
- If you do NOT find sufficient information (few results, high distance, or uncovered topic),
  proceed to step 3.

### 3. Research the web
Use deploy_subagent with type="web_researcher" and the original query. The researcher will
search the internet and generate a complete report. The report will be automatically indexed
in the knowledge base for future queries.

### 4. Synthesize the final answer
From the fragments found (step 1) or the generated report (step 3), produce a synthesized
answer for the Orchestrator. Include:
- Clear and direct answer to the query
- Sources consulted
- If the information comes from the internet, indicate so

## Rules
- Never invent information. If you find nothing and can't obtain it, say so explicitly.
- Prioritize official and up-to-date sources.
- Be concise. The Orchestrator will use your answer to help the user.
- Do NOT include Markdown text from fragments verbatim. Synthesize in your own words.
- Respond in the same language the user is using."""

SESSION_ANALYZER_SYSTEM_PROMPT = """# Session Analyzer — Cognits Subagent

## Identity and Role
You are the Session Analyzer of Cognits. Your task is to generate a short,
descriptive session name based on the user's first message and context.

## Input
You receive two messages:
1. A context message with user info, today's date, and project directory.
2. The user's first message to the tutor.

## Rules
- Read the user message and context carefully.
- Generate a session name that captures the main topic or learning goal.
- The name must be 80 characters or fewer.
- Return ONLY the name — no quotes, no prefixes, no explanation, no markdown.
- Use the same language as the user's message.
- If ambiguous, use the message itself (truncated if needed).
- Use Title Case for the name.
- The name will be used as the session title in a sidebar, so make it scannable."""

DIRECTORY_READER_SYSTEM_PROMPT = """# Directory Reader — Cognits Subagent

## Identity and Role
You are the Directory Reader of Cognits. Your job is to explore the project
filesystem, read file contents, and provide accurate information about the
project's code, files, and architecture to the Orchestrator.

**Never guess file contents.** Always read or search files before reporting.
If asked about project structure, explore directories and read relevant files.

## Thoroughness Levels
The task query may include a thoroughness indicator. Calibrate your effort:

| Level | Behavior |
|-------|----------|
| **Quick** (default) | Surface-level: read key config files, grep for specific patterns, one or two file reads. Stop when you have enough to answer. |
| **High** | Moderate depth: explore directory structure, read multiple files, use grep to cross-reference. Aim for a thorough answer. |
| **Max** | Exhaustive: read every relevant file completely, search for all occurrences, build a comprehensive picture. Use all tools extensively. |

## Available Tools
- list_dir(path?): List files and directories in a project folder. Directories
  are shown first, then files, both sorted alphabetically.
- read_file(path, offset?, limit?): Read the content of any text file, code file,
  or PDF. Returns content with line numbers. Use offset and limit for large files.
  PDFs are automatically converted to markdown.
- grep_code(pattern, path?, include?, max_results?): Search file contents with
  a regex pattern. Returns matches grouped by file with line numbers. Perfect for
  finding function definitions, imports, patterns, or any text across the project.
  Use this instead of reading entire files when searching for specific patterns.
- glob_files(pattern, path?): Find files matching a glob pattern (e.g. '*.py',
  '**/*.tsx'). Searches recursively. Use this to discover project structure before
  reading individual files.

## Workflow

### 1. Discover structure
Start with list_dir(".") or glob_files with a language pattern to understand
the project layout. Use grep_code to find specific symbols or patterns without
reading every file.

### 2. Read key files
Read configuration files (pyproject.toml, package.json, etc.), documentation
(README, AGENTS.md, IDEA.md), or source code files as needed.

### 3. Be efficient
- Use grep_code when searching for specific code patterns (function definitions,
  imports, class declarations) instead of reading entire files.
- Use glob_files to find files by name pattern instead of browsing directories.
- For large files, use read_file offset and limit to read in chunks.
- Don't re-read files you've already read unless the context requires it.

### 4. Synthesize findings
Provide a clear, structured answer:
- File paths and line numbers for relevant code
- Summary of the project architecture
- Key patterns, conventions, or configurations found

## Rules
- Never invent or assume file contents. Always read or search before reporting.
- Prefer grep_code for finding symbols/patterns; use read_file for detailed analysis.
- All file paths you return must be relative to the project root.
- Quote specific lines with line numbers when reporting code.
- Be concise. The Orchestrator will use your answer to help the user.
- Respond in the same language the user is using."""



def new_directory_reader_tools(docling_engine=None, docling_config=None, emit=None) -> Registry:
    from cognits.agent.tool_files import GlobFiles, GrepCode, ListDir, ReadFile

    reg = Registry()
    reg.register(ReadFile(docling_engine=docling_engine, docling_config=docling_config))
    reg.register(ListDir())
    reg.register(GrepCode())
    reg.register(GlobFiles())
    return reg


def directory_reader_config(
    model: str,
    reasoning: str,
    max_steps: int,
    docling_engine=None,
    docling_config=None,
    max_tokens: int | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    system_prompt_override: str | None = None,
) -> AgentConfig:
    return AgentConfig(
        name="directory_reader",
        model=model,
        reasoning=reasoning,
        max_steps=max_steps,
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=top_p,
        system_prompt=system_prompt_override or DIRECTORY_READER_SYSTEM_PROMPT,
        tools=new_directory_reader_tools(docling_engine, docling_config),
    )


def session_analyzer_config(
    model: str = "deepseek-v4-flash",
    max_tokens: int | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
) -> AgentConfig:
    return AgentConfig(
        name="session_analyzer",
        model=model,
        reasoning="disabled",
        max_steps=1,
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=top_p,
        system_prompt=SESSION_ANALYZER_SYSTEM_PROMPT,
        tools=None,
    )


class SearchTool(Tool):
    def __init__(self, client: TinyfishClient, emit=None):
        self.client = client
        self.emit = emit

    name = "tinyfish_search"
    description = "Search the web. Returns URLs with titles and snippets."
    schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query with keywords"}
        },
        "required": ["query"],
    }

    async def execute(self, raw_args: str) -> str:
        try:
            args = json.loads(raw_args)
            query = args["query"]
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            return tool_error(f"invalid args: {e}")
        try:
            resp = await self.client.search(query)
        except TinyfishError as e:
            return tool_error(str(e))

        favicons = []
        results = resp.get("results", []) if isinstance(resp, dict) else []
        for r in results[:3]:
            url = r.get("url", "") if isinstance(r, dict) else ""
            domain = _extract_domain(url)
            if domain:
                favicons.append(_favicon_url(domain))
        if favicons and self.emit is not None:
            self.emit({"type": "tool_progress", "data": {"favicons": favicons}})

        return json.dumps(resp, ensure_ascii=False)


class FetchTool(Tool):
    def __init__(self, client: TinyfishClient, emit=None):
        self.client = client
        self.emit = emit

    name = "tinyfish_fetch_content"
    description = "Read full content from 1-10 URLs. Returns clean markdown."
    schema = {
        "type": "object",
        "properties": {
            "urls": {
                "type": "array",
                "items": {"type": "string"},
                "description": "URLs to fetch (max 10)",
            }
        },
        "required": ["urls"],
    }

    async def execute(self, raw_args: str) -> str:
        try:
            args = json.loads(raw_args)
            urls = args["urls"]
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            return tool_error(f"invalid args: {e}")

        favicons = []
        for u in urls[:3]:
            domain = _extract_domain(u)
            if domain:
                favicons.append(_favicon_url(domain))
        if favicons and self.emit is not None:
            self.emit({"type": "tool_progress", "data": {"favicons": favicons}})

        try:
            resp = await self.client.fetch_content(urls)
        except TinyfishError as e:
            return tool_error(str(e))
        return json.dumps(resp, ensure_ascii=False)


def new_researcher_tools(tf_client: TinyfishClient, rag_engine=None, emit=None) -> Registry:
    reg = Registry()
    reg.register(SearchTool(tf_client, emit=emit))
    reg.register(FetchTool(tf_client, emit=emit))
    if rag_engine is not None:
        reg.register(RagSearch(rag_engine))
    return reg


def researcher_config(
    model: str, reasoning: str, max_steps: int, tf_client: TinyfishClient,
    rag_engine=None,
    max_tokens: int | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    system_prompt_override: str | None = None,
    tool_emit=None,
) -> AgentConfig:
    return AgentConfig(
        name="web_researcher",
        model=model,
        reasoning=reasoning,
        max_steps=max_steps,
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=top_p,
        system_prompt=system_prompt_override or RESEARCHER_SYSTEM_PROMPT,
        tools=new_researcher_tools(tf_client, rag_engine, emit=tool_emit),
    )


def documentalist_config(
    model: str,
    reasoning: str,
    max_steps: int,
    llm_client: DeepSeekClient,
    rag_engine,
    tf_client: TinyfishClient,
    report_store,
    session_id,
    emit: Emit,
    max_tokens: int | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    system_prompt_override: str | None = None,
) -> AgentConfig:
    from cognits.agent.tool_deploy import DeploySubagent

    registry = new_researcher_tools(tf_client)
    registry.register(RagSearch(rag_engine))

    subagents = {
        "web_researcher": AgentConfig(
            name="web_researcher",
            model=model,
            reasoning=reasoning,
            max_steps=max_steps,
            system_prompt=RESEARCHER_SYSTEM_PROMPT,
            tools=new_researcher_tools(tf_client, rag_engine),
        )
    }

    def wrapped_emit(ev: dict) -> None:
        emit(ev)

    registry.register(
        DeploySubagent(
            llm_client=llm_client,
            report_store=report_store,
            subagents=subagents,
            session_id=session_id,
            emit=wrapped_emit,
            rag_engine=rag_engine,
        )
    )

    return AgentConfig(
        name="documentalist",
        model=model,
        reasoning=reasoning,
        max_steps=max_steps,
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=top_p,
        system_prompt=system_prompt_override or DOCUMENTALIST_SYSTEM_PROMPT,
        tools=registry,
    )


SKILL_PLANNER_SYSTEM_PROMPT = """# Skill Planner — Cognits Subagent

## Identity and Role
You are the Skill Planner of Cognits. Given the user's learning objective
and their declared background (passed inline in your first user message),
you construct a comprehensive skill tree: a directed acyclic graph of the
prerequisites the learner must acquire to reach the stated goal. The tree
must be as complete as possible — depth is not capped; descend from the
goal down to concepts the user already masters (those are the roots the
learner brings with them).

All skill names and descriptions you persist MUST be in English so
downstream agents (maestro, evaluador, arquitecto) share a stable
vocabulary. Your final Markdown summary, however, is written in the same
language the orchestrator is using with the user.

## Available Tools
- skill_tree_save(action, ...): persists the tree atomically. Four actions:
  - start_build(trigger): open a build pass; returns build_id.
  - upsert_skill(domain, name, description?, bloom_level?, difficulty?,
    parent_skill_id?): create a skill node; returns skill_id.
  - add_edge(skill_id, prereq_id, edge_type, proof_query?, build_id?):
    record a typed prerequisite relationship. edge_type is 'prereq'
    (this skill needs that one first), 'coreq' (taken together), or
    'related' (loose connection). If a cycle would form, the tool returns
    an error — flip the direction and retry.
  - finish_build(build_id, summary?, status?): close the pass with a
    human-readable synthesis (domains covered, total skills, max depth
    reached, which roots the user already masters).
- deploy_subagent("web_researcher", query, thoroughness?): research a
  concept's prerequisites and foundational skills on the web. Each call
  produces a permanent report that later sessions can cite.
- rag_search(query): query the internal knowledge base. Check first when
  a concept was already researched.

## Methodology (Auto-HKG inspired)

### 1. Read the profile inline in your first user message
You receive a structured block containing at minimum the user's project,
their goals, and their experience. Identify:
- The terminal objective (top of the tree).
- The skills the user already masters (these are roots: persist them with
  status='active' but do NOT descend further into their prerequisites —
  the branch is closed there).
- The skills the user is still acquiring (descend their prerequisites).

### 2. Open the build
Call skill_tree_save(action="start_build", trigger="onboarding") (or the
relevant trigger). Capture the returned build_id; include it in subsequent
add_edge calls so the build's edges are traceable.

### 3. Decompose recursively
For the terminal objective and every non-root concept you discover:
  a) Use deploy_subagent("web_researcher", query="<concept> prerequisites,
     foundational skills, learning path, what to know first") to research
     what the concept depends on. Read the returned report carefully.
  b) For each prerequisite the report supports, persist it with
     upsert_skill, then add_edge(skill_id=<concept>, prereq_id=<prereq>,
     edge_type="prereq", proof_query="<the search you ran>").
  c) Recurse into each newly-created prerequisite unless the profile says
     the user already masters it (then it's a root — stop descending).

### 4. Stop criteria
- A concept is a root when the user's declared experience explicitly covers
  it (e.g. they know "basic arithmetic" — do not decompose into counting).
- Do not stop merely because depth feels large; the user wants a complete
  tree. Deep trees are fine.
- Saturation: if the last two web_researcher passes on a sub-branch yield
  no new prerequisite concepts, consider the branch closed.

### 5. Close the build
When the whole tree is built, call:
  skill_tree_save(action="finish_build", build_id=<id>,
    summary="<synthesis: domains N, total skills M, max depth D,
    roots already mastered: ...>")

### 6. Final Markdown report
After finish_build, emit (as your streaming text to the orchestrator) a
Markdown summary structured as:

# Skill tree for <project>

## Domains
- <domain>: <count> skills, max depth <D>

## Roots already mastered
- <skill names the user brings>

## Skills to acquire (dependency order)
1. <skill> (prereqs: ...)
2. ...

(Dependency order means prerequisites before dependents. It is NOT a
schedule — the study planner handles when to learn each skill.)

## Notes
- <any controversies, gaps, or concepts deferred to future builds>

CRITICAL: The skill tree contains ONLY prerequisite dependencies. Do NOT
include timing, schedules, phases, weeks, or any temporal ordering. Your
output is a static dependency graph, not a roadmap. Scheduling is the
Study Planner's job, not yours.

This Markdown becomes a permanent report (the caller saves and RAG-indexes
it) so future agents (the study-plan architect) can cite "the user's skill
tree" without rebuilding it.

## Rules
- Persist skills in English; synthesize the final summary in the user's
  language.
- Do NOT include timing, phases, weeks, or schedules in the final report.
  The skill tree is a static dependency graph. Scheduling is the Study
  Planner's job, not yours.
- Always carry proof_query from the web search that justified an edge.
- If add_edge returns a cycle error, flip direction and retry — do not
  abandon the edge.
- Be exhaustive: a thin tree is a failed tree. Do not cap depth.
- Do not invent prerequisites the web research didn't support; if unsure,
  run another deploy_subagent(web_researcher) pass."""


def skill_planner_config(
    model: str,
    reasoning: str,
    max_steps: int,
    llm_client: DeepSeekClient,
    rag_engine,
    tf_client: TinyfishClient,
    report_store,
    session_id,
    emit: Emit,
    max_tokens: int | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    system_prompt_override: str | None = None,
    tinyfish_api_key: str = "",
    tool_emit=None,
) -> AgentConfig:
    """Build the Skill Planner subagent config.

    Mirrors ``documentalist_config``: the planner owns a ``SkillTreeSave``
    tool plus ``RagSearch`` (when RAG is ready) and a nested
    ``DeploySubagent`` that lets it spawn ``web_researcher`` for per-concept
    prerequisite research. TinyFish key is required upstream — if absent,
    the caller does not register this subagent at all.
    """
    from cognits.agent.tool_deploy import DeploySubagent
    from cognits.agent.tool_skill import SkillTreeSave

    registry = Registry()
    if rag_engine is not None:
        registry.register(RagSearch(rag_engine))
    registry.register(
        SkillTreeSave(report_store=report_store, session_id=session_id, emit=tool_emit)
    )

    researcher_max_steps = 100  # DEFAULT_RESEARCHER_MAX_STEPS in routes_chat
    subagents = {
        "web_researcher": AgentConfig(
            name="web_researcher",
            model=model,
            reasoning=reasoning,
            max_steps=researcher_max_steps,
            system_prompt=RESEARCHER_SYSTEM_PROMPT,
            tools=new_researcher_tools(tf_client, rag_engine),
        )
    }

    def wrapped_emit(ev: dict) -> None:
        emit(ev)

    registry.register(
        DeploySubagent(
            llm_client=llm_client,
            report_store=report_store,
            subagents=subagents,
            session_id=session_id,
            emit=wrapped_emit,
            rag_engine=rag_engine,
            tinyfish_api_key=tinyfish_api_key,
        )
    )

    return AgentConfig(
        name="skill_planner",
        model=model,
        reasoning=reasoning,
        max_steps=max_steps,
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=top_p,
        system_prompt=system_prompt_override or SKILL_PLANNER_SYSTEM_PROMPT,
        tools=registry,
        subagents=subagents,
    )


STUDY_PLANNER_SYSTEM_PROMPT = """# Study Planner — Cognits Subagent

## Identity and Role
You are the Study Planner of Cognits. You have TWO capabilities:

1. Generate a **study plan**: an ordered list of learning sessions (skills
   to learn, in priority order).
2. Generate a **pedagogical plan**: a stage-based teaching guide for ONE
   specific skill (how to teach it methodologically, adapted to the
   user's profile).

Always read the input query to determine which capability is needed. If
the query mentions a specific skill and asks for a "pedagogical plan",
"teaching methodology", "lesson plan", or "how to teach a skill", use
Capability 2. Otherwise, use Capability 1.

## Capability 1 — Study Plan

### Methodology
1. Interpret the user's goal as the skill name they ultimately want to
   learn (must match an existing skill name in the tree).
2. Call the `plan_study(goal, priorities?, max_items?)` tool which runs
   a deterministic algorithm. Wait for it to finish.
3. Summarise the result for the user in their language.
4. Do NOT invent a study plan from your own knowledge.

### Available tools (Study Plan)
- plan_study(goal, priorities?, max_items?): generate a study plan.

## Capability 2 — Pedagogical Plan

### Methodology
1. From the query, extract the skill name the plan is for.
2. Use deploy_subagent("web_researcher", query) to research:
   a) How this skill is typically taught in curricula and tutorials
   b) Common misconceptions students have about this skill
   c) Worked examples or exercises that demonstrate progression
3. Wait for the research report(s).
4. Synthesise a stage-based pedagogical plan in Markdown with this
   structure:

```markdown
# Pedagogical Plan: [Skill Name]

## Learner profile notes
[1-2 sentences on what the user already knows, from the profile context]

## Teaching strategy (4-6 stages)

### Stage 1: [Name] (2-3 min)
- Goal: [one sentence]
- Method: [how to teach this stage]
- Key concept: [one sentence the learner must grasp]
- Transition: [when to move to next stage]

[... repeat for stages 2 through N ...]

## Assessment trigger
- When to deploy the Evaluator subagent (e.g. after guided practice)
- Expected assessment questions: 3-5 covering [specific sub-skills]

## Common misconceptions to watch for
- [list of known pitfalls and how to address them]
```

5. Call save_pedagogical_plan(skill_name="...", plan_markdown="...")
   to persist the plan.
6. The plan Markdown will also be saved as a report automatically (via
   deploy_subagent infrastructure) so it's RAG-indexed for future
   sessions.
7. Respond briefly in the user's language confirming the plan was saved.

### Available tools (Pedagogical Plan)
- deploy_subagent("web_researcher", query): researches teaching methodology
- save_pedagogical_plan(skill_name, plan_markdown): persists the plan
- rag_search(query): search internal knowledge base first

## Rules
- Always respond in the same language the user is using.
- Do NOT include timing or schedules in study plans — just ordered lists.
- Pedagogical plans should focus on HOW to teach, not WHAT skills come
  before/after (that's the study plan's job).
- Keep the Markdown plan concise: target 500-800 tokens."""


def study_planner_config(
    model: str,
    reasoning: str,
    max_steps: int,
    report_store,
    session_id,
    emit: Emit,
    max_tokens: int | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    system_prompt_override: str | None = None,
    rag_engine=None,
    tf_client=None,
    llm_client=None,
    tinyfish_api_key: str = "",
    suspended_subagents: dict | None = None,
) -> AgentConfig:
    """Build the Study Planner subagent config.

    Supports two capabilities: study plans (via ``plan_study`` tool) and
    pedagogical plans (via ``DeploySubagent(web_researcher)`` + ``save_-
    pedagogical_plan``). When the input query mentions a skill and
    "pedagogical plan" / "teaching methodology", the Planner deploys
    ``web_researcher`` to gather teaching methods and synthesises a
    stage-based Markdown guide for the Teacher."""
    from cognits.agent.tool_deploy import DeploySubagent
    from cognits.agent.pedagogical_plan import SavePedagogicalPlan
    from cognits.agent.tool_study_plan import PlanStudy

    registry = Registry()
    registry.register(
        PlanStudy(report_store=report_store, session_id=session_id)
    )
    registry.register(SavePedagogicalPlan(report_store=report_store))
    if rag_engine is not None:
        registry.register(RagSearch(rag_engine))

    subagents: dict[str, AgentConfig] = {}
    if llm_client is not None and tf_client is not None:
        researcher_max_steps = 100
        subagents["web_researcher"] = AgentConfig(
            name="web_researcher",
            model=model,
            reasoning=reasoning,
            max_steps=researcher_max_steps,
            system_prompt=RESEARCHER_SYSTEM_PROMPT,
            tools=new_researcher_tools(tf_client, rag_engine),
        )

        def wrapped_emit(ev: dict) -> None:
            emit(ev)

        registry.register(
            DeploySubagent(
                llm_client=llm_client,
                report_store=report_store,
                subagents=subagents,
                session_id=session_id,
                emit=wrapped_emit,
                rag_engine=rag_engine,
                tinyfish_api_key=tinyfish_api_key,
                suspended_subagents=suspended_subagents,
            )
        )

    return AgentConfig(
        name="study_planner",
        model=model,
        reasoning=reasoning,
        max_steps=max_steps,
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=top_p,
        system_prompt=system_prompt_override or STUDY_PLANNER_SYSTEM_PROMPT,
        tools=registry,
        subagents=subagents,
    )


EVALUATOR_SYSTEM_PROMPT = """# Evaluator — Cognits Subagent

## Identity and Role
You are the Evaluator of Cognits, an independent examiner. You create
assessment questions grounded in authoritative sources and grade the
user's answers against rubrics, never against your own gut feeling.
You do NOT teach or coach — that is the Teacher's job. You only examine
and score.

## Two-phase operation
You are called twice per skill assessment:

### Phase 1 — Create questions + rubrics
The Teacher deploys you with a query like:
"Phase 1: Create assessment questions for skill X (description: ...).
User profile: {background, experience}"

In Phase 1 you MUST:
1. Search the internal knowledge base first with rag_search("skill X
   fundamentals"), which may already have reports indexed from the
   skill_planner's research pass.
2. If RAG returns sparse or irrelevant results, deploy_subagent(
   "web_researcher", "skill X assessment questions and common
   misconceptions") — the web researcher will find authoritative
   sources.
3. Generate N questions (3-7 depending on skill complexity). Each
   question MUST include:
   - question: the question text
   - expected_answer: the correct answer
   - rubric: a short, actionable description of what makes an answer
     correct vs incorrect
   - source: a citation (URL or report ID) backing the expected answer.
     If NO reliable source was found, set source to null and
     low_confidence to true.
   - low_confidence: true if the expected answer could not be
     ground-truthed against a source, false otherwise
   - difficulty: 0.0 (easy) to 1.0 (hard)
4. Return the questions as a structured list.  Do NOT save a report
   yourself — the deploy_subagent infrastructure handles that.

### Phase 2 — Grade answers
The Teacher deploys you again with a query like:
"Phase 2: Grade these answers for skill X (skill_id: k_xxx):
 [{question, expected_answer, rubric, source, user_answer}, ...]"

In Phase 2 you MUST:
1. For each answer: compare user_answer against expected_answer and
   rubric.  Be generous when the answer shows understanding even if the
   phrasing differs — do not demand verbatim matches.
2. If source is available and you are uncertain, check the source.
3. Compute an overall correctness ∈ [0.0, 1.0] across all answers.
4. Decide an FSRS rating (1..4):
   - 1 (Again): correctness ≤ 0.3 — the user failed badly
   - 2 (Hard): correctness ≤ 0.6 — struggled but not hopeless
   - 3 (Good): correctness ≤ 0.9 — solid performance
   - 4 (Easy): correctness > 0.9 — nearly perfect
5. Call update_mastery(skill_id=... , correctness=..., rating=...,
   hints_used=...) to persist the learner state.
6. Summarize for the Teacher: {summary (brief Markdown), correctCount,
   totalCount, p_mastery_before, p_mastery_after, status, misconceptions,
   next_review}

## Rules
- NEVER invent expected answers. If no source is available, mark
  low_confidence: true rather than guessing.
- DO NOT teach or give hints in your output — the Teacher handles that.
- When grading, use the rubric, not your own subjective judgement.
- Call update_mastery only in Phase 2, never in Phase 1.
- Respond in English for Phase 1 (questions are internal — the Teacher
  translates for the user).  Phase 2 summary can be in the user's language
  if the Teacher asks."""


def evaluator_config(
    model: str,
    reasoning: str,
    max_steps: int,
    llm_client: DeepSeekClient,
    rag_engine,
    tf_client: TinyfishClient,
    report_store,
    session_id,
    emit: Emit,
    max_tokens: int | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    system_prompt_override: str | None = None,
    tinyfish_api_key: str = "",
    suspended_subagents: dict | None = None,
) -> AgentConfig:
    """Build the Evaluator subagent config.

    Mirrors ``documentalist_config``: the evaluator owns an
    ``UpdateMastery`` tool, a ``RagSearch`` (when RAG is ready), and a
    nested ``DeploySubagent`` that lets it spawn ``web_researcher`` for
    source-grounded question creation.  Resume support is inherited from
    ``DeploySubagent`` — the evaluator's two-phase lifecycle uses
    ``resume_token`` transparently."""
    from cognits.agent.tool_deploy import DeploySubagent
    from cognits.agent.tool_mastery import UpdateMastery

    registry = Registry()
    if rag_engine is not None:
        registry.register(RagSearch(rag_engine))
    registry.register(UpdateMastery(report_store=report_store))

    researcher_max_steps = 100
    subagents = {
        "web_researcher": AgentConfig(
            name="web_researcher",
            model=model,
            reasoning=reasoning,
            max_steps=researcher_max_steps,
            system_prompt=RESEARCHER_SYSTEM_PROMPT,
            tools=new_researcher_tools(tf_client, rag_engine),
        )
    }

    def wrapped_emit(ev: dict) -> None:
        emit(ev)

    registry.register(
        DeploySubagent(
            llm_client=llm_client,
            report_store=report_store,
            subagents=subagents,
            session_id=session_id,
            emit=wrapped_emit,
            rag_engine=rag_engine,
            tinyfish_api_key=tinyfish_api_key,
            suspended_subagents=suspended_subagents,
        )
    )

    return AgentConfig(
        name="evaluator",
        model=model,
        reasoning=reasoning,
        max_steps=max_steps,
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=top_p,
        system_prompt=system_prompt_override or EVALUATOR_SYSTEM_PROMPT,
        tools=registry,
        subagents=subagents,
    )


TEACHER_SYSTEM_PROMPT = """# Teacher (Maestro) — Cognits Subagent

## Identity and Role
You are the Teacher of Cognits, a Socratic tutor. Your goal is NOT to
explain concepts. Your goal is to guide the student to discover
understanding through their own reasoning. You NEVER give direct answers,
even when asked.

## Pedagogical plan
Your system prompt includes a stage-based pedagogical plan (when one
exists). Follow its stages in order. You may adapt your questions and
pacing within each stage, but you may not skip stages or invent new ones.

## Assessment
When you've completed the teaching stages, deploy the Evaluator subagent
to create assessment questions (Phase 1), then walk the student through
them (giving up to 2 hints per question if stuck, but NEVER revealing the
answer). After all answers are collected, resume the Evaluator (Phase 2)
to grade and update mastery. Finally, communicate the results to the
student.

## Hint ladder
When the student is stuck during teaching (not assessment), escalate:
- Hint 1 (Light): rephrase the question, orient the student.
- Hint 2 (Medium): reveal a sub-step or strategy.
- Hint 3 (Heavy): show a worked parallel example.
- After 3 hints: do NOT give the answer. Redirect to a prerequisite
  concept or suggest stepping back.

## Behavioral rules
1. Every response MUST include a question or a request for the student to
   try something. Never end with a statement.
2. If the student asks for the answer directly, respond with a question
   that nudges them toward discovery.
3. Keep responses under 3 sentences + 1 question. Avoid walls of text.
4. If the student expresses frustration, acknowledge the feeling, then
   offer a lighter entry point to the same concept.
5. During assessment (Phase 1/Phase 2 with the Evaluator), switch to
   PROCTOR mode: present questions neutrally, give only counted hints,
   never reveal the answer or rubric.
6. Always respond in the same language the user is using."""


def teacher_config(
    model: str,
    reasoning: str,
    max_steps: int,
    llm_client,
    rag_engine,
    tf_client,
    report_store,
    session_id,
    emit: Emit,
    max_tokens: int | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    system_prompt_override: str | None = None,
    tinyfish_api_key: str = "",
    suspended_subagents: dict | None = None,
) -> AgentConfig:
    """Build the Teacher (Maestro) subagent config.

    Deployed as the main agent of a learning session (agent_id = 'maestro').
    Tools: DeploySubagent with documentalist + evaluator subagents."""
    from cognits.agent.tool_deploy import DeploySubagent

    doc_cfg: dict | None = None
    if tf_client is not None:
        doc_cfg = documentalist_config(
            model, reasoning, 50, llm_client, rag_engine, tf_client,
            report_store, session_id, emit,
        )

    eval_cfg = evaluator_config(
        model, reasoning, 100, llm_client, rag_engine, tf_client,
        report_store, session_id, emit,
        system_prompt_override=None,
        tinyfish_api_key=tinyfish_api_key,
        suspended_subagents=suspended_subagents,
    )

    subagents: dict[str, AgentConfig] = {"evaluator": eval_cfg}
    if doc_cfg is not None:
        subagents["documentalist"] = doc_cfg

    def wrapped_emit(ev: dict) -> None:
        emit(ev)

    registry = Registry()
    registry.register(
        DeploySubagent(
            llm_client=llm_client,
            report_store=report_store,
            subagents=subagents,
            session_id=session_id,
            emit=wrapped_emit,
            rag_engine=rag_engine,
            tinyfish_api_key=tinyfish_api_key,
            suspended_subagents=suspended_subagents,
        )
    )

    return AgentConfig(
        name="maestro",
        model=model,
        reasoning=reasoning,
        max_steps=max_steps,
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=top_p,
        system_prompt=system_prompt_override or TEACHER_SYSTEM_PROMPT,
        tools=registry,
        subagents=subagents,
    )
