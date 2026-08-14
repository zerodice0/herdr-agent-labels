import subprocess
import tempfile
import unittest
from dataclasses import dataclass, replace
from pathlib import Path
from unittest import mock

import agent_skill_cli
from request_lifecycle import (
    JsonRequestStateStore,
    OutputSnapshot,
    RequestLifecycleMachine,
    SubmissionResult,
    capture_new_output,
    limit_output,
)


@dataclass(frozen=True)
class FakeTarget:
    identity: str
    status: str
    output: str = ""


class MemoryStore:
    def __init__(self):
        self.payloads = {}
        self.history = []

    def save(self, request_id, payload):
        copied = dict(payload)
        copied["response"] = dict(payload["response"])
        self.payloads[request_id] = copied
        self.history.append(copied)

    def load(self, request_id):
        return self.payloads.get(request_id)


class FakeClock:
    def __init__(self):
        self.value = 0.0

    def monotonic(self):
        return self.value

    def sleep(self, seconds):
        self.value += seconds


class FakeTransport:
    def __init__(self, targets, submission):
        self.targets = list(targets)
        self.last_target = self.targets[-1]
        self.submission = submission
        self.prompts = []

    def resolve(self):
        if self.targets:
            self.last_target = self.targets.pop(0)
        return self.last_target

    def describe(self, target):
        return {"identity": target.identity, "status": target.status}

    def submit(self, target, prompt):
        self.prompts.append((target, prompt))
        if isinstance(self.submission, Exception):
            raise self.submission
        return self.submission

    def read_output(self, target, *, max_lines, max_chars):
        return limit_output(
            target.output,
            max_lines=max_lines,
            max_chars=max_chars,
        )


def run_machine(targets, submission, *, timeout=3.0, lines=20, chars=500):
    store = MemoryStore()
    clock = FakeClock()
    transport = FakeTransport(targets, submission)
    machine = RequestLifecycleMachine(
        transport,
        store,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )
    result = machine.run(
        request_id="1" * 32,
        prompt="do it",
        timeout_seconds=timeout,
        poll_interval_seconds=1.0,
        max_output_lines=lines,
        max_output_chars=chars,
    )
    return result, store, transport


