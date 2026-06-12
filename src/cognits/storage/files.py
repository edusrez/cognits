"""Port of internal/storage/storage.go: JSON sessions, global config, crypto.

The encrypted format is bit-compatible with the Go backend's
(base64std(nonce_12B || ciphertext || tag_GCM)) and the key is reused as-is
from the location Go used.
"""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from cognits import paths

NONCE_SIZE = 12


def write_file_atomic(path: Path, data: bytes) -> None:
    # Write to a temp file and rename: a crash mid-write cannot leave the
    # destination file truncated or corrupted.
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


@dataclass
class Session:
    id: str = ""
    name: str = ""
    created_at: str = ""

    def to_json(self) -> dict:
        return {"id": self.id, "name": self.name, "createdAt": self.created_at}

    @classmethod
    def from_json(cls, d: dict) -> "Session":
        return cls(
            id=d.get("id", ""),
            name=d.get("name", ""),
            created_at=d.get("createdAt", ""),
        )


@dataclass
class SubagentConfig:
    model: str = ""
    reasoning: str = ""
    max_steps: int = 0

    def to_json(self) -> dict:
        return {"model": self.model, "reasoning": self.reasoning, "maxSteps": self.max_steps}

    @classmethod
    def from_json(cls, d: dict) -> "SubagentConfig":
        return cls(
            model=d.get("model", ""),
            reasoning=d.get("reasoning", ""),
            max_steps=int(d.get("maxSteps", 0) or 0),
        )


@dataclass
class Config:
    llm_provider: str = ""
    llm_agent_id: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    llm_reasoning: str = ""
    agent_overrides: dict[str, str] = field(default_factory=dict)
    chat_font_size: int = 0
    tinyfish_api_key: str = ""
    tinyfish_tier: str = ""
    subagent_config: dict[str, SubagentConfig] = field(default_factory=dict)
    user_name: str = ""
    user_location: str = ""
    default_learnit_viewport: str = ""
    write_langs: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        return {
            "llmProvider": self.llm_provider,
            "llmAgentId": self.llm_agent_id,
            "llmApiKey": self.llm_api_key,
            "llmModel": self.llm_model,
            "llmReasoning": self.llm_reasoning,
            "agentOverrides": self.agent_overrides,
            "chatFontSize": self.chat_font_size,
            "tinyfishApiKey": self.tinyfish_api_key,
            "tinyfishTier": self.tinyfish_tier,
            "subagentConfig": {k: v.to_json() for k, v in self.subagent_config.items()},
            "userName": self.user_name,
            "userLocation": self.user_location,
            "defaultLearnitViewport": self.default_learnit_viewport,
            "writeLangs": self.write_langs,
        }

    @classmethod
    def from_json(cls, d: dict) -> "Config":
        return cls(
            llm_provider=d.get("llmProvider") or "",
            llm_agent_id=d.get("llmAgentId") or "",
            llm_api_key=d.get("llmApiKey") or "",
            llm_model=d.get("llmModel") or "",
            llm_reasoning=d.get("llmReasoning") or "",
            agent_overrides=d.get("agentOverrides") or {},
            chat_font_size=int(d.get("chatFontSize", 0) or 0),
            tinyfish_api_key=d.get("tinyfishApiKey") or "",
            tinyfish_tier=d.get("tinyfishTier") or "",
            subagent_config={
                k: SubagentConfig.from_json(v or {})
                for k, v in (d.get("subagentConfig") or {}).items()
            },
            user_name=d.get("userName") or "",
            user_location=d.get("userLocation") or "",
            default_learnit_viewport=d.get("defaultLearnitViewport") or "",
            write_langs=d.get("writeLangs") or [],
        )


def encrypt_with_key(key: bytes, plaintext: str) -> str:
    nonce = os.urandom(NONCE_SIZE)
    ct = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.b64encode(nonce + ct).decode("ascii")


def decrypt_with_key(key: bytes, cipher_b64: str) -> str:
    raw = base64.b64decode(cipher_b64)
    if len(raw) < NONCE_SIZE:
        raise ValueError("storage: ciphertext too short")
    nonce, ct = raw[:NONCE_SIZE], raw[NONCE_SIZE:]
    return AESGCM(key).decrypt(nonce, ct, None).decode("utf-8")


