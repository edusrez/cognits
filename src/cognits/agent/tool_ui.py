"""UI manipulation tools."""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
from collections.abc import Awaitable, Callable
from difflib import SequenceMatcher

from cognits.constants import CHANGELOG_VALUE_MAX_CHARS
from cognits.tools import Tool, tool_error
from cognits.storage.files import StudentProfile

log_ui = logging.getLogger("cognits.tool_ui")


class CreateLearningSession(Tool):
    """Signal the frontend to create a new learning session for a
    specific skill. The tool does NOT create the session directly — it
    emits a ``create_learning_session`` SSE event. The frontend (Fase 10)
    will listen and call POST /api/sessions + POST .../config with
    agent_id="maestro"."""

    def __init__(self, emit=None, skills=None, session_id: Callable[[], str] | None = None, store=None):
        self.emit = emit
        self.skills = skills
        self.session_id = session_id
        self.store = store

    name = "create_learning_session"
    description = (
        "Signal the frontend to create a new learning session for a skill "
        "the user has chosen to learn. Call this ONLY after the user has "
        "explicitly confirmed they want to learn that skill. The UI will "
        "transition to a new learning session automatically — do NOT "
        "continue the conversation after calling this tool."
    )
    schema = {
        "type": "object",
        "properties": {
            "skill_name": {
                "type": "string",
                "description": "Name of the skill the user wants to learn (must match an existing skill name in the tree).",
            },
        },
        "required": ["skill_name"],
    }

    @staticmethod
    def _levenshtein(a: str, b: str) -> int:
        if len(a) < len(b):
            a, b = b, a
        if len(b) == 0:
            return len(a)
        prev = list(range(len(b) + 1))
        for i, ca in enumerate(a, 1):
            curr = [i]
            for j, cb in enumerate(b, 1):
                curr.append(min(
                    curr[j - 1] + 1,
                    prev[j] + 1,
                    prev[j - 1] + (0 if ca == cb else 1),
                ))
            prev = curr
        return prev[-1]

    @staticmethod
    def _fuzzy_match_skills(skills, query: str):
        q = " ".join(query.lower().strip().split())
        for s in skills:
            sn = " ".join(s.name.lower().strip().split())
            if q in sn or sn in q:
                return s
        best = None
        best_dist = 3
        for s in skills:
            sn = " ".join(s.name.lower().strip().split())
            d = CreateLearningSession._levenshtein(q, sn)
            if d < best_dist:
                best = s
                best_dist = d
        return best if best_dist <= 2 else None

    async def execute(self, raw_args: str) -> str:
        try:
            args = json.loads(raw_args)
            skill_name = args["skill_name"].strip()
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            return tool_error(f"invalid args: {e}")

        if not skill_name:
            return tool_error("skill_name is required")

        if self.skills is not None:
            skills = await asyncio.to_thread(self.skills.list_active)
            match = next((s for s in skills if s.name.lower() == skill_name.lower()), None)
            if match is None:
                match = self._fuzzy_match_skills(skills, skill_name)
            if match is None:
                return tool_error(
                    f"skill '{skill_name}' not found in the skill tree. "
                    "Use the list_skills or search_skills tool to find the exact name."
                )
            skill_id = match.id
        else:
            skill_id = ""

        if self.emit is not None:
            self.emit({
                "type": "create_learning_session",
                "data": {"skill_name": skill_name, "skill_id": skill_id},
            })

        if self.store is not None and self.session_id is not None:
            sid = self.session_id()
            if sid:
                try:
                    await asyncio.to_thread(self.store.hide_session, sid)
                except FileNotFoundError:
                    pass
                except Exception as e:
                    log_ui.warning("hide orchestrator session %s: %s", sid, e)

        return json.dumps({
            "message": f"Learning session requested for '{skill_name}'. The UI will transition.",
        }, ensure_ascii=False)


