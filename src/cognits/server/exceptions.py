"""CognitsError hierarchy: consistent JSON error responses.

Replaces text_error() / JSONResponse / HTTPException with a single pattern:
    raise CognitsError(message, code, http_status)

Registered in app.py via @app.exception_handler(CognitsError).
"""

from __future__ import annotations


class CognitsError(Exception):
    def __init__(
        self,
        message: str,
        code: str = "INTERNAL_ERROR",
        http_status: int = 500,
        details: dict | None = None,
    ):
        self.message = message
        self.code = code
        self.http_status = http_status
        self.details = details or {}


class NotFoundError(CognitsError):
    def __init__(self, message: str = "not found", details: dict | None = None):
        super().__init__(message, "NOT_FOUND", 404, details)


class SessionNotFound(NotFoundError):
    def __init__(self, session_id: str = ""):
        super().__init__("session not found", {"session_id": session_id} if session_id else None)


class AgentBusy(CognitsError):
    def __init__(self, session_id: str):
        super().__init__(
            "agent already running for this session",
            "AGENT_BUSY", 409,
            {"session_id": session_id},
        )


class ConfigError(CognitsError):
    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message, "CONFIG_ERROR", 400, details)


class StorageError(CognitsError):
    def __init__(self, message: str):
        super().__init__(message, "STORAGE_ERROR", 500)
