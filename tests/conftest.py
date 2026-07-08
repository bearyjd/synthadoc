# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Paul Chen / axoviq.com
import shutil
import pytest
from pathlib import Path

_DEMOS_ROOT = Path(__file__).resolve().parent.parent / "synthadoc" / "demos"


@pytest.fixture
def tmp_wiki(tmp_path: Path) -> Path:
    """Minimal wiki root with all required subdirectories."""
    (tmp_path / "wiki").mkdir()
    (tmp_path / "raw_sources").mkdir()
    (tmp_path / "hooks").mkdir()
    (tmp_path / "skills").mkdir()
    sd = tmp_path / ".synthadoc"
    sd.mkdir()
    (sd / "logs").mkdir()
    return tmp_path


@pytest.fixture
def demo_wiki(tmp_path: Path):
    """Factory fixture: copy a shipped demo wiki into a tmp dir for reproduction.

    Usage: ``def test_x(demo_wiki): wiki = demo_wiki("ai-research")``.
    Also fills in any subdirectories ``tmp_wiki`` guarantees (``hooks/``,
    ``skills/``, ``.synthadoc/logs/``) that a given demo doesn't ship, so the
    copy is a drop-in wiki root just like ``tmp_wiki``.
    """

    def _copy(name: str) -> Path:
        src = _DEMOS_ROOT / name
        if not src.is_dir():
            available = sorted(
                p.name for p in _DEMOS_ROOT.iterdir() if p.is_dir() and not p.name.startswith("_")
            )
            raise ValueError(f"Unknown demo wiki {name!r}. Available: {available}")
        dest = tmp_path / name
        shutil.copytree(src, dest)
        for required in ("wiki", "raw_sources", "hooks", "skills"):
            (dest / required).mkdir(exist_ok=True)
        sd = dest / ".synthadoc"
        sd.mkdir(exist_ok=True)
        (sd / "logs").mkdir(exist_ok=True)
        return dest

    return _copy
