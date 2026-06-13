"""Port of internal/agent/subagents/{researcher,documentalist}.go."""

from __future__ import annotations

import json

from cognits.agent.agent import AgentConfig, Emit
from cognits.agent.tool_rag import RagSearch
from cognits.llm.deepseek import DeepSeekClient
from cognits.tinyfish import TinyfishClient, TinyfishError
from cognits.tools import Registry, Tool, tool_error

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


class SearchTool(Tool):
    def __init__(self, client: TinyfishClient):
        self.client = client

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
        return json.dumps(resp, ensure_ascii=False)


class FetchTool(Tool):
    def __init__(self, client: TinyfishClient):
        self.client = client

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
        try:
            resp = await self.client.fetch_content(urls)
        except TinyfishError as e:
            return tool_error(str(e))
        return json.dumps(resp, ensure_ascii=False)


def new_researcher_tools(tf_client: TinyfishClient, rag_engine=None) -> Registry:
    reg = Registry()
    reg.register(SearchTool(tf_client))
    reg.register(FetchTool(tf_client))
    if rag_engine is not None:
        reg.register(RagSearch(rag_engine))
    return reg


def researcher_config(
    model: str, reasoning: str, max_steps: int, tf_client: TinyfishClient,
    rag_engine=None,
) -> AgentConfig:
    return AgentConfig(
        name="web_researcher",
        model=model,
        reasoning=reasoning,
        max_steps=max_steps,
        system_prompt=RESEARCHER_SYSTEM_PROMPT,
        tools=new_researcher_tools(tf_client, rag_engine),
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
        if ev["type"] == "tool_progress":
            data = ev.get("data")
            if isinstance(data, dict):
                msg = data.get("message")
                # Empty message clears the status banner: don't prefix it.
                if isinstance(msg, str) and msg != "":
                    data["message"] = "Documentalist: " + msg
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
        system_prompt=DOCUMENTALIST_SYSTEM_PROMPT,
        tools=registry,
    )
