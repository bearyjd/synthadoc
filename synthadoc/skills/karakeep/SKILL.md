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

Pulls bookmarks from a [Karakeep](https://karakeep.app) instance and ingests them
as wiki pages. Each bookmark is dispatched to the appropriate existing Synthadoc
skill (URL, markdown, PDF, image) via `child_sources`.

## URI patterns

| URI | Ingests |
|-----|---------|
| `karakeep://all` | Every bookmark in the vault |
| `karakeep://lists/<listId>` | Bookmarks in a specific list |
| `karakeep://tags/<tagName>` | Bookmarks carrying a tag (by name) |
| `karakeep://bookmark/<id>` | A single bookmark |

## Required environment variables

- `KARAKEEP_URL` — base URL of your Karakeep instance
- `KARAKEEP_API_KEY` — bearer token from Settings → API Keys

## Optional environment variables

- `KARAKEEP_ARCHIVED_CONTENT` — `true` (default) to use cached HTML over live URL
- `KARAKEEP_REQUEST_DELAY_MS` — ms between API requests (default: `200`)
