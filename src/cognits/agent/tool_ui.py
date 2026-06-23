"""UI manipulation tool for the System Support agent."""

from __future__ import annotations

import json

from cognits.tools import Tool, tool_error


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
