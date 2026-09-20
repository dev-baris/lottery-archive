"""Four-game updates, explicit commits, CLI validation and failure propagation."""

import contextlib
import io
import runpy
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import update_all
from update_all import main, update_country


ALIASES = ("fetch_at", "fetch_de", "fetch_eu", "fetch_ej")
MODULE_NAMES = (
    "fetch_lotto_at_6aus45",
    "fetch_lotto_de_6aus49",
    "fetch_euromillions",
    "fetch_eurojackpot",
)


def draw(date="2026-09-18"):
    return SimpleNamespace(date=date)


class TestUpdateCountry(unittest.TestCase):
    def setUp(self):
        self.commit = self.enterContext(patch("update_all.git_commit", return_value=True))
        self.stdout = self.enterContext(contextlib.redirect_stdout(io.StringIO()))

    def test_empty_draws_do_not_commit_even_with_flag(self):
        self.assertEqual(update_country("AT", "Lotto 6 aus 45", "/f.csv", [], commit=True), 0)
        self.commit.assert_not_called()

    def test_no_new_draws_can_retry_committing_an_existing_file(self):
        with tempfile.TemporaryDirectory(prefix="lottery-commit-retry-") as temp:
            path = Path(temp) / "results.csv"
            path.write_text("previously written results\n", encoding="utf-8")
            self.assertEqual(update_country("EJ", "Eurojackpot", str(path), [], commit=True), 0)
            self.commit.assert_called_once_with(str(path), "Update EJ Eurojackpot results")
        self.assertIn("Committed pending results file changes", self.stdout.getvalue())

    def test_no_new_draws_and_unchanged_existing_file_is_success(self):
        self.commit.return_value = False
        with tempfile.TemporaryDirectory(prefix="lottery-commit-retry-") as temp:
            path = Path(temp) / "results.csv"
            path.write_text("existing results\n", encoding="utf-8")
            self.assertEqual(update_country("EJ", "Eurojackpot", str(path), [], commit=True), 0)
            self.commit.assert_called_once()

    def test_default_reports_written_draws_without_git(self):
        self.assertEqual(update_country("EJ", "Eurojackpot", "/f.csv", [draw()]), 1)
        self.commit.assert_not_called()
        self.assertIn("Wrote 1 new draw", self.stdout.getvalue())

    def test_explicit_commit_includes_game_and_dates(self):
        draws = [draw("2026-09-15"), draw("2026-09-18")]
        self.assertEqual(update_country("EJ", "Eurojackpot", "/f.csv", draws, commit=True), 2)
        self.commit.assert_called_once_with(
            "/f.csv", "Add EJ Eurojackpot results: 2026-09-15, 2026-09-18"
        )

    def test_unchanged_file_still_returns_written_draw_count(self):
        self.commit.return_value = False
        self.assertEqual(update_country("AT", "Lotto 6 aus 45", "/f.csv", [draw()], commit=True), 1)
        self.assertIn("nothing to commit", self.stdout.getvalue())

    def test_commit_error_propagates(self):
        self.commit.side_effect = RuntimeError("Git failed")
        with self.assertRaisesRegex(RuntimeError, "Git failed"):
            update_country("AT", "Lotto 6 aus 45", "/f.csv", [draw()], commit=True)


