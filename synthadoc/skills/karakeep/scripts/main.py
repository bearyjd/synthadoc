# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 jd@beary.us
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

from synthadoc.skills.base import BaseSkill, ExtractedContent, SkillMeta

logger = logging.getLogger(__name__)

_SCHEME = "karakeep://"


# ── Models ────────────────────────────────────────────────────────────────────

class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore")


class LinkContent(_Base):
    type: Literal["link"]
    url: str
    title: str | None = None
    htmlContent: str | None = None
    fullPageArchiveAssetId: str | None = None
    crawlStatus: str | None = None
    author: str | None = None
    publisher: str | None = None


class TextContent(_Base):
    type: Literal["text"]
    text: str
    sourceUrl: str | None = None


class AssetContent(_Base):
    type: Literal["asset"]
    assetType: str
    assetId: str
    fileName: str | None = None
    sourceUrl: str | None = None


class UnknownContent(_Base):
    type: Literal["unknown"]


BookmarkContent = Annotated[
    LinkContent | TextContent | AssetContent | UnknownContent,
    Field(discriminator="type"),
]


class BookmarkTag(_Base):
    id: str
    name: str
    attachedBy: str


class Bookmark(_Base):
    id: str
    createdAt: datetime
    title: str | None = None
    archived: bool
    favourited: bool
    note: str | None = None
    tags: list[BookmarkTag] = []
    content: BookmarkContent


class PaginatedBookmarks(_Base):
    bookmarks: list[Bookmark]
    nextCursor: str | None


class KarakeepList(_Base):
    id: str
    name: str
    icon: str
    public: bool


class KarakeepTag(_Base):
    id: str
    name: str
    numBookmarks: int


class PaginatedTags(_Base):
    tags: list[KarakeepTag]
    nextCursor: str | None


# Rebuild models to resolve forward references when loaded dynamically via importlib
for _m in [LinkContent, TextContent, AssetContent, UnknownContent,
           BookmarkTag, Bookmark, PaginatedBookmarks,
           KarakeepList, KarakeepTag, PaginatedTags]:
    _m.model_rebuild()


# ── HTTP client ───────────────────────────────────────────────────────────────

class KarakeepClient:
    def __init__(self, base_url: str, api_key: str, timeout: int = 30) -> None:
        self._base = base_url.rstrip("/") + "/api/v1"
        self._client = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )

    async def __aenter__(self) -> KarakeepClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self._client.aclose()

    async def _get(self, path: str, **params: object) -> dict:
        params = {k: v for k, v in params.items() if v is not None}
        for attempt in range(2):
            r = await self._client.get(f"{self._base}{path}", params=params)
            if r.status_code == 401:
                raise PermissionError(
                    "[ERR-SKILL-KAR-003] Karakeep API key invalid or expired. "
                    "Regenerate it in Settings → API Keys."
                )
            if r.status_code == 429:
                if attempt == 0:
                    await asyncio.sleep(5)
                    continue
                raise RuntimeError("[ERR-SKILL-KAR-004] Karakeep rate limit hit.")
            r.raise_for_status()
            return r.json()
        raise RuntimeError("unreachable")

    async def list_bookmarks(self, cursor: str | None = None, limit: int = 50) -> PaginatedBookmarks:
        data = await self._get("/bookmarks", cursor=cursor, limit=limit, includeContent=True)
        return PaginatedBookmarks.model_validate(data)

    async def list_bookmarks_in_list(self, list_id: str, cursor: str | None = None, limit: int = 50) -> PaginatedBookmarks:
        data = await self._get(f"/lists/{list_id}/bookmarks", cursor=cursor, limit=limit, includeContent=True)
        return PaginatedBookmarks.model_validate(data)

    async def list_bookmarks_for_tag(self, tag_id: str, cursor: str | None = None, limit: int = 50) -> PaginatedBookmarks:
        data = await self._get(f"/tags/{tag_id}/bookmarks", cursor=cursor, limit=limit, includeContent=True)
        return PaginatedBookmarks.model_validate(data)

    async def get_bookmark(self, bookmark_id: str) -> Bookmark:
        try:
            data = await self._get(f"/bookmarks/{bookmark_id}", includeContent=True)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise KeyError(f"Bookmark {bookmark_id!r} not found") from exc
            raise
        return Bookmark.model_validate(data)

    async def find_tag_id(self, name: str) -> str:
        cursor: str | None = None
        while True:
            data = await self._get("/tags", cursor=cursor, limit=50, nameContains=name)
            page = PaginatedTags.model_validate(data)
            for tag in page.tags:
                if tag.name.lower() == name.lower():
                    return tag.id
            if page.nextCursor is None:
                break
            cursor = page.nextCursor
        raise KeyError(f"[ERR-SKILL-KAR-005] Tag {name!r} not found in Karakeep.")

    async def download_asset(self, asset_id: str, dest: Path) -> None:
        async with self._client.stream("GET", f"{self._base}/assets/{asset_id}") as r:
            if r.status_code == 404:
                raise FileNotFoundError(f"Asset {asset_id!r} not found")
            r.raise_for_status()
            with dest.open("wb") as f:
                async for chunk in r.aiter_bytes(chunk_size=65536):
                    f.write(chunk)


# ── Skill ─────────────────────────────────────────────────────────────────────

