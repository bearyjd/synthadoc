# PRP: Karakeep Community Skill for Synthadoc

**Status:** Draft
**Author:** JD (via PRP-plan command)
**Target:** standalone pip package; upstream PR to axoviq-ai/synthadoc once skill API stabilises
**Package name:** `karakeep-synthadoc-skill`
**Skill URI scheme:** `karakeep://`

---

## 1. Problem statement

Karakeep users accumulate hundreds or thousands of bookmarks — links, saved text, PDFs, images — but this knowledge is locked in a read-later silo. Synthadoc's `ingest` command can process individual URLs one at a time, but there is no way to pull an entire Karakeep vault (or a filtered subset: a list, a tag, a single bookmark) into a wiki in one operation. This skill bridges that gap: `synthadoc ingest karakeep://all -w main` pages through every bookmark in the vault, maps each to the appropriate existing Synthadoc skill (URL, markdown, PDF, image), and ingests the results as wiki pages — turning a passive read-later archive into a searchable, queryable knowledge base.

---

## 2. Skill contract (from codebase research)

### Base class

```python
from synthadoc.skills.base import BaseSkill, ExtractedContent, SkillMeta, Triggers
```

`BaseSkill` is defined in `synthadoc/skills/base.py`. It is an abstract class with one abstract method.

### Required methods

```python
@abstractmethod
async def extract(self, source: str) -> ExtractedContent: ...
```

`ExtractedContent` is a dataclass:
```python
@dataclass
class ExtractedContent:
    text: str
    source_path: str
    metadata: dict = field(default_factory=dict)
```

The skill may also accept `provider=None` in `__init__` if it needs a vision-capable LLM (passed by the orchestrator).

**Convention for child sources:** when a skill generates multiple downstream sources to ingest (as `web_search` does), return them via `metadata["child_sources"]: list[str]`. The orchestrator picks these up and dispatches each through skill detection. This is the correct pattern for the Karakeep skill.

### Source URI patterns this skill will handle

| URI | Meaning |
|-----|---------|
| `karakeep://all` | All bookmarks in the vault, paginated |
| `karakeep://lists/<listId>` | All bookmarks in a specific Karakeep list |
| `karakeep://tags/<tagName>` | All bookmarks carrying a specific tag name |
| `karakeep://bookmark/<bookmarkId>` | A single bookmark by ID |

`can_handle` is implicit — the trigger prefix `"karakeep://"` in `SKILL.md` means the skill is selected for any source that starts with `karakeep://`.

### SKILL.md for the community package

```yaml
---
name: karakeep
version: "1.0"
description: Ingest bookmarks from a Karakeep instance into Synthadoc
entry:
  script: scripts/main.py
  class: KarakeepSkill
triggers:
  extensions:
    - "karakeep://"
  intents:
    - "karakeep"
    - "import bookmarks"
    - "karakeep vault"
requires:
  - httpx
  - pydantic
author: jd@beary.us
license: Apache-2.0
---
```

### Registration: pyproject.toml entry point

`_entry_point_skill_dirs()` in `skill_agent.py` (lines 43–53) does `Path(ep.value)` — it treats the entry point value as a **raw filesystem path string**. `ep.load()` is never called. `module:attr` form (e.g. `"karakeep_synthadoc_skill:SKILL_DIR"`) does NOT work: `Path("karakeep_synthadoc_skill:SKILL_DIR")` is a relative path that fails `is_dir()`.

**Required one-line fix to `skill_agent.py`** — include in the upstream PR:

```python
# skill_agent.py: _entry_point_skill_dirs() — replace the inner try block
try:
    try:
        loaded = ep.load()       # module:attr form → resolves SKILL_DIR attribute
        d = Path(str(loaded))
    except Exception:
        d = Path(ep.value)       # fallback: raw absolute path string
    if d.is_dir() and (d / "SKILL.md").exists():
        dirs.append(d)
except Exception:
    logger.warning("Bad entry point skill %s", ep.name, exc_info=True)
```

With this fix, the pip package's `pyproject.toml`:

```toml
[project.entry-points."synthadoc.skills"]
karakeep = "karakeep_synthadoc_skill:SKILL_DIR"
```

```python
# karakeep_synthadoc_skill/__init__.py
from pathlib import Path
SKILL_DIR = str(Path(__file__).parent / "skill")
```

