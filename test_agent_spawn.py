import argparse
import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import agent_spawn
from agent_directory import SSH_CONFIG_ENV, SSH_HOSTS_FILE_ENV, parse_agent_payload
from agent_labels import ALIASES, LEGACY_SOURCE, SOURCE, candidates
from agent_route import resolve_agent_route


class FakeHerdr:
    """Small stateful Herdr: starts occupy panes and closing removes them."""

    def __init__(self):
        self.agents = []
        self.commands = []
        self.transports = []
        self.starts = []
        self.start_errors = {}
        self.start_error = ""
        self.create_error = ""
        self.close_error = ""
        self.metadata_error = False
        self.rename_error = False
        self.banner = ""
        self.workspace_label = "project"
        self.created = {}
        self.metadata = {}
        self.cwd = "/work"
        self.workspace_id = "w-new"
        self.tab_id = "tab-new"
        self.pane_id = "pane-new"
        self.terminal_id = "terminal-new"

    def __call__(self, command, **kwargs):
        self.transports.append(list(command))
        if command[0] == "ssh":
            script = shlex.split(command[-1])[2]
            arguments = shlex.split(script.partition('exec "$herdr_bin" ')[2])
        else:
            arguments = command[1:]
        self.commands.append(list(arguments))
        operation = tuple(arguments[:2])

        def response(payload, returncode=0, stderr=""):
            return subprocess.CompletedProcess(
                command, returncode, self.banner + json.dumps(payload), stderr,
            )

        if operation == ("agent", "list"):
            return response({"result": {
                "agents": self.agents,
                "workspaces": [{"workspace_id": self.workspace_id, "label": self.workspace_label}],
            }})
        if operation == ("pane", "get"):
            return response({"result": {"pane": {
                "pane_id": arguments[2], "workspace_id": "w-source",
            }}})
        if operation in (("pane", "split"), ("tab", "create"), ("workspace", "create")):
            if self.create_error:
                return response({}, 1, self.create_error)
            self.cwd = arguments[arguments.index("--cwd") + 1]
            if "--workspace" in arguments:
                self.workspace_id = arguments[arguments.index("--workspace") + 1]
            if "--label" in arguments:
                self.workspace_label = arguments[arguments.index("--label") + 1]
            entity = operation[0]
            self.created[entity] = self.pane_id
            pane = {
                "pane_id": self.pane_id, "terminal_id": self.terminal_id,
                "workspace_id": self.workspace_id, "tab_id": self.tab_id,
            }
            return response({"result": {
                "pane" if entity == "pane" else "root_pane": pane,
                "workspace_id": self.workspace_id, "tab_id": self.tab_id,
            }})
        if operation == ("agent", "start"):
            label = arguments[2]
            self.starts.append(label)
            error = self.start_errors.get(label, self.start_error)
            if error:
                return response({"error": {"code": error}}, 1, error)
            if any(agent.get("name") == label or agent.get("agent_name") == label for agent in self.agents):
                return response({}, 1, "agent_name_taken")
            self.agents.append({
                "name": label, "pane_id": self.pane_id,
                "terminal_id": self.terminal_id, "workspace_id": self.workspace_id,
                "agent": arguments[arguments.index("--kind") + 1], "agent_status": "idle",
                "agent_session": {"value": "session-new"}, "cwd": self.cwd,
            })
            return response({"result": {"ready": True}})
        if operation == ("pane", "report-metadata"):
            if self.metadata_error:
                return response({}, 1, "metadata unavailable")
            if "--display-agent" in arguments:
                self.metadata[arguments[2]] = {
                    "source": arguments[arguments.index("--source") + 1],
                    "display_agent": arguments[arguments.index("--display-agent") + 1],
                    "tokens": [arguments[index + 1] for index, value in enumerate(arguments) if value == "--token"],
                }
            return response({"result": {}})
        if operation[1] == "rename":
            if self.rename_error:
                return response({}, 1, "rename unavailable")
            self.workspace_label = arguments[3]
            return response({"result": {}})
        if operation[1] == "close":
            if self.close_error:
                return response({}, 1, self.close_error)
            self.created.pop(operation[0], None)
            self.agents = [agent for agent in self.agents if agent.get("pane_id") != self.pane_id]
            return response({"result": {}})
        raise AssertionError(f"Unexpected Herdr command: {arguments!r}")


