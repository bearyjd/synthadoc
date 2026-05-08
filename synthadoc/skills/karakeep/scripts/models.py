# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 jd@beary.us
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore")


class LinkContent(_Base):
    type: Literal["link"]
    url: str
    title: str | None = None
    description: str | None = None
    htmlContent: str | None = None
    fullPageArchiveAssetId: str | None = None
    precrawledArchiveAssetId: str | None = None
    contentAssetId: str | None = None
    screenshotAssetId: str | None = None
    pdfAssetId: str | None = None
    crawlStatus: str | None = None
    author: str | None = None
    publisher: str | None = None


class TextContent(_Base):
    type: Literal["text"]
    text: str
    sourceUrl: str | None = None


class AssetContent(_Base):
    type: Literal["asset"]
    assetType: str  # "image" | "pdf" and others
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


class BookmarkAsset(_Base):
    id: str
    assetType: str
    fileName: str | None = None


class Bookmark(_Base):
    id: str
    createdAt: datetime
    modifiedAt: datetime | None = None
    title: str | None = None
    archived: bool
    favourited: bool
    note: str | None = None
    summary: str | None = None
    tags: list[BookmarkTag] = []
    content: BookmarkContent
    assets: list[BookmarkAsset] = []


class PaginatedBookmarks(_Base):
    bookmarks: list[Bookmark]
    nextCursor: str | None


class KarakeepList(_Base):
    id: str
    name: str
    description: str | None = None
    icon: str
    type: str = "manual"
    public: bool


class KarakeepTag(_Base):
    id: str
    name: str
    numBookmarks: int


class PaginatedTags(_Base):
    tags: list[KarakeepTag]
    nextCursor: str | None