**Until the fix merges**, document manual installation:
```bash
# After pip install karakeep-synthadoc-skill:
python -c "import karakeep_synthadoc_skill; print(karakeep_synthadoc_skill.SKILL_DIR)"
# Copy that path to ~/.synthadoc/skills/karakeep or wiki_root/skills/karakeep
```

---

## 3. Karakeep API surface used

### Authentication

```
Authorization: Bearer <api-key>
```

API keys are generated in the Karakeep web UI under **Settings → API Keys**.

### Endpoints

| Method | Path | Purpose | Key query params |
|--------|------|---------|-----------------|
| `GET` | `/api/v1/bookmarks` | All bookmarks (paginated) | `cursor`, `limit`, `archived`, `favourited`, `sortOrder`, `includeContent` |
| `GET` | `/api/v1/bookmarks/{id}` | Single bookmark | `includeContent` |
| `GET` | `/api/v1/lists/{listId}/bookmarks` | Bookmarks in a list (paginated) | `cursor`, `limit`, `sortOrder`, `includeContent` |
| `GET` | `/api/v1/tags/{tagId}/bookmarks` | Bookmarks with a tag (paginated) | `cursor`, `limit`, `sortOrder`, `includeContent` |
| `GET` | `/api/v1/lists` | All lists (non-paginated) | — |
| `GET` | `/api/v1/tags` | All tags (paginated) | `cursor`, `limit`, `nameContains`, `sort`, `attachedBy` |
| `GET` | `/api/v1/assets/{assetId}` | Download asset binary | — |

**Note on `includeContent`:** must be `true` to get `htmlContent`, `text`, `assetId`, etc. Default is `false`. Always pass `includeContent=true` when fetching bookmarks for ingestion.

**Note on filtering:** `GET /bookmarks` has NO `tagId` or `listId` filter. Use the dedicated `/lists/{id}/bookmarks` and `/tags/{id}/bookmarks` endpoints. For `karakeep://tags/<name>`, resolve name → ID via `GET /tags?nameContains=<name>` first.

### Bookmark type mapping

| Karakeep type | Key fields used | Delegate to Synthadoc skill | Strategy |
|---|---|---|---|
| `link` | `content.url`, `content.htmlContent`, `content.fullPageArchiveAssetId`, `content.precrawledArchiveAssetId` | `UrlSkill` | Add `content.url` to `child_sources`; URL skill fetches live page. If `KARAKEEP_ARCHIVED_CONTENT=true`, prefer `content.htmlContent` written to temp `.html` file. |
| `text` | `content.text`, `content.sourceUrl` | `MarkdownSkill` | Write `content.text` to a temp `.md` file; add temp path to `child_sources`. |
| `asset` (pdf) | `content.assetId`, `content.fileName` | `PdfSkill` | Download asset via `/api/v1/assets/{assetId}`, write to temp `.pdf`; add path to `child_sources`. |
| `asset` (image) | `content.assetId`, `content.fileName` | `ImageSkill` | Download asset via `/api/v1/assets/{assetId}`, write to temp `.png`/`.jpg`; add path to `child_sources`. Requires vision-capable provider. |
| `unknown` | — | — | Skip with a log warning. |

**Asset download endpoint:** `GET /api/v1/assets/{assetId}` — not in the docs pages fetched, but standard REST convention for Karakeep; verify in Open Questions.

### Pagination strategy (pseudocode)

```
cursor = None
while True:
    params = {limit: 50, includeContent: true, cursor: cursor}
    response = GET /api/v1/bookmarks, params=params
    for bookmark in response.bookmarks:
        process(bookmark)
    if response.nextCursor is None:
        break
    cursor = response.nextCursor
```

Same pattern for tags pagination. Lists are non-paginated (single response).

### Rate limiting

The Karakeep API enforces per-IP request limits when enabled. Exceeding returns `429 Too Many Requests` with a message indicating seconds to wait. No `Retry-After` header documented. Default: 200ms delay between requests (`KARAKEEP_REQUEST_DELAY_MS`). On 429, back off with 5s sleep and retry once before raising.

---

## 4. Configuration