class AgentSpawnTest(unittest.TestCase):
    def arguments(self, *options):
        parser = argparse.ArgumentParser()
        agent_spawn.add_spawn_parser(parser.add_subparsers(dest="command", required=True))
        return parser.parse_args(["spawn", "--kind", "codex", *options])

    def spawn(self, backend, *options, environment=None):
        return agent_spawn.spawn_command(
            self.arguments(*options),
            {"HERDR_PANE_ID": "pane-source"} if environment is None else environment,
            command_runner=backend,
        )

    def test_auto_label_skips_both_registered_name_fields(self):
        backend = FakeHerdr()
        first, second, third = list(candidates(f"{backend.terminal_id}:"))[:3]
        backend.agents.append({
            "name": first.name, "agent_name": second.name, "pane_id": "pane-existing",
            "agent": "omp", "agent_session": {"value": "session-existing"},
        })
        result = self.spawn(backend)
        self.assertEqual(result["address"], f"local/{third.name}")
        self.assertEqual(backend.starts, [third.name])
        self.assertEqual(len(backend.agents), 2)
        self.assertEqual(backend.agents[0]["name"], first.name)
        self.assertNotIn("label_metadata_reported", result)
        self.assertEqual(backend.metadata[backend.pane_id], {
            "source": SOURCE,
            "display_agent": f"{third.marker} {third.name}",
            "tokens": [f"alias={third.name}", f"color={third.color}"],
        })
        self.assertTrue(any(
            "--clear-display-agent" in command and LEGACY_SOURCE in command
            for command in backend.commands
        ))

    def test_name_taken_retries_the_next_candidate_in_the_same_pane(self):
        backend = FakeHerdr()
        first, second = list(candidates(f"{backend.terminal_id}:"))[:2]
        backend.start_errors[first.name] = "agent_name_taken"
        result = self.spawn(backend)
        self.assertEqual(backend.starts, [first.name, second.name])
        self.assertEqual(result["address"], f"local/{second.name}")
        self.assertEqual(len(backend.created), 1)
        self.assertEqual(len(backend.agents), 1)
        self.assertEqual(result["pane_id"], backend.pane_id)

    def test_custom_label_is_verbatim_and_skips_palette_metadata(self):
        backend = FakeHerdr()
        result = self.spawn(backend, "--label", "Review Worker")
        self.assertEqual(result["address"], "local/Review Worker")
        self.assertEqual(result["marker"], "")
        self.assertFalse(result["label_metadata_reported"])
        self.assertEqual(backend.metadata, {})
        self.assertFalse(any(command[:2] == ["pane", "report-metadata"] for command in backend.commands))

    def test_explicit_palette_label_receives_metadata(self):
        backend = FakeHerdr()
        alias = ALIASES[0]
        result = self.spawn(backend, "--label", alias.name)
        self.assertNotIn("label_metadata_reported", result)
        self.assertEqual(result["marker"], alias.marker)

    def test_verbose_returns_the_legacy_payload_and_observed_route(self):
        backend = FakeHerdr()
        backend.banner = "Welcome to the remote shell\n"
        result = self.spawn(backend, "--verbose", "--cwd", "/work/actual")
        self.assertEqual(result["address"], f"local/{result['label']}")
        self.assertEqual(result["pane_id"], backend.pane_id)
        self.assertEqual(result["workspace_id"], backend.workspace_id)
        self.assertEqual(result["tab_id"], backend.tab_id)
        self.assertEqual(result["cwd"], "/work/actual")
        self.assertEqual(result["created"], "pane")
        observed = parse_agent_payload({"result": {"agents": backend.agents}}, host="local", local=True)
        resolved = resolve_agent_route(result["route"], observed).agent
        self.assertEqual(resolved.session_id, "session-new")
        self.assertEqual(resolved.name, result["label"])
        self.assertEqual(result["agent"]["address"], result["address"])
        self.assertEqual(set(result), {
            "address", "label", "marker", "color", "host", "created", "pane_id",
            "tab_id", "workspace_id", "kind", "cwd", "label_metadata_reported",
            "placement_label_reported", "agent", "route",
        })

    def test_default_returns_only_compact_placement_fields(self):
        backend = FakeHerdr()
        result = self.spawn(backend)
        alias = next(alias for alias in ALIASES if alias.name == backend.starts[0])
        self.assertEqual(result, {
            "address": f"local/{alias.name}",
            "marker": alias.marker,
            "created": "pane",
            "pane_id": backend.pane_id,
            "tab_id": backend.tab_id,
            "workspace_id": backend.workspace_id,
        })

    def test_default_omits_unavailable_tab_id(self):
        backend = FakeHerdr()
        backend.tab_id = ""
        result = self.spawn(backend)
        self.assertEqual(set(result), {
            "address", "marker", "created", "pane_id", "workspace_id",
        })

    def test_start_failure_cleans_up_each_placement(self):
        for placement in ("split", "tab", "workspace"):
            with self.subTest(placement=placement):
                backend = FakeHerdr()
                backend.start_error = "unsupported agent"
                with self.assertRaises(agent_spawn.SpawnError) as raised:
                    self.spawn(backend, "--placement", placement)
                self.assertEqual(raised.exception.code, "agent_start_failed")
                self.assertIn("cleanup", raised.exception.message)
                self.assertEqual(backend.created, {})
                self.assertEqual(backend.agents, [])

    def test_cleanup_failure_preserves_start_error(self):
        backend = FakeHerdr()
        backend.start_error = "agent exited"
        backend.close_error = "permission denied"
        with self.assertRaises(agent_spawn.SpawnError) as raised:
            self.spawn(backend)
        self.assertEqual(raised.exception.code, "agent_start_failed")
        self.assertIn("permission denied", raised.exception.message)
        self.assertIn("cleanup", raised.exception.message)

    def test_custom_name_taken_is_not_retried(self):
        backend = FakeHerdr()
        backend.start_error = "agent_name_taken"
        with self.assertRaises(agent_spawn.SpawnError) as raised:
            self.spawn(backend, "--label", "custom-worker")
        self.assertEqual(raised.exception.code, "agent_start_failed")
        self.assertEqual(backend.starts, ["custom-worker"])
        self.assertEqual(backend.created, {})

    def test_no_available_label_closes_created_pane(self):
        backend = FakeHerdr()
        backend.agents = [
            {"name": alias.name, "agent": "omp", "pane_id": f"existing-{index}"}
            for index, alias in enumerate(ALIASES)
        ]
        with self.assertRaises(agent_spawn.SpawnError) as raised:
            self.spawn(backend)
        self.assertEqual(raised.exception.code, "label_unavailable")
        self.assertEqual(backend.starts, [])
        self.assertEqual(backend.created, {})
        self.assertEqual(len(backend.agents), len(ALIASES))

    def test_remote_split_requires_explicit_from_pane(self):
        backend = FakeHerdr()
        with self.assertRaises(agent_spawn.SpawnError) as raised:
            self.spawn(backend, "--host", "remote", "--cwd", "/remote/work")
        self.assertEqual(raised.exception.code, "sender_pane_unavailable")
        self.assertEqual(backend.commands, [])

    def test_local_split_requires_sender_pane_only_when_not_explicit(self):
        backend = FakeHerdr()
        with self.assertRaises(agent_spawn.SpawnError) as raised:
            self.spawn(backend, environment={})
        self.assertEqual(raised.exception.code, "sender_pane_unavailable")
        result = self.spawn(backend, "--from-pane", "chosen-pane", environment={})
        self.assertEqual(result["created"], "pane")
        split = next(command for command in backend.commands if command[:2] == ["pane", "split"])
        self.assertEqual(split[split.index("--pane") + 1], "chosen-pane")

    def test_tab_and_workspace_do_not_require_sender_environment(self):
        for placement in ("tab", "workspace"):
            with self.subTest(placement=placement):
                backend = FakeHerdr()
                result = self.spawn(backend, "--placement", placement, environment={})
                self.assertEqual(result["created"], placement)
                self.assertEqual(backend.workspace_label, result["address"].split("/", 1)[1])
                self.assertNotIn("placement_label_reported", result)

    def test_tab_inherits_explicit_source_workspace(self):
        backend = FakeHerdr()
        result = self.spawn(backend, "--placement", "tab", "--from-pane", "other-pane")
        self.assertEqual(result["workspace_id"], "w-source")

    def test_tab_explicit_workspace_overrides_source_workspace(self):
        backend = FakeHerdr()
        result = self.spawn(backend, "--placement", "tab", "--workspace", "w-chosen")
        self.assertEqual(result["workspace_id"], "w-chosen")
        self.assertFalse(any(command[:2] == ["pane", "get"] for command in backend.commands))

    def test_workspace_label_is_independent_of_agent_label(self):
        backend = FakeHerdr()
        result = self.spawn(backend, "--placement", "workspace", "--workspace-label", "Review room")
        self.assertEqual(backend.workspace_label, "Review room")
        self.assertNotEqual(result["address"], "local/Review room")
        self.assertNotIn("placement_label_reported", result)

    def test_noncritical_reporting_failures_keep_the_agent_running(self):
        backend = FakeHerdr()
        backend.metadata_error = True
        backend.rename_error = True
        result = self.spawn(backend, "--placement", "workspace")
        self.assertFalse(result["label_metadata_reported"])
        self.assertFalse(result["placement_label_reported"])
        self.assertEqual(len(backend.agents), 1)
        self.assertIn("workspace", backend.created)

    def test_remote_commands_metadata_and_discovery_use_ssh(self):
        backend = FakeHerdr()
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config"
            config.write_text("Host test-remote\n  HostName example.invalid\n", encoding="utf-8")
            result = self.spawn(
                backend, "--host", "test-remote", "--cwd", "/remote/project",
                "--from-pane", "remote-pane", "--verbose",
                environment={
                    SSH_CONFIG_ENV: str(config),
                    SSH_HOSTS_FILE_ENV: str(Path(directory) / "ssh-hosts"),
                },
            )
        self.assertTrue(all(command[0] == "ssh" for command in backend.transports))
        self.assertTrue(result["label_metadata_reported"])
        self.assertEqual(result["address"], f"test-remote/{result['label']}")
        observed = parse_agent_payload({"result": {"agents": backend.agents}}, host="test-remote", local=False)
        self.assertEqual(resolve_agent_route(result["route"], observed).agent.host, "test-remote")

    def test_remote_cwd_is_required_before_any_commands(self):
        backend = FakeHerdr()
        with self.assertRaises(agent_spawn.SpawnError) as raised:
            self.spawn(backend, "--host", "remote", "--placement", "workspace")
        self.assertEqual(raised.exception.code, "cwd_required")
        self.assertEqual(backend.commands, [])

    def test_remote_host_must_be_a_concrete_configured_alias(self):
        backend = FakeHerdr()
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config"
            config.write_text("Host wildcard-*\n  HostName example.invalid\n", encoding="utf-8")
            with self.assertRaises(agent_spawn.SpawnError) as raised:
                self.spawn(
                    backend, "--host", "wildcard-worker", "--placement", "workspace",
                    "--cwd", "/remote/work", environment={
                        SSH_CONFIG_ENV: str(config),
                        SSH_HOSTS_FILE_ENV: str(Path(directory) / "ssh-hosts"),
                    },
                )
        self.assertEqual(raised.exception.code, "host_not_configured")
        self.assertEqual(backend.commands, [])

    def test_timeout_boundaries(self):
        for timeout in ("0", "-1", "300001"):
            with self.subTest(timeout=timeout):
                backend = FakeHerdr()
                with self.assertRaises(agent_spawn.SpawnError) as raised:
                    self.spawn(backend, "--timeout", timeout)
                self.assertEqual(raised.exception.code, "invalid_timeout")
                self.assertEqual(backend.commands, [])
        for timeout in ("1", "300000"):
            with self.subTest(timeout=timeout):
                backend = FakeHerdr()
                self.spawn(backend, "--timeout", timeout)
                start = next(command for command in backend.commands if command[:2] == ["agent", "start"])
                self.assertEqual(start[start.index("--timeout") + 1], timeout)

    def test_labels_reject_empty_and_address_separator(self):
        for label in ("", "   ", "remote/worker"):
            with self.subTest(label=label):
                backend = FakeHerdr()
                with self.assertRaises(agent_spawn.SpawnError) as raised:
                    self.spawn(backend, "--label", label)
                self.assertEqual(raised.exception.code, "invalid_label")
                self.assertEqual(backend.commands, [])

    def test_unknown_kind_is_left_to_herdr_and_maps_to_start_failure(self):
        backend = FakeHerdr()
        backend.start_error = "invalid value for --kind"
        arguments = self.arguments()
        arguments.kind = "new-herdr-kind"
        with self.assertRaises(agent_spawn.SpawnError) as raised:
            agent_spawn.spawn_command(arguments, {"HERDR_PANE_ID": "source"}, command_runner=backend)
        self.assertEqual(raised.exception.code, "agent_start_failed")
        self.assertEqual(backend.created, {})

    def test_placement_failure_does_not_start_agent(self):
        backend = FakeHerdr()
        backend.create_error = "pane unavailable"
        with self.assertRaises(agent_spawn.SpawnError) as raised:
            self.spawn(backend)
        self.assertEqual(raised.exception.code, "placement_failed")
        self.assertEqual(backend.starts, [])

    def test_agent_arguments_after_separator_are_forwarded_verbatim(self):
        backend = FakeHerdr()
        self.spawn(backend, "--", "--model", "model name", "--kind", "not-a-spawn-option")
        start = next(command for command in backend.commands if command[:2] == ["agent", "start"])
        self.assertEqual(start[start.index("--") + 1:], [
            "--model", "model name", "--kind", "not-a-spawn-option",
        ])

    def test_local_cwd_defaults_to_current_directory(self):
        backend = FakeHerdr()
        self.spawn(backend)
        split = next(command for command in backend.commands if command[:2] == ["pane", "split"])
        self.assertEqual(split[split.index("--cwd") + 1], os.getcwd())

    def test_import_does_not_import_cli(self):
        result = subprocess.run(
            [sys.executable, "-c", "import sys; import agent_spawn; assert 'agent_skill_cli' not in sys.modules"],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
