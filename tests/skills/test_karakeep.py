# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 jd@beary.us
"""Tests for the Karakeep built-in skill (synthadoc/skills/karakeep)."""
import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx


BASE_URL = "https://keep.example.com"
API_BASE = f"{BASE_URL}/api/v1"


# ── Fixtures / helpers ────────────────────────────────────────────────────────

def _bm(bm_id="bm1", title="Test Bookmark", content_type="link", **kwargs):
    bm = {
        "id": bm_id,
        "createdAt": "2026-01-01T00:00:00.000Z",
        "title": title,
        "archived": False,
        "favourited": False,
        "note": None,
        "tags": [],
    }
    if content_type == "link":
        bm["content"] = {
            "type": "link",
            "url": kwargs.get("url", "https://example.com"),
            "title": title,
            "htmlContent": kwargs.get("htmlContent"),
            "crawlStatus": "success",
            "author": None,
            "publisher": None,
        }
    elif content_type == "text":
        bm["content"] = {
            "type": "text",
            "text": kwargs.get("text", "Sample text"),
            "sourceUrl": None,
        }
    elif content_type == "asset":
        bm["content"] = {
            "type": "asset",
            "assetType": kwargs.get("assetType", "pdf"),
            "assetId": kwargs.get("assetId", "asset1"),
            "fileName": kwargs.get("fileName", "doc.pdf"),
            "sourceUrl": None,
        }
    elif content_type == "unknown":
        bm["content"] = {"type": "unknown"}
    return bm


def _page(bookmarks, next_cursor=None):
    return {"bookmarks": bookmarks, "nextCursor": next_cursor}


@pytest.fixture
def skill_env(tmp_wiki):
    """Environment variables required for KarakeepSkill.extract."""
    return {
        "KARAKEEP_URL": BASE_URL,
        "KARAKEEP_API_KEY": "test-api-key",
        "SYNTHADOC_WIKI_ROOT": str(tmp_wiki),
    }


@pytest.fixture
def tmp_dir(tmp_wiki):
    d = tmp_wiki / "raw_sources" / "karakeep"
    d.mkdir(parents=True)
    return d


# ── KarakeepClient._get ────────────────────────────────────────────────────────

@respx.mock
async def test_client_success():
    from synthadoc.skills.karakeep.scripts.main import KarakeepClient
    respx.get(f"{API_BASE}/bookmarks").mock(
        return_value=httpx.Response(200, json=_page([_bm()]))
    )
    async with KarakeepClient(BASE_URL, "test-key") as client:
        page = await client.list_bookmarks()
    assert len(page.bookmarks) == 1
    assert page.bookmarks[0].id == "bm1"


@respx.mock
async def test_client_401_raises_permission_error():
    from synthadoc.skills.karakeep.scripts.main import KarakeepClient
    respx.get(f"{API_BASE}/bookmarks").mock(return_value=httpx.Response(401))
    async with KarakeepClient(BASE_URL, "bad-key") as client:
        with pytest.raises(PermissionError, match="ERR-SKILL-KAR-003"):
            await client.list_bookmarks()


@respx.mock
async def test_client_429_retries_then_raises():
    from synthadoc.skills.karakeep.scripts.main import KarakeepClient
    respx.get(f"{API_BASE}/bookmarks").mock(return_value=httpx.Response(429))
    async with KarakeepClient(BASE_URL, "test-key") as client:
        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(RuntimeError, match="ERR-SKILL-KAR-004"):
                await client.list_bookmarks()


# ── KarakeepClient pagination ──────────────────────────────────────────────────

@respx.mock
async def test_list_bookmarks_in_list():
    from synthadoc.skills.karakeep.scripts.main import KarakeepClient
    respx.get(f"{API_BASE}/lists/list-123/bookmarks").mock(
        return_value=httpx.Response(200, json=_page([_bm("b1"), _bm("b2")]))
    )
    async with KarakeepClient(BASE_URL, "test-key") as client:
        page = await client.list_bookmarks_in_list("list-123")
    assert len(page.bookmarks) == 2