| Env variable | Required | Default | Description |
|---|---|---|---|
| `KARAKEEP_URL` | Yes | — | Base URL of your Karakeep instance, e.g. `https://karakeep.example.com` |
| `KARAKEEP_API_KEY` | Yes | — | Bearer token from Settings → API Keys |
| `KARAKEEP_ARCHIVED_CONTENT` | No | `true` | When `true`, prefer `content.htmlContent` over fetching the live URL for `link` bookmarks |
| `KARAKEEP_REQUEST_DELAY_MS` | No | `200` | Milliseconds to sleep between Karakeep API requests |

**How they are read:** skills read `os.environ` directly. Pattern from `web_search` skill:

```python
api_key = os.environ.get("KARAKEEP_API_KEY", "").strip()
if not api_key:
    raise EnvironmentError(
        "[ERR-SKILL-KAR-001] KARAKEEP_API_KEY is not set. "
        "Generate a key in your Karakeep instance under Settings → API Keys "
        "and set: export KARAKEEP_API_KEY=<your-key>"
    )
```

No config injection is used — skills do not receive a config object. All runtime configuration is via environment variables.

---

## 5. Implementation plan

### File layout

```
karakeep-synthadoc-skill/
  karakeep_synthadoc_skill/
    __init__.py          # exposes skill_dir path string for entry point resolution
    skill/
      SKILL.md
      scripts/
        main.py          # KarakeepSkill class
        client.py        # KarakeepClient (async httpx)
        models.py        # Pydantic models for API responses
  tests/
    conftest.py          # fixtures: mock Karakeep API responses with respx
    test_skill.py        # KarakeepSkill extraction tests
    test_client.py       # KarakeepClient unit tests
  pyproject.toml
  README.md
```

### `scripts/main.py`: KarakeepSkill

**`extract(self, source: str) -> ExtractedContent`**

1. Read and validate `KARAKEEP_URL` and `KARAKEEP_API_KEY` from env. Raise `EnvironmentError` with error code `[ERR-SKILL-KAR-001]`/`[ERR-SKILL-KAR-002]` if missing.
2. Parse the source URI:
   - `karakeep://all` → fetch all bookmarks (no filter)
   - `karakeep://lists/<id>` → fetch bookmarks from list `<id>`
   - `karakeep://tags/<name>` → resolve tag name to tag ID via `GET /tags?nameContains=<name>`, then filter bookmarks by that tag
   - `karakeep://bookmark/<id>` → fetch single bookmark via `GET /bookmarks/<id>?includeContent=true`
   - Unrecognised pattern → raise `ValueError("Unknown karakeep:// URI pattern: ...")`
3. Paginate bookmarks using `KarakeepClient.list_bookmarks()`. Sleep `KARAKEEP_REQUEST_DELAY_MS` ms between pages.
4. For each bookmark, call `_process_bookmark(bookmark) -> str | None`:
   - Returns a source string (URL or temp file path) to add to `child_sources`, or `None` to skip.
5. Return `ExtractedContent(text="", source_path=source, metadata={"child_sources": [...]})`.

**`_process_bookmark(self, bookmark: Bookmark, tmp_dir: Path) -> str | None`**

- `content.type == "link"`:
  - If `KARAKEEP_ARCHIVED_CONTENT=true` AND `content.htmlContent` is non-empty: write to `tmp_dir/<id>.html`, return path.
  - Else: return `content.url`.
- `content.type == "text"`:
  - Write `content.text` to `tmp_dir/<id>.md`, return path.
- `content.type == "asset"` AND `content.assetType == "pdf"`:
  - Download via `KarakeepClient.download_asset(content.assetId)`.
  - Write bytes to `tmp_dir/<id>.pdf`, return path.
- `content.type == "asset"` AND `content.assetType == "image"`:
  - Download via `KarakeepClient.download_asset(content.assetId)`.
  - Extension from `content.fileName` or default `.jpg`.
  - Write bytes to `tmp_dir/<id><ext>`, return path.
- `content.type == "unknown"` or unhandled: log warning, return `None`.

**Note on temp files:** use a single `tmp_dir = Path(tempfile.mkdtemp(prefix="karakeep-"))` per `extract()` call. The caller (orchestrator) will process `child_sources` and the temp dir can be cleaned up after.

**`__init__(self, provider=None, **kwargs)`**
- Call `super().__init__()`
- Store `self._provider = provider` (needed if image skill is invoked indirectly via child_sources dispatch)
- Read `KARAKEEP_REQUEST_DELAY_MS` here and store as `self._delay_ms`

