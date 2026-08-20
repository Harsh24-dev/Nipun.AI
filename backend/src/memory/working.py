"""
L0 — Working Memory (in-process, zero latency).
Stores the last N turns of the current conversation per session.
FIFO eviction when max_turns is exceeded.
"""

import json
from collections import OrderedDict, deque
from dataclasses import dataclass
from threading import Lock

import structlog

log = structlog.get_logger("memory.working")

# Shared-store keys + TTL, so session state survives across the app's multiple worker
# processes (a follow-up may hit a different worker than the one that answered before).
#   * turns  → a Redis LIST (one JSON element per turn) so new turns are appended atomically
#              (RPUSH) instead of a read-modify-write of a JSON blob that clobbers a concurrent
#              worker's turns. Bounded with LTRIM to the last _WM_MAX_TURNS elements.
#   * facts  → a Redis HASH (one field per fact) so a worker only writes the fields it learned
#              (HSET), merging with fields another worker set rather than overwriting the blob.
_WM_TURNS_KEY = "nipun:wm:turns:{sid}"
_WM_FACTS_KEY = "nipun:wm:facts:{sid}"
_WM_TTL = 60 * 60 * 24   # 24h — a conversation's hot window
# Per-worker LRU cap on in-process sessions. Evicted sessions simply re-hydrate from the
# shared store on their next turn, so eviction is safe — it only bounds per-worker memory.
_WM_MAX_SESSIONS = 1000


@dataclass
class ConversationTurn:
    role: str       # "user" | "assistant"
    content: str
    language: str
    domain: str | None = None
    tokens: int = 0


def _turn_to_dict(t: "ConversationTurn") -> dict:
    return {"role": t.role, "content": t.content, "language": t.language, "domain": t.domain}


def _turn_from_dict(d: dict) -> "ConversationTurn":
    return ConversationTurn(
        role=d.get("role", ""), content=d.get("content", ""),
        language=d.get("language", "en"), domain=d.get("domain"))