class RequestLifecycleMachineTest(unittest.TestCase):
    def test_submission_failure_is_terminal_and_distinct(self):
        result, store, transport = run_machine(
            [FakeTarget("agent-1", "idle", "before")],
            SubmissionResult.failed("rejected"),
        )

        self.assertEqual(result["state"], "submission_failed")
        self.assertFalse(result["submitted"])
        self.assertFalse(result["timed_out"])
        self.assertEqual(result["error"], "rejected")
        self.assertEqual(len(transport.prompts), 1)
        self.assertEqual(store.load(result["request_id"]), result)

    def test_submission_process_timeout_is_not_reported_as_send_failure(self):
        idle = FakeTarget("agent-1", "idle", "before")
        result, _store, _transport = run_machine(
            [idle, idle, idle, idle],
            SubmissionResult.unknown("command timed out", timed_out=True),
        )

        self.assertEqual(result["state"], "submitted_unknown")
        self.assertIsNone(result["submitted"])
        self.assertTrue(result["submission_timed_out"])
        self.assertTrue(result["timed_out"])

    def test_timeout_exception_is_also_an_unknown_submission(self):
        idle = FakeTarget("agent-1", "idle", "before")
        result, _store, _transport = run_machine(
            [idle, idle, idle, idle],
            subprocess.TimeoutExpired(["herdr"], 5),
        )

        self.assertEqual(result["state"], "submitted_unknown")
        self.assertIsNone(result["submitted"])
        self.assertTrue(result["submission_timed_out"])

    def test_fresh_working_then_nonworking_is_settled(self):
        result, _store, _transport = run_machine(
            [
                FakeTarget("agent-1", "idle", "before\n"),
                FakeTarget("agent-1", "working", "before\npartial\n"),
                FakeTarget("agent-1", "done", "before\nanswer\n"),
            ],
            SubmissionResult.submitted(),
        )

        self.assertEqual(result["state"], "submitted_settled")
        self.assertTrue(result["submitted"])
        self.assertTrue(result["requested_turn_observed"])
        self.assertEqual(result["response"]["output"], "answer\n")
        self.assertTrue(result["response"]["correlated"])
        self.assertFalse(result["response"]["truncated"])

    def test_working_at_wait_deadline_remains_a_submitted_working_timeout(self):
        working = FakeTarget("agent-1", "working", "before\npartial\n")
        result, _store, _transport = run_machine(
            [FakeTarget("agent-1", "idle", "before\n"), working, working, working],
            SubmissionResult.submitted(),
        )

        self.assertEqual(result["state"], "submitted_working")
        self.assertTrue(result["timed_out"])
        self.assertTrue(result["requested_turn_observed"])
        self.assertFalse(result["terminal"])

    def test_cancel_stops_waiting_without_forgetting_accepted_submission(self):
        store = MemoryStore()
        clock = FakeClock()
        working = FakeTarget("agent-1", "working", "before\npartial\n")
        transport = FakeTransport(
            [FakeTarget("agent-1", "idle", "before\n"), working, working],
            SubmissionResult.submitted(),
        )
        result = RequestLifecycleMachine(
            transport,
            store,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        ).run(
            request_id="f" * 32,
            prompt="do it",
            timeout_seconds=30,
            poll_interval_seconds=1,
            max_output_lines=20,
            max_output_chars=500,
            cancelled=lambda: clock.value >= 1,
        )

        self.assertTrue(result["cancelled"])
        self.assertTrue(result["submitted"])
        self.assertEqual(result["state"], "submitted_working")
        self.assertEqual(result["phase"], "wait_cancelled")
        self.assertFalse(result["terminal"])

    def test_refresh_advances_a_timed_out_working_request_to_settled(self):
        working = FakeTarget("agent-1", "working", "before\npartial\n")
        result, store, _transport = run_machine(
            [FakeTarget("agent-1", "idle", "before\n"), working, working, working],
            SubmissionResult.submitted(),
        )
        refresh_transport = FakeTransport(
            [FakeTarget("agent-1", "done", "before\nanswer\n")],
            SubmissionResult.submitted(),
        )
        refreshed = RequestLifecycleMachine(refresh_transport, store).refresh(
            request_id=result["request_id"]
        )

        self.assertEqual(refreshed["state"], "submitted_settled")
        self.assertTrue(refreshed["terminal"])
        self.assertFalse(refreshed["timed_out"])
        self.assertEqual(refreshed["response"]["output"], "answer\n")

    def test_preexisting_turn_settlement_is_not_mistaken_for_requested_turn(self):
        old_done = FakeTarget("agent-1", "done", "old complete\n")
        result, _store, _transport = run_machine(
            [
                FakeTarget("agent-1", "working", "old partial\n"),
                old_done,
                old_done,
                old_done,
            ],
            SubmissionResult.submitted(),
        )

        self.assertEqual(result["state"], "submitted_unknown")
        self.assertTrue(result["preexisting_working"])
        self.assertFalse(result["requested_turn_observed"])
        self.assertEqual(result["response"]["output"], "")
        self.assertFalse(result["response"]["correlated"])

    def test_preexisting_turn_requires_a_second_working_settled_cycle(self):
        result, _store, _transport = run_machine(
            [
                FakeTarget("agent-1", "working", "old partial\n"),
                FakeTarget("agent-1", "done", "old complete\n"),
                FakeTarget("agent-1", "working", "old complete\nnew partial\n"),
                FakeTarget("agent-1", "done", "old complete\nnew answer\n"),
            ],
            SubmissionResult.submitted(),
            timeout=5,
        )

        self.assertEqual(result["state"], "submitted_settled")
        self.assertTrue(result["wait_safe"])
        self.assertEqual(result["response"]["output"], "new answer\n")
        self.assertTrue(result["response"]["correlated"])

    def test_refresh_keeps_preexisting_and_requested_turns_separate(self):
        old_working = FakeTarget("agent-1", "working", "old partial\n")
        result, store, _transport = run_machine(
            [old_working, old_working, old_working, old_working],
            SubmissionResult.submitted(),
        )
        refresh_transport = FakeTransport(
            [
                FakeTarget("agent-1", "done", "old complete\n"),
                FakeTarget("agent-1", "working", "old complete\nnew partial\n"),
                FakeTarget("agent-1", "done", "old complete\nnew answer\n"),
            ],
            SubmissionResult.submitted(),
        )
        refresher = RequestLifecycleMachine(refresh_transport, store)

        old_settled_state = refresher.refresh(request_id=result["request_id"])["state"]
        requested_working_state = refresher.refresh(
            request_id=result["request_id"]
        )["state"]
        requested_settled = refresher.refresh(request_id=result["request_id"])

        self.assertEqual(old_settled_state, "submitted_unknown")
        self.assertEqual(requested_working_state, "submitted_working")
        self.assertEqual(requested_settled["state"], "submitted_settled")
        self.assertEqual(
            requested_settled["response"]["output"],
            "new answer\n",
        )

    def test_recipient_replacement_makes_an_accepted_request_unknown(self):
        result, _store, _transport = run_machine(
            [
                FakeTarget("agent-1", "idle", "before"),
                FakeTarget("agent-2", "working", "replacement"),
            ],
            SubmissionResult.submitted(),
        )

        self.assertEqual(result["state"], "submitted_unknown")
        self.assertEqual(result["phase"], "recipient_changed")