### `scripts/client.py`: KarakeepClient

**Constructor:** `__init__(self, base_url: str, api_key: str, timeout: int = 30)`
- Stores base URL (strips trailing `/`), API key, timeout.
- Creates `httpx.AsyncClient` with `Authorization: Bearer <api_key>` header and `timeout=timeout`.

**`list_bookmarks(self, cursor=None, limit=50, **filters) -> PaginatedBookmarks`**
- `GET /api/v1/bookmarks` with `includeContent=true`, `limit`, `cursor` (if set), plus any extra `filters` (e.g. `archived=False`).
- On 401: raise `PermissionError("[ERR-SKILL-KAR-003] Karakeep API key invalid or expired")`
- On 429: sleep 5s, retry once. If still 429, raise `RuntimeError("Karakeep rate limit hit")`
- On other non-2xx: raise `httpx.HTTPStatusError`

**`get_bookmark(self, bookmark_id: str) -> Bookmark`**
- `GET /api/v1/bookmarks/{bookmark_id}?includeContent=true`
- On 404: raise `KeyError(f"Bookmark {bookmark_id} not found")`

**`list_lists(self) -> list[KarakeepList]`**
- `GET /api/v1/lists`

**`list_tags(self, cursor=None, limit=50, name_contains=None) -> PaginatedTags`**
- `GET /api/v1/tags` with optional filters

**`download_asset(self, asset_id: str) -> bytes`**
- `GET /api/v1/assets/{asset_id}`
- On 404: raise `FileNotFoundError(f"Asset {asset_id} not found")`
- Returns raw bytes; caller writes to disk.

**`aclose(self) -> None`**
- Closes the httpx.AsyncClient.

Use as async context manager: `async with KarakeepClient(...) as client: ...`

### `scripts/models.py`

All models use Pydantic v2 (`model_config = ConfigDict(extra="ignore")` to tolerate API additions).

```python
class LinkContent(BaseModel):
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

class TextContent(BaseModel):
    type: Literal["text"]
    text: str
    sourceUrl: str | None = None

class AssetContent(BaseModel):
    type: Literal["asset"]
    assetType: Literal["image", "pdf"]
    assetId: str
    fileName: str | None = None
    sourceUrl: str | None = None

class UnknownContent(BaseModel):
    type: Literal["unknown"]

BookmarkContent = Annotated[
    LinkContent | TextContent | AssetContent | UnknownContent,
    Field(discriminator="type")
]

class Tag(BaseModel):
    id: str
    name: str
    attachedBy: str

class BookmarkAsset(BaseModel):
    id: str
    assetType: str
    fileName: str | None = None

class Bookmark(BaseModel):
    id: str
    createdAt: datetime
    modifiedAt: datetime | None = None
    title: str | None = None
    archived: bool
    favourited: bool
    note: str | None = None
    summary: str | None = None
    tags: list[Tag] = []
    content: BookmarkContent
    assets: list[BookmarkAsset] = []

class PaginatedBookmarks(BaseModel):
    bookmarks: list[Bookmark]
    nextCursor: str | None

class KarakeepList(BaseModel):
    id: str
    name: str
    description: str | None = None
    icon: str
    type: str = "manual"
    public: bool

class KarakeepTag(BaseModel):
    id: str
    name: str
    numBookmarks: int

class PaginatedTags(BaseModel):
    tags: list[KarakeepTag]
    nextCursor: str | None
```

---

## 6. Edge cases and error handling

