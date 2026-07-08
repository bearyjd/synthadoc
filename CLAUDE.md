# CLAUDE.md — Synthadoc

Guidance for AI coding agents working in this repository. Commands below are
verified against `pyproject.toml`, `CONTRIBUTING.md`, `.github/workflows/ci.yml`,
and `README.md` — do not substitute invented commands.

## What this is

Synthadoc is a domain-agnostic LLM knowledge compilation engine: it ingests
raw documents (PDF, DOCX, PPTX, XLSX, images, YouTube, web) and uses an LLM to
synthesize them into a persistent Markdown wiki, exposed via CLI, HTTP API,
and MCP server. There's a companion Obsidian plugin (TypeScript) that talks to
the Python HTTP server over `127.0.0.1`. See `docs/design.md` for the full
architecture and `README.md` for the command reference.

## Setup

```bash
pip3 install -e ".[dev]"
```

Requires Python 3.11+. Optional `vectors` extra (`pip3 install -e ".[vectors]"`)
needs a Rust toolchain to build `fastembed` — skip unless the task touches
vector search.

## Build / test / lint commands (verified)

```bash
# Full Python test suite (performance benchmarks excluded — this is what CI runs by default)
pytest --ignore=tests/performance/ -q

# With coverage, matching CI's coverage job
pytest --cov=synthadoc --cov-report=term-missing -v

# Performance/benchmark tests (opt-in, Linux/macOS; measures SLOs, not correctness)
pytest tests/performance/ -v --benchmark-disable

# Deselect integration tests that need real external tools
pytest -m "not integration"

# Obsidian plugin (separate toolchain, run from obsidian-plugin/)
cd obsidian-plugin && npm install && npm run build && npm test
```

There is no `ruff` config committed (`pyproject.toml` has no `[tool.ruff]`
table), even though `CONTRIBUTING.md` says to "use `ruff` for linting" — run
`ruff check .` with defaults if asked to lint, but flag this gap rather than
assuming a specific rule set; see `.agent_native/agent_roadmap.md` backlog.

CI (`.github/workflows/ci.yml`) runs the full matrix (ubuntu/windows/macos ×
Python 3.11/3.12): `pip install -e ".[dev]"` → `python scripts/update_badges.py --check`
→ `pytest --cov=synthadoc --cov-report=term-missing -v`, plus a separate
`build-plugin` job (`cd obsidian-plugin && npm install && npm run build && npm test`).
A change is not "CI-clean" until both jobs would pass.

## Repository structure

- `synthadoc/cli/` — Typer CLI commands (`synthadoc <verb>`), one file per
  command group (`ingest.py`, `query.py`, `lint.py`, `scaffold.py`, `jobs.py`, …).
- `synthadoc/core/` — orchestration, job queue, cache, cost guard, hooks
  runtime, routing. This is where cross-cutting engine logic lives.
- `synthadoc/agents/` — the LLM-driving agents (`ingest_agent.py`,
  `query_agent.py`, `lint_agent.py`, `scaffold_agent.py`, `skill_agent.py`, …).
- `synthadoc/skills/base.py` and `synthadoc/providers/base.py` — **Apache-2.0**,
  the only Apache-licensed files in the repo (see Licensing below). Everything
  else in `synthadoc/` is AGPL-3.0-or-later.
- `synthadoc/providers/` — LLM backend adapters (Anthropic, OpenAI, Ollama,
  coding-tool passthrough) plus `pricing.py`, which must stay accurate against
  live provider pricing pages (see Release process below).
- `synthadoc/integration/` — `http_server.py` (FastAPI) and `mcp_server.py`;
  the REST contract the Obsidian plugin's `obsidian-plugin/src/api.ts` depends on.
- `synthadoc/demos/` — two full example wikis (`ai-research/`,
  `history-of-computing/`) with `raw_sources/`, `AGENTS.md`, and compiled
  `wiki/*.md` — installable via `synthadoc install <name> --demo` and useful
  as realistic reproduction fixtures for bug reports (not yet wired into
  `tests/conftest.py`; see roadmap item 1).
