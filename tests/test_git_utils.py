"""Path-scoped Git commits, including regressions in isolated real repositories."""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, call, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from git_utils import git_commit


class TestGitCommit(unittest.TestCase):
    def setUp(self):
        self.file = Path.cwd() / "data" / "results.csv"
        self.git = ["git", "--literal-pathspecs", "-C", str(self.file.parent)]
        self.diff = [*self.git, "diff", "--cached", "--quiet", "--", self.file.name]

    def test_unchanged_file_is_not_committed(self):
        with patch("git_utils.subprocess.run", return_value=MagicMock(returncode=0)) as run:
            self.assertFalse(git_commit(self.file, "message"))
        self.assertEqual(
            run.call_args_list,
            [
                call([*self.git, "add", "--", self.file.name], check=True),
                call(self.diff, check=False),
            ],
        )

    def test_changed_file_is_committed_with_only_path(self):
        with patch("git_utils.subprocess.run") as run:
            run.side_effect = [
                MagicMock(returncode=0),
                MagicMock(returncode=1),
                MagicMock(returncode=0),
            ]
            self.assertTrue(git_commit(self.file, "Add results: 2026-09-18"))
        run.assert_called_with(
            [
                *self.git,
                "commit",
                "--only",
                "-m",
                "Add results: 2026-09-18",
                "--",
                self.file.name,
            ],
            check=True,
        )

    def test_diff_error_is_not_treated_as_a_change(self):
        with patch("git_utils.subprocess.run") as run:
            run.side_effect = [MagicMock(returncode=0), MagicMock(returncode=128)]
            with self.assertRaises(subprocess.CalledProcessError) as caught:
                git_commit(self.file, "message")
        self.assertEqual(caught.exception.returncode, 128)
        self.assertEqual(caught.exception.cmd, self.diff)
        self.assertEqual(run.call_count, 2)

    def test_add_failure_propagates_without_attempting_commit(self):
        error = subprocess.CalledProcessError(128, ["git", "add"])
        with patch("git_utils.subprocess.run", side_effect=error) as run:
            with self.assertRaises(subprocess.CalledProcessError):
                git_commit(self.file, "message")
        run.assert_called_once()

    def test_commit_failure_propagates(self):
        error = subprocess.CalledProcessError(1, ["git", "commit"])
        with patch("git_utils.subprocess.run") as run:
            run.side_effect = [MagicMock(returncode=0), MagicMock(returncode=1), error]
            with self.assertRaises(subprocess.CalledProcessError):
                git_commit(self.file, "message")


@unittest.skipUnless(shutil.which("git"), "Git is required for repository regression tests")
class TestGitCommitRepository(unittest.TestCase):
    def setUp(self):
        self.temp = self.enterContext(tempfile.TemporaryDirectory(prefix="lottery-git-test-"))
        self.repo = Path(self.temp)
        # Keep the tests independent of the caller's repository, identity and hooks.
        env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
        self.enterContext(patch.dict(os.environ, env, clear=True))
        self.git("init", "--quiet")
        self.git("config", "user.name", "Lottery archive tests")
        self.git("config", "user.email", "lottery-tests@example.invalid")
        self.git("config", "core.hooksPath", str(self.repo / "disabled-hooks"))
        self.results = self.repo / "results.csv"
        self.unrelated = self.repo / "notes.txt"
        self.results.write_text("original results\n", encoding="utf-8")
        self.unrelated.write_text("original notes\n", encoding="utf-8")
        self.git("add", "--", ".")
        self.git("commit", "--quiet", "-m", "Initial fixture")

    def git(self, *args):
        return subprocess.run(
            ["git", "-C", str(self.repo), *args],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def stage_unrelated_change(self):
        self.unrelated.write_text("staged notes\n", encoding="utf-8")
        self.git("add", "--", self.unrelated.name)

    def test_unrelated_staged_file_is_preserved_but_not_committed(self):
        self.stage_unrelated_change()
        self.results.write_text("new results\n", encoding="utf-8")
        self.assertTrue(git_commit(self.results, "Update lottery results"))
        self.assertEqual(self.git("show", "--format=", "--name-only", "HEAD"), "results.csv")
        self.assertEqual(self.git("show", "HEAD:notes.txt"), "original notes")
        self.assertEqual(self.git("diff", "--cached", "--name-only"), "notes.txt")
        self.assertEqual(self.git("show", ":notes.txt"), "staged notes")
        self.assertEqual(self.git("diff", "--name-only"), "")

    def test_unchanged_target_does_not_commit_unrelated_staged_file(self):
        previous_head = self.git("rev-parse", "HEAD")
        self.stage_unrelated_change()
        self.assertFalse(git_commit(self.results, "Should not create a commit"))
        self.assertEqual(self.git("rev-parse", "HEAD"), previous_head)
        self.assertEqual(self.git("diff", "--cached", "--name-only"), "notes.txt")

    def test_untracked_literal_path_with_option_and_glob_characters(self):
        self.stage_unrelated_change()
        target = self.repo / "--results [1]*.csv"
        target.write_text("new results\n", encoding="utf-8")
        self.assertTrue(git_commit(target, "Add a literal filename"))
        self.assertEqual(self.git("show", "--format=", "--name-only", "HEAD"), target.name)
        self.assertEqual(self.git("show", f"HEAD:{target.name}"), "new results")
        self.assertEqual(self.git("diff", "--cached", "--name-only"), "notes.txt")

    def test_subdirectory_target_works_outside_repository(self):
        target = self.repo / "eu" / "eurojackpot" / "results.csv"
        target.parent.mkdir(parents=True)
        target.write_text("new results\n", encoding="utf-8")
        self.stage_unrelated_change()
        self.assertTrue(git_commit(target, "Add Eurojackpot"))
        self.assertEqual(
            self.git("show", "--format=", "--name-only", "HEAD"),
            "eu/eurojackpot/results.csv",
        )
        self.assertEqual(self.git("diff", "--cached", "--name-only"), "notes.txt")


if __name__ == "__main__":
    unittest.main()
