# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 jd@beary.us
from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from pathlib import Path

from synthadoc.skills.base import BaseSkill, ExtractedContent, SkillMeta

from .client import KarakeepClient
from .models import AssetContent, Bookmark, LinkContent, TextContent

logger = logging.getLogger(__name__)

_SCHEME = "karakeep://"


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
                "Set it to the base URL of your Karakeep instance, "
                "e.g.: export KARAKEEP_URL=https://karakeep.example.com"
            )
        if not api_key:
            raise EnvironmentError(
                "[ERR-SKILL-KAR-001] KARAKEEP_API_KEY is not set. "
                "Generate a key in your Karakeep instance under Settings → API Keys "
                "and set: export KARAKEEP_API_KEY=<your-key>"
            )

        prefer_archived = os.environ.get("KARAKEEP_ARCHIVED_CONTENT", "true").lower() != "false"
        tmp_dir = Path(tempfile.mkdtemp(prefix="karakeep-"))

        child_sources: list[str] = []
        async with KarakeepClient(url, api_key) as client:
            async for bm in self._iter_bookmarks(client, source):
                result = await self._process_bookmark(bm, client, tmp_dir, prefer_archived)
                if result:
                    child_sources.append(result)
                if self._delay_ms > 0:
                    await asyncio.sleep(self._delay_ms / 1000)

        logger.info("karakeep: collected %d child sources from %s", len(child_sources), source)
        return ExtractedContent(
            text="",
            source_path=source,
            metadata={"child_sources": child_sources},
        )

    async def _iter_bookmarks(self, client: KarakeepClient, source: str):
        if not source.startswith(_SCHEME):
            raise ValueError(f"KarakeepSkill cannot handle: {source!r}")
        path = source[len(_SCHEME):]  # e.g. "all", "lists/abc", "tags/research", "bookmark/xyz"

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
                f"Unknown karakeep:// URI pattern: {source!r}\n"
                "Valid patterns: karakeep://all, karakeep://lists/<id>, "
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
                dest = tmp_dir / f"{bm.id}.html"
                dest.write_text(content.htmlContent, encoding="utf-8")
                logger.debug("karakeep: bookmark %s → cached HTML %s", bm.id, dest)
                return str(dest)
            if content.url:
                logger.debug("karakeep: bookmark %s → live URL %s", bm.id, content.url)
                return content.url
            logger.warning("karakeep: link bookmark %s has no URL — skipping", bm.id)
            return None

        if isinstance(content, TextContent):
            if not content.text:
                logger.debug("karakeep: text bookmark %s is empty — skipping", bm.id)
                return None
            dest = tmp_dir / f"{bm.id}.md"
            title = f"# {bm.title}\n\n" if bm.title else ""
            dest.write_text(title + content.text, encoding="utf-8")
            logger.debug("karakeep: bookmark %s → text file %s", bm.id, dest)
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
                logger.warning(
                    "karakeep: unsupported asset type %r for bookmark %s — skipping",
                    content.assetType,
                    bm.id,
                )
                return None
            dest = tmp_dir / f"{bm.id}{ext}"
            try:
                await client.download_asset(content.assetId, dest)
            except (FileNotFoundError, Exception) as exc:
                logger.warning(
                    "karakeep: asset download failed for bookmark %s (%s) — skipping: %s",
                    bm.id,
                    content.assetId,
                    exc,
                )
                return None
            logger.debug("karakeep: bookmark %s → asset file %s", bm.id, dest)
            return str(dest)

        logger.warning("karakeep: unknown content type for bookmark %s — skipping", bm.id)
        return None