| Case | Handling |
|------|---------|
| `link` bookmark with no archived content AND dead URL | Add live URL to `child_sources`; URL skill will handle the HTTP error gracefully (returns empty `ExtractedContent` on SSL error, raises on 403/429) |
| Asset download 404 | Log warning `"Asset <id> not found for bookmark <bookmark_id> — skipping"`, return `None` from `_process_bookmark` |
| Asset download timeout | Log warning, return `None`; do not abort the whole batch |
| Karakeep instance unreachable | `httpx.ConnectError` propagates from client; `extract()` raises with clear message including the configured URL |
| `KARAKEEP_API_KEY` missing | Raise `EnvironmentError("[ERR-SKILL-KAR-001] ...")` before any HTTP call |
| `KARAKEEP_URL` missing | Raise `EnvironmentError("[ERR-SKILL-KAR-002] ...")` before any HTTP call |
| 401 from API | Raise `PermissionError("[ERR-SKILL-KAR-003] ...")` |
| 429 rate limit | Sleep 5s, retry once; if still 429 raise `RuntimeError` |
| Very large vault (10k+ bookmarks) | Cursor-based pagination handles this; temp files prevent memory blowup. Each page is processed and files written before next page is fetched. |
| Duplicate ingestion | Synthadoc's ingest deduplication (by source URL/path) handles this upstream. The skill does not need to track seen IDs. |
| `asset` type with `assetType` not `image` or `pdf` | Log warning `"Unsupported asset type <type> for bookmark <id> — skipping"`, return `None` |
| Image bookmark with no vision provider | `child_sources` will include the image path; if `ImageSkill` is dispatched without a provider it raises `ValueError`. Document that vision-capable LLM is required for image bookmarks. |
| Bookmarks with no text content (image-only, no OCR) | Image skill attempts OCR via LLM vision. If provider doesn't support vision, returns empty `ExtractedContent`. |
| `text` bookmark with empty `content.text` | Return `None` from `_process_bookmark`, skip. |
| Tag not found for `karakeep://tags/<name>` | Raise `KeyError(f"Tag '{name}' not found in Karakeep")` |

---

## 7. Test plan

### Unit tests — `tests/test_skill.py` (mock Karakeep API via `respx`)

| Test case | What it verifies |
|-----------|-----------------|
| `test_extract_all_returns_child_sources` | `karakeep://all` pages through 2 pages; returns correct `child_sources` count |
| `test_link_bookmark_uses_url_as_child_source` | `link` type → `content.url` in `child_sources` |
| `test_link_bookmark_with_html_content_writes_temp_file` | `link` + `htmlContent` + `KARAKEEP_ARCHIVED_CONTENT=true` → `.html` temp file path in `child_sources` |
| `test_text_bookmark_writes_temp_md_file` | `text` type → `.md` temp file with `content.text` written |
| `test_asset_pdf_downloads_and_writes_temp_file` | `asset/pdf` → asset downloaded, `.pdf` temp file in `child_sources` |
| `test_asset_image_downloads_and_writes_temp_file` | `asset/image` → `.jpg` temp file in `child_sources` |
| `test_unknown_bookmark_type_skipped` | `unknown` type → not in `child_sources`, no error |
| `test_pagination_follows_next_cursor` | Two pages with `nextCursor`; both pages processed; stops at `nextCursor=null` |
| `test_single_bookmark_uri` | `karakeep://bookmark/<id>` → exactly one child source |
| `test_list_uri_filters_by_list_id` | `karakeep://lists/<id>` → correct API endpoint called |
| `test_tag_uri_resolves_tag_name` | `karakeep://tags/research` → resolves to tag ID, filters bookmarks |
| `test_missing_api_key_raises_env_error` | No `KARAKEEP_API_KEY` → `EnvironmentError` with code `ERR-SKILL-KAR-001` |
| `test_missing_url_raises_env_error` | No `KARAKEEP_URL` → `EnvironmentError` with code `ERR-SKILL-KAR-002` |
| `test_401_raises_permission_error` | API returns 401 → `PermissionError` |
| `test_429_retries_then_raises` | API returns 429 twice → `RuntimeError` |
| `test_asset_download_404_skips_bookmark` | Asset 404 → bookmark skipped, no error raised |
| `test_unknown_uri_pattern_raises` | `karakeep://invalid` → `ValueError` |
| `test_empty_text_bookmark_skipped` | `text` type with `text=""` → not in `child_sources` |

### Unit tests — `tests/test_client.py`

| Test case | What it verifies |
|-----------|-----------------|
| `test_list_bookmarks_passes_cursor` | `cursor` param forwarded correctly |
| `test_download_asset_returns_bytes` | Returns raw bytes from response |
| `test_client_sets_auth_header` | `Authorization: Bearer <key>` in all requests |

### Integration test — `tests/test_integration.py`

```python
@pytest.mark.skipif(
    not (os.environ.get("KARAKEEP_URL") and os.environ.get("KARAKEEP_API_KEY")),
    reason="KARAKEEP_URL and KARAKEEP_API_KEY not set"
)
@pytest.mark.asyncio
async def test_live_single_bookmark():
    # Ingests karakeep://all with limit=1 against real instance
    # Asserts at least one child_source returned
    ...
```

