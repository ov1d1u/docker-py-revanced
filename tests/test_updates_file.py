"""Tests for loading and persisting updates.json outside GitHub Actions."""

# ruff: noqa: PT009

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Self
from unittest import TestCase
from unittest.mock import patch

from environs import Env

from src import utils


class UpdatesFileTests(TestCase):
    """Self-hosted runs must remember the last run's versions so unchanged apps can be skipped."""

    def setUp(self: Self) -> None:
        """Run each test in an empty working directory."""
        self._tmp = TemporaryDirectory()
        self._old_cwd = Path.cwd()
        os.chdir(self._tmp.name)

    def tearDown(self: Self) -> None:
        """Restore the working directory."""
        os.chdir(self._old_cwd)
        self._tmp.cleanup()

    def test_default_path_without_github_repository_is_in_apks(self: Self) -> None:
        """Without GITHUB_REPOSITORY the file lives next to the APKs, which is the persisted folder."""
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(utils.get_updates_file_path(Env()), Path("apks") / "updates.json")

    def test_default_path_with_github_repository_is_repo_root(self: Self) -> None:
        """GitHub Actions keeps the original repo-root location the workflow publishes."""
        with patch.dict(os.environ, {"GITHUB_REPOSITORY": "owner/repo"}, clear=True):
            self.assertEqual(utils.get_updates_file_path(Env()), Path("updates.json"))

    def test_updates_file_env_overrides_path(self: Self) -> None:
        """UPDATES_FILE wins over the defaults."""
        with patch.dict(os.environ, {"UPDATES_FILE": "/data/u.json", "GITHUB_REPOSITORY": "o/r"}, clear=True):
            self.assertEqual(utils.get_updates_file_path(Env()), Path("/data/u.json"))

    def test_load_falls_back_to_local_file_without_github_repository(self: Self) -> None:
        """No GITHUB_REPOSITORY: read apks/updates.json and never hit the network."""
        previous = {"youtube": {"app_version": "1.0", "output_file_name": "youtube.apk"}}
        Path("apks").mkdir()
        Path("apks/updates.json").write_text(json.dumps(previous))
        with patch.dict(os.environ, {}, clear=True), patch("src.utils.urllib.request.urlopen") as urlopen:
            self.assertEqual(utils.load_older_updates(Env()), previous)
        urlopen.assert_not_called()

    def test_load_falls_back_to_local_file_when_fetch_fails(self: Self) -> None:
        """A failed GitHub fetch still uses the local copy."""
        previous = {"reddit": {"app_version": "2.0"}}
        Path("updates.json").write_text(json.dumps(previous))
        with (
            patch.dict(os.environ, {"GITHUB_REPOSITORY": "owner/repo"}, clear=True),
            patch("src.utils.urllib.request.urlopen", side_effect=OSError("offline")),
        ):
            self.assertEqual(utils.load_older_updates(Env()), previous)

    def test_load_returns_empty_when_no_local_file(self: Self) -> None:
        """First run: nothing remote, nothing local."""
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(utils.load_older_updates(Env()), {})

    def test_load_ignores_corrupt_local_file(self: Self) -> None:
        """A corrupt file must not crash the build; it just disables skipping for this run."""
        Path("apks").mkdir()
        Path("apks/updates.json").write_text("{not json")
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(utils.load_older_updates(Env()), {})

    def test_write_then_load_round_trips_through_apks(self: Self) -> None:
        """What one self-hosted run writes, the next run reads back."""
        updates_info = {"youtube": {"app_version": "1.0", "output_file_name": "youtube.apk"}}
        with patch.dict(os.environ, {}, clear=True):
            env = Env()
            utils.write_changelog_to_file(updates_info, env)
            self.assertTrue(Path("apks/updates.json").is_file())
            self.assertFalse(Path("updates.json").exists())
            self.assertEqual(utils.load_older_updates(env), updates_info)
