"""Book-ingestion tests (offline) — discovery parsing + download/ingest routing.

Network + Qdrant are monkeypatched; these verify that discovery parses provider
responses, de-dups, and that ingest_book routes txt-URLs vs PDFs correctly through
the shared ingestion pipeline."""

import pytest

from src.config import settings
from src.ingestion import books


@pytest.fixture(autouse=True)
def _enable(monkeypatch):
    monkeypatch.setattr(settings, "BOOKS_INGEST_ENABLED", True)
    monkeypatch.setattr(settings, "BOOKS_INGEST_MAX", 3)


async def test_discover_parses_gutenberg(monkeypatch):
    async def fake_get_json(url, params=None, headers=None, timeout=None):
        if "gutendex" in url:
            return {"results": [
                {"title": "Pure Mathematics", "authors": [{"name": "Hardy"}],
                 "formats": {"text/plain; charset=utf-8": "https://g.org/1.txt"}},
                {"title": "Amusements", "authors": [],
                 "formats": {"application/pdf": "https://g.org/2.pdf"}},
            ]}
        return None  # archive returns nothing

    monkeypatch.setattr(books, "get_json", fake_get_json)
    found = await books.discover_book_sources("mathematics", max_books=3)
    assert len(found) == 2
    assert found[0]["format"] == "txt" and found[0]["source"] == "Project Gutenberg"
    assert found[1]["format"] == "pdf"


async def test_discover_dedups_by_title(monkeypatch):
    async def fake_get_json(url, params=None, headers=None, timeout=None):
        if "gutendex" in url:
            return {"results": [
                {"title": "Same Book", "authors": [], "formats": {"text/plain": "https://g.org/a.txt"}},
                {"title": "same book", "authors": [], "formats": {"text/plain": "https://g.org/b.txt"}},
            ]}
        return None

    monkeypatch.setattr(books, "get_json", fake_get_json)
    found = await books.discover_book_sources("x", max_books=5)
    assert len(found) == 1  # case-insensitive title de-dup


async def test_ingest_book_txt_url_uses_pipeline(monkeypatch):
    captured = {}

    async def fake_ingest_spec(spec, skip_dedup=False):
        captured["source"] = spec.source
        captured["domain"] = spec.domain
        captured["kind"] = spec.metadata.get("kind")
        return {"status": "success", "chunks": 12, "title": spec.title}

    monkeypatch.setattr(books, "ingest_spec", fake_ingest_spec)
    result = await books.ingest_book("https://g.org/1.txt", "Book A", domain="student", fmt="txt")
    assert result["status"] == "success" and result["chunks"] == 12
    assert captured["source"] == "https://g.org/1.txt"   # txt URL passed straight through
    assert captured["kind"] == "book" and captured["domain"] == "student"


async def test_ingest_book_pdf_downloads_first(monkeypatch):
    captured = {}

    async def fake_download(url, suffix):
        return "/tmp/fake_book.pdf"

    async def fake_ingest_spec(spec, skip_dedup=False):
        captured["source"] = spec.source
        captured["source_url"] = spec.source_url
        return {"status": "success", "chunks": 5, "title": spec.title}

    monkeypatch.setattr(books, "_download_to_temp", fake_download)
    monkeypatch.setattr(books, "ingest_spec", fake_ingest_spec)
    monkeypatch.setattr(books.os.path, "exists", lambda p: False)  # skip cleanup unlink
    result = await books.ingest_book("https://g.org/2.pdf", "Book B", fmt="pdf")
    assert result["chunks"] == 5
    assert captured["source"] == "/tmp/fake_book.pdf"        # local temp path for parse_pdf
    assert captured["source_url"] == "https://g.org/2.pdf"   # citation keeps the real URL


async def test_ingest_topic_summary(monkeypatch):
    async def fake_discover(topic, max_books=None):
        return [{"title": "B1", "url": "https://g.org/1.txt", "format": "txt",
                 "source": "Project Gutenberg", "license": "public_domain"}]

    async def fake_ingest_book(url, title, domain=None, language="en", fmt="txt", source="", license="", author=""):
        return {"status": "success", "chunks": 7, "title": title}

    monkeypatch.setattr(books, "discover_book_sources", fake_discover)
    monkeypatch.setattr(books, "ingest_book", fake_ingest_book)
    summary = await books.ingest_books_for_topic("become a doctor", domain="student")
    assert summary["ingested"] == 1 and summary["chunks"] == 7 and summary["discovered"] == 1


async def test_ingest_disabled(monkeypatch):
    monkeypatch.setattr(settings, "BOOKS_INGEST_ENABLED", False)
    summary = await books.ingest_books_for_topic("anything")
    assert summary["status"] == "disabled"


def test_is_open_license():
    assert books._is_open("public_domain")
    assert books._is_open("open_access")
    assert not books._is_open("unknown")
    assert not books._is_open("")


def test_annas_archive_pointers_opt_in(monkeypatch):
    monkeypatch.setattr(settings, "ANNAS_ARCHIVE_ENABLED", False)
    monkeypatch.setattr(settings, "LIBGEN_METADATA_ENABLED", False)
    assert books._annas_archive_pointers("q") == []  # off by default

    monkeypatch.setattr(settings, "ANNAS_ARCHIVE_ENABLED", True)
    pointers = books._annas_archive_pointers("python")
    assert pointers and pointers[0]["downloadable"] is False
    assert pointers[0]["source"] == "Anna's Archive"


async def test_copyrighted_sources_not_downloaded(monkeypatch):
    """Anna's Archive / non-open items become find-it links, never embedded."""
    async def fake_discover(topic, max_books=None):
        return [
            {"title": "Open Book", "url": "https://g.org/1.txt", "format": "txt",
             "source": "Project Gutenberg", "license": "public_domain", "downloadable": True},
            {"title": "Find X on Anna's Archive", "url": "https://annas-archive.org/search?q=x",
             "format": "link", "source": "Anna's Archive", "license": "unknown", "downloadable": False},
        ]

    ingested_titles = []

    async def fake_ingest_book(url, title, domain=None, language="en", fmt="txt", source="", license="", author=""):
        ingested_titles.append(title)
        return {"status": "success", "chunks": 3, "title": title}

    monkeypatch.setattr(books, "discover_book_sources", fake_discover)
    monkeypatch.setattr(books, "ingest_book", fake_ingest_book)
    summary = await books.ingest_books_for_topic("x", domain="student")
    assert ingested_titles == ["Open Book"]              # only the open book downloaded
    assert summary["ingested"] == 1
    assert len(summary["find_it_links"]) == 1            # Anna's Archive → link only
    assert summary["find_it_links"][0]["source"] == "Anna's Archive"
