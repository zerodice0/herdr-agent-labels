import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from io import StringIO
from pathlib import Path
from unittest import mock

import agent_directory
import agent_skill_cli

SKILL_WRAPPER_PATH = Path(
    ".agents/skills/herdr-agent-messenger/scripts/herdr_agent_messenger.py"
).resolve()


def load_skill_wrapper():
    spec = importlib.util.spec_from_file_location(
        "herdr_agent_messenger_wrapper_test",
        SKILL_WRAPPER_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load the skill wrapper.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def agent(
    *,
    host: str = "local",
    name: str = "white-bison",
    pane_id: str = "w1:p1",
    local: bool = True,
) -> agent_directory.AgentRecord:
    return agent_directory.AgentRecord(
        host=host,
        name=name,
        pane_id=pane_id,
        workspace_id="w1",
        workspace_label="project",
        status="idle",
        session_id=f"session-{pane_id}",
        cwd="/work/project",
        local=local,
        revision=1,
        agent_kind="codex",
        terminal_id=f"terminal-{pane_id}",
    )


class AgentSkillCliTest(unittest.TestCase):
    def test_route_token_resolves_exact_current_occupant(self):
        recipient = agent(name="", pane_id="w7:p9")
        token = agent_skill_cli.encode_agent_route(recipient)
        with mock.patch.object(
            agent_skill_cli,
            "discover_agents",
            return_value=[recipient],
        ) as discover:
            self.assertEqual(agent_skill_cli.resolve_routed_agent(token), recipient)

        discover.assert_called_once_with("local", None)

    def test_route_token_preserves_the_ssh_alias(self):
        recipient = agent(
            host="macbook-pro",
            name="",
            pane_id="w7:p9",
            local=False,
        )
        token = agent_skill_cli.encode_agent_route(recipient)
        with mock.patch.object(
            agent_skill_cli,
            "discover_agents",
            return_value=[recipient],
        ) as discover:
            self.assertEqual(agent_skill_cli.resolve_routed_agent(token), recipient)

        discover.assert_called_once_with("macbook-pro", None)

    def test_route_token_expires_when_the_pane_occupant_changes(self):
        original = agent(name="", pane_id="w7:p9")
        replacement = replace(original, session_id="replacement-session")
        token = agent_skill_cli.encode_agent_route(original)
        with (
            mock.patch.object(
                agent_skill_cli,
                "discover_agents",
                return_value=[replacement],
            ),
            self.assertRaises(agent_skill_cli.SkillCommandError) as raised,
        ):
            agent_skill_cli.resolve_routed_agent(token)

        self.assertEqual(raised.exception.code, "route_expired")

    def test_route_token_rejects_invalid_payload(self):
        with self.assertRaises(agent_skill_cli.SkillCommandError) as raised:
            agent_skill_cli.resolve_routed_agent("not-a-route")
        self.assertEqual(raised.exception.code, "invalid_route")

    def test_display_only_label_is_listed_with_pane_routing_target(self):
        recipient = agent(
            host="macbook-pro",
            name="purple-koala",
            pane_id="w1:p4",
            local=False,
        )
        recipient = replace(recipient, route_target="w1:p4")
        with mock.patch.object(
            agent_skill_cli,
            "discover_agents",
            return_value=[recipient],
        ):
            payload = agent_skill_cli.list_command("macbook-pro")

        self.assertEqual(payload["agents"][0]["address"], "macbook-pro/purple-koala")
        self.assertEqual(payload["agents"][0]["route_target"], "w1:p4")

    def test_list_returns_only_addressable_labeled_agents(self):
        labeled = agent(name="white-bison")
        unnamed = agent(name="", pane_id="w1:p2")
        with mock.patch.object(
            agent_skill_cli,
            "discover_agents",
            return_value=[labeled, unnamed],
        ):
            payload = agent_skill_cli.list_command("local")
        self.assertEqual([item["label"] for item in payload["agents"]], ["white-bison"])
        self.assertEqual(payload["agents"][0]["address"], "local/white-bison")

    def test_hostname_alias_is_remote_even_when_it_matches_local_hostname(self):
        remote = agent(host="shared", local=False)
        with (
            mock.patch.object(agent_skill_cli, "ssh_hosts", return_value=["shared"]),
            mock.patch.object(
                agent_skill_cli,
                "query_local_agents",
            ) as query_local,
            mock.patch.object(
                agent_skill_cli,
                "query_remote_agents",
                return_value=agent_directory.ProbeResult("shared", (remote,), True),
            ) as query_remote,
        ):
            self.assertEqual(agent_skill_cli.discover_agents("shared", {}), [remote])

        query_local.assert_not_called()
        query_remote.assert_called_once()

    def test_remote_host_must_be_a_concrete_configured_alias(self):
        with (
            mock.patch.object(
                agent_skill_cli,
                "ssh_hosts",
                return_value=["macbook-pro"],
            ),
            self.assertRaises(agent_skill_cli.SkillCommandError) as raised,
        ):
            agent_skill_cli.discover_agents("unlisted-host", {})
        self.assertEqual(raised.exception.code, "host_not_configured")

    def test_resolve_labeled_agent_requires_exact_unique_label(self):
        first = agent(name="white-bison")
        second = agent(name="blue-raven", pane_id="w1:p2")
        with mock.patch.object(
            agent_skill_cli,
            "discover_agents",
            return_value=[first, second],
        ):
            self.assertEqual(
                agent_skill_cli.resolve_labeled_agent("local", "white-bison"),
                first,
            )
            with self.assertRaises(agent_skill_cli.SkillCommandError) as raised:
                agent_skill_cli.resolve_labeled_agent("local", "white")
        self.assertEqual(raised.exception.code, "agent_not_found")

    def test_send_waits_and_includes_verified_sender(self):
        recipient = agent(name="white-bison", pane_id="w1:p2")
        sender = agent(name="blue-raven")
        completed = subprocess.CompletedProcess(["herdr"], 0, '{"result":"done"}\n', "")
        with (
            mock.patch.object(
                agent_skill_cli,
                "resolve_labeled_agent",
                return_value=recipient,
            ),
            mock.patch.object(agent_skill_cli, "current_sender", return_value=sender),
            mock.patch.object(
                agent_skill_cli,
                "run_bounded_command",
                return_value=completed,
            ) as run,
        ):
            payload = agent_skill_cli.send_command(
                host="local",
                label="white-bison",
                message="Review this change.",
                wait=True,
                timeout_ms=90_000,
                environment={},
            )

        command = run.call_args.args[0]
        self.assertEqual(command[:4], ["herdr", "agent", "prompt", "white-bison"])
        self.assertIn("Message from local/blue-raven:\n\nReview this change.", command)
        self.assertEqual(command[-3:], ["--wait", "--timeout", "90000"])
        self.assertEqual(run.call_args.kwargs["timeout"], 95)
        self.assertTrue(payload["sent"])
        self.assertTrue(payload["waited"])
        self.assertTrue(payload["wait_can_track_submitted_turn"])
        self.assertEqual(payload["warnings"], [])

    def test_send_accepts_gui_route_without_a_label_or_installed_skill(self):
        recipient = agent(name="", pane_id="w7:p9")
        sender = agent(name="blue-raven")
        token = agent_skill_cli.encode_agent_route(recipient)
        completed = subprocess.CompletedProcess(["herdr"], 0, "{}\n", "")
        with (
            mock.patch.object(
                agent_skill_cli,
                "discover_agents",
                return_value=[recipient],
            ),
            mock.patch.object(agent_skill_cli, "current_sender", return_value=sender),
            mock.patch.object(
                agent_skill_cli,
                "run_bounded_command",
                return_value=completed,
            ) as run,
        ):
            payload = agent_skill_cli.send_command(
                host="local",
                route=token,
                message="Inspect this session.",
                wait=True,
                timeout_ms=90_000,
                environment={},
            )

        self.assertEqual(run.call_args.args[0][3], "w7:p9")
        self.assertEqual(payload["recipient"]["pane_id"], "w7:p9")

    def test_cli_route_runs_with_an_empty_skill_home(self):
        with tempfile.TemporaryDirectory() as empty_home:
            root = Path(empty_home)
            log_path = root / "prompt.json"
            snapshot = {
                "result": {
                    "snapshot": {
                        "agents": [
                            {
                                "agent": "codex",
                                "agent_session": {"value": "sender-session"},
                                "agent_status": "idle",
                                "cwd": "/work/coordinator",
                                "name": "blue-raven",
                                "pane_id": "w1:p1",
                                "revision": 1,
                                "terminal_id": "sender-terminal",
                                "workspace_id": "w1",
                            },
                            {
                                "agent": "codex",
                                "agent_session": {"value": "recipient-session"},
                                "agent_status": "idle",
                                "cwd": "/work/worker",
                                "pane_id": "w7:p9",
                                "revision": 1,
                                "terminal_id": "recipient-terminal",
                                "workspace_id": "w7",
                            },
                        ],
                        "workspaces": [],
                    }
                }
            }
            records = agent_directory.parse_agent_payload(
                snapshot,
                host=agent_directory.local_host_name(),
                local=True,
            )
            recipient = next(record for record in records if record.pane_id == "w7:p9")
            token = agent_skill_cli.encode_agent_route(recipient)
            fake_herdr = root / "herdr"
            fake_herdr.write_text(
                "#!/usr/bin/env python3\n"
                "import json, pathlib, sys\n"
                f"snapshot = {snapshot!r}\n"
                f"log_path = pathlib.Path({os.fspath(log_path)!r})\n"
                "if sys.argv[1:3] == ['api', 'snapshot']:\n"
                "    print(json.dumps(snapshot))\n"
                "elif sys.argv[1:3] == ['agent', 'prompt']:\n"
                "    log_path.write_text(json.dumps(sys.argv[1:4]))\n"
                "    print('{}')\n"
                "else:\n"
                "    raise SystemExit(2)\n",
                encoding="utf-8",
            )
            fake_herdr.chmod(0o700)
            environment = {
                **os.environ,
                "HOME": empty_home,
                "HERDR_BIN_PATH": os.fspath(fake_herdr),
                "HERDR_PANE_ID": "w1:p1",
            }
            self.assertFalse(root.joinpath(".agents", "skills").exists())
            self.assertFalse(root.joinpath(".claude", "skills").exists())
            completed = subprocess.run(
                [
                    sys.executable,
                    os.fspath(Path(agent_skill_cli.__file__).resolve()),
                    "send",
                    "--route",
                    token,
                    "--message",
                    "Inspect this session.",
                    "--no-wait",
                ],
                capture_output=True,
                check=False,
                text=True,
                timeout=10,
                env=environment,
                cwd=empty_home,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertTrue(json.loads(completed.stdout)["sent"])
            self.assertEqual(
                json.loads(log_path.read_text(encoding="utf-8")),
                ["agent", "prompt", "w7:p9"],
            )

    def test_send_warns_when_waiting_on_an_already_working_agent(self):
        recipient = agent(name="white-bison", pane_id="w1:p2")
        recipient = replace(recipient, status="working")
        sender = agent(name="blue-raven")
        completed = subprocess.CompletedProcess(["herdr"], 0, "{}\n", "")
        with (
            mock.patch.object(
                agent_skill_cli,
                "resolve_labeled_agent",
                return_value=recipient,
            ),
            mock.patch.object(agent_skill_cli, "current_sender", return_value=sender),
            mock.patch.object(
                agent_skill_cli,
                "run_bounded_command",
                return_value=completed,
            ),
        ):
            payload = agent_skill_cli.send_command(
                host="local",
                label="white-bison",
                message="Review this change.",
                wait=True,
                timeout_ms=90_000,
                environment={},
            )
        self.assertFalse(payload["wait_can_track_submitted_turn"])
        self.assertEqual(len(payload["warnings"]), 1)

    def test_send_rejects_the_current_sender_as_recipient(self):
        sender = agent(name="white-bison")
        with (
            mock.patch.object(
                agent_skill_cli,
                "resolve_labeled_agent",
                return_value=sender,
            ),
            mock.patch.object(agent_skill_cli, "current_sender", return_value=sender),
            self.assertRaises(agent_skill_cli.SkillCommandError) as raised,
        ):
            agent_skill_cli.send_command(
                host="local",
                label="white-bison",
                message="Do this.",
                wait=True,
                timeout_ms=90_000,
                environment={},
            )
        self.assertEqual(raised.exception.code, "recipient_is_sender")

    def test_send_without_wait_keeps_a_short_process_deadline(self):
        recipient = agent(name="white-bison", pane_id="w1:p2")
        sender = agent(name="blue-raven")
        completed = subprocess.CompletedProcess(["herdr"], 0, "{}\n", "")
        with (
            mock.patch.object(
                agent_skill_cli,
                "resolve_labeled_agent",
                return_value=recipient,
            ),
            mock.patch.object(agent_skill_cli, "current_sender", return_value=sender),
            mock.patch.object(
                agent_skill_cli,
                "run_bounded_command",
                return_value=completed,
            ) as run,
        ):
            payload = agent_skill_cli.send_command(
                host="local",
                label="white-bison",
                message="Review this change.",
                wait=False,
                timeout_ms=90_000,
                environment={},
            )
        self.assertNotIn("--wait", run.call_args.args[0])
        self.assertIsNone(payload["wait_can_track_submitted_turn"])
        self.assertEqual(
            run.call_args.kwargs["timeout"],
            agent_directory.REMOTE_DISCOVERY_TIMEOUT_SECONDS,
        )

    def test_send_classifies_timeout_and_cancellation(self):
        recipient = agent(name="white-bison", pane_id="w1:p2")
        sender = agent(name="blue-raven")
        failures = (
            ("timeout", "prompt_timeout"),
            ("cancelled", "prompt_cancelled"),
        )
        for detail, expected_code in failures:
            completed = subprocess.CompletedProcess(["herdr"], 1, "", detail)
            with (
                self.subTest(detail=detail),
                mock.patch.object(
                    agent_skill_cli,
                    "resolve_routed_agent",
                    return_value=recipient,
                ),
                mock.patch.object(
                    agent_skill_cli,
                    "current_sender",
                    return_value=sender,
                ),
                mock.patch.object(
                    agent_skill_cli,
                    "run_bounded_command",
                    return_value=completed,
                ),
                self.assertRaises(agent_skill_cli.SkillCommandError) as raised,
            ):
                agent_skill_cli.send_command(
                    host="local",
                    route="opaque",
                    message="Review this change.",
                    wait=True,
                    timeout_ms=90_000,
                    environment={},
                )
            self.assertEqual(raised.exception.code, expected_code)

    def test_batch_reuses_send_and_aggregates_per_target_results(self):
        def send_command(**arguments):
            route = arguments["route"]
            if route == "self":
                raise agent_skill_cli.SkillCommandError(
                    "recipient_is_sender",
                    "The current sender cannot also be the recipient.",
                )
            if route == "slow":
                raise agent_skill_cli.SkillCommandError(
                    "prompt_timeout",
                    "timeout",
                )
            return {
                "sent": True,
                "waited": True,
                "wait_can_track_submitted_turn": True,
            }

        with mock.patch.object(
            agent_skill_cli,
            "send_command",
            side_effect=send_command,
        ) as send:
            payload = agent_skill_cli.batch_command(
                requests_json=(
                    '[{"route":"ok","message":"one"},'
                    '{"route":"self","message":"two"},'
                    '{"route":"slow","message":"three"}]'
                ),
                wait=True,
                timeout_ms=90_000,
                max_workers=1,
                environment={"HERDR_PANE_ID": "w1:p1"},
            )

        self.assertEqual(send.call_count, 3)
        self.assertEqual(
            [result["status"] for result in payload["results"]],
            ["succeeded", "failed", "timeout"],
        )
        self.assertEqual(payload["results"][1]["error"], "recipient_is_sender")
        self.assertEqual(payload["status"], "partial")

    def test_batch_no_wait_reports_submitted(self):
        with mock.patch.object(
            agent_skill_cli,
            "send_command",
            return_value={"sent": True, "waited": False},
        ):
            payload = agent_skill_cli.batch_command(
                requests_json='[{"route":"one","message":"instruction"}]',
                wait=False,
                timeout_ms=90_000,
                max_workers=1,
                environment={},
            )

        self.assertEqual(payload["status"], "succeeded")
        self.assertEqual(payload["results"][0]["status"], "submitted")

    def test_batch_normalizes_future_request_lifecycle_payloads(self):
        cases = (
            ({"state": "submitted_settled"}, "succeeded"),
            ({"state": "submitted_working"}, "submitted"),
            (
                {"state": "submitted_working", "timed_out": True},
                "timeout",
            ),
            ({"state": "submission_failed", "error": "rejected"}, "failed"),
        )
        for lifecycle_payload, expected in cases:
            with self.subTest(payload=lifecycle_payload):
                outcome = agent_skill_cli._batch_outcome_from_payload(
                    lifecycle_payload,
                    waited=True,
                )
                self.assertEqual(outcome.status, expected)

    def test_batch_returns_a_future_refreshed_route(self):
        with mock.patch.object(
            agent_skill_cli,
            "send_command",
            return_value={
                "sent": True,
                "waited": True,
                "wait_trackable": True,
                "route": "v2-refreshed",
            },
        ):
            payload = agent_skill_cli.batch_command(
                requests_json='[{"route":"v1-stale","message":"instruction"}]',
                wait=True,
                timeout_ms=90_000,
                max_workers=1,
                environment={},
            )

        self.assertEqual(payload["results"][0]["route"], "v2-refreshed")

    def test_read_resolves_label_before_fetching_output(self):
        recipient = agent(name="white-bison")
        completed = subprocess.CompletedProcess(["herdr"], 0, "final report\n", "")
        with (
            mock.patch.object(
                agent_skill_cli,
                "resolve_labeled_agent",
                return_value=recipient,
            ),
            mock.patch.object(
                agent_skill_cli,
                "run_bounded_command",
                return_value=completed,
            ) as run,
        ):
            payload = agent_skill_cli.read_command(
                host="local",
                label="white-bison",
                lines=80,
                environment={},
            )

        self.assertEqual(
            run.call_args.args[0],
            [
                "herdr",
                "agent",
                "read",
                "white-bison",
                "--source",
                "recent-unwrapped",
                "--lines",
                "80",
                "--format",
                "text",
            ],
        )
        self.assertEqual(payload["output"], "final report\n")

    def test_sender_must_be_a_current_agent(self):
        with (
            mock.patch.object(
                agent_skill_cli,
                "fetch_local_agent",
                return_value=None,
            ),
            self.assertRaises(agent_skill_cli.SkillCommandError) as raised,
        ):
            agent_skill_cli.current_sender({})
        self.assertEqual(raised.exception.code, "sender_unavailable")

    def test_sender_uses_only_the_invoking_pane_environment(self):
        sender = agent(name="blue-raven", pane_id="w1:p1")
        with mock.patch.object(
            agent_skill_cli,
            "fetch_local_agent",
            return_value=sender,
        ) as fetch:
            self.assertEqual(
                agent_skill_cli.current_sender(
                    {
                        "HERDR_PANE_ID": "w1:p1",
                        "HERDR_ACTIVE_PANE_ID": "w9:p9",
                    }
                ),
                sender,
            )
        self.assertEqual(fetch.call_args.args[0], "w1:p1")

    def test_send_parser_has_no_sender_override(self):
        with (
            mock.patch("sys.stderr"),
            self.assertRaises(SystemExit),
        ):
            agent_skill_cli.parse_cli_arguments(
                [
                    "send",
                    "--label",
                    "white-bison",
                    "--message",
                    "hello",
                    "--sender-pane",
                    "w2:p2",
                ]
            )

    def test_send_parser_accepts_a_verified_route_instead_of_a_label(self):
        arguments = agent_skill_cli.parse_cli_arguments(
            [
                "send",
                "--route",
                "opaque-token",
                "--message",
                "hello",
            ]
        )
        self.assertEqual(arguments.route, "opaque-token")
        self.assertIsNone(arguments.label)

    def test_batch_parser_accepts_json_and_worker_limit(self):
        arguments = agent_skill_cli.parse_cli_arguments(
            [
                "batch",
                "--requests-json",
                '[{"route":"one","message":"hello"}]',
                "--max-workers",
                "3",
                "--no-wait",
            ]
        )
        self.assertEqual(arguments.command, "batch")
        self.assertEqual(arguments.max_workers, 3)
        self.assertFalse(arguments.wait)

    def test_batch_main_returns_nonzero_partial_result_as_compact_json(self):
        result = {
            "status": "partial",
            "results": [
                {"route": "one", "status": "succeeded"},
                {"route": "two", "status": "failed", "error": "route_expired"},
            ],
        }
        output = StringIO()
        with (
            mock.patch.object(agent_skill_cli, "batch_command", return_value=result),
            mock.patch("sys.stdout", output),
        ):
            exit_code = agent_skill_cli.main(
                [
                    "batch",
                    "--requests-json",
                    '[{"route":"one","message":"hello"}]',
                ],
                {},
            )

        self.assertEqual(exit_code, 1)
        self.assertEqual(
            output.getvalue(),
            '{"status":"partial","results":['
            '{"route":"one","status":"succeeded"},'
            '{"route":"two","status":"failed","error":"route_expired"}]}\n',
        )


class AgentSkillWrapperTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.wrapper = load_skill_wrapper()

    def test_bundled_wrapper_finds_repository_plugin_root(self):
        runner = mock.Mock()
        self.assertEqual(
            self.wrapper.find_plugin_root(SKILL_WRAPPER_PATH, runner),
            Path(__file__).resolve().parent,
        )
        runner.assert_not_called()

    def test_standalone_wrapper_uses_installed_plugin_root(self):
        plugin_root = Path(__file__).resolve().parent
        completed = subprocess.CompletedProcess(
            ["herdr"],
            0,
            (
                '{"result":{"plugins":[{"plugin_root":"'
                + str(plugin_root)
                + '"}]}}'
            ),
            "",
        )
        runner = mock.Mock(return_value=completed)

        self.assertEqual(
            self.wrapper.find_plugin_root(
                Path("/tmp/copied-skill/scripts/herdr_agent_messenger.py"),
                runner,
            ),
            plugin_root,
        )
        self.assertEqual(
            runner.call_args.args[0],
            [
                "herdr",
                "plugin",
                "list",
                "--json",
                "--plugin",
                "herdr.agent-labels",
            ],
        )

    def test_standalone_wrapper_rejects_invalid_plugin_responses(self):
        cases = (
            subprocess.CompletedProcess(["herdr"], 0, "not-json", ""),
            subprocess.CompletedProcess(["herdr"], 0, '{"result":{"plugins":[]}}', ""),
            subprocess.CompletedProcess(
                ["herdr"],
                0,
                '{"result":{"plugins":[{"plugin_root":"/missing/plugin"}]}}',
                "",
            ),
        )
        for completed in cases:
            with (
                self.subTest(stdout=completed.stdout),
                self.assertRaises(SystemExit),
            ):
                self.wrapper.find_plugin_root(
                    Path("/tmp/copied-skill/scripts/herdr_agent_messenger.py"),
                    mock.Mock(return_value=completed),
                )


if __name__ == "__main__":
    unittest.main()
