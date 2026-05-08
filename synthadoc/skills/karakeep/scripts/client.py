# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 jd@beary.us
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import AsyncIterator

import httpx

from .models import Bookmark, KarakeepList, KarakeepTag, PaginatedBookmarks, PaginatedTags


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
                raise RuntimeError(
                    "[ERR-SKILL-KAR-004] Karakeep rate limit hit. "
                    "Increase KARAKEEP_REQUEST_DELAY_MS and retry."
                )
            r.raise_for_status()
            return r.json()
        raise RuntimeError("unreachable")

    async def list_bookmarks(
        self,
        cursor: str | None = None,
        limit: int = 50,
        **filters: object,
    ) -> PaginatedBookmarks:
        data = await self._get(
            "/bookmarks",
            cursor=cursor,
            limit=limit,
            includeContent=True,
            **filters,
        )
        return PaginatedBookmarks.model_validate(data)

    async def list_bookmarks_in_list(
        self,
        list_id: str,
        cursor: str | None = None,
        limit: int = 50,
    ) -> PaginatedBookmarks:
        data = await self._get(
            f"/lists/{list_id}/bookmarks",
            cursor=cursor,
            limit=limit,
            includeContent=True,
        )
        return PaginatedBookmarks.model_validate(data)

    async def list_bookmarks_for_tag(
        self,
        tag_id: str,
        cursor: str | None = None,
        limit: int = 50,
    ) -> PaginatedBookmarks:
        data = await self._get(
            f"/tags/{tag_id}/bookmarks",
            cursor=cursor,
            limit=limit,
            includeContent=True,
        )
        return PaginatedBookmarks.model_validate(data)

    async def get_bookmark(self, bookmark_id: str) -> Bookmark:
        try:
            data = await self._get(f"/bookmarks/{bookmark_id}", includeContent=True)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise KeyError(f"Bookmark {bookmark_id!r} not found") from exc
            raise
        return Bookmark.model_validate(data)

    async def list_lists(self) -> list[KarakeepList]:
        data = await self._get("/lists")
        return [KarakeepList.model_validate(item) for item in data.get("lists", [])]

    async def list_tags(
        self,
        cursor: str | None = None,
        limit: int = 50,
        name_contains: str | None = None,
    ) -> PaginatedTags:
        data = await self._get(
            "/tags",
            cursor=cursor,
            limit=limit,
            nameContains=name_contains,
        )
        return PaginatedTags.model_validate(data)

    async def find_tag_id(self, name: str) -> str:
        cursor: str | None = None
        while True:
            page = await self.list_tags(cursor=cursor, name_contains=name)
            for tag in page.tags:
                if tag.name.lower() == name.lower():
                    return tag.id
            if page.nextCursor is None:
                break
            cursor = page.nextCursor
        raise KeyError(
            f"[ERR-SKILL-KAR-005] Tag {name!r} not found in Karakeep. "
            "Check the tag name and try again."
        )

    async def download_asset(self, asset_id: str, dest: Path) -> None:
        async with self._client.stream("GET", f"{self._base}/assets/{asset_id}") as r:
            if r.status_code == 404:
                raise FileNotFoundError(f"Asset {asset_id!r} not found")
            r.raise_for_status()
            with dest.open("wb") as f:
                async for chunk in r.aiter_bytes(chunk_size=65536):
                    f.write(chunk)

    async def all_bookmarks(
        self, fetch_fn: object = None, **filters: object
    ) -> AsyncIterator[Bookmark]:
        if fetch_fn is None:
            fetch_fn = self.list_bookmarks
        cursor: str | None = None
        while True:
            page: PaginatedBookmarks = await fetch_fn(cursor=cursor, **filters)
            for bm in page.bookmarks:
                yield bm
            if page.nextCursor is None:
                break
            cursor = page.nextCursor
