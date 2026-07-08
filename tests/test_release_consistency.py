# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Paul Chen / axoviq.com
"""Release-consistency checks that used to be tribal knowledge.

Previously enforced only via a human hand-verifying `CONTRIBUTING.md`'s
release checklist. These checks turn that checklist into something CI can
fail on: VERSION vs. the Obsidian plugin's two package files drifting apart,
and stale LLM provider pricing data.
"""
import json
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_PRICING_STALENESS_DAYS = 90


def _read_version_file() -> str:
    return (ROOT / "VERSION").read_text(encoding="utf-8").strip()


def _read_json_version(path: Path) -> str:
    return json.loads(path.read_text(encoding="utf-8"))["version"]


def test_version_file_matches_obsidian_manifest():
    version = _read_version_file()
    manifest_version = _read_json_version(ROOT / "obsidian-plugin" / "manifest.json")
    assert version == manifest_version, (
        f"VERSION ({version!r}) does not match obsidian-plugin/manifest.json "
        f"({manifest_version!r}) — run `python scripts/bump_version.py <version>`."
    )


def test_version_file_matches_obsidian_package_json():
    version = _read_version_file()
    package_version = _read_json_version(ROOT / "obsidian-plugin" / "package.json")
    assert version == package_version, (
        f"VERSION ({version!r}) does not match obsidian-plugin/package.json "
        f"({package_version!r}) — run `python scripts/bump_version.py <version>`."
    )


def test_version_file_is_semver():
    version = _read_version_file()
    assert re.fullmatch(r"\d+\.\d+\.\d+.*", version), (
        f"VERSION ({version!r}) is not semver-shaped."
    )


def test_pricing_last_updated_is_not_stale():
    """`_LAST_UPDATED` in pricing.py must be refreshed at least every ~90 days.

    This doesn't verify the rates themselves are accurate (that still needs a
    human to check live provider pricing pages per CONTRIBUTING.md) — it just
    gives a scriptable trigger for "go check pricing.py again."
    """
    from synthadoc.providers.pricing import _LAST_UPDATED

    last_updated = date.fromisoformat(_LAST_UPDATED)
    age_days = (date.today() - last_updated).days
    assert age_days <= _PRICING_STALENESS_DAYS, (
        f"synthadoc/providers/pricing.py's _LAST_UPDATED ({_LAST_UPDATED}) is "
        f"{age_days} days old (limit {_PRICING_STALENESS_DAYS}). Verify rates "
        f"against live provider pricing pages (see CONTRIBUTING.md release "
        f"checklist) and update _LAST_UPDATED."
    )
