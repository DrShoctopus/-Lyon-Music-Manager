from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "push-release.sh"


@pytest.mark.skipif(sys.platform == "win32", reason="bash syntax check uses the POSIX release helper")
def test_push_release_script_is_valid_bash():
    assert SCRIPT.exists()

    result = subprocess.run(
        ["bash", "-n", str(SCRIPT)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_push_release_script_has_draft_release_safety_gates():
    script = SCRIPT.read_text(encoding="utf-8")

    required_snippets = [
        "scripts/changelog-section.py",
        "git status --short",
        "git rev-list --left-right --count",
        "git show-ref --verify --quiet \"refs/tags/$tag\"",
        "git ls-remote --exit-code --tags \"$remote\" \"$tag\"",
        "git tag -a \"$tag\"",
        "git push \"$remote\" \"$branch\"",
        "git push \"$remote\" \"$tag\"",
        "--skip-tests",
        "--yes",
    ]

    for snippet in required_snippets:
        assert snippet in script


def test_push_release_script_stops_before_publication():
    script = SCRIPT.read_text(encoding="utf-8")

    assert "gh release create" not in script
    assert "gh release edit" not in script
    assert "gh release upload" not in script
    assert "published" not in script.lower()
    assert "Draft release" in script
