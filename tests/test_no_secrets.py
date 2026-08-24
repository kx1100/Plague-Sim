"""
A paste accident should fail the suite, not ship.

Run records are tracked in git and published, and the harness talks to two
backends that need keys. Nothing here reads a key or needs one — the scan is
over what is already committed, which is exactly what a leak would be.
"""

import os
import subprocess

import pytest

from tools.run_store import ROOT, find_provider_keys

# Text worth scanning. Binaries and dependency trees are excluded rather than
# decoded, and `git ls-files` already excludes everything gitignored.
_SCAN_SUFFIXES = {
    ".py", ".json", ".js", ".mjs", ".md", ".txt", ".html", ".css",
    ".yml", ".yaml", ".ini", ".cfg", ".toml", ".sh", ".env", ".ps1",
}
_MAX_BYTES = 8 * 1024 * 1024

# Variables the harness knows how to use. If one is set in this shell, its
# value must appear in no committed file.
_KEY_VARS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY",
             "GOOGLE_API_KEY", "OPENROUTER_API_KEY")


def tracked_text_files():
    try:
        out = subprocess.run(
            ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        pytest.skip("git is not available")
    if out.returncode != 0:
        pytest.skip("not a git checkout")

    for name in out.stdout.splitlines():
        path = ROOT / name
        if path.suffix.lower() not in _SCAN_SUFFIXES:
            continue
        if not path.is_file() or path.stat().st_size > _MAX_BYTES:
            continue
        yield path, path.read_text(encoding="utf-8", errors="replace")


def test_no_committed_file_contains_a_provider_key():
    leaks = [
        f"{path.relative_to(ROOT).as_posix()}: {found[0][:12]}…"
        for path, text in tracked_text_files()
        for found in [find_provider_keys(text)]
        if found
    ]
    assert not leaks, "credential-shaped strings in tracked files: " + "; ".join(leaks)


def test_no_committed_file_contains_a_key_from_this_environment():
    """
    The precise check: whatever key this shell actually holds must not appear
    anywhere in the tree. Zero false positives, and it catches a provider whose
    key format the prefix list has never heard of.
    """
    live = {var: os.environ[var] for var in _KEY_VARS
            if len(os.environ.get(var, "")) >= 16}
    if not live:
        pytest.skip("no API keys set in this environment")

    leaks = [
        f"{path.relative_to(ROOT).as_posix()} contains ${var}"
        for path, text in tracked_text_files()
        for var, value in live.items()
        if value in text
    ]
    assert not leaks, "; ".join(leaks)
