"""Ensure patched ci-cost does not load a user's npm configuration on Windows.

This fixture only inspects sandbox paths; it never installs npm packages or
reads research credentials.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from evaluation.optimizers.ci_cost import _environment
from evaluation.third_party.ci_cost.setup import (
    _run, _safe_tool_environment, isolate_npm_config,
)


class CiCostNpmConfigTests(unittest.TestCase):
    def test_npm_settings_are_distinct_absolute_empty_files(self):
        for base_env in (_safe_tool_environment(), _environment()):
            with self.subTest(base_env=base_env.get("CI")):
                with tempfile.TemporaryDirectory() as scratch:
                    env = isolate_npm_config(base_env, Path(scratch))
                    user = Path(env["NPM_CONFIG_USERCONFIG"])
                    global_file = Path(env["NPM_CONFIG_GLOBALCONFIG"])
                    self.assertNotEqual(user, global_file)
                    self.assertTrue(user.is_absolute())
                    self.assertTrue(global_file.is_absolute())
                    self.assertEqual(user.read_bytes(), b"")
                    self.assertEqual(global_file.read_bytes(), b"")
                    self.assertTrue(user.is_relative_to(scratch))
                    self.assertTrue(global_file.is_relative_to(scratch))

    def test_inherited_npm_config_and_secrets_are_not_passed_to_tool(self):
        with patch.dict(os.environ, {
            "GITHUB_TOKEN": "hidden-secret",
            "OPENROUTER_API_KEY": "hidden-key",
            "NPM_CONFIG__AUTH": "hidden-npm-auth",
            "NPM_CONFIG_USERCONFIG": "unsafe-user.npmrc",
            "NPM_CONFIG_GLOBALCONFIG": "unsafe-global.npmrc",
        }):
            for env in (_safe_tool_environment(), _environment()):
                self.assertNotIn("GITHUB_TOKEN", env)
                self.assertNotIn("OPENROUTER_API_KEY", env)
                self.assertNotIn("NPM_CONFIG__AUTH", env)
                self.assertNotIn("NPM_CONFIG_USERCONFIG", env)
                self.assertNotIn("NPM_CONFIG_GLOBALCONFIG", env)

    def test_subprocess_config_files_lifetime_and_cleanup(self):
        seen = []

        def fake_run(command, **options):
            env = options["env"]
            files = [Path(env[k]) for k in ("NPM_CONFIG_USERCONFIG", "NPM_CONFIG_GLOBALCONFIG")]
            self.assertNotEqual(files[0], files[1])
            self.assertTrue(all(x.exists() and x.read_bytes() == b"" for x in files))
            seen.extend(files)
            class Completed:
                returncode = 0
                stdout = "ok\n"
                stderr = ""
            return Completed()

        with patch("evaluation.third_party.ci_cost.setup.subprocess.run", side_effect=fake_run):
            self.assertEqual(_run(["npm", "ci"]), "ok")
        self.assertTrue(all(not path.exists() for path in seen))


if __name__ == "__main__":
    unittest.main()
