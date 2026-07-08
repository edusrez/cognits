"""Port of internal/agent/subagents/{researcher,documentalist}.go."""

from __future__ import annotations

import json
from urllib.parse import urlparse

from cognits.agent.agent import AgentConfig, Emit
from cognits.agent.agent_loader import load_agent_prompt
from cognits.constants import DEFAULT_FLASH_MODEL, DEFAULT_MODEL, DOCUMENTALIST_MAX_STEPS, EVALUATOR_MAX_STEPS, FAVICON_URL_TEMPLATE, RESEARCHER_MAX_STEPS, BRANCH_BUILDER_MAX_STEPS, MASTERY_JUDGE_MAX_STEPS
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
    return FAVICON_URL_TEMPLATE.format(domain=domain)











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
        system_prompt=system_prompt_override or load_agent_prompt("directory_reader"),
        tools=new_directory_reader_tools(docling_engine, docling_config),
    )


def session_namer_config(
    model: str = DEFAULT_FLASH_MODEL,
    max_tokens: int | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
) -> AgentConfig:
    return AgentConfig(
        name="session_namer",
        model=model,
        reasoning="disabled",
        max_steps=1,
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=top_p,
        system_prompt=load_agent_prompt("session_namer"),
        tools=None,
        internal=True,
    )





def session_analyzer_config(
    model: str = DEFAULT_FLASH_MODEL,
    reasoning: str = "disabled",
    max_tokens: int | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
) -> AgentConfig:
    return AgentConfig(
        name="session_analyzer",
        model=model,
        reasoning=reasoning,
        max_steps=1,
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=top_p,
        system_prompt=load_agent_prompt("session_analyzer"),
        tools=None,
        internal=True,
    )


def mastery_judge_config(
    model: str = DEFAULT_MODEL,
    reasoning: str = "max",
    max_steps: int = MASTERY_JUDGE_MAX_STEPS,
    max_tokens: int | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
) -> AgentConfig:
    """Build the mastery_judge subagent config.

    Single-turn estimator that judges whether a learner has mastered a
    specific skill based on their profile + chat history. Uses NO tools.
    Internal subagent (no chat cards, like evaluator).
    """
    return AgentConfig(
        name="mastery_judge",
        model=model,
        reasoning=reasoning,
        max_steps=max_steps,
        max_tokens=max_tokens,
        temperature=temperature if temperature is not None else 0.0,
        top_p=top_p,
        system_prompt=load_agent_prompt("mastery_judge"),
        tools=None,
        internal=True,
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
        emit = self.emit  # capture locally — race-safe against parallel rebinds
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
        if favicons and emit is not None:
            emit({"type": "tool_progress", "data": {"favicons": favicons}})

        return json.dumps(resp, ensure_ascii=False)


class FetchTool(Tool):
    def __init__(self, client: TinyfishClient, emit=None):
        self.client = client
        self.emit = emit

    name = "tinyfish_fetch_content"
    description = "Read full content from 1-3 URLs. Returns clean markdown."
    schema = {
        "type": "object",
        "properties": {
            "urls": {
                "type": "array",
                "items": {"type": "string"},
                "description": "URLs to fetch (max 3)",
            }
        },
        "required": ["urls"],
    }

    async def execute(self, raw_args: str) -> str:
        emit = self.emit  # capture locally — race-safe against parallel rebinds
        try:
            args = json.loads(raw_args)
            urls = args["urls"][:3]
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            return tool_error(f"invalid args: {e}")

        favicons = []
        for u in urls:
            domain = _extract_domain(u)
            if domain:
                favicons.append(_favicon_url(domain))
        if favicons and emit is not None:
            emit({"type": "tool_progress", "data": {"favicons": favicons}})

        try:
            resp = await self.client.fetch_content(urls)
        except TinyfishError as e:
            return tool_error(str(e))
        if isinstance(resp, dict):
            resp["results"] = [
                {**r, "content": r.get("content", "")[:50000]}
                for r in resp.get("results", []) or []
            ]
        return json.dumps(resp, ensure_ascii=False)


def new_researcher_tools(tf_client: TinyfishClient, rag_engine=None, emit=None, reports=None) -> Registry:
    reg = Registry()
    reg.register(SearchTool(tf_client, emit=emit))
    reg.register(FetchTool(tf_client, emit=emit))
    if rag_engine is not None:
        reg.register(RagSearch(rag_engine, reports_repo=reports))
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
        system_prompt=system_prompt_override or load_agent_prompt("web_researcher"),
        tools=new_researcher_tools(tf_client, rag_engine, emit=tool_emit),
    )


