import contextlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import plugin_rollout


EXACT_REF = "1" * 40


def target_snapshot() -> plugin_rollout.TargetSnapshot:
    return plugin_rollout.TargetSnapshot(
        EXACT_REF,
        "0.7.0",
        {
            "agent_labels.py": plugin_rollout.FileFingerprint("file", "a" * 64),
            "herdr-plugin.toml": plugin_rollout.FileFingerprint("file", "b" * 64),
        },
    )


def plugin_list_payload() -> str:
    return json.dumps(
        {
            "result": {
                "plugins": [
                    {
                        "plugin_id": plugin_rollout.PLUGIN_ID,
                        "enabled": True,
                        "version": "0.7.0",
                        "plugin_root": "/managed/plugin",
                        "source": {
                            "kind": "github",
                            "owner": "zerodice0",
                            "repo": "herdr-agent-labels",
                            "requested_ref": EXACT_REF,
                            "resolved_commit": EXACT_REF,
                            "managed_path": "/managed/plugin",
                        },
                    }
                ]
            }
        }
    )


def action_list_payload() -> str:
    return json.dumps(
        {
            "result": {
                "actions": [
                    {"action_id": action_id}
                    for action_id in sorted(plugin_rollout.CORE_ACTION_IDS)
                ]
            }
        }
    )


class FakeRemoteRunner:
    def __init__(self, *, failing_host: str | None = None, bad_hashes: bool = False):
        self.failing_host = failing_host
        self.bad_hashes = bad_hashes
        self.calls: list[tuple[list[str], float]] = []

    def __call__(
        self,
        command: list[str] | tuple[str, ...],
        timeout: float,
    ) -> subprocess.CompletedProcess[str]:
        argv = list(command)
        self.calls.append((argv, timeout))
        host = argv[-2]
        remote = argv[-1]
        if host == self.failing_host and "plugin install" in remote:
            return subprocess.CompletedProcess(argv, 1, "", "install refused")
        if "plugin list" in remote:
            return subprocess.CompletedProcess(argv, 0, plugin_list_payload(), "")
        if "plugin action list" in remote:
            return subprocess.CompletedProcess(argv, 0, action_list_payload(), "")
        if "hashlib.sha256" in remote:
            fingerprints = {
                path: {
                    "kind": fingerprint.kind,
                    "sha256": (
                        "0" * 64 if self.bad_hashes else fingerprint.sha256
                    ),
                }
                for path, fingerprint in target_snapshot().files.items()
            }
            return subprocess.CompletedProcess(argv, 0, json.dumps(fingerprints), "")
        return subprocess.CompletedProcess(argv, 0, "{}", "")


