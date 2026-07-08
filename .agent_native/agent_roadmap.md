# Synthadoc — Agent-Native Roadmap

Goal: an AI coding agent should be able to pick up a raw bug report or feature
request, reproduce it, implement a fix, test it, and verify it — with minimal
human input.

Items are ordered by **Human-Attention-Saved per Unit of Effort** (highest
leverage first). The top 5 are immediately actionable with concrete files,
commands, and acceptance criteria. Everything after is lower priority /
longer-horizon.

Stack: Python 3.11+ (FastAPI, Typer CLI, pytest), TypeScript Obsidian plugin
(esbuild + Vitest), Docker multi-stage build, GitHub Actions CI.

---

## Top 5 — do these first

### 1. Wire a demo wiki into the test fixtures as a realistic reproduction harness — DONE

**Status:** Implemented. Added a `demo_wiki(name: str)` factory fixture to
`tests/conftest.py` (copies `synthadoc/demos/<name>/` into `tmp_path` via
`shutil.copytree`, backfilling any `tmp_wiki`-guaranteed subdirectories a demo
doesn't ship) and `tests/demos/test_demo_wikis.py` with parametrized smoke
tests over both shipped demos (`POST /query`, `GET /lint/report`).
`pytest tests/demos/ -q` passes (4 passed).

**Problem:** `tests/conftest.py` only provides `tmp_wiki`, an empty directory
skeleton (`wiki/`, `raw_sources/`, `hooks/`, `skills/`, `.synthadoc/`). Every
test that needs realistic wiki content (pages with frontmatter, `[[wikilinks]]`,
contradictions, orphans) hand-writes it inline. Meanwhile
`synthadoc/demos/ai-research/` and `synthadoc/demos/history-of-computing/`
already contain full realistic wikis with `raw_sources/`, `AGENTS.md`, and
compiled `wiki/*.md` pages — but they're only reachable through
`synthadoc install --demo`, not through pytest. An agent asked to reproduce
"query returns wrong citation on the ai-research demo" has no fast path from
bug report to a running test.

**Fix:**
- Add a `demo_wiki(name: str)` fixture to `tests/conftest.py` that copies
  `synthadoc/demos/<name>/` into `tmp_path` (via `shutil.copytree`), so tests
  can do `def test_x(demo_wiki): wiki = demo_wiki("ai-research")`.
- Add one regression test per demo directory under a new `tests/demos/`
  package that runs `POST /query` and `GET /lint/report` against the copied
  wiki via `TestClient(create_app(wiki_root=wiki))`, asserting non-error
  responses — a baseline "the shipped demo wikis still work" smoke test.

**Files:** `tests/conftest.py`, new `tests/demos/test_demo_wikis.py`,
reference content in `synthadoc/demos/ai-research/`,
`synthadoc/demos/history-of-computing/`.

**Acceptance criteria:** `pytest tests/demos/ -q` passes; a bug report that
references demo content can be reproduced by pointing a new test at
`demo_wiki("<name>")` with zero fixture authoring.

---

### 2. Add a test harness for `hooks/git-auto-commit.py` and document the hook contract in code — DONE

**Status:** Implemented. Added `tests/hooks/test_git_auto_commit.py`, which
runs the hook script as a real subprocess against a tmp git repo (commit
message format, "nothing to commit" exit-0 path, git-failure exit-1 path)
and statically cross-checks its `ctx.get(...)` keys against the dict
`synthadoc/core/orchestrator.py` fires for `on_ingest_complete`, so a renamed
context key fails CI (verified: renaming `"wiki"` to `"wiki_root"` in
`orchestrator.py` makes the new schema test fail, as required by the
acceptance criteria). Along the way the new test caught a real bug in the
shipped hook: the `git add` step used `check=True` with no exception
handling, so a git failure produced an unhandled Python traceback instead of
the documented `git-auto-commit error: ...` message + exit 1. Fixed in
`hooks/git-auto-commit.py`. `pytest tests/hooks/ tests/core/test_hooks.py -v`
passes (10 passed).

**Problem:** The hook system (`on_ingest_complete`, `on_lint_complete`) is a
real extension point — `hooks/git-auto-commit.py` ships as the only example —
but there is no test anywhere in `tests/` for it, and the JSON context schema
it depends on (`wiki`, `source`, `pages_created`, `pages_updated`) lives only
in prose in `docs/design.md` §12 and `hooks/README.md`. `synthadoc/core/hooks.py`
is the runtime that invokes these scripts and does have its own tests
(`tests/core/test_hooks.py`), but the shipped hook script itself is untested,
so a regression in its JSON parsing or git invocation would only surface in
production.

**Fix:**
- Add `tests/hooks/test_git_auto_commit.py` that invokes
  `hooks/git-auto-commit.py` as a subprocess with a JSON context on stdin
  against a real tmp git repo, asserting a commit is created with the
  expected message format, and that "nothing to commit" and git-failure paths
  exit with the documented codes.
- Cross-check `synthadoc/core/hooks.py`'s context-building code against
  `hooks/git-auto-commit.py`'s `ctx.get(...)` keys in the same test file
  (import both, assert key parity) so schema drift fails CI instead of
  failing silently in a user's wiki.

**Files:** `hooks/git-auto-commit.py`, `synthadoc/core/hooks.py`,
`tests/core/test_hooks.py`, new `tests/hooks/test_git_auto_commit.py`.

**Acceptance criteria:** new test file passes under `pytest`; deliberately
renaming a context key in `synthadoc/core/hooks.py` without updating the hook
script makes the new test fail.

---

### 3. Codify the release process as a single script/CI job instead of a manual checklist — PARTIALLY DONE

**Status:** Added `tests/test_release_consistency.py`, which will run as part
of the normal `pytest` CI job (no separate script/CI job needed): asserts
`VERSION` == `obsidian-plugin/manifest.json` version ==
`obsidian-plugin/package.json` version (verified: bumping only `VERSION`
without running `scripts/bump_version.py` fails 2 of the 4 tests), plus a
staleness check that `synthadoc/providers/pricing.py`'s `_LAST_UPDATED` is
no more than 90 days old. Not done: the pricing *rates themselves* still
require a human to hand-verify against live provider pages per
`CONTRIBUTING.md` — this only makes staleness (not accuracy) scriptable, as
scoped in the original acceptance criteria. `pytest
tests/test_release_consistency.py -v` passes (4 passed).

**Problem:** Releasing today requires a human to: (1) edit `VERSION`, (2) run
`scripts/bump_version.py <ver>` to sync `obsidian-plugin/manifest.json` and
`obsidian-plugin/package.json`, (3) manually `git tag`, and separately (4)
open `CONTRIBUTING.md`'s release checklist to hand-verify LLM provider
pricing against four external pricing pages before touching
`synthadoc/providers/pricing.py`. None of this is enforced by CI: nothing
checks that `VERSION`, `obsidian-plugin/manifest.json["version"]`, and
`obsidian-plugin/package.json["version"]` actually agree, and nothing checks
that `pricing.py`'s `_LAST_UPDATED` isn't stale. This is pure tribal knowledge
today — it lives in a contributor's head plus two markdown files.

**Fix:**
- Add a `tests/test_release_consistency.py` (or a `scripts/check_release.py`
  invoked from CI) that asserts `VERSION` == `obsidian-plugin/manifest.json`
  version == `obsidian-plugin/package.json` version, failing loudly if
  `scripts/bump_version.py` was skipped.
- Add a lightweight staleness check: fail (or warn) if
  `synthadoc/providers/pricing.py`'s `_LAST_UPDATED` is more than ~90 days
  old, so an agent (or human) doing routine maintenance gets a concrete,
  scriptable signal instead of relying on remembering the CONTRIBUTING.md
  checklist.
- This has been captured as an explicit rule in the new root `CLAUDE.md`
  (see below) so an agent following instructions will run these checks
  before proposing a release PR.

**Files:** `VERSION`, `scripts/bump_version.py`, `synthadoc/providers/pricing.py`,
`obsidian-plugin/manifest.json`, `obsidian-plugin/package.json`, new test/script.

**Acceptance criteria:** a version bump that only edits `VERSION` (forgetting
the plugin files) fails CI; `_LAST_UPDATED` staleness is programmatically
detectable, not just documented prose.

---

### 4. Add a contract test between the FastAPI server and the Obsidian plugin's `api.ts`

**Problem:** The Python HTTP server (`synthadoc/integration/http_server.py`)
and the TypeScript plugin (`obsidian-plugin/src/api.ts`, 42 lines, hand-written
HTTP client) are two independently-maintained implementations of the same
REST contract, tested in two different frameworks (`pytest` +
`TestClient` vs. `vitest` + mocked `requestUrl`). Nothing currently checks
that a route or response shape change on one side is reflected on the other —
`tests/integration/test_http_api.py` and `obsidian-plugin/src/api.test.ts`
each assert against their own hard-coded expectations. This is the single
biggest "entangled modules" risk called out in the audit: the Python package
and the plugin are structurally decoupled (HTTP boundary, separate build
tooling, separate package managers) but have zero automated boundary
verification.

**Fix:**
- Generate/export the FastAPI OpenAPI schema (`app.openapi()`) to a checked-in
  JSON file (`docs/openapi.json`) via a small script, refreshed in CI.
- Add a CI step (or vitest test) that parses `obsidian-plugin/src/api.ts` calls
  (method + path) and asserts each exists in `docs/openapi.json`, catching
  silent drift (renamed/removed endpoints) at build time rather than at
  runtime inside a user's Obsidian vault.

**Files:** `synthadoc/integration/http_server.py`, `obsidian-plugin/src/api.ts`,
`obsidian-plugin/src/api.test.ts`, `tests/integration/test_http_api.py`, new
`docs/openapi.json` + generator script.

**Acceptance criteria:** deleting or renaming a route in `http_server.py`
without updating `api.ts` fails a CI check with a specific route name, instead
of only failing silently at runtime.

---

### 5. Root `CLAUDE.md` capturing verified commands and tribal knowledge (this deliverable)

**Problem:** There was no `CLAUDE.md` in the repo. An agent starting cold has
to reverse-engineer the dual-license boundary (`skills/base.py`,
`providers/base.py` are Apache-2.0; everything else is AGPL — mixing this up
in a PR is a real legal/structural mistake), the exact test commands
(`pytest --ignore=tests/performance/ -q`, not bare `pytest`, since performance
tests are opt-in benchmarks), the version-bump sequence, and the SPDX header
requirement for new files.

**Fix:** Done as part of this audit — see `/home/user/Documents/vibe-code/synthadoc/CLAUDE.md`,
sourced only from `pyproject.toml`, `CONTRIBUTING.md`, `.github/workflows/ci.yml`,
and `README.md` (no invented commands).

**Acceptance criteria:** a fresh agent session can run the build/test/lint
commands in `CLAUDE.md` verbatim and get the same result CI gets.

---

## Backlog (lower leverage, still worth tracking)

- **No `ruff` config** exists in `pyproject.toml` despite `CONTRIBUTING.md`
  instructing contributors to "use `ruff` for linting" and a populated
  `.ruff_cache/` — defaults are implicit. Add a `[tool.ruff]` table (or
  `ruff.toml`) pinning rule selection so an agent's lint pass matches what a
  human reviewer expects, rather than guessing ruff's shifting defaults.
- **`docker.yml` smoke test** only checks `--version` and `/health` for both
  image variants — it never exercises an actual ingest → query round trip
  inside the container. A minimal `synthadoc ingest` + `synthadoc query`
  smoke step would catch container-only regressions (missing runtime deps,
  path issues) that unit tests can't see.
- **`synthadoc/demos/*`** ship full demo content (raw source binaries: `.pptx`,
  `.pdf`, `.xlsx`, `.png`) inside the installable Python package
  (`synthadoc/demos/`), increasing wheel size and blurring "product code" vs.
  "fixture content." Consider moving demo raw sources to a separate
  data-only extra or git submodule if wheel size becomes a concern — not
  urgent, but worth a note before the next packaging change.
- **`scripts/update_badges.py` and `scripts/bump_version.py`** have no tests
  of their own (only exercised via CI's `--check` mode for badges). Low risk
  since they're simple, but a bug in `bump_version.py`'s JSON round-trip
  would silently corrupt `manifest.json`/`package.json` formatting.
