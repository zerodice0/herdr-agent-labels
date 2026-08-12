#!/usr/bin/env python3

import json
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

import agent_directory


class AgentDirectoryTest(unittest.TestCase):
    def test_parse_ssh_hosts_keeps_only_concrete_aliases(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config"
            config.write_text(
                """
                Host macbook-pro desktop
                  User tester
                Host *.example.com !blocked
                  User deploy
                Host -unsafe
                Host rogallyx
                """,
                encoding="utf-8",
            )
            self.assertEqual(
                agent_directory.parse_ssh_hosts(config),
                ["macbook-pro", "desktop", "rogallyx"],
            )

    def test_parse_ssh_hosts_follows_recursive_includes_without_cycles(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            included = root / "hosts"
            config = root / "config"
            config.write_text(
                "Include hosts\nHost root-host\n",
                encoding="utf-8",
            )
            included.write_text(
                "Include config\nHost included-host\n",
                encoding="utf-8",
            )
            self.assertEqual(
                agent_directory.parse_ssh_hosts(config),
                ["included-host", "root-host"],
            )

    def test_ssh_descriptors_map_alias_to_tailscale_device_name(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config"
            config.write_text(
                "Host macbook-pro\n  HostName 100.122.240.112\n",
                encoding="utf-8",
            )
            status = subprocess.CompletedProcess(
                ["tailscale"],
                0,
                json.dumps(
                    {
                        "Peer": {
                            "node": {
                                "HostName": "MacBook Pro",
                                "DNSName": "macbook-pro.example.ts.net.",
                                "TailscaleIPs": ["100.122.240.112"],
                            }
                        }
                    }
                ),
                "",
            )
            with mock.patch.object(
                agent_directory,
                "_run_command",
                return_value=status,
            ):
                descriptors = agent_directory.ssh_host_descriptors(
                    ["macbook-pro"],
                    config_path=config,
                )

        descriptor = descriptors["macbook-pro"]
        self.assertEqual(descriptor.destination, "100.122.240.112")
        self.assertEqual(descriptor.device_name, "MacBook Pro")
        self.assertEqual(descriptor.dns_name, "macbook-pro.example.ts.net")
        self.assertEqual(descriptor.display_name, "macbook-pro → MacBook Pro")

    def test_parse_tailscale_devices_accepts_magicdns_short_name(self):
        devices = agent_directory.parse_tailscale_devices(
            {
                "Self": {
                    "HostName": "작업용 미니 PC",
                    "DNSName": "winmini.example.ts.net.",
                    "TailscaleIPs": ["100.86.235.65"],
                }
            }
        )
        self.assertEqual(
            devices["winmini"],
            ("작업용 미니 PC", "winmini.example.ts.net"),
        )

    def test_parse_agent_payload_builds_addressable_records(self):
        payload = {
            "result": {
                "agents": [
                    {
                        "agent": "codex",
                        "agent_session": {"value": "session-1"},
                        "agent_status": "idle",
                        "cwd": "/work/project",
                        "name": "blue-raven",
                        "pane_id": "w1:p1",
                        "workspace_id": "w1",
                    }
                ]
            }
        }
        records = agent_directory.parse_agent_payload(payload, host="macbook", local=False)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].qualified_name, "macbook/blue-raven")
        self.assertEqual(records[0].session_id, "session-1")
        self.assertEqual(records[0].workspace_label, "project")

    def test_snapshot_uses_unicode_workspace_label_and_worktree_metadata(self):
        payload = {
            "result": {
                "snapshot": {
                    "agents": [
                        {
                            "agent": "codex",
                            "agent_status": "idle",
                            "cwd": "/work/repo/.herdr/worktrees/feature-a",
                            "name": "blue-raven",
                            "pane_id": "w1:p1",
                            "workspace_id": "w1",
                        }
                    ],
                    "workspaces": [
                        {
                            "workspace_id": "w1",
                            "label": "결제 기능 작업트리",
                            "worktree": {
                                "checkout_path": "/work/repo/.herdr/worktrees/feature-a",
                                "is_linked_worktree": True,
                            },
                        }
                    ],
                }
            }
        }

        records = agent_directory.parse_agent_payload(
            payload,
            host="local",
            local=True,
        )

        self.assertEqual(records[0].workspace_label, "결제 기능 작업트리")
        self.assertTrue(records[0].workspace_is_worktree)

    def test_snapshot_does_not_badge_the_primary_checkout_as_a_worktree(self):
        payload = {
            "result": {
                "snapshot": {
                    "agents": [
                        {
                            "agent": "codex",
                            "cwd": "/work/repo",
                            "pane_id": "w1:p1",
                            "workspace_id": "w1",
                        }
                    ],
                    "workspaces": [
                        {
                            "workspace_id": "w1",
                            "label": "기본 체크아웃",
                            "worktree": {
                                "checkout_path": "/work/repo",
                                "is_linked_worktree": False,
                            },
                        }
                    ],
                }
            }
        }

        records = agent_directory.parse_agent_payload(
            payload,
            host="local",
            local=True,
        )

        self.assertEqual(records[0].workspace_label, "기본 체크아웃")
        self.assertFalse(records[0].workspace_is_worktree)

    def test_display_metadata_alias_routes_through_current_pane(self):
        records = agent_directory.parse_agent_payload(
            {
                "result": {
                    "agents": [
                        {
                            "agent": "codex",
                            "display_agent": "🟪 purple-koala",
                            "pane_id": "w1:p4",
                            "tokens": {
                                "alias": "purple-koala",
                                "color": "purple",
                            },
                        }
                    ]
                }
            },
            host="macbook-pro",
            local=False,
        )

        self.assertEqual(records[0].name, "purple-koala")
        self.assertEqual(records[0].target, "w1:p4")
        self.assertEqual(records[0].qualified_name, "macbook-pro/purple-koala")

    def test_unverified_display_metadata_is_not_an_addressable_label(self):
        records = agent_directory.parse_agent_payload(
            {
                "result": {
                    "agents": [
                        {
                            "agent": "codex",
                            "display_agent": "someone else",
                            "pane_id": "w1:p4",
                            "tokens": {"alias": "purple-koala"},
                        }
                    ]
                }
            },
            host="macbook-pro",
            local=False,
        )

        self.assertEqual(records[0].name, "")
        self.assertEqual(records[0].target, "w1:p4")

    def test_agent_list_payload_requires_expected_result_shape(self):
        self.assertTrue(
            agent_directory.is_agent_list_payload({"result": {"agents": []}})
        )
        self.assertFalse(agent_directory.is_agent_list_payload({"result": {}}))
        self.assertFalse(agent_directory.is_agent_list_payload({"message": "ok"}))

    def test_cache_uses_different_success_and_failure_ttls(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = agent_directory.AgentCache(Path(directory) / "cache.json")
            cache.update(agent_directory.ProbeResult("host", (), True))
            now = time.time()
            self.assertTrue(cache.is_fresh("host", now + 9))
            self.assertFalse(cache.is_fresh("host", now + 11))

            cache.update(agent_directory.ProbeResult("host", (), False, "timeout"))
            now = time.time()
            self.assertTrue(cache.is_fresh("host", now + 29))
            self.assertFalse(cache.is_fresh("host", now + 31))

    def test_cache_round_trip_preserves_agents(self):
        record = agent_directory.AgentRecord(
            host="macbook",
            name="blue-raven",
            pane_id="w1:p1",
            workspace_id="w1",
            workspace_label="project",
            status="idle",
            session_id="session-1",
            cwd="/work/project",
            local=False,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cache.json"
            cache = agent_directory.AgentCache(path)
            cache.update(agent_directory.ProbeResult("macbook", (record,), True))
            cache.save()
            loaded = agent_directory.AgentCache(path)
            self.assertEqual(loaded.agents("macbook"), [record])

    def test_failed_probe_preserves_last_successful_agents_as_stale(self):
        record = agent_directory.AgentRecord(
            "macbook",
            "blue-raven",
            "w1:p1",
            "w1",
            "project",
            "idle",
            "session-1",
            "/work/project",
            False,
        )
        with tempfile.TemporaryDirectory() as directory:
            cache = agent_directory.AgentCache(Path(directory) / "cache.json")
            cache.update(agent_directory.ProbeResult("macbook", (record,), True))
            cache.update(
                agent_directory.ProbeResult("macbook", (), False, "timeout")
            )
            stale = cache.agents("macbook", stale=True)

        self.assertEqual(len(stale), 1)
        self.assertEqual(stale[0].identity, record.identity)
        self.assertTrue(stale[0].stale)

    def test_noisy_remote_output_extracts_last_agent_list_json_line(self):
        payload = {
            "result": {
                "agents": [
                    {
                        "agent": "codex",
                        "pane_id": "w1:p1",
                        "name": "blue-raven",
                    }
                ]
            }
        }
        completed = subprocess.CompletedProcess(
            ["ssh"],
            0,
            f"profile banner\n{json.dumps(payload)}\n",
            "",
        )
        with mock.patch.object(agent_directory, "_run_command", return_value=completed):
            result = agent_directory.query_remote_agents(
                "macbook",
                config_path=Path("/tmp/config"),
            )
        self.assertTrue(result.success)
        self.assertEqual(result.agents[0].name, "blue-raven")

    def test_remote_command_quotes_prompt_as_one_argument(self):
        prompt = "Review this; do not expand $HOME"
        command = agent_directory._remote_herdr_command(
            ["agent", "prompt", "blue-raven", prompt]
        )
        shell, login_flag, script = shlex.split(command)
        self.assertEqual((shell, login_flag), ("sh", "-c"))
        self.assertIn(shlex.quote(prompt), script)

    def test_ssh_command_hardens_probe_without_overriding_host_key_policy(self):
        command = agent_directory.ssh_command(
            "macbook",
            ["agent", "list"],
            config_path=Path("/tmp/ssh-config"),
        )
        self.assertNotIn("StrictHostKeyChecking=accept-new", command)
        self.assertIn("ClearAllForwardings=yes", command)
        self.assertIn("ForwardAgent=no", command)
        self.assertIn("ForwardX11=no", command)
        self.assertIn("PermitLocalCommand=no", command)

    def test_dispatch_revalidates_agent_before_local_prompt(self):
        sender = agent_directory.AgentRecord(
            "local", "blue-raven", "w1:p1", "w1", "project", "idle", "s1", "/work", True
        )
        recipient = agent_directory.AgentRecord(
            "local", "red-fox", "w1:p2", "w1", "project", "idle", "s2", "/work", True
        )
        sent = agent_directory.SendResult(recipient, True)
        with (
            mock.patch.object(agent_directory, "query_local_agents", return_value=[recipient]),
            mock.patch.object(agent_directory, "_send_local_prompt", return_value=sent) as send,
        ):
            results = agent_directory.dispatch_prompts(
                sender,
                [recipient],
                "Review it",
                config_path=Path("/tmp/ssh-config"),
            )
        self.assertEqual(results, [sent])
        self.assertIn("Message from local/blue-raven", send.call_args.args[1])

    def test_dispatch_separates_local_and_ssh_agents_with_same_host_name(self):
        sender = agent_directory.AgentRecord(
            "shared", "sender", "w:p0", "w", "project", "idle", "s0", "/work", True
        )
        local = agent_directory.AgentRecord(
            "shared", "local", "w:p1", "w", "project", "idle", "s1", "/work", True
        )
        remote = agent_directory.AgentRecord(
            "shared", "remote", "w:p2", "w", "project", "idle", "s2", "/work", False
        )
        local_sent = agent_directory.SendResult(local, True)
        remote_sent = agent_directory.SendResult(remote, True)
        with (
            mock.patch.object(agent_directory, "query_local_agents", return_value=[local]),
            mock.patch.object(
                agent_directory,
                "query_remote_agents",
                return_value=agent_directory.ProbeResult("shared", (remote,), True),
            ),
            mock.patch.object(
                agent_directory,
                "_send_local_prompt",
                return_value=local_sent,
            ) as send_local,
            mock.patch.object(
                agent_directory,
                "_send_remote_prompt",
                return_value=remote_sent,
            ) as send_remote,
        ):
            results = agent_directory.dispatch_prompts(
                sender,
                [local, remote],
                "Review",
                config_path=Path("/tmp/config"),
            )

        self.assertCountEqual(results, [local_sent, remote_sent])
        send_local.assert_called_once()
        send_remote.assert_called_once()

    def test_sessionless_agent_requires_full_occupant_fingerprint(self):
        selected = agent_directory.AgentRecord(
            "local", "", "w:p1", "w", "project", "idle", "", "/work", True,
            revision=2, agent_kind="codex", terminal_id="term-1",
        )
        replacement = agent_directory.replace(selected, revision=3)
        self.assertIsNone(agent_directory._matching_agent(selected, [replacement]))
        self.assertEqual(
            agent_directory._matching_agent(selected, [selected]),
            selected,
        )

    def test_remote_discovery_creates_at_most_max_workers_threads(self):
        discovery = agent_directory.RemoteDiscovery(
            [f"host-{index}" for index in range(100)],
            config_path=Path("/tmp/config"),
        )
        with mock.patch.object(agent_directory.threading, "Thread") as thread:
            discovery.start()
        self.assertEqual(thread.call_count, agent_directory.MAX_REMOTE_WORKERS)

    def test_bounded_command_can_be_cancelled(self):
        cancelled = threading.Event()
        cancelled.set()
        started_at = time.monotonic()
        result = agent_directory._run_command(
            [sys.executable, "-c", "import time; time.sleep(5)"],
            timeout=5,
            cancel_event=cancelled,
        )
        self.assertLess(time.monotonic() - started_at, 1)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "cancelled")


if __name__ == "__main__":
    unittest.main()