class RequestOutputTest(unittest.TestCase):
    def test_limit_output_returns_tail_and_truncation_flag(self):
        captured = limit_output("one\ntwo\nthree\n", max_lines=2, max_chars=100)
        self.assertEqual(captured.text, "two\nthree\n")
        self.assertTrue(captured.truncated)

    def test_new_output_uses_rolling_tail_overlap(self):
        captured = capture_new_output(
            OutputSnapshot("one\ntwo\nthree\n", truncated=True),
            OutputSnapshot("three\nfour\n"),
            max_lines=10,
            max_chars=100,
        )
        self.assertEqual(captured.text, "four\n")
        self.assertFalse(captured.truncated)

    def test_lost_baseline_marks_output_truncated(self):
        captured = capture_new_output(
            OutputSnapshot("old baseline"),
            OutputSnapshot("new tail"),
            max_lines=10,
            max_chars=100,
        )
        self.assertEqual(captured.text, "new tail")
        self.assertTrue(captured.truncated)


class RequestStateStoreTest(unittest.TestCase):
    def test_json_store_round_trips_queryable_state(self):
        with tempfile.TemporaryDirectory() as directory:
            store = JsonRequestStateStore(Path(directory) / "requests")
            request_id = "a" * 32
            payload = {"request_id": request_id, "state": "submitted_unknown"}
            store.save(request_id, payload)

            self.assertEqual(store.load(request_id), payload)
            self.assertEqual(
                (Path(directory) / "requests" / f"{request_id}.json").stat().st_mode
                & 0o777,
                0o600,
            )

    def test_json_store_rejects_path_like_request_id(self):
        with tempfile.TemporaryDirectory() as directory:
            store = JsonRequestStateStore(Path(directory))
            with self.assertRaises(ValueError):
                store.load("../request")