---

## 8. Documentation

### README.md sections

1. **What this is** — one paragraph
2. **Installation** — `pip install karakeep-synthadoc-skill`
3. **Configuration** — env var table (`KARAKEEP_URL`, `KARAKEEP_API_KEY`, `KARAKEEP_ARCHIVED_CONTENT`, `KARAKEEP_REQUEST_DELAY_MS`)
4. **Usage examples**
   ```bash
   synthadoc ingest karakeep://all -w main
   synthadoc ingest "karakeep://lists/abc123" -w main
   synthadoc ingest "karakeep://tags/research" -w main
   synthadoc ingest "karakeep://bookmark/xyz789" -w main
   ```
5. **Source URI reference** — table of all URI patterns
6. **Docker Compose** — how to add env vars:
   ```yaml
   environment:
     KARAKEEP_URL: "${KARAKEEP_URL}"
     KARAKEEP_API_KEY: "${KARAKEEP_API_KEY}"
   ```
   Add to `.env`:
   ```
   KARAKEEP_URL=https://karakeep.example.com
   KARAKEEP_API_KEY=your-api-key-here
   ```
7. **Notes on archived vs live content** — explain `KARAKEEP_ARCHIVED_CONTENT`
8. **Image bookmarks** — note that vision-capable LLM provider required

### `docs/karakeep.md` in main Synthadoc repo (outline)

```
# Karakeep Integration

Brief: what Karakeep is, why you'd use it with Synthadoc.

## Install the skill
pip install karakeep-synthadoc-skill

## Configure
env var table

## Ingest your vault
example commands

## Link to community skill repo
```

---

## 9. PR checklist

- [ ] `can_handle` (trigger prefix `karakeep://`) tested with all URI patterns
- [ ] All four bookmark types (`link`, `text`, `asset/pdf`, `asset/image`) produce `child_sources`
- [ ] Pagination tested with >1 page (mocked `nextCursor`)
- [ ] `KARAKEEP_URL` missing → `[ERR-SKILL-KAR-002]`, not stack trace
- [ ] `KARAKEEP_API_KEY` missing → `[ERR-SKILL-KAR-001]`, not stack trace
- [ ] `pyproject.toml` entry point verified against `_entry_point_skill_dirs()` in `skill_agent.py`
- [ ] Type annotations throughout (`str | None`, not `Optional[str]`)
- [ ] No API key or URL logged at any log level
- [ ] SPDX header on all source files: `# SPDX-License-Identifier: Apache-2.0`
- [ ] README covers Docker Compose env var addition
- [ ] `pytest` passes with no integration env vars set (all integration tests skip)

---

## 10. Resolved questions

All questions from the initial draft have been answered through codebase and API research.

| # | Question | Resolution |
|---|----------|-----------|
| 1 | Entry point resolution | `ep.value` is the raw string — `module:attr` form does NOT work. `skill_agent.py` must be patched to call `ep.load()`. Fix included in Section 2. |
| 2 | List bookmark endpoint | **Confirmed:** `GET /lists/{listId}/bookmarks` exists with `cursor`, `limit`, `sortOrder`, `includeContent`. |
| 3 | Asset download endpoint | **Confirmed:** `GET /assets/{assetId}` returns raw binary with dynamic `Content-Type`. |
| 4 | Async vs sync | **Async.** `BaseSkill.extract()` is `async def`. Use `httpx.AsyncClient`. |
| 5 | Preferred HTTP client | **httpx.** Already in synthadoc core deps (`httpx>=0.27`). Do not add aiohttp or requests. |
| 6 | Asset streaming vs buffering | **Stream to disk.** Use `async with client.stream(...) as r: async for chunk in r.aiter_bytes(): f.write(chunk)`. Applies to all asset downloads. |
| 7 | Incremental sync | **Not in scope v1.** Synthadoc deduplication handles re-runs. Future: `KARAKEEP_SINCE` env var. |
| 8 | Tag filtering | **Confirmed:** `GET /tags/{tagId}/bookmarks` exists. For `karakeep://tags/<name>`: resolve name → ID via `GET /tags?nameContains=<name>`, then use the dedicated endpoint. No client-side filtering needed. |

No open questions remain. Implementation can proceed from this plan.