@respx.mock
async def test_get_bookmark_success():
    from synthadoc.skills.karakeep.scripts.main import KarakeepClient
    respx.get(f"{API_BASE}/bookmarks/bm-abc").mock(
        return_value=httpx.Response(200, json=_bm("bm-abc", title="My Bookmark"))
    )
    async with KarakeepClient(BASE_URL, "test-key") as client:
        bm = await client.get_bookmark("bm-abc")
    assert bm.id == "bm-abc"
    assert bm.title == "My Bookmark"


@respx.mock
async def test_get_bookmark_404_raises_key_error():
    from synthadoc.skills.karakeep.scripts.main import KarakeepClient
    respx.get(f"{API_BASE}/bookmarks/missing").mock(return_value=httpx.Response(404))
    async with KarakeepClient(BASE_URL, "test-key") as client:
        with pytest.raises(KeyError, match="missing"):
            await client.get_bookmark("missing")


@respx.mock
async def test_find_tag_id_success():
    from synthadoc.skills.karakeep.scripts.main import KarakeepClient
    respx.get(f"{API_BASE}/tags").mock(return_value=httpx.Response(200, json={
        "tags": [
            {"id": "t1", "name": "python", "numBookmarks": 5},
            {"id": "t2", "name": "ai", "numBookmarks": 3},
        ],
        "nextCursor": None,
    }))
    async with KarakeepClient(BASE_URL, "test-key") as client:
        tag_id = await client.find_tag_id("ai")
    assert tag_id == "t2"


@respx.mock
async def test_find_tag_id_not_found_raises():
    from synthadoc.skills.karakeep.scripts.main import KarakeepClient
    respx.get(f"{API_BASE}/tags").mock(
        return_value=httpx.Response(200, json={"tags": [], "nextCursor": None})
    )
    async with KarakeepClient(BASE_URL, "test-key") as client:
        with pytest.raises(KeyError, match="ERR-SKILL-KAR-005"):
            await client.find_tag_id("nonexistent-tag")


# ── KarakeepSkill._iter_bookmarks ─────────────────────────────────────────────

async def test_iter_bookmarks_all_paginates():
    from synthadoc.skills.karakeep.scripts.main import KarakeepSkill, PaginatedBookmarks

    page1 = PaginatedBookmarks.model_validate(_page([_bm("b1")], next_cursor="cur1"))
    page2 = PaginatedBookmarks.model_validate(_page([_bm("b2")]))

    call_count = 0

    async def fake_list(cursor=None, limit=50):
        nonlocal call_count
        call_count += 1
        return page1 if cursor is None else page2

    mock_client = AsyncMock()
    mock_client.list_bookmarks = fake_list
    skill = KarakeepSkill()

    results = [bm async for bm in skill._iter_bookmarks(mock_client, "karakeep://all")]
    assert len(results) == 2
    assert results[0].id == "b1"
    assert results[1].id == "b2"
    assert call_count == 2


async def test_iter_bookmarks_unknown_uri_raises():
    from synthadoc.skills.karakeep.scripts.main import KarakeepSkill
    skill = KarakeepSkill()
    with pytest.raises(ValueError, match="Unknown karakeep"):
        async for _ in skill._iter_bookmarks(AsyncMock(), "karakeep://bad/path/here"):
            pass


# ── KarakeepSkill._process_bookmark ──────────────────────────────────────────

async def test_process_link_with_html_writes_md(tmp_dir):
    from synthadoc.skills.karakeep.scripts.main import KarakeepSkill, Bookmark
    bm = Bookmark.model_validate(_bm(
        "bm1", "My Article",
        htmlContent="<html><body><p>Hello world</p></body></html>",
    ))
    result = await KarakeepSkill()._process_bookmark(bm, AsyncMock(), tmp_dir, True)
    assert result is not None and result.endswith(".md")
    assert "Hello world" in Path(result).read_text()
    assert "# My Article" in Path(result).read_text()