class TestMain(unittest.TestCase):
    def setUp(self):
        self.modules = {}
        for alias in ALIASES:
            collector = MagicMock()
            collector.fetch_new_draws.return_value = []
            collector.RESULTS_CSV = Path("/example") / alias / "results.csv"
            self.modules[alias] = collector
            self.enterContext(patch.object(update_all, alias, collector))
        self.commit = self.enterContext(patch("update_all.git_commit", return_value=True))
        self.stdout = self.enterContext(contextlib.redirect_stdout(io.StringIO()))
        self.stderr = self.enterContext(contextlib.redirect_stderr(io.StringIO()))

    def test_returns_combined_count_including_eurojackpot(self):
        self.modules["fetch_at"].fetch_new_draws.return_value = [draw()]
        self.modules["fetch_de"].fetch_new_draws.return_value = [draw(), draw()]
        self.modules["fetch_eu"].fetch_new_draws.return_value = [draw()]
        self.modules["fetch_ej"].fetch_new_draws.return_value = [draw()]
        self.assertEqual(main([]), 5)
        self.commit.assert_not_called()

    def test_no_new_draws_writes_nothing_and_returns_zero(self):
        self.assertEqual(main([]), 0)
        for collector in self.modules.values():
            collector.fetch_new_draws.assert_called_once_with(init=False)
            collector.write_draws.assert_not_called()
        self.commit.assert_not_called()
        self.assertIn("No new draws in any archive", self.stdout.getvalue())

    def test_only_games_with_new_draws_are_written(self):
        draws = [draw()]
        self.modules["fetch_ej"].fetch_new_draws.return_value = draws
        self.assertEqual(main([]), 1)
        self.modules["fetch_ej"].write_draws.assert_called_once_with(draws)
        for alias in ALIASES[:3]:
            self.modules[alias].write_draws.assert_not_called()

    def test_init_is_forwarded_to_all_four_collectors(self):
        self.assertEqual(main(["--init"]), 0)
        for collector in self.modules.values():
            collector.fetch_new_draws.assert_called_once_with(init=True)

    def test_commit_is_opt_in_for_every_updated_game(self):
        for collector in self.modules.values():
            collector.fetch_new_draws.return_value = [draw()]
        self.assertEqual(main(["--commit"]), 4)
        self.assertEqual(self.commit.call_count, 4)
        paths = [item.args[0] for item in self.commit.call_args_list]
        self.assertEqual(paths, [str(collector.RESULTS_CSV) for collector in self.modules.values()])
        self.assertIn("EJ Eurojackpot", self.commit.call_args_list[-1].args[1])

    def test_each_fetch_failure_causes_failure_but_all_games_are_attempted(self):
        for failed_alias in ALIASES:
            with self.subTest(failed_alias=failed_alias):
                for alias, collector in self.modules.items():
                    collector.reset_mock(side_effect=True)
                    collector.fetch_new_draws.return_value = [draw()]
                    if alias == failed_alias:
                        collector.fetch_new_draws.side_effect = RuntimeError("source unavailable")
                self.assertEqual(main([]), -1)
                for alias, collector in self.modules.items():
                    collector.fetch_new_draws.assert_called_once()
                    if alias == failed_alias:
                        collector.write_draws.assert_not_called()
                    else:
                        collector.write_draws.assert_called_once()
        self.assertIn("Update incomplete", self.stderr.getvalue())

    def test_write_failure_does_not_prevent_later_updates(self):
        for collector in self.modules.values():
            collector.fetch_new_draws.return_value = [draw()]
        self.modules["fetch_de"].write_draws.side_effect = OSError("disk full")
        self.assertEqual(main([]), -1)
        for collector in self.modules.values():
            collector.fetch_new_draws.assert_called_once()
        self.modules["fetch_ej"].write_draws.assert_called_once()
        self.assertIn("DE update failed: disk full", self.stderr.getvalue())

    def test_commit_failure_does_not_prevent_later_updates(self):
        for collector in self.modules.values():
            collector.fetch_new_draws.return_value = [draw()]
        self.commit.side_effect = [RuntimeError("Git identity missing"), True, True, True]
        self.assertEqual(main(["--commit"]), -1)
        self.assertEqual(self.commit.call_count, 4)
        self.modules["fetch_ej"].write_draws.assert_called_once()
        self.assertIn("AT update failed: Git identity missing", self.stderr.getvalue())

    def test_unknown_option_fails_before_any_fetch(self):
        with self.assertRaises(SystemExit) as caught:
            main(["--inti"])
        self.assertEqual(caught.exception.code, 2)
        for collector in self.modules.values():
            collector.fetch_new_draws.assert_not_called()

    def test_help_exits_before_any_fetch(self):
        with self.assertRaises(SystemExit) as caught:
            main(["--help"])
        self.assertEqual(caught.exception.code, 0)
        self.assertIn("--commit", self.stdout.getvalue())
        for collector in self.modules.values():
            collector.fetch_new_draws.assert_not_called()

    def test_no_arguments_uses_cli_argv(self):
        with patch.object(sys, "argv", ["update_all.py", "--init"]):
            self.assertEqual(main(), 0)
        for collector in self.modules.values():
            collector.fetch_new_draws.assert_called_once_with(init=True)

    def test_extracted_project_can_write_without_git_repository(self):
        with tempfile.TemporaryDirectory(prefix="lottery-update-test-") as temp:
            for alias, collector in self.modules.items():
                path = Path(temp) / f"{alias}.csv"
                collector.RESULTS_CSV = path
                collector.fetch_new_draws.return_value = [draw()]
                collector.write_draws.side_effect = lambda draws, path=path: path.write_text(
                    "date\n" + "\n".join(item.date for item in draws) + "\n", encoding="utf-8"
                )
            self.assertEqual(main([]), 4)
            self.assertFalse((Path(temp) / ".git").exists())
            for collector in self.modules.values():
                self.assertEqual(collector.RESULTS_CSV.read_text(encoding="utf-8"), "date\n2026-09-18\n")
        self.commit.assert_not_called()

    def test_retry_after_commit_failure_commits_previously_written_csv(self):
        with tempfile.TemporaryDirectory(prefix="lottery-commit-retry-") as temp:
            collector = self.modules["fetch_ej"]
            collector.RESULTS_CSV = Path(temp) / "results.csv"
            collector.fetch_new_draws.return_value = [draw()]
            collector.write_draws.side_effect = lambda draws: collector.RESULTS_CSV.write_text(
                "date\n" + "\n".join(item.date for item in draws) + "\n", encoding="utf-8"
            )
            self.commit.side_effect = RuntimeError("Git temporarily failed")
            self.assertEqual(main(["--commit"]), -1)
            self.assertTrue(collector.RESULTS_CSV.is_file())
            collector.fetch_new_draws.return_value = []
            self.commit.reset_mock(side_effect=True)
            self.commit.return_value = True
            self.assertEqual(main(["--commit"]), 0)
            self.commit.assert_called_once_with(
                str(collector.RESULTS_CSV), "Update EJ Eurojackpot results"
            )
            collector.write_draws.assert_called_once()

    def test_script_exits_nonzero_after_partial_failure(self):
        self.modules["fetch_at"].fetch_new_draws.side_effect = RuntimeError("offline")
        module_map = dict(zip(MODULE_NAMES, self.modules.values()))
        with patch.dict(sys.modules, module_map), patch.object(sys, "argv", ["update_all.py"]):
            with self.assertRaises(SystemExit) as caught:
                runpy.run_path(str(Path(update_all.__file__)), run_name="__main__")
        self.assertEqual(caught.exception.code, 1)
        for collector in self.modules.values():
            collector.fetch_new_draws.assert_called_once()

    def test_script_exits_zero_when_updates_succeed(self):
        self.modules["fetch_ej"].fetch_new_draws.return_value = [draw()]
        module_map = dict(zip(MODULE_NAMES, self.modules.values()))
        with patch.dict(sys.modules, module_map), patch.object(sys, "argv", ["update_all.py"]):
            with self.assertRaises(SystemExit) as caught:
                runpy.run_path(str(Path(update_all.__file__)), run_name="__main__")
        self.assertEqual(caught.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