class FinishSetup(Tool):
    def __init__(
        self,
        emit=None,
        store=None,
        skill_planner_deployer: Callable[[str], Awaitable[str]] | None = None,
    ):
        self.emit = emit
        self.store = store
        # Optional async callable that runs the skill_planner subagent with
        # the profile serialised inline. When None (no TinyFish key), the
        # tool still saves the profile and emits setup_complete but marks
        # the skill tree as not built.
        self.skill_planner_deployer = skill_planner_deployer

    name = "finish_setup"
    description = (
        "Complete the onboarding interview and save the user's learning "
        "profile. Call this ONLY after you have presented a structured "
        "summary to the user and they have confirmed it. This tool "
        "finalizes the setup, optionally triggers the skill_planner "
        "subagent to build an initial skill tree (which may take several "
        "minutes), and transitions the UI to normal operation. The tool "
        "does not return until the skill tree pass finishes or fails."
    )
    schema = {
        "type": "object",
        "properties": {
            "background": {
                "type": "string",
                "description": "User's professional/academic background.",
            },
            "project": {
                "type": "string",
                "description": "What the user wants to learn or accomplish.",
            },
            "experience": {
                "type": "string",
                "description": "What the user already knows vs what is new.",
            },
            "learning_style": {
                "type": "string",
                "description": "Preferred learning approach (socratic, examples, hands-on, theory).",
            },
            "availability": {
                "type": "string",
                "description": "User's schedule and time constraints.",
            },
            "goals": {
                "type": "string",
                "description": "Short-term and long-term goals.",
            },
        },
        "required": ["background", "project", "experience", "learning_style", "availability", "goals"],
    }

    async def execute(self, raw_args: str) -> str:
        try:
            args = json.loads(raw_args)
            background = args["background"]
            project = args["project"]
            experience = args["experience"]
            learning_style = args["learning_style"]
            availability = args["availability"]
            goals = args["goals"]
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            return tool_error(f"invalid args: {e}")

        if self.store is not None:
            profile = StudentProfile(
                declared={
                    "background": background,
                    "project": project,
                    "experience": experience,
                    "preferences": {"style": learning_style},
                    "availability": availability,
                    "goals": [goals],
                },
                meta={
                    "created": datetime.datetime.now(datetime.timezone.utc).isoformat() + "Z",
                    "sessions": 0,
                    "source": "onboarding",
                },
            )
            await asyncio.to_thread(self.store.save_profile, profile)

        # Build the skill tree automatically when a deployer is wired (i.e.
        # TinyFish key is configured and the orchestrator registered skill_
        # planner). The tool does not return until the subagent finishes so
        # the system_support agent can report results to the user in one
        # coherent follow-up. setup_complete is emitted AFTER the tree pass
        # finishes so the UI stays in the onboarding state meanwhile.
        skill_tree_built = False
        skill_tree_report: str | None = None
        skill_tree_error: str | None = None
        if self.skill_planner_deployer is not None:
            query = self._serialize_profile_for_planner(
                background=background,
                project=project,
                experience=experience,
                learning_style=learning_style,
                availability=availability,
                goals=goals,
            )
            try:
                deployer_result = await self.skill_planner_deployer(query)
                try:
                    result_data = json.loads(deployer_result)
                except (TypeError, json.JSONDecodeError):
                    result_data = {"content": deployer_result}
                if isinstance(result_data, dict) and "error" in result_data:
                    skill_tree_error = str(result_data["error"])
                else:
                    skill_tree_built = True
                    skill_tree_report = (
                        result_data.get("content", "") if isinstance(result_data, dict) else ""
                    )
            except asyncio.CancelledError:
                # Let cancellation propagate: no setup_complete, no result.
                raise
            except Exception as e:
                skill_tree_error = str(e)
        else:
            skill_tree_error = "TinyFish API key not configured"

        if self.emit is not None:
            self.emit({
                "type": "setup_complete",
                "data": {
                    "background": background,
                    "project": project,
                    "skillTreeBuilt": skill_tree_built,
                },
            })

        return json.dumps({
            "message": "Profile saved. Setup is complete.",
            "skillTreeBuilt": skill_tree_built,
            "skillTreeReport": skill_tree_report,
            "skillTreeError": skill_tree_error,
        }, ensure_ascii=False)

    @staticmethod
    def _serialize_profile_for_planner(
        *,
        background: str,
        project: str,
        experience: str,
        learning_style: str,
        availability: str,
        goals: str,
    ) -> str:
        """Inline block passed to skill_planner as the first user message."""
        return (
            f"Project: {project}\n"
            f"Goals: {goals}\n"
            f"Experience: {experience}\n"
            f"Background: {background}\n"
            f"Learning style: {learning_style}\n"
            f"Availability: {availability}"
        )