class AgentRequestCliIntegrationTest(unittest.TestCase):
    def test_request_and_status_arguments_are_available(self):
        request = agent_skill_cli.parse_cli_arguments(
            [
                "request",
                "--route",
                "opaque-route",
                "--message",
                "inspect",
                "--output-lines",
                "40",
            ]
        )
        status = agent_skill_cli.parse_cli_arguments(
            ["request-status", "--request-id", "d" * 32]
        )

        self.assertEqual(request.command, "request")
        self.assertEqual(request.route, "opaque-route")
        self.assertEqual(request.output_lines, 40)
        self.assertEqual(status.command, "request-status")
        self.assertEqual(status.request_id, "d" * 32)

    def test_request_command_uses_injected_resolver_without_herdr_wait(self):
        sender = agent_skill_cli.AgentRecord(
            host="local",
            name="sender",
            pane_id="w1:p1",
            workspace_id="w1",
            workspace_label="one",
            status="idle",
            session_id="sender-session",
            cwd="/work/one",
            local=True,
        )
        idle = agent_skill_cli.AgentRecord(
            host="local",
            name="worker",
            pane_id="w1:p2",
            workspace_id="w1",
            workspace_label="one",
            status="idle",
            session_id="worker-session",
            cwd="/work/one",
            local=True,
        )
        working = replace(idle, status="working")
        done = replace(idle, status="done")
        recipients = iter([idle, working, done])
        output_reads = iter(["before\n", "before\nanswer\n"])
        commands = []

        def runner(command, *, timeout):
            commands.append((command, timeout))
            if command[1:3] == ["agent", "read"]:
                return subprocess.CompletedProcess(command, 0, next(output_reads), "")
            return subprocess.CompletedProcess(command, 0, "{}\n", "")

        store = MemoryStore()
        clock = FakeClock()
        with mock.patch.object(agent_skill_cli, "current_sender", return_value=sender):
            result = agent_skill_cli.request_command(
                host="local",
                label="worker",
                message="inspect",
                timeout_ms=3_000,
                output_lines=10,
                output_chars=500,
                environment={},
                resolver=lambda: next(recipients),
                state_store=store,
                command_runner=runner,
                request_id="b" * 32,
                monotonic=clock.monotonic,
                sleep=clock.sleep,
            )

        prompt = next(
            command for command, _timeout in commands if command[2] == "prompt"
        )
        self.assertNotIn("--wait", prompt)
        self.assertEqual(result["state"], "submitted_settled")
        self.assertEqual(result["request_id"], "b" * 32)
        self.assertEqual(result["response"]["output"], "answer\n")
        self.assertFalse(any(key.startswith("_") for key in result))
        self.assertEqual(
            agent_skill_cli.request_status_command(
                request_id="b" * 32,
                state_store=store,
            ),
            result,
        )

    def test_request_persists_a_safely_refreshed_v2_route(self):
        sender = agent_skill_cli.AgentRecord(
            host="local",
            name="sender",
            pane_id="w1:p1",
            workspace_id="w1",
            workspace_label="one",
            status="idle",
            session_id="sender-session",
            cwd="/work/one",
            local=True,
        )
        original = agent_skill_cli.AgentRecord(
            host="local",
            name="worker",
            pane_id="w1:p2",
            workspace_id="w1",
            workspace_label="one",
            status="idle",
            session_id="old-session",
            cwd="/work/one",
            local=True,
            revision=1,
            agent_kind="codex",
            terminal_id="worker-terminal",
        )
        replacement = replace(
            original,
            session_id="new-session",
            revision=2,
        )
        snapshots = iter(
            [
                [replacement],
                [replace(replacement, status="working")],
                [replace(replacement, status="done")],
            ]
        )
        outputs = iter(["before\n", "before\nanswer\n"])

        def runner(command, *, timeout):
            if command[1:3] == ["agent", "read"]:
                return subprocess.CompletedProcess(command, 0, next(outputs), "")
            return subprocess.CompletedProcess(command, 0, "{}\n", "")

        store = MemoryStore()
        clock = FakeClock()
        token = agent_skill_cli.encode_agent_route(original)
        with (
            mock.patch.object(agent_skill_cli, "current_sender", return_value=sender),
            mock.patch.object(
                agent_skill_cli,
                "discover_agents",
                side_effect=lambda *_arguments: next(snapshots),
            ),
        ):
            result = agent_skill_cli.request_command(
                host="local",
                route=token,
                message="inspect",
                timeout_ms=3_000,
                output_lines=10,
                output_chars=500,
                environment={},
                state_store=store,
                command_runner=runner,
                request_id="e" * 32,
                monotonic=clock.monotonic,
                sleep=clock.sleep,
            )

        refreshed_route = agent_skill_cli.encode_agent_route(replacement)
        self.assertTrue(result["route_refreshed"])
        self.assertEqual(result["route"], refreshed_route)
        self.assertEqual(result["recipient"]["route"], refreshed_route)
        self.assertEqual(
            agent_skill_cli.request_status_command(
                request_id="e" * 32,
                state_store=store,
            )["route"],
            refreshed_route,
        )

    def test_transport_classifies_bounded_runner_timeout_as_unknown(self):
        target = mock.Mock(identity="worker", status="idle", target="worker")
        sender = mock.Mock(identity="sender")
        result = subprocess.CompletedProcess(
            ["herdr"],
            1,
            "",
            "Command '['herdr']' timed out after 5.0 seconds",
        )
        transport = agent_skill_cli.AgentRequestTransport(
            resolver=lambda: target,
            sender_identity=sender.identity,
            environment={},
            command_runner=mock.Mock(return_value=result),
        )

        submission = transport.submit(target, "prompt")

        self.assertIsNone(submission.accepted)
        self.assertTrue(submission.timed_out)
        self.assertNotIn("['herdr']", submission.error)

    def test_status_command_refreshes_a_nonterminal_stored_request(self):
        sender = agent_skill_cli.AgentRecord(
            host="local",
            name="sender",
            pane_id="w1:p1",
            workspace_id="w1",
            workspace_label="one",
            status="idle",
            session_id="sender-session",
            cwd="/work/one",
            local=True,
        )
        idle = agent_skill_cli.AgentRecord(
            host="local",
            name="worker",
            pane_id="w1:p2",
            workspace_id="w1",
            workspace_label="one",
            status="idle",
            session_id="worker-session",
            cwd="/work/one",
            local=True,
        )
        working = replace(idle, status="working")
        done = replace(idle, status="done")
        recipients = iter([idle, working, working, working])
        request_reads = iter(["before\n", "before\npartial\n"])

        def request_runner(command, *, timeout):
            if command[1:3] == ["agent", "read"]:
                return subprocess.CompletedProcess(
                    command,
                    0,
                    next(request_reads),
                    "",
                )
            return subprocess.CompletedProcess(command, 0, "{}\n", "")

        store = MemoryStore()
        clock = FakeClock()
        with mock.patch.object(agent_skill_cli, "current_sender", return_value=sender):
            timed_out = agent_skill_cli.request_command(
                host="local",
                label="worker",
                message="inspect",
                timeout_ms=3_000,
                output_lines=10,
                output_chars=500,
                environment={},
                resolver=lambda: next(recipients),
                state_store=store,
                command_runner=request_runner,
                request_id="c" * 32,
                monotonic=clock.monotonic,
                sleep=clock.sleep,
            )

        self.assertEqual(timed_out["state"], "submitted_working")
        self.assertFalse(timed_out["terminal"])
        stored = store.load("c" * 32)
        self.assertIsNone(stored["_context"]["label"])
        self.assertIsInstance(stored["_context"]["route"], str)
        status_runner = mock.Mock(
            return_value=subprocess.CompletedProcess(
                ["herdr"],
                0,
                "before\nanswer\n",
                "",
            )
        )
        current_route = agent_skill_cli.encode_agent_route(done)
        with mock.patch.object(
            agent_skill_cli,
            "resolve_or_refresh_recipient",
            return_value=agent_skill_cli.RouteResolution(
                done,
                route_refreshed=False,
                route=current_route,
            ),
        ) as resolve:
            settled = agent_skill_cli.request_status_command(
                request_id="c" * 32,
                environment={},
                state_store=store,
                command_runner=status_runner,
            )

        self.assertEqual(settled["state"], "submitted_settled")
        self.assertEqual(settled["response"]["output"], "answer\n")
        self.assertFalse(any(key.startswith("_") for key in settled))
        resolve.assert_called_once_with(
            host="local",
            label=None,
            route=stored["_context"]["route"],
            environment={},
        )


if __name__ == "__main__":
    unittest.main()
