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
    tmp = path.with_name(path.name + ".tmp")
    try:
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp, path)
        dfd = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
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
    max_tokens: int = 0
    temperature: float = 0.0
    top_p: float = 0.0

    def to_json(self) -> dict:
        return {
            "model": self.model,
            "reasoning": self.reasoning,
            "maxSteps": self.max_steps,
            "maxTokens": self.max_tokens,
            "temperature": self.temperature,
            "topP": self.top_p,
        }

    @classmethod
    def from_json(cls, d: dict) -> "SubagentConfig":
        return cls(
            model=d.get("model", ""),
            reasoning=d.get("reasoning", ""),
            max_steps=int(d.get("maxSteps", 0) or 0),
            max_tokens=int(d.get("maxTokens", 0) or 0),
            temperature=float(d.get("temperature", 0.0) or 0.0),
            top_p=float(d.get("topP", 0.0) or 0.0),
        )


@dataclass
class DoclingConfig:
    table_mode: str = "fast"
    images_scale: float = 1.0
    do_ocr: bool = True
    do_code_enrichment: bool = False
    do_formula_enrichment: bool = False
    do_picture_classification: bool = False
    force_backend_text: bool = True

    def to_json(self) -> dict:
        return {
            "tableMode": self.table_mode,
            "imagesScale": self.images_scale,
            "doOcr": self.do_ocr,
            "doCodeEnrichment": self.do_code_enrichment,
            "doFormulaEnrichment": self.do_formula_enrichment,
            "doPictureClassification": self.do_picture_classification,
            "forceBackendText": self.force_backend_text,
        }

    @classmethod
    def from_json(cls, d: dict | None) -> "DoclingConfig":
        if not d:
            return cls()
        return cls(
            table_mode=d.get("tableMode") or "fast",
            images_scale=float(d.get("imagesScale", 1.0) or 1.0),
            do_ocr=bool(d.get("doOcr", True)),
            do_code_enrichment=bool(d.get("doCodeEnrichment", False)),
            do_formula_enrichment=bool(d.get("doFormulaEnrichment", False)),
            do_picture_classification=bool(d.get("doPictureClassification", False)),
            force_backend_text=bool(d.get("forceBackendText", True)),
        )


@dataclass
class StudentProfile:
    version: int = 1
    declared: dict = field(default_factory=dict)
    inferred: dict = field(default_factory=dict)
    meta: dict = field(default_factory=dict)

    def to_json(self) -> dict:
        return {
            "version": self.version,
            "declared": self.declared,
            "inferred": self.inferred,
            "meta": self.meta,
        }

    @classmethod
    def from_json(cls, d: dict | None) -> "StudentProfile":
        if not d:
            return cls()
        return cls(
            version=int(d.get("version", 1) or 1),
            declared=d.get("declared") or {},
            inferred=d.get("inferred") or {},
            meta=d.get("meta") or {},
        )