class ApplyProfile(Tool):
    def __init__(self, store=None, session_id: str = "", emit=None):
        self.store = store
        self.session_id = session_id
        self.emit = emit

    name = "apply_profile"
    description = (
        "Merge a profile_patch into the learner's inferred profile. The patch "
        "is produced by the session_analyzer after analyzing the full session "
        "transcript. Only call this after deploying the session_analyzer."
    )
    schema = {
        "type": "object",
        "properties": {
            "patch_json": {
                "type": "string",
                "description": (
                    "The profile_patch JSON object produced by the session_analyzer, "
                    "serialized as a string. Must include inferred and meta keys."
                ),
            },
        },
        "required": ["patch_json"],
    }

    async def execute(self, raw_args: str) -> str:
        try:
            args = json.loads(raw_args)
            patch_json_str = args["patch_json"]
            patch = json.loads(patch_json_str)
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            return tool_error(f"invalid args: {e}")

        if self.store is None:
            return tool_error("store not available")

        try:
            profile = await asyncio.to_thread(self.store.load_profile)
        except Exception:
            profile = StudentProfile()

        inferred_patch = patch.get("inferred", {}) if isinstance(patch, dict) else {}
        meta_patch = patch.get("meta", {}) if isinstance(patch, dict) else {}

        for key, value in inferred_patch.items():
            if isinstance(value, dict) and "confidence" in value:
                patch_conf = value.get("confidence", 0.0)
                current = profile.inferred.get(key)
                current_conf = current.get("confidence", 0.0) if isinstance(current, dict) else 0.0
                if patch_conf > current_conf:
                    profile.inferred[key] = value
            else:
                profile.inferred[key] = value

        if meta_patch.get("sessions") == "increment":
            profile.meta["sessions"] = profile.meta.get("sessions", 0) + 1

        now = datetime.datetime.now(datetime.timezone.utc).isoformat() + "Z"
        changelog = profile.meta.get("changelog", [])
        if not isinstance(changelog, list):
            changelog = []
        changelog.append({
            "session_id": self.session_id,
            "timestamp": now,
            "changes": {k: str(v)[:CHANGELOG_VALUE_MAX_CHARS] for k, v in inferred_patch.items()},
        })
        profile.meta["changelog"] = changelog
        profile.meta["last_session_at"] = now

        await asyncio.to_thread(self.store.save_profile, profile)

        return json.dumps({
            "message": "Profile updated successfully.",
            "sessions": profile.meta.get("sessions", 0),
        }, ensure_ascii=False)


class ListSkills(Tool):
    def __init__(self, skills=None):
        self.skills = skills

    name = "list_skills"
    description = (
        "List all skills in the skill tree. Returns skill names, domains, "
        "and parent skill names. Use this to find the exact skill name "
        "before calling create_learning_session or save_pedagogical_plan."
    )
    schema = {
        "type": "object",
        "properties": {
            "domain": {"type": "string", "description": "Optional: filter by domain"},
        },
    }

    async def execute(self, raw_args: str) -> str:
        args = json.loads(raw_args) if raw_args else {}
        domain = args.get("domain") or None
        if self.skills is not None:
            skills = await asyncio.to_thread(self.skills.list_active, domain)
            result = [{"name": s.name, "domain": s.domain, "id": s.id} for s in skills]
            return json.dumps({"skills": result}, ensure_ascii=False)
        return json.dumps({"skills": []}, ensure_ascii=False)


class SearchSkills(Tool):
    def __init__(self, skills=None):
        self.skills = skills

    name = "search_skills"
    description = (
        "Search skills by name (fuzzy match). Returns matching skills with "
        "their exact names for use with create_learning_session."
    )
    schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Skill name or keyword to search for"},
        },
        "required": ["query"],
    }

    async def execute(self, raw_args: str) -> str:
        args = json.loads(raw_args)
        query = args["query"].strip()
        if self.skills is not None:
            skills = await asyncio.to_thread(self.skills.list_active)
            matches = []
            for s in skills:
                if query.lower() in s.name.lower() or s.name.lower() in query.lower():
                    matches.append({"name": s.name, "domain": s.domain, "id": s.id, "score": 1.0})
                else:
                    ratio = SequenceMatcher(None, query.lower(), s.name.lower()).ratio()
                    if ratio > 0.6:
                        matches.append({"name": s.name, "domain": s.domain, "id": s.id, "score": ratio})
            matches.sort(key=lambda x: -x["score"])
            return json.dumps({"skills": matches[:10]}, ensure_ascii=False)
        return json.dumps({"skills": []}, ensure_ascii=False)