class KarakeepSkill(BaseSkill):
    meta = SkillMeta(
        name="karakeep",
        description="Ingest bookmarks from a Karakeep instance",
        extensions=[_SCHEME],
    )

    def __init__(self, provider=None, **kwargs) -> None:
        super().__init__()
        self._provider = provider
        self._delay_ms = int(os.environ.get("KARAKEEP_REQUEST_DELAY_MS", "200"))

    async def extract(self, source: str) -> ExtractedContent:
        url = os.environ.get("KARAKEEP_URL", "").strip()
        api_key = os.environ.get("KARAKEEP_API_KEY", "").strip()
        if not url:
            raise EnvironmentError(
                "[ERR-SKILL-KAR-002] KARAKEEP_URL is not set. "
                "Set it to the base URL of your Karakeep instance."
            )
        if not api_key:
            raise EnvironmentError(
                "[ERR-SKILL-KAR-001] KARAKEEP_API_KEY is not set. "
                "Generate a key in your Karakeep instance under Settings → API Keys."
            )

        prefer_archived = os.environ.get("KARAKEEP_ARCHIVED_CONTENT", "true").lower() != "false"

        # Write staging files inside wiki raw_sources/ so ingest_agent path check passes.
        # SYNTHADOC_WIKI_ROOT is set by http_server.py before any skill runs.
        wiki_root_env = os.environ.get("SYNTHADOC_WIKI_ROOT", "")
        if not wiki_root_env:
            raise EnvironmentError(
                "[ERR-SKILL-KAR-006] SYNTHADOC_WIKI_ROOT is not set. "
                "Run this skill via synthadoc serve, not directly."
            )
        tmp_dir = Path(wiki_root_env) / "raw_sources" / "karakeep"
        tmp_dir.mkdir(parents=True, exist_ok=True)

        child_sources: list[str] = []

        async with KarakeepClient(url, api_key) as client:
            async for bm in self._iter_bookmarks(client, source):
                result = await self._process_bookmark(bm, client, tmp_dir, prefer_archived)
                if result:
                    child_sources.append(result)
                if self._delay_ms > 0:
                    await asyncio.sleep(self._delay_ms / 1000)

        logger.info("karakeep: %d child sources from %s", len(child_sources), source)
        return ExtractedContent(
            text="",
            source_path=source,
            metadata={"child_sources": child_sources},
        )

    async def _iter_bookmarks(self, client: KarakeepClient, source: str):
        if not source.startswith(_SCHEME):
            raise ValueError(f"KarakeepSkill cannot handle: {source!r}")
        path = source[len(_SCHEME):]

        if path == "all":
            cursor: str | None = None
            while True:
                page = await client.list_bookmarks(cursor=cursor)
                for bm in page.bookmarks:
                    yield bm
                if not page.nextCursor:
                    break
                cursor = page.nextCursor

        elif path.startswith("lists/"):
            list_id = path[len("lists/"):]
            if not list_id:
                raise ValueError("karakeep://lists/ requires a list ID")
            cursor = None
            while True:
                page = await client.list_bookmarks_in_list(list_id, cursor=cursor)
                for bm in page.bookmarks:
                    yield bm
                if not page.nextCursor:
                    break
                cursor = page.nextCursor

        elif path.startswith("tags/"):
            tag_name = path[len("tags/"):]
            if not tag_name:
                raise ValueError("karakeep://tags/ requires a tag name")
            tag_id = await client.find_tag_id(tag_name)
            cursor = None
            while True:
                page = await client.list_bookmarks_for_tag(tag_id, cursor=cursor)
                for bm in page.bookmarks:
                    yield bm
                if not page.nextCursor:
                    break
                cursor = page.nextCursor

        elif path.startswith("bookmark/"):
            bm_id = path[len("bookmark/"):]
            if not bm_id:
                raise ValueError("karakeep://bookmark/ requires a bookmark ID")
            yield await client.get_bookmark(bm_id)

        else:
            raise ValueError(
                f"Unknown karakeep:// URI: {source!r}\n"
                "Valid: karakeep://all, karakeep://lists/<id>, "
                "karakeep://tags/<name>, karakeep://bookmark/<id>"
            )

    async def _process_bookmark(
        self,
        bm: Bookmark,
        client: KarakeepClient,
        tmp_dir: Path,
        prefer_archived: bool,
    ) -> str | None:
        content = bm.content

        if isinstance(content, LinkContent):
            if prefer_archived and content.htmlContent:
                try:
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(content.htmlContent, "html.parser")
                    for tag in soup(["script", "style", "nav", "footer"]):
                        tag.decompose()
                    text = soup.get_text(separator="\n", strip=True)
                except Exception:
                    text = content.htmlContent
                if text.strip():
                    dest = tmp_dir / f"{bm.id}.md"
                    title = f"# {bm.title or content.url}\n\n"
                    dest.write_text(title + text, encoding="utf-8")
                    return str(dest)
            if content.url:
                return content.url
            logger.warning("karakeep: link bookmark %s has no URL — skipping", bm.id)
            return None

        if isinstance(content, TextContent):
            if not content.text:
                return None
            dest = tmp_dir / f"{bm.id}.md"
            title = f"# {bm.title}\n\n" if bm.title else ""
            dest.write_text(title + content.text, encoding="utf-8")
            return str(dest)

        if isinstance(content, AssetContent):
            asset_type = content.assetType.lower()
            if asset_type == "pdf":
                ext = ".pdf"
            elif asset_type == "image":
                ext = Path(content.fileName).suffix.lower() if content.fileName else ".jpg"
                if ext not in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".tiff"}:
                    ext = ".jpg"
            else:
                logger.warning("karakeep: unsupported asset type %r for %s — skipping", content.assetType, bm.id)
                return None
            dest = tmp_dir / f"{bm.id}{ext}"
            try:
                await client.download_asset(content.assetId, dest)
            except Exception as exc:
                logger.warning("karakeep: asset download failed for %s — skipping: %s", bm.id, exc)
                return None
            return str(dest)

        logger.warning("karakeep: unknown content type for bookmark %s — skipping", bm.id)
        return None