@dataclass
class Config:
    llm_provider: str = ""
    llm_agent_id: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    llm_reasoning: str = ""
    providers: dict = field(default_factory=dict)
    agent_overrides: dict[str, str] = field(default_factory=dict)
    chat_font_size: int = 0
    note_font_size: int = 0
    report_font_size: int = 0
    typewriter_speed: float = 5.0
    tinyfish_api_key: str = ""
    tinyfish_tier: str = ""
    subagent_config: dict[str, SubagentConfig] = field(default_factory=dict)
    user_name: str = ""
    user_location: str = ""
    default_learnit_viewport: str = ""
    default_files_viewport: str = ""
    pdf_headings: bool = True
    docling_config: DoclingConfig = field(default_factory=DoclingConfig)
    write_langs: list[str] = field(default_factory=list)
    note_mode: str = ""
    max_tokens: int = 0
    temperature: float = 0.0
    top_p: float = 0.0
    max_steps: int = 0
    display_thinking: bool = True
    reflection_enabled: bool = True

    def to_json(self) -> dict:
        return {
            "llmProvider": self.llm_provider,
            "llmAgentId": self.llm_agent_id,
            "llmApiKey": self.llm_api_key,
            "llmModel": self.llm_model,
            "llmReasoning": self.llm_reasoning,
            "providers": self.providers,
            "agentOverrides": self.agent_overrides,
            "chatFontSize": self.chat_font_size,
            "noteFontSize": self.note_font_size,
            "reportFontSize": self.report_font_size,
            "typewriterSpeed": self.typewriter_speed,
            "tinyfishApiKey": self.tinyfish_api_key,
            "tinyfishTier": self.tinyfish_tier,
            "subagentConfig": {k: v.to_json() for k, v in self.subagent_config.items()},
            "userName": self.user_name,
            "userLocation": self.user_location,
            "defaultLearnitViewport": self.default_learnit_viewport,
            "defaultFilesViewport": self.default_files_viewport,
            "pdfHeadings": self.pdf_headings,
            "doclingConfig": self.docling_config.to_json(),
            "writeLangs": self.write_langs,
            "noteMode": self.note_mode,
            "maxTokens": self.max_tokens,
            "temperature": self.temperature,
            "topP": self.top_p,
            "maxSteps": self.max_steps,
            "displayThinking": self.display_thinking,
            "reflectionEnabled": self.reflection_enabled,
        }

    @classmethod
    def from_json(cls, d: dict) -> "Config":
        return cls(
            llm_provider=d.get("llmProvider") or "",
            llm_agent_id=d.get("llmAgentId") or "",
            llm_api_key=d.get("llmApiKey") or "",
            llm_model=d.get("llmModel") or "",
            llm_reasoning=d.get("llmReasoning") or "",
            providers=d.get("providers") or {},
            agent_overrides=d.get("agentOverrides") or {},
            chat_font_size=int(d.get("chatFontSize", 0) or 0),
            note_font_size=int(d.get("noteFontSize", 0) or 0),
            report_font_size=int(d.get("reportFontSize", 0) or 0),
            typewriter_speed=float(d.get("typewriterSpeed", 5.0) or 5.0),
            tinyfish_api_key=d.get("tinyfishApiKey") or "",
            tinyfish_tier=d.get("tinyfishTier") or "",
            subagent_config={
                k: SubagentConfig.from_json(v or {})
                for k, v in (d.get("subagentConfig") or {}).items()
            },
            user_name=d.get("userName") or "",
            user_location=d.get("userLocation") or "",
            default_learnit_viewport=d.get("defaultLearnitViewport") or "",
            default_files_viewport=d.get("defaultFilesViewport") or "",
            pdf_headings=bool(d.get("pdfHeadings", True)),
            docling_config=DoclingConfig.from_json(d.get("doclingConfig")),
            write_langs=d.get("writeLangs") or [],
            note_mode=d.get("noteMode") or "",
            max_tokens=int(d.get("maxTokens", 0) or 0),
            temperature=float(d.get("temperature", 0.0) or 0.0),
            top_p=float(d.get("topP", 0.0) or 0.0),
            max_steps=int(d.get("maxSteps", 0) or 0),
            display_thinking=bool(d.get("displayThinking", True)),
            reflection_enabled=bool(d.get("reflectionEnabled", True)),
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

    # --- profile ---

    def _profile_dir(self) -> Path:
        return self.base_path / "student"

    def _profile_path(self) -> Path:
        return self._profile_dir() / "profile.json"

    def load_profile(self) -> StudentProfile:
        try:
            data = self._profile_path().read_text(encoding="utf-8")
        except FileNotFoundError:
            return StudentProfile()
        return StudentProfile.from_json(json.loads(data))

    def save_profile(self, profile: StudentProfile) -> None:
        self._profile_dir().mkdir(parents=True, exist_ok=True)
        data = json.dumps(profile.to_json(), indent=2, ensure_ascii=False).encode("utf-8")
        write_file_atomic(self._profile_path(), data)

    def reset_setup_state(self) -> None:
        if self._profile_path().exists():
            self._profile_path().unlink()
        sessions_dir = self._sessions_dir()
        if sessions_dir.exists():
            for f in sessions_dir.iterdir():
                if f.is_file():
                    f.unlink()
        order_path = self._order_path()
        if order_path.exists():
            order_path.unlink()
        db_path = self.base_path / "cognits.db"
        if db_path.exists():
            db_path.unlink()
        legacy_db = self.base_path / "learnit.db"
        if legacy_db.exists():
            legacy_db.unlink()
        try:
            cfg = self.load_config()
        except Exception:
            cfg = Config()
        cfg.llm_api_key = ""
        cfg.tinyfish_api_key = ""
        self.save_config(cfg)

    # --- sessions ---

    def _sessions_dir(self) -> Path:
        return self.base_path / "sessions"

    def _session_path(self, session_id: str) -> Path:
        return self._sessions_dir() / f"{session_id}.json"

    def init_sessions_dir(self) -> None:
        self._sessions_dir().mkdir(parents=True, exist_ok=True)

    def save_session(self, session: Session) -> None:
        data = json.dumps(session.to_json(), indent=2, ensure_ascii=False).encode("utf-8")
        write_file_atomic(self._session_path(session.id), data)

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
        order = self._load_order()
        if order:
            by_id = {s.id: s for s in sessions}
            ordered: list[Session] = []
            for sid in order:
                if sid in by_id:
                    ordered.append(by_id.pop(sid))
            ordered.extend(by_id.values())
            sessions = ordered
        else:
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

    def _order_path(self) -> Path:
        return self.base_path / "session_order.json"

    def reorder_sessions(self, ordered_ids: list[str]) -> None:
        data = json.dumps(ordered_ids).encode("utf-8")
        write_file_atomic(self._order_path(), data)

    def _load_order(self) -> list[str]:
        try:
            data = json.loads(self._order_path().read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (FileNotFoundError, json.JSONDecodeError):
            return []

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