def documentalist_config(
    model: str,
    reasoning: str,
    max_steps: int,
    llm_client: DeepSeekClient,
    rag_engine,
    tf_client: TinyfishClient,
    reports,
    session_id,
    emit: Emit,
    max_tokens: int | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    system_prompt_override: str | None = None,
) -> AgentConfig:
    from cognits.agent.tool_deploy import DeploySubagent

    registry = new_researcher_tools(tf_client, reports=reports)
    registry.register(RagSearch(rag_engine, reports_repo=reports))

    subagents = {
        "web_researcher": AgentConfig(
            name="web_researcher",
            model=model,
            reasoning=reasoning,
            max_steps=max_steps,
            system_prompt=load_agent_prompt("web_researcher"),
            tools=new_researcher_tools(tf_client, rag_engine, reports=reports),
        )
    }

    registry.register(
        DeploySubagent(
            llm_client=llm_client,
            reports=reports,
            subagents=subagents,
            session_id=session_id,
            emit=emit,
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
        system_prompt=system_prompt_override or load_agent_prompt("documentalist"),
        tools=registry,
    )






def skill_planner_config(
    model: str,
    reasoning: str,
    max_steps: int,
    llm_client: DeepSeekClient,
    rag_engine,
    tf_client: TinyfishClient,
    reports,
    skills,
    assessment,
    learner_state,
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
    from cognits.agent.tool_mastery import SeedMastery, UpdateMastery
    from cognits.agent.tool_skill import SkillTreeSave

    registry = Registry()
    if rag_engine is not None:
        registry.register(RagSearch(rag_engine, reports_repo=reports))
    registry.register(
        SkillTreeSave(skills=skills, assessment=assessment, session_id=session_id, emit=tool_emit, rag_engine=rag_engine)
    )
    registry.register(UpdateMastery(learner_state=learner_state, skills=skills))
    registry.register(SeedMastery(learner_state=learner_state, skills=skills))

    researcher_max_steps = RESEARCHER_MAX_STEPS  # DEFAULT_RESEARCHER_MAX_STEPS in routes_chat
    subagents = {
        "web_researcher": AgentConfig(
            name="web_researcher",
            model=model,
            reasoning=reasoning,
            max_steps=researcher_max_steps,
            system_prompt=load_agent_prompt("web_researcher"),
            tools=new_researcher_tools(tf_client, rag_engine, reports=reports),
        ),
        "skill_branch_builder": skill_branch_builder_config(
            model=DEFAULT_MODEL,
            reasoning="max",
            max_steps=BRANCH_BUILDER_MAX_STEPS,
            llm_client=llm_client,
            rag_engine=rag_engine,
            tf_client=tf_client,
            reports=reports,
            skills=skills,
            assessment=assessment,
            learner_state=learner_state,
            session_id=session_id,
            emit=emit,
            tinyfish_api_key=tinyfish_api_key,
            tool_emit=tool_emit,
        ),
    }

    registry.register(
        DeploySubagent(
            llm_client=llm_client,
            reports=reports,
            subagents=subagents,
            session_id=session_id,
            emit=emit,
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
        system_prompt=system_prompt_override or load_agent_prompt("skill_planner"),
        tools=registry,
        subagents=subagents,
    )


def skill_branch_builder_config(
    model: str,
    reasoning: str,
    max_steps: int,
    llm_client,
    rag_engine,
    tf_client,
    reports,
    skills,
    assessment,
    learner_state,
    session_id,
    emit: Emit,
    max_tokens: int | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    system_prompt_override: str | None = None,
    tinyfish_api_key: str = "",
    tool_emit=None,
) -> AgentConfig:
    """Build the per-domain Skill Branch Builder subagent config.

    Scoped to ONE domain (unlike the level-0 skill_planner which owns the
    full tree). Tools: SkillTreeSave, SeedMastery, UpdateMastery,
    DeploySubagent (web_researcher only - no self-recursion; 2-level
    fractal MVP), and RagSearch (when RAG is ready).

    Its report is internal (goes to the level-0 planner, not the user),
    mirroring the skill_planner's internal flag.
    """
    from cognits.agent.tool_deploy import DeploySubagent
    from cognits.agent.tool_mastery import SeedMastery, UpdateMastery
    from cognits.agent.tool_skill import SkillTreeSave

    registry = Registry()
    if rag_engine is not None:
        registry.register(RagSearch(rag_engine, reports_repo=reports))
    registry.register(
        SkillTreeSave(skills=skills, assessment=assessment, session_id=session_id, emit=tool_emit)
    )
    registry.register(UpdateMastery(learner_state=learner_state, skills=skills))
    registry.register(SeedMastery(learner_state=learner_state, skills=skills))

    researcher_max_steps = RESEARCHER_MAX_STEPS
    subagents = {
        "web_researcher": AgentConfig(
            name="web_researcher",
            model=DEFAULT_MODEL,
            reasoning="max",
            max_steps=researcher_max_steps,
            system_prompt=load_agent_prompt("web_researcher"),
            tools=new_researcher_tools(tf_client, rag_engine, reports=reports),
        )
    }

    registry.register(
        DeploySubagent(
            llm_client=llm_client,
            reports=reports,
            subagents=subagents,
            session_id=session_id,
            emit=emit,
            rag_engine=rag_engine,
            tinyfish_api_key=tinyfish_api_key,
        )
    )

    return AgentConfig(
        name="skill_branch_builder",
        model=model,
        reasoning=reasoning,
        max_steps=max_steps,
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=top_p,
        system_prompt=system_prompt_override or load_agent_prompt("skill_branch_builder"),
        tools=registry,
        subagents=subagents,
        internal=True,
    )





def study_planner_config(
    model: str,
    reasoning: str,
    max_steps: int,
    reports,
    plans,
    skills,
    learner_state,
    pedagogy,
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
        PlanStudy(plans=plans, skills=skills, learner_state=learner_state, session_id=session_id)
    )
    registry.register(SavePedagogicalPlan(skills=skills, pedagogy=pedagogy))
    if rag_engine is not None:
        registry.register(RagSearch(rag_engine, reports_repo=reports))

    subagents: dict[str, AgentConfig] = {}
    if llm_client is not None and tf_client is not None:
        researcher_max_steps = RESEARCHER_MAX_STEPS
        subagents["web_researcher"] = AgentConfig(
            name="web_researcher",
            model=model,
            reasoning=reasoning,
            max_steps=researcher_max_steps,
            system_prompt=load_agent_prompt("web_researcher"),
            tools=new_researcher_tools(tf_client, rag_engine, reports=reports),
        )

    registry.register(
            DeploySubagent(
                llm_client=llm_client,
                reports=reports,
                subagents=subagents,
                session_id=session_id,
                emit=emit,
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
        system_prompt=system_prompt_override or load_agent_prompt("study_planner"),
        tools=registry,
        subagents=subagents,
    )





def evaluator_config(
    model: str,
    reasoning: str,
    max_steps: int,
    llm_client: DeepSeekClient,
    rag_engine,
    tf_client: TinyfishClient,
    reports,
    skills,
    assessment,
    learner_state,
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
    from cognits.agent.tool_skill import SkillTreeSave

    registry = Registry()
    if rag_engine is not None:
        registry.register(RagSearch(rag_engine, reports_repo=reports))
    registry.register(UpdateMastery(learner_state=learner_state, skills=skills))
    registry.register(
        SkillTreeSave(skills=skills, assessment=assessment, session_id=session_id, rag_engine=rag_engine)
    )

    researcher_max_steps = RESEARCHER_MAX_STEPS
    subagents = {
        "web_researcher": AgentConfig(
            name="web_researcher",
            model=model,
            reasoning=reasoning,
            max_steps=researcher_max_steps,
            system_prompt=load_agent_prompt("web_researcher"),
            tools=new_researcher_tools(tf_client, rag_engine, reports=reports),
        )
    }

    registry.register(
        DeploySubagent(
            llm_client=llm_client,
            reports=reports,
            subagents=subagents,
            session_id=session_id,
            emit=emit,
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
        system_prompt=system_prompt_override or load_agent_prompt("evaluator"),
        tools=registry,
        subagents=subagents,
        internal=True,
    )






def teacher_config(
    model: str,
    reasoning: str,
    max_steps: int,
    llm_client,
    rag_engine,
    tf_client,
    reports,
    skills,
    assessment,
    learner_state,
    messages=None,
    pedagogy=None,
    session_id=None,
    emit: Emit = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    system_prompt_override: str | None = None,
    tinyfish_api_key: str = "",
    suspended_subagents: dict | None = None,
) -> AgentConfig:
    """Build the Teacher (Maestro) subagent config.

    Deployed as the main agent of a learning session (agent_id = 'maestro').
    Tools: DeploySubagent with documentalist + evaluator subagents,
    plus CheckBranchFloor for per-branch floor discovery,
    plus RefocusTree for goal-change re-decomposition."""
    from cognits.agent.tool_deploy import DeploySubagent
    from cognits.agent.tool_floor import CheckBranchFloor
    from cognits.agent.tool_refocus import RefocusTree

    doc_cfg: dict | None = None
    if tf_client is not None:
        doc_cfg = documentalist_config(
            model, reasoning, DOCUMENTALIST_MAX_STEPS, llm_client, rag_engine, tf_client,
            reports, session_id, emit,
        )

    eval_cfg = evaluator_config(
        model, reasoning, EVALUATOR_MAX_STEPS, llm_client, rag_engine, tf_client,
        reports, skills, assessment, learner_state, session_id, emit,
        system_prompt_override=None,
        tinyfish_api_key=tinyfish_api_key,
        suspended_subagents=suspended_subagents,
    )

    subagents: dict[str, AgentConfig] = {"evaluator": eval_cfg}
    if doc_cfg is not None:
        subagents["documentalist"] = doc_cfg

    registry = Registry()
    registry.register(
        DeploySubagent(
            llm_client=llm_client,
            reports=reports,
            subagents=subagents,
            session_id=session_id,
            emit=emit,
            rag_engine=rag_engine,
            tinyfish_api_key=tinyfish_api_key,
            suspended_subagents=suspended_subagents,
        )
    )

    # Wire CheckBranchFloor + RefocusTree when messages repo is available.
    if messages is not None:
        registry.register(
            CheckBranchFloor(
                skills=skills,
                learner_state=learner_state,
                messages=messages,
                llm_client=llm_client,
                rag_engine=rag_engine,
                tf_client=tf_client,
                reports=reports,
                assessment=assessment,
                session_id=session_id,
                emit=emit,
                tinyfish_api_key=tinyfish_api_key,
            )
        )
        registry.register(
            RefocusTree(
                skills=skills,
                learner_state=learner_state,
                assessment=assessment,
                llm_client=llm_client,
                rag_engine=rag_engine,
                tf_client=tf_client,
                reports=reports,
                session_id=session_id,
                emit=emit,
                tinyfish_api_key=tinyfish_api_key,
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
        system_prompt=system_prompt_override or load_agent_prompt("maestro"),
        tools=registry,
        subagents=subagents,
    )