def _session_sort_key(s: Session) -> float:
    try:
        return datetime.fromisoformat(s.created_at.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


class Store:
    def __init__(self, base_path: Path):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    # --- sessions ---

    def _sessions_dir(self) -> Path:
        return self.base_path / "sessions"

    def _session_path(self, session_id: str) -> Path:
        return self._sessions_dir() / f"{session_id}.json"

    def init_sessions_dir(self) -> None:
        self._sessions_dir().mkdir(parents=True, exist_ok=True)

    def save_session(self, session: Session) -> None:
        data = json.dumps(session.to_json(), indent=2, ensure_ascii=False)
        self._session_path(session.id).write_text(data, encoding="utf-8")

    def list_sessions(self) -> list[Session]:
        sessions: list[Session] = []
        try:
            entries = list(self._sessions_dir().iterdir())
        except FileNotFoundError:
            return sessions
        for p in entries:
            if p.is_dir() or p.suffix != ".json":
                continue
            try:
                sessions.append(Session.from_json(json.loads(p.read_text(encoding="utf-8"))))
            except (OSError, json.JSONDecodeError):
                continue
        sessions.sort(key=_session_sort_key)
        return sessions

    def get_session(self, session_id: str) -> Session | None:
        try:
            data = self._session_path(session_id).read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        return Session.from_json(json.loads(data))

    def rename_session(self, session_id: str, new_name: str) -> None:
        session = self.get_session(session_id)
        if session is None:
            raise FileNotFoundError(f"storage: session {session_id} not found")
        session.name = new_name
        self.save_session(session)

    def delete_session(self, session_id: str) -> None:
        self._session_path(session_id).unlink(missing_ok=True)

    # --- config + crypto ---

    def _config_path(self) -> Path:
        return self.base_path / "config.json"

    def _legacy_encryption_key_path(self) -> Path:
        return self.base_path / ".encryption-key"

    def ensure_encryption_key(self) -> bytes:
        key_path = paths.encryption_key_path()
        try:
            return key_path.read_bytes()
        except FileNotFoundError:
            pass

        key_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(key_path.parent, 0o700)
        except OSError:
            pass

        # Migration from the Go backend's key (~/.config/learnit/): copied
        # without deleting the original so the legacy Go binary keeps working
        # during the transition.
        go_key = paths.go_encryption_key_path()
        if go_key.is_file():
            key = go_key.read_bytes()
            key_path.write_bytes(key)
            os.chmod(key_path, 0o600)
            return key

        # Migration from the old in-project location (pre-Go).
        legacy = self._legacy_encryption_key_path()
        if legacy.is_file():
            key = legacy.read_bytes()
            key_path.write_bytes(key)
            os.chmod(key_path, 0o600)
            legacy.unlink(missing_ok=True)
            return key

        key = os.urandom(32)
        key_path.write_bytes(key)
        os.chmod(key_path, 0o600)
        return key

    def encrypt_api_key(self, plaintext: str) -> str:
        if plaintext == "":
            return ""
        return encrypt_with_key(self.ensure_encryption_key(), plaintext)

    def decrypt_api_key(self, cipher_b64: str) -> str:
        if cipher_b64 == "":
            return ""
        return decrypt_with_key(self.ensure_encryption_key(), cipher_b64)

    def load_config(self) -> Config:
        try:
            data = self._config_path().read_text(encoding="utf-8")
        except FileNotFoundError:
            return Config()
        cfg = Config.from_json(json.loads(data))
        if cfg.llm_api_key:
            cfg.llm_api_key = self.decrypt_api_key(cfg.llm_api_key)
        if cfg.tinyfish_api_key:
            cfg.tinyfish_api_key = self.decrypt_api_key(cfg.tinyfish_api_key)
        return cfg

    def save_config(self, cfg: Config) -> None:
        self.base_path.mkdir(parents=True, exist_ok=True)
        # Do not mutate the caller's object: the encrypted copy is disk-only.
        on_disk = Config.from_json(cfg.to_json())
        if on_disk.llm_api_key:
            on_disk.llm_api_key = self.encrypt_api_key(on_disk.llm_api_key)
        if on_disk.tinyfish_api_key:
            on_disk.tinyfish_api_key = self.encrypt_api_key(on_disk.tinyfish_api_key)
        data = json.dumps(on_disk.to_json(), indent=2, ensure_ascii=False).encode("utf-8")
        write_file_atomic(self._config_path(), data)
