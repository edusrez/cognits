"""UI manipulation tool for the System Support agent."""

from __future__ import annotations

import asyncio
import datetime
import json
from collections.abc import Awaitable, Callable

from cognits.tools import Tool, tool_error
from cognits.storage.files import StudentProfile


class ToggleTabVisibility(Tool):
    def __init__(self, emit=None):
        self.emit = emit

    name = "toggle_tab_visibility"
    description = (
        "Show or hide a tab in the user interface. Use this to guide the "
        "user through the interface: show Settings when needed, hide setup "
        "after onboarding, etc. Always explain what you're doing before "
        "calling this tool."
    )
    schema = {
        "type": "object",
        "properties": {
            "viewportId": {
                "type": "string",
                "description": "Viewport identifier (e.g. '111' for right panel, '1100' for center-upper, '1101' for center-lower).",
            },
            "tabId": {
                "type": "string",
                "description": "Tab identifier (e.g. 'settings', 'chat', 'write', 'setup', 'files', 'sessions').",
            },
            "hidden": {
                "type": "boolean",
                "description": "Set to true to hide the tab, false to show it.",
            },
        },
        "required": ["viewportId", "tabId", "hidden"],
    }

    async def execute(self, raw_args: str) -> str:
        try:
            args = json.loads(raw_args)
            viewport_id = args["viewportId"]
            tab_id = args["tabId"]
            hidden = bool(args["hidden"])
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            return tool_error(f"invalid args: {e}")

        if self.emit is not None:
            self.emit({
                "type": "ui_action",
                "data": {
                    "action": "toggle_tab",
                    "viewportId": viewport_id,
                    "tabId": tab_id,
                    "hidden": hidden,
                },
            })

        verb = "hidden" if hidden else "shown"
        return json.dumps({
            "message": f"Tab '{tab_id}' in viewport '{viewport_id}' is now {verb}.",
        }, ensure_ascii=False)


class CreateLearningSession(Tool):
    """Signal the frontend to create a new learning session for a
    specific skill. The tool does NOT create the session directly — it
    emits a ``create_learning_session`` SSE event. The frontend (Fase 10)
    will listen and call POST /api/sessions + POST .../config with
    agent_id="maestro"."""

    def __init__(self, emit=None, report_store=None):
        self.emit = emit
        self.store = report_store

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

    async def execute(self, raw_args: str) -> str:
        try:
            args = json.loads(raw_args)
            skill_name = args["skill_name"].strip()
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            return tool_error(f"invalid args: {e}")

        if not skill_name:
            return tool_error("skill_name is required")

        # Validate the skill exists in the tree.
        if self.store is not None:
            skills = await asyncio.to_thread(self.store.list_skills)
            found = any(s.name.lower() == skill_name.lower() for s in skills)
            if not found:
                return tool_error(
                    f"skill '{skill_name}' not found in the skill tree. "
                    "Ask the user to choose a different skill."
                )

        if self.emit is not None:
            self.emit({
                "type": "create_learning_session",
                "data": {"skill_name": skill_name},
            })

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
            self.store.save_profile(profile)

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
