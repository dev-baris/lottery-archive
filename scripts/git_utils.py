#!/usr/bin/env python3
"""Shared git utilities used by all lottery update scripts."""

import subprocess
from pathlib import Path


def git_commit(file: str | Path, message: str) -> bool:
    """
    Stage and commit only ``file``, preserving unrelated staged changes.

    Run Git from the file's directory so callers need not start in the repository.
    Returns True if a commit was created, False if that file is unchanged.
    Git errors, including failures to inspect the index, propagate to the caller.
    """
    path = Path(file).absolute()
    git = ["git", "--literal-pathspecs", "-C", str(path.parent)]
    subprocess.run([*git, "add", "--", path.name], check=True)
    diff = [*git, "diff", "--cached", "--quiet", "--", path.name]
    result = subprocess.run(diff, check=False)
    if result.returncode == 0:
        return False
    if result.returncode != 1:
        raise subprocess.CalledProcessError(result.returncode, diff)
    subprocess.run(
        [*git, "commit", "--only", "-m", message, "--", path.name], check=True
    )
    return True
