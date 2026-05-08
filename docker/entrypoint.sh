#!/usr/bin/env bash
# docker/entrypoint.sh — Synthadoc container entrypoint
#
# Environment variables:
#   WIKI_NAME     wiki identifier              (default: main)
#   WIKI_DOMAIN   domain string for scaffold   (default: "Personal knowledge base")
#   WIKI_PORT     port synthadoc listens on    (default: 7070)
#
# Secrets (pass as env vars — never bake into image):
#   ANTHROPIC_API_KEY | OPENAI_API_KEY | GEMINI_API_KEY | GROQ_API_KEY | TAVILY_API_KEY

set -euo pipefail

WIKI_NAME="${WIKI_NAME:-main}"
WIKI_DIR="/wikis/${WIKI_NAME}"
WIKI_DOMAIN="${WIKI_DOMAIN:-Personal knowledge base}"
WIKI_PORT="${WIKI_PORT:-7070}"

# ── Validate at least one LLM key is present ──────────────
if [[ -z "${ANTHROPIC_API_KEY:-}" && \
      -z "${OPENAI_API_KEY:-}" && \
      -z "${GEMINI_API_KEY:-}" && \
      -z "${GROQ_API_KEY:-}" ]]; then
  echo "[entrypoint] WARNING: No LLM API key found in environment." >&2
  echo "[entrypoint] Set ANTHROPIC_API_KEY, GEMINI_API_KEY, GROQ_API_KEY, or OPENAI_API_KEY." >&2
  echo "[entrypoint] Synthadoc will start but ingest/query will fail without a provider key." >&2
fi

# ── First-run: initialise the wiki ────────────────────────
if [[ ! -d "${WIKI_DIR}/.synthadoc" ]]; then
  echo "[entrypoint] Wiki '${WIKI_NAME}' not found — initialising..."
  if ! synthadoc install "${WIKI_NAME}" \
      --target /wikis \
      --domain "${WIKI_DOMAIN}" \
      --port "${WIKI_PORT}"; then
    echo "[entrypoint] ERROR: install failed — check /wikis is writable and config is valid" >&2
    exit 1
  fi
  echo "[entrypoint] Wiki initialised at ${WIKI_DIR}"
else
  echo "[entrypoint] Wiki '${WIKI_NAME}' found at ${WIKI_DIR} — re-registering in local registry..."
  # The registry (~/.synthadoc/wikis.json) is ephemeral per container start.
  # Re-register the existing wiki so synthadoc serve can resolve it by name.
  python3 - <<PYEOF
import json
from pathlib import Path
from datetime import date
reg = Path.home() / ".synthadoc" / "wikis.json"
reg.parent.mkdir(parents=True, exist_ok=True)
registry = json.loads(reg.read_text()) if reg.exists() else {}
registry["${WIKI_NAME}"] = {"path": "${WIKI_DIR}", "demo": None, "installed": date.today().isoformat()}
reg.write_text(json.dumps(registry, indent=2))
PYEOF
fi

# ── Start server ──────────────────────────────────────────
echo "[entrypoint] Starting synthadoc serve -w ${WIKI_NAME} --port ${WIKI_PORT}"
exec synthadoc serve \
  -w "${WIKI_NAME}" \
  --port "${WIKI_PORT}"
