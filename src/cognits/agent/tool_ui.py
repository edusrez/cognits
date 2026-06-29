"""UI manipulation tool for the System Support agent."""

from __future__ import annotations

import datetime
import json

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


class FinishSetup(Tool):
    def __init__(self, emit=None, store=None):
        self.emit = emit
        self.store = store

    name = "finish_setup"
    description = (
        "Complete the onboarding interview and save the user's learning "
        "profile. Call this ONLY after you have presented a structured "
        "summary to the user and they have confirmed it. This tool "
        "finalizes the setup and transitions the UI to normal operation."
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

        if self.emit is not None:
            self.emit({
                "type": "setup_complete",
                "data": {
                    "background": background,
                    "project": project,
                },
            })

        return json.dumps({
            "message": "Profile saved. Setup is complete.",
        }, ensure_ascii=False)