class PluginRolloutTest(unittest.TestCase):
    def test_selected_hosts_are_explicit_concrete_authorized_aliases(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config"
            allowlist = root / "ssh-hosts"
            config.write_text(
                "Host desktop spare\nHost *.example.com\n",
                encoding="utf-8",
            )
            allowlist.write_text("desktop\nspare\n", encoding="utf-8")
            environment = {
                "HERDR_AGENT_LABELS_SSH_CONFIG": str(config),
                "HERDR_AGENT_LABELS_SSH_HOSTS_FILE": str(allowlist),
            }

            self.assertEqual(
                plugin_rollout.resolve_selected_hosts(["desktop"], environment),
                ["desktop"],
            )
            with self.assertRaises(plugin_rollout.RolloutError):
                plugin_rollout.resolve_selected_hosts(["local"], environment)
            with self.assertRaises(plugin_rollout.RolloutError):
                plugin_rollout.resolve_selected_hosts(["unknown"], environment)

    def test_install_uses_exact_ref_and_shared_hardened_transport(self):
        command = plugin_rollout.install_command(
            "desktop",
            EXACT_REF,
            config_path=Path("/tmp/ssh-config"),
        )

        self.assertEqual(command[-2], "desktop")
        self.assertIn(f"plugin install {plugin_rollout.PLUGIN_SOURCE}", command[-1])
        self.assertIn(f"--ref {EXACT_REF} --yes", command[-1])
        self.assertIn("ClearAllForwardings=yes", command)
        self.assertIn("ForwardAgent=no", command)
        self.assertNotIn("StrictHostKeyChecking=accept-new", command)

    def test_dry_run_constructs_commands_without_calling_subprocess(self):
        runner = mock.Mock(side_effect=AssertionError("runner must not be called"))

        results = plugin_rollout.rollout_hosts(
            ["desktop"],
            "full",
            target_snapshot(),
            config_path=Path("/tmp/ssh-config"),
            dry_run=True,
            runner=runner,
        )

        runner.assert_not_called()
        self.assertEqual([result.host for result in results], ["desktop"])
        self.assertTrue(all(check.status == "planned" for check in results[0].checks))
        self.assertEqual(
            [command["step"] for command in results[0].commands],
            ["install", "metadata", "config", "reload", "actions", "hashes", "unittest"],
        )

    def test_cli_requires_explicit_confirmation_before_preflight(self):
        stdout = io.StringIO()
        with (
            contextlib.redirect_stdout(stdout),
            mock.patch.object(plugin_rollout, "resolve_selected_hosts") as resolve,
        ):
            exit_code = plugin_rollout.main(
                [
                    "--host",
                    "desktop",
                    "--ref",
                    EXACT_REF,
                    "--format",
                    "json",
                ],
                {},
            )

        self.assertEqual(exit_code, 2)
        self.assertIn("--confirm", json.loads(stdout.getvalue())["error"])
        resolve.assert_not_called()

    def test_cli_confirmation_authorizes_the_non_dry_run_path(self):
        completed = plugin_rollout.HostResult("desktop", "smoke")
        completed.add("install", "pass", "ok")
        stdout = io.StringIO()
        with (
            contextlib.redirect_stdout(stdout),
            mock.patch.object(
                plugin_rollout,
                "resolve_selected_hosts",
                return_value=["desktop"],
            ),
            mock.patch.object(
                plugin_rollout,
                "load_target_snapshot",
                return_value=target_snapshot(),
            ),
            mock.patch.object(
                plugin_rollout,
                "rollout_hosts",
                return_value=[completed],
            ) as rollout,
        ):
            exit_code = plugin_rollout.main(
                [
                    "--host",
                    "desktop",
                    "--ref",
                    EXACT_REF,
                    "--confirm",
                    "--format",
                    "json",
                ],
                {"HERDR_AGENT_LABELS_SSH_CONFIG": "/tmp/ssh-config"},
            )

        self.assertEqual(exit_code, 0)
        self.assertTrue(json.loads(stdout.getvalue())["success"])
        self.assertFalse(rollout.call_args.kwargs["dry_run"])

    def test_ref_must_be_an_immutable_full_commit_before_git_is_called(self):
        with (
            mock.patch.object(plugin_rollout, "_run_local_bytes") as run,
            self.assertRaises(plugin_rollout.RolloutError),
        ):
            plugin_rollout.load_target_snapshot("main")

        run.assert_not_called()

    def test_partial_failure_is_reported_per_host_and_does_not_stop_next_host(self):
        runner = FakeRemoteRunner(failing_host="broken")

        results = plugin_rollout.rollout_hosts(
            ["broken", "healthy"],
            "smoke",
            target_snapshot(),
            config_path=Path("/tmp/ssh-config"),
            dry_run=False,
            runner=runner,
        )

        self.assertFalse(results[0].success)
        self.assertTrue(results[1].success)
        self.assertEqual(results[0].checks[0].status, "fail")
        self.assertEqual(results[0].checks[1].status, "skipped")
        self.assertEqual(
            {call[0][-2] for call in runner.calls},
            {"broken", "healthy"},
        )

    def test_smoke_omits_hash_and_unittest_while_full_runs_both(self):
        smoke_runner = FakeRemoteRunner()
        smoke = plugin_rollout.rollout_hosts(
            ["desktop"],
            "smoke",
            target_snapshot(),
            config_path=Path("/tmp/ssh-config"),
            dry_run=False,
            runner=smoke_runner,
        )[0]
        full_runner = FakeRemoteRunner()
        full = plugin_rollout.rollout_hosts(
            ["desktop"],
            "full",
            target_snapshot(),
            config_path=Path("/tmp/ssh-config"),
            dry_run=False,
            runner=full_runner,
        )[0]

        self.assertTrue(smoke.success)
        self.assertNotIn("hashes", [check.name for check in smoke.checks])
        self.assertNotIn("unittest", [check.name for check in smoke.checks])
        self.assertTrue(full.success)
        self.assertEqual(full.checks[-2].name, "hashes")
        self.assertEqual(full.checks[-1].name, "unittest")
        self.assertIn("hashlib.sha256", full_runner.calls[-2][0][-1])
        self.assertIn("PYTHONDONTWRITEBYTECODE=1", full_runner.calls[-1][0][-1])

    def test_hash_mismatch_prevents_execution_of_plugin_tests(self):
        runner = FakeRemoteRunner(bad_hashes=True)

        result = plugin_rollout.rollout_hosts(
            ["desktop"],
            "full",
            target_snapshot(),
            config_path=Path("/tmp/ssh-config"),
            dry_run=False,
            runner=runner,
        )[0]

        self.assertFalse(result.success)
        self.assertEqual(result.checks[-2].status, "fail")
        self.assertEqual(result.checks[-1].status, "skipped")
        self.assertFalse(
            any("PYTHONDONTWRITEBYTECODE=1" in call[0][-1] for call in runner.calls)
        )


if __name__ == "__main__":
    unittest.main()
