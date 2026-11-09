"""Server-side business sessions and one-time login transactions.

The browser only ever holds an opaque random session id. Unknown ids are
ignored (never adopted), and a new id is generated on every login.
"""

from __future__ import annotations

import json
import secrets
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

from .principal import Principal


def new_token() -> str:
    return secrets.token_urlsafe(32)


@dataclass
class SessionRecord:
    sid: str
    csrf_token: str
    created_at: float
    last_seen_at: float
    principal: Principal | None = None
    session_epoch: int | None = None
    session_checked_at: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def new(cls, now: float, principal: Principal | None = None) -> SessionRecord:
        return cls(
            sid=new_token(),
            csrf_token=new_token(),
            created_at=now,
            last_seen_at=now,
            principal=principal,
        )

    def dumps(self) -> str:
        data = asdict(self)
        data["principal"] = self.principal.to_dict() if self.principal else None
        return json.dumps(data)

    @classmethod
    def loads(cls, raw: str) -> SessionRecord:
        data = json.loads(raw)
        principal = data.get("principal")
        data["principal"] = Principal.from_dict(principal) if principal else None
        return cls(**data)


@dataclass(frozen=True)
class LoginTransaction:
    state: str
    nonce: str
    code_verifier: str
    return_to: str
    created_at: float

    def dumps(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def loads(cls, raw: str) -> LoginTransaction:
        return cls(**json.loads(raw))


class SessionStore(Protocol):
    def get(self, sid: str) -> SessionRecord | None: ...

    def put(self, record: SessionRecord, ttl_seconds: int) -> None: ...

    def delete(self, sid: str) -> None: ...

    def put_transaction(self, tx: LoginTransaction, ttl_seconds: int) -> None: ...

    def pop_transaction(self, state: str) -> LoginTransaction | None:
        """Atomically fetch-and-delete: a state can be consumed at most once."""
        ...


class MemorySessionStore:
    """Process-local store; suitable for one replica and for tests."""

    def __init__(self, clock: Any = time.time) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._sessions: dict[str, tuple[float, str]] = {}
        self._transactions: dict[str, tuple[float, str]] = {}

    def get(self, sid: str) -> SessionRecord | None:
        with self._lock:
            entry = self._sessions.get(sid)
            if entry is None:
                return None
            if entry[0] <= self._clock():
                del self._sessions[sid]
                return None
            return SessionRecord.loads(entry[1])

    def put(self, record: SessionRecord, ttl_seconds: int) -> None:
        with self._lock:
            self._sessions[record.sid] = (self._clock() + ttl_seconds, record.dumps())

    def delete(self, sid: str) -> None:
        with self._lock:
            self._sessions.pop(sid, None)

    def put_transaction(self, tx: LoginTransaction, ttl_seconds: int) -> None:
        with self._lock:
            self._transactions[tx.state] = (self._clock() + ttl_seconds, tx.dumps())

    def pop_transaction(self, state: str) -> LoginTransaction | None:
        with self._lock:
            entry = self._transactions.pop(state, None)
        if entry is None or entry[0] <= self._clock():
            return None
        return LoginTransaction.loads(entry[1])


class RedisSessionStore:
    """Redis-backed store (``pip install jxccs-access[redis]``)."""

    def __init__(self, url: str, *, key_prefix: str, client: Any = None) -> None:
        if client is None:
            import redis

            client = redis.Redis.from_url(url, decode_responses=True)
        self._redis = client
        self._prefix = key_prefix

    def _skey(self, sid: str) -> str:
        return f"{self._prefix}:session:{sid}"

    def _tkey(self, state: str) -> str:
        return f"{self._prefix}:login:{state}"

    def get(self, sid: str) -> SessionRecord | None:
        raw = self._redis.get(self._skey(sid))
        return SessionRecord.loads(raw) if raw else None

    def put(self, record: SessionRecord, ttl_seconds: int) -> None:
        self._redis.set(self._skey(record.sid), record.dumps(), ex=ttl_seconds)

    def delete(self, sid: str) -> None:
        self._redis.delete(self._skey(sid))

    def put_transaction(self, tx: LoginTransaction, ttl_seconds: int) -> None:
        self._redis.set(self._tkey(tx.state), tx.dumps(), ex=ttl_seconds)

    def pop_transaction(self, state: str) -> LoginTransaction | None:
        raw = self._redis.getdel(self._tkey(state))
        return LoginTransaction.loads(raw) if raw else None


def build_store(url: str | None, *, key_prefix: str) -> SessionStore:
    if not url:
        return MemorySessionStore()
    if url.startswith(("redis://", "rediss://", "unix://")):
        return RedisSessionStore(url, key_prefix=key_prefix)
    raise ValueError("SESSION_STORE_URL must be a redis:// URL or empty for the memory store")
