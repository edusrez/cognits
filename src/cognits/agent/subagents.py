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
