# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Paul Chen / axoviq.com
"""Tests for the shipped hooks/git-auto-commit.py example hook.

Runs the script as a real subprocess (as the hook runtime,
synthadoc.core.hooks.HookExecutor, does) against a real tmp git repo, and
cross-checks its `ctx.get(...)` keys against the JSON context that
synthadoc/core/orchestrator.py actually fires for `on_ingest_complete`, so a
renamed context key fails this test instead of failing silently in a user's
wiki.
"""
import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

_PY = sys.executable
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_HOOK_SCRIPT = _REPO_ROOT / "hooks" / "git-auto-commit.py"
_ORCHESTRATOR = _REPO_ROOT / "synthadoc" / "core" / "orchestrator.py"


def _init_git_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
    (root / "wiki").mkdir()
    (root / "wiki" / "index.md").write_text("# Index\n", encoding="utf-8")
    subprocess.run(["git", "add", "wiki/"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=root, check=True)


def _run_hook(ctx: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [_PY, str(_HOOK_SCRIPT)],
        input=json.dumps(ctx),
        capture_output=True,
        text=True,
    )


def test_hook_creates_commit_with_expected_message_format(tmp_path):
    _init_git_repo(tmp_path)
    (tmp_path / "wiki" / "alan-turing.md").write_text("# Alan Turing\n", encoding="utf-8")
    (tmp_path / "wiki" / "index.md").write_text("# Index\nupdated\n", encoding="utf-8")

    ctx = {
        "wiki": str(tmp_path),
        "source": "report.pdf",
        "pages_created": ["alan-turing"],
        "pages_updated": ["index"],
    }
    result = _run_hook(ctx)

    assert result.returncode == 0, result.stderr
    assert "git-auto-commit:" in result.stderr

    log = subprocess.run(
        ["git", "log", "-1", "--pretty=%s"], cwd=tmp_path, capture_output=True, text=True, check=True
    )
    assert log.stdout.strip() == "wiki: ingest report.pdf → created alan-turing; updated index"


def test_hook_nothing_to_commit_exits_zero(tmp_path):
    """Documented behaviour: a no-op ingest (no wiki/ changes) must not fail the hook."""
    _init_git_repo(tmp_path)

    ctx = {"wiki": str(tmp_path), "source": "report.pdf", "pages_created": [], "pages_updated": []}
    result = _run_hook(ctx)

    assert result.returncode == 0, result.stderr
    assert "nothing to commit" in result.stderr


def test_hook_git_failure_exits_nonzero(tmp_path):
    """Documented behaviour: a git failure (not a repo) must exit non-zero."""
    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki" / "index.md").write_text("# Index\n", encoding="utf-8")

    ctx = {"wiki": str(tmp_path), "source": "report.pdf", "pages_created": ["index"], "pages_updated": []}
    result = _run_hook(ctx)

    assert result.returncode == 1
    assert "git-auto-commit error" in result.stderr


def _extract_ctx_get_keys(script_path: Path) -> set[str]:
    """Statically extract every `ctx.get("key", ...)` literal key from a script."""
    tree = ast.parse(script_path.read_text(encoding="utf-8"))
    keys = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "ctx"
            and node.args
            and isinstance(node.args[0], ast.Constant)
        ):
            keys.add(node.args[0].value)
    return keys


def _extract_on_ingest_complete_context_keys(orchestrator_path: Path) -> set[str]:
    """Statically extract the dict keys passed to `self._hooks.fire("on_ingest_complete", {...})`."""
    tree = ast.parse(orchestrator_path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "fire"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "on_ingest_complete"
        ):
            dict_arg = node.args[1]
            assert isinstance(dict_arg, ast.Dict), "expected a dict literal as the fire() context arg"
            return {k.value for k in dict_arg.keys if isinstance(k, ast.Constant)}
    raise AssertionError('No self._hooks.fire("on_ingest_complete", {...}) call found in orchestrator.py')


def test_hook_context_keys_match_orchestrator_schema():
    """Schema-drift guard: every key the hook script reads must exist in the
    context dict the orchestrator actually fires for on_ingest_complete.

    Deliberately renaming a context key in orchestrator.py (e.g. "wiki" ->
    "wiki_root") without updating the hook script must fail this test.
    """
    hook_keys = _extract_ctx_get_keys(_HOOK_SCRIPT)
    orchestrator_keys = _extract_on_ingest_complete_context_keys(_ORCHESTRATOR)

    missing = hook_keys - orchestrator_keys
    assert not missing, (
        f"hooks/git-auto-commit.py reads ctx keys {missing} that "
        f"orchestrator.py no longer provides for on_ingest_complete "
        f"(available: {orchestrator_keys})"
    )