class WorkingMemory:
    """Thread-safe in-process conversation buffer."""

    def __init__(self, max_turns: int = 20, max_sessions: int = _WM_MAX_SESSIONS):
        self._max_turns = max_turns
        self._max_sessions = max_sessions
        # OrderedDict so we can evict least-recently-used sessions and keep per-worker memory
        # bounded (see _evict_locked). Most-recently-touched session sits at the end.
        self._store: OrderedDict[str, deque[ConversationTurn]] = OrderedDict()
        # Per-session "facts" the user has volunteered this conversation (e.g. the answers
        # to a clarify form, or details stated in a message). Kept in-process for the life
        # of the session — NOT persisted to the DB — so the assistant stops re-asking what
        # it was just told, without permanently storing rarely-used personal data.
        self._facts: dict[str, dict] = {}
        # Turns appended since this session's last successful persist — the delta we RPUSH to
        # the shared list, so persist never rewrites (and so never clobbers) the whole history.
        self._pending: dict[str, list[ConversationTurn]] = {}
        self._lock = Lock()

    def _evict_locked(self) -> None:
        """Drop least-recently-used sessions beyond the cap. Caller must hold the lock.
        Evicted sessions re-hydrate from the shared store on their next request, so this only
        bounds memory — it never loses durable state."""
        while len(self._store) > self._max_sessions:
            old_sid, _ = self._store.popitem(last=False)
            self._facts.pop(old_sid, None)
            self._pending.pop(old_sid, None)

    def append(self, session_id: str, turn: ConversationTurn) -> None:
        with self._lock:
            if session_id not in self._store:
                self._store[session_id] = deque(maxlen=self._max_turns)
            self._store[session_id].append(turn)
            # Track the new turn as pending so persist() appends ONLY the delta to Redis.
            self._pending.setdefault(session_id, []).append(turn)
            self._store.move_to_end(session_id)
            self._evict_locked()

    def get(self, session_id: str) -> list[ConversationTurn]:
        with self._lock:
            return list(self._store.get(session_id, []))

    def remember_facts(self, session_id: str, facts: dict | None) -> None:
        """Merge user-volunteered facts (clarify answers) into this session's memory.

        Skips empty values and control keys (``_skipped`` etc.). Later answers overwrite
        earlier ones for the same field so a correction sticks."""
        if not facts:
            return
        clean = {
            k: v for k, v in facts.items()
            if v not in (None, "", [], {}) and not str(k).startswith("_")
        }
        if not clean:
            return
        with self._lock:
            self._facts.setdefault(session_id, {}).update(clean)

    def get_facts(self, session_id: str) -> dict:
        with self._lock:
            return dict(self._facts.get(session_id, {}))

    def recent_user_text(self, session_id: str, max_turns: int = 6) -> str:
        """Concatenated text of the user's recent messages this session — the raw material
        for deciding whether a detail was already mentioned in conversation."""
        with self._lock:
            turns = list(self._store.get(session_id, []))
        user_turns = [t.content for t in turns if t.role == "user" and t.content]
        return "  ".join(user_turns[-max_turns:])

    def clear(self, session_id: str) -> None:
        with self._lock:
            self._store.pop(session_id, None)
            self._facts.pop(session_id, None)
            self._pending.pop(session_id, None)

    # ── Cross-worker sharing (best-effort; falls back to in-process when Redis is down) ──
    async def hydrate(self, session_id: str) -> None:
        """Load this session's turns + facts from the shared store into the in-process cache,
        so a request served by a DIFFERENT worker still sees the prior context. Called once at
        the start of each request. Never raises — degrades to in-process-only on any failure.

        Reads the new storage format (turns = Redis LIST, facts = Redis HASH) and stays
        BACKWARD-TOLERANT of the old single-JSON-blob format written by earlier builds."""
        turn_items: list[dict] | None = None
        facts: dict | None = None
        try:
            from src.db.redis import get_json, get_redis
            r = get_redis()
            tkey = _WM_TURNS_KEY.format(sid=session_id)
            ktype = await r.type(tkey)
            if ktype == "list":
                raw = await r.lrange(tkey, -self._max_turns, -1)
                turn_items = []
                for x in raw:
                    try:
                        turn_items.append(json.loads(x))
                    except (TypeError, ValueError):
                        continue
            elif ktype == "string":
                # Backward-compat: old format stored the whole list as one JSON blob.
                blob = await get_json(tkey)
                if isinstance(blob, dict):
                    turn_items = blob.get("turns")

            fkey = _WM_FACTS_KEY.format(sid=session_id)
            ftype = await r.type(fkey)
            if ftype == "hash":
                raw_f = await r.hgetall(fkey)
                facts = {}
                for k, v in (raw_f or {}).items():
                    try:
                        facts[k] = json.loads(v)
                    except (TypeError, ValueError):
                        facts[k] = v
            elif ftype == "string":
                blob_f = await get_json(fkey)   # old JSON-blob facts
                if isinstance(blob_f, dict):
                    facts = blob_f
        except Exception as exc:   # Redis absent/down → single-worker behaviour, still correct
            log.debug("wm_hydrate_skipped", error=str(exc))
            return
        with self._lock:
            # Redis is the source of truth for turns across workers: ALWAYS refresh the local
            # cache from it (not only when the session is absent locally). The old in-process
            # guard let a worker keep a stale turn list once it had cached the session, so a
            # follow-up load-balanced onto it missed turns another worker added. Rebuilding from
            # Redis here makes the shared store authoritative; when Redis has nothing (or is
            # down) we keep whatever is already local, preserving single-worker behaviour.
            if turn_items:
                dq: deque[ConversationTurn] = deque(maxlen=self._max_turns)
                for t in turn_items[-self._max_turns:]:
                    if isinstance(t, dict):
                        dq.append(_turn_from_dict(t))
                self._store[session_id] = dq
                self._store.move_to_end(session_id)
                self._evict_locked()
            # The loaded turns ARE the persisted state, so nothing is pending against Redis now.
            self._pending[session_id] = []
            if isinstance(facts, dict) and facts:
                self._facts.setdefault(session_id, {}).update(facts)

    async def persist(self, session_id: str) -> None:
        """Mirror this session's turns + facts to the shared store so other workers can read
        them on the next turn. Best-effort; never raises.

        Turns are APPENDED atomically (RPUSH of only the pending delta) so a concurrent turn
        from another worker cannot be clobbered — the old code rewrote the entire JSON blob,
        a non-atomic read-modify-write that was last-writer-wins. Facts are HSET field-by-field
        for the same reason. The whole write is bounded (LTRIM) and TTL-refreshed (EXPIRE)."""
        with self._lock:
            pending = [_turn_to_dict(t) for t in self._pending.get(session_id, [])]
            all_turns = [_turn_to_dict(t) for t in self._store.get(session_id, [])]
            facts = dict(self._facts.get(session_id, {}))
        try:
            from src.db.redis import get_redis
            r = get_redis()
            tkey = _WM_TURNS_KEY.format(sid=session_id)
            if all_turns:
                ktype = await r.type(tkey)
                pipe = r.pipeline()
                if ktype == "list":
                    # Established list → append only the new turns (may be empty on a
                    # facts-only persist, in which case we just refresh the cap + TTL).
                    for t in pending:
                        pipe.rpush(tkey, json.dumps(t))
                else:
                    # First write for this session, or migrating an OLD single-blob value:
                    # drop any stale non-list value and seed the list with the full history.
                    if ktype != "none":
                        pipe.delete(tkey)
                    for t in all_turns:
                        pipe.rpush(tkey, json.dumps(t))
                pipe.ltrim(tkey, -self._max_turns, -1)
                pipe.expire(tkey, _WM_TTL)
                await pipe.execute()
            if facts:
                fkey = _WM_FACTS_KEY.format(sid=session_id)
                ftype = await r.type(fkey)
                fpipe = r.pipeline()
                if ftype == "string":
                    fpipe.delete(fkey)   # migrate old JSON-blob facts to a hash
                fpipe.hset(fkey, mapping={k: json.dumps(v) for k, v in facts.items()})
                fpipe.expire(fkey, _WM_TTL)
                await fpipe.execute()
            with self._lock:
                # Delta is now in Redis — reset pending so the next persist appends only the
                # turns added after this point.
                self._pending[session_id] = []
        except Exception as exc:
            log.debug("wm_persist_skipped", error=str(exc))

    def to_llm_messages(self, session_id: str) -> list[dict[str, str]]:
        """Convert working memory to the message format LiteLLM expects."""
        return [
            {"role": turn.role, "content": turn.content}
            for turn in self.get(session_id)
        ]

    @property
    def active_sessions(self) -> int:
        return len(self._store)


# Module-level singleton
_working_memory: WorkingMemory | None = None


def get_working_memory() -> WorkingMemory:
    global _working_memory
    if _working_memory is None:
        from src.config import settings
        _working_memory = WorkingMemory(max_turns=settings.WORKING_MEMORY_MAX_TURNS)
    return _working_memory