async def test_process_link_no_html_returns_url(tmp_dir):
    from synthadoc.skills.karakeep.scripts.main import KarakeepSkill, Bookmark
    bm = Bookmark.model_validate(_bm("bm1", url="https://example.com/article"))
    result = await KarakeepSkill()._process_bookmark(bm, AsyncMock(), tmp_dir, True)
    assert result == "https://example.com/article"


async def test_process_text_bookmark_writes_md(tmp_dir):
    from synthadoc.skills.karakeep.scripts.main import KarakeepSkill, Bookmark
    bm = Bookmark.model_validate(
        _bm("bm1", "My Note", content_type="text", text="Note content here")
    )
    result = await KarakeepSkill()._process_bookmark(bm, AsyncMock(), tmp_dir, True)
    assert result is not None
    content = Path(result).read_text()
    assert "Note content here" in content
    assert "# My Note" in content


async def test_process_asset_pdf_downloads(tmp_dir):
    from synthadoc.skills.karakeep.scripts.main import KarakeepSkill, Bookmark
    bm = Bookmark.model_validate(
        _bm("bm1", content_type="asset", assetType="pdf", assetId="a1", fileName="report.pdf")
    )
    mock_client = AsyncMock()

    async def fake_download(asset_id, dest):
        dest.write_bytes(b"%PDF fake content")

    mock_client.download_asset = fake_download
    result = await KarakeepSkill()._process_bookmark(bm, mock_client, tmp_dir, True)
    assert result is not None and result.endswith(".pdf")
    assert Path(result).read_bytes() == b"%PDF fake content"


async def test_process_unknown_content_returns_none(tmp_dir):
    from synthadoc.skills.karakeep.scripts.main import KarakeepSkill, Bookmark
    bm = Bookmark.model_validate(_bm("bm1", content_type="unknown"))
    result = await KarakeepSkill()._process_bookmark(bm, AsyncMock(), tmp_dir, True)
    assert result is None


# ── KarakeepSkill.extract — environment validation ────────────────────────────

async def test_extract_raises_if_url_missing(tmp_wiki):
    from synthadoc.skills.karakeep.scripts.main import KarakeepSkill
    env = {"KARAKEEP_API_KEY": "key", "SYNTHADOC_WIKI_ROOT": str(tmp_wiki)}
    with patch.dict(os.environ, env, clear=True):
        with pytest.raises(EnvironmentError, match="ERR-SKILL-KAR-002"):
            await KarakeepSkill().extract("karakeep://all")


async def test_extract_raises_if_api_key_missing(tmp_wiki):
    from synthadoc.skills.karakeep.scripts.main import KarakeepSkill
    env = {"KARAKEEP_URL": BASE_URL, "SYNTHADOC_WIKI_ROOT": str(tmp_wiki)}
    with patch.dict(os.environ, env, clear=True):
        with pytest.raises(EnvironmentError, match="ERR-SKILL-KAR-001"):
            await KarakeepSkill().extract("karakeep://all")


async def test_extract_raises_if_wiki_root_missing():
    from synthadoc.skills.karakeep.scripts.main import KarakeepSkill
    env = {"KARAKEEP_URL": BASE_URL, "KARAKEEP_API_KEY": "key"}
    with patch.dict(os.environ, env, clear=True):
        with pytest.raises(EnvironmentError, match="ERR-SKILL-KAR-006"):
            await KarakeepSkill().extract("karakeep://all")


# ── Optional integration test ─────────────────────────────────────────────────

@pytest.mark.integration
async def test_integration_list_all_bookmarks():
    """Hits a real Karakeep instance. Skipped unless KARAKEEP_URL and
    KARAKEEP_API_KEY are set in the environment."""
    url = os.environ.get("KARAKEEP_URL", "")
    key = os.environ.get("KARAKEEP_API_KEY", "")
    if not url or not key:
        pytest.skip("KARAKEEP_URL / KARAKEEP_API_KEY not set")
    from synthadoc.skills.karakeep.scripts.main import KarakeepClient
    async with KarakeepClient(url, key) as client:
        page = await client.list_bookmarks(limit=5)
    assert isinstance(page.bookmarks, list)