- `obsidian-plugin/` — separate npm package (`main.ts` + `api.ts`), tested
  with Vitest against a mocked `obsidian` module (`__mocks__/obsidian.ts`).
  Talks to the Python server only over HTTP — do not add direct Python↔TS
  imports; keep the HTTP boundary as the sole integration surface.
- `hooks/` — example lifecycle hook scripts (`on_ingest_complete`,
  `on_lint_complete`) users copy into their own wiki root and wire up via
  `.synthadoc/config.toml`. Contract: read JSON from stdin, write status to
  stderr, exit 0/non-zero. Full schema in `docs/design.md` §12.
- `tests/` mirrors `synthadoc/` package structure 1:1
  (`tests/agents/`, `tests/core/`, `tests/cli/`, `tests/integration/`,
  `tests/providers/`, `tests/skills/`, `tests/storage/`, `tests/security/`,
  `tests/performance/`). Put new tests in the matching subpackage.
- `docker/`, `Dockerfile`, `docker-compose.yml` — multi-target build
  (`base` and `vectors`); CI's `.github/workflows/docker.yml` builds both and
  runs a `/health` smoke test against the `edge` tag.

## Versioning (single source of truth: `VERSION`)

`VERSION` at repo root is the only source of truth. `synthadoc/__init__.py`
reads it at runtime; `pyproject.toml` uses `[tool.hatch.version]` with
`source = "code"` to derive the package version from it. **Never hand-edit
version strings elsewhere** — use:

```bash
python scripts/bump_version.py <new_version>   # e.g. 0.5.0
```

This updates `VERSION`, `obsidian-plugin/manifest.json`, and
`obsidian-plugin/package.json` together. After running it:

```bash
git add VERSION obsidian-plugin/manifest.json obsidian-plugin/package.json
git commit -m "chore: bump version to <new_version>"
git tag v<new_version>
```

Before tagging a release, also check `CONTRIBUTING.md`'s release checklist:
verify `synthadoc/providers/pricing.py`'s rates and `_LAST_UPDATED` against
each provider's live pricing page (Anthropic, OpenAI, Gemini, Groq) — this is
not currently enforced by CI, so treat it as a mandatory manual step until
`.agent_native/agent_roadmap.md` item 3 is implemented.

## Licensing (must respect when adding files)

Split-license model — get this wrong and a PR cannot be merged:

| Path | License |
|---|---|
| `synthadoc/skills/base.py` | Apache-2.0 |
| `synthadoc/providers/base.py` | Apache-2.0 |
| Everything else | AGPL-3.0-or-later |

Add an SPDX header to every new source file:

```python
# SPDX-License-Identifier: AGPL-3.0-or-later   # core files
# SPDX-License-Identifier: Apache-2.0           # new plugin/provider interface files
# Copyright (C) 2026 Paul Chen / axoviq.com
```

New third-party skills/providers should only extend the Apache-2.0 base
classes, not modify AGPL core files, to preserve the licensing boundary that
lets third parties write closed-source skills/providers.

## Code style

- Python: PEP 8, `ruff` for linting (see gap noted above).
- TypeScript (`obsidian-plugin/`): follow the existing eslint/prettier config
  already in that directory — don't introduce a new one.
- One logical change per commit; new behavior needs a test, bug fixes need a
  regression test (per `CONTRIBUTING.md`).

## Workflow expectations for agents

1. Open/read the relevant issue or bug report; if it references demo wiki
   content, reproduce against `synthadoc/demos/ai-research/` or
   `synthadoc/demos/history-of-computing/` rather than fabricating fixtures.
2. Write a failing test in the matching `tests/<subpackage>/` directory first.
3. Implement the minimal fix.
4. Run `pytest --ignore=tests/performance/ -q` (and `npm test` in
   `obsidian-plugin/` if the change touches the plugin) before calling work done.
5. Do not open a PR without a passing local test run — CI mirrors these exact
   commands, so a local pass is a strong signal of a green CI run.

See `.agent_native/agent_roadmap.md` for prioritized gaps in this workflow
(missing hook tests, no demo-wiki test fixtures, no release-consistency CI
check, no plugin/server contract test) and concrete next steps to close them.
