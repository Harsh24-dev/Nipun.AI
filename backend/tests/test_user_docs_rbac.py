"""RBAC + user-document + rich-metadata + cross-lingual tests (offline).

Verify the isolation invariants (owner_id always filters user-doc retrieval), the role
hierarchy, the metadata payload/citation builders, the classifier fallback, and that
cross-lingual retrieval targets every language collection."""

import pytest

from src.config import settings
from src.db.qdrant import build_filter, user_collection_name
from src.ingestion import metadata as M
from src.ingestion.chunker import Chunk


# ── Metadata schema / payload / citation ───────────────────────────────────────

def test_build_chunk_payload_carries_rich_metadata():
    meta = M.DocumentMetadata(
        title="Pure Mathematics", domain="student", language="en", author="G. H. Hardy",
        subject="calculus", level="advanced", book_id="book:abc", source_url="http://x",
    )
    chunk = Chunk(text="A limit is...", chunk_index=3, section="Chapter 2", page_number=42, token_estimate=5)
    payload = M.build_chunk_payload(meta, chunk)
    assert payload["author"] == "G. H. Hardy"
    assert payload["subject"] == "calculus" and payload["level"] == "advanced"
    assert payload["book_id"] == "book:abc"
    assert payload["section"] == "Chapter 2" and payload["page_number"] == 42
    assert payload["chunk_index"] == 3 and payload["active"] is True
    assert payload["source"] == "Pure Mathematics"     # falls back to title


def test_citation_for_builds_reference():
    payload = {"title": "IPC", "author": "Govt", "source_url": "http://law",
               "section": "Section 302", "page_number": 12, "subject": "criminal", "level": "academic"}
    cite = M.citation_for(payload)
    assert cite["text"] == "IPC" and cite["author"] == "Govt"
    assert "Section 302" in cite["reference"] and "p.12" in cite["reference"]


def test_heuristic_classify_detects_domain_and_level():
    out = M._heuristic_classify("This Section of the Act was upheld by the court under the constitution.")
    assert out["domain"] == "legal"
    out2 = M._heuristic_classify("An introduction to the basics for beginners.")
    assert out2["level"] == "beginner"


async def test_classify_document_empty_text():
    out = await M.classify_document("")
    assert out["domain"] == "general"


# ── Qdrant filter building (RBAC + routing) ────────────────────────────────────

def test_build_filter_whitelists_and_supports_lists():
    f = build_filter({"owner_id": "u1", "subject": ["math", "physics"], "evil_key": "x"})
    # 2 accepted conditions (owner_id + subject); evil_key dropped.
    assert len(f.must) == 2


def test_build_filter_empty_returns_none():
    assert build_filter(None) is None
    assert build_filter({"owner_id": ""}) is None


def test_user_collection_is_single():
    # One shared user_documents collection; language is a payload field, not a suffix.
    assert user_collection_name() == "user_documents"
    assert user_collection_name("hi") == "user_documents"   # language arg ignored


# ── Storage layout: one collection per domain, all languages inside ────────────

def test_collection_is_per_domain_not_per_language():
    from src.language.constants import collection_name

    assert collection_name("legal") == "legal"
    assert collection_name("legal", "hi") == "legal"        # language ignored
    assert collection_name("health", "ta") == "health"


# ── RBAC layer ─────────────────────────────────────────────────────────────────

def test_role_hierarchy():
    from src.api.rbac import _has_role

    assert _has_role("admin", "user") and _has_role("admin", "moderator")
    assert _has_role("moderator", "user")
    assert not _has_role("user", "admin")
    assert not _has_role("user", "moderator")


def test_assert_owner_allows_owner():
    from src.api.rbac import assert_owner

    assert_owner("u1", {"user_id": "u1"})   # no raise


def test_assert_owner_denies_other_user():
    from fastapi import HTTPException

    from src.api.rbac import assert_owner
    with pytest.raises(HTTPException) as exc:
        assert_owner("u2", {"user_id": "u1", "role": "user"}, resource="document")
    assert exc.value.status_code == 404       # 404 not 403 (don't leak existence)


def test_assert_owner_admin_override():
    from src.api.rbac import assert_owner

    assert_owner("someone_else", {"user_id": "admin1", "role": "admin"})   # admin passes


async def test_retrieve_user_document_requires_owner():
    """No owner_id → empty (fail-closed), never a broad search."""
    from src.retrieval.hybrid import retrieve_user_document

    assert await retrieve_user_document("q", owner_id="") == []


async def test_user_doc_retrieval_always_filters_owner(monkeypatch):
    """The owner_id filter must ALWAYS be applied to the vector search (RBAC invariant)."""
    import src.retrieval.hybrid as H

    captured = {}

    async def fake_search(dense, sparse, collection, top_k, query_filter=None):
        captured["filter"] = query_filter
        return []

    class _Emb:
        dense = [[0.1] * 8]
        sparse = [{}]

    async def fake_embed(q):
        return _Emb()

    monkeypatch.setattr(H, "_qdrant_hybrid_search", fake_search)
    monkeypatch.setattr(H, "embed_query_async", fake_embed)
    monkeypatch.setattr(settings, "CROSS_LINGUAL_RETRIEVAL", False)
    await H.retrieve_user_document("q", owner_id="u1", language="en", document_id="d1")
    flt = captured["filter"]
    assert flt is not None
    # owner_id must be one of the filter conditions.
    keys = [c.key for c in flt.must]
    assert "owner_id" in keys and "document_id" in keys
