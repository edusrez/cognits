"""Port of internal/agent/tools/rag_search.go."""

from __future__ import annotations

import json

from cognits.tools import Tool, tool_error


class RagSearch(Tool):
    def __init__(self, rag_engine):
        self.rag = rag_engine

    name = "rag_search"
    description = (
        "Search the internal knowledge base (indexed research reports and "
        "documentation). Returns relevant fragments with their source and "
        "similarity score."
    )
    schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Semantic search text"},
            "max_results": {
                "type": "integer",
                "description": "Maximum number of fragments to return (default 10)",
            },
        },
        "required": ["query"],
    }

    async def execute(self, raw_args: str) -> str:
        try:
            args = json.loads(raw_args)
            query = args["query"]
            max_results = int(args.get("max_results") or 0)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
            return tool_error(f"invalid args: {e}")

        try:
            results = await self.rag.search(query, max_results)
        except Exception as e:
            return tool_error(f"rag search error: {e}")

        if not results:
            return '{"found": false, "results": []}'

        out = [
            {
                "text": r.get("text", ""),
                "report_id": r.get("report_id", ""),
                "source_type": r.get("source_type", ""),
                "topic": r.get("topic", ""),
                "distance": r.get("distance", 0.0),
            }
            for r in results
        ]
        return json.dumps({"found": True, "results": out}, ensure_ascii=False)
