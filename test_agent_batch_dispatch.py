import threading
import time
import unittest
from concurrent.futures import CancelledError

import agent_batch_dispatch


class CodedError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class AgentBatchDispatchTest(unittest.TestCase):
    def test_results_keep_input_order_with_bounded_concurrency(self):
        active = 0
        peak = 0
        lock = threading.Lock()

        def send_one(request):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.004 * (6 - int(request.route)))
            with lock:
                active -= 1
            return agent_batch_dispatch.DispatchOutcome(
                agent_batch_dispatch.SUCCEEDED
            )

        items = [
            {"route": str(index), "message": f"instruction {index}"}
            for index in range(6)
        ]
        payload = agent_batch_dispatch.dispatch_batch(
            items,
            send_one,
            max_workers=2,
        )

        self.assertEqual(
            [result["route"] for result in payload["results"]],
            [str(index) for index in range(6)],
        )
        self.assertEqual(peak, 2)
        self.assertEqual(payload["status"], agent_batch_dispatch.SUCCEEDED)

    def test_all_duplicate_routes_fail_without_dispatch(self):
        calls = []

        def send_one(request):
            calls.append(request)
            return agent_batch_dispatch.DispatchOutcome(
                agent_batch_dispatch.SUCCEEDED
            )

        payload = agent_batch_dispatch.dispatch_batch(
            [
                {"route": "same", "message": "first"},
                {"route": "unique", "message": "valid"},
                {"route": "same", "message": "second"},
            ],
            send_one,
        )

        self.assertEqual([request.route for request in calls], ["unique"])
        self.assertEqual(payload["status"], "partial")
        self.assertEqual(
            payload["results"],
            [
                {
                    "route": "same",
                    "status": agent_batch_dispatch.FAILED,
                    "error": "duplicate_route",
                },
                {
                    "route": "unique",
                    "status": agent_batch_dispatch.SUCCEEDED,
                },
                {
                    "route": "same",
                    "status": agent_batch_dispatch.FAILED,
                    "error": "duplicate_route",
                },
            ],
        )

    def test_empty_message_and_sender_route_are_per_target_failures(self):
        def send_one(request):
            if request.route == "self":
                raise CodedError(
                    "recipient_is_sender",
                    "The current sender cannot also be the recipient.",
                )
            return agent_batch_dispatch.DispatchOutcome(
                agent_batch_dispatch.SUCCEEDED
            )

        payload = agent_batch_dispatch.dispatch_batch(
            [
                {"route": "empty", "message": " \n"},
                {"route": "self", "message": "do not send"},
            ],
            send_one,
        )

        self.assertEqual(payload["status"], agent_batch_dispatch.FAILED)
        self.assertEqual(payload["results"][0]["error"], "empty_message")
        self.assertEqual(payload["results"][1]["error"], "recipient_is_sender")

    def test_timeout_cancel_and_submission_are_preserved(self):
        def send_one(request):
            if request.route == "timeout":
                raise TimeoutError("deadline reached")
            if request.route == "cancel":
                raise CancelledError()
            return agent_batch_dispatch.DispatchOutcome(
                agent_batch_dispatch.SUBMITTED
            )

        payload = agent_batch_dispatch.dispatch_batch(
            [
                {"route": "timeout", "message": "one"},
                {"route": "submit", "message": "two"},
                {"route": "cancel", "message": "three"},
            ],
            send_one,
        )

        self.assertEqual(payload["status"], "partial")
        self.assertEqual(
            [result["status"] for result in payload["results"]],
            [
                agent_batch_dispatch.TIMED_OUT,
                agent_batch_dispatch.SUBMITTED,
                agent_batch_dispatch.CANCELLED,
            ],
        )

    def test_cancel_event_marks_requests_that_never_started(self):
        cancel_event = threading.Event()

        def send_one(_request):
            cancel_event.set()
            return agent_batch_dispatch.DispatchOutcome(
                agent_batch_dispatch.CANCELLED,
                "cancelled",
            )

        payload = agent_batch_dispatch.dispatch_batch(
            [
                {"route": "first", "message": "one"},
                {"route": "second", "message": "two"},
            ],
            send_one,
            max_workers=1,
            cancel_event=cancel_event,
        )

        self.assertEqual(
            [result["status"] for result in payload["results"]],
            [agent_batch_dispatch.CANCELLED, agent_batch_dispatch.CANCELLED],
        )

    def test_worker_limit_is_enforced(self):
        items = [{"route": "one", "message": "instruction"}]
        for workers in (0, agent_batch_dispatch.MAX_BATCH_WORKERS + 1):
            with (
                self.subTest(workers=workers),
                self.assertRaises(agent_batch_dispatch.BatchDispatchError) as raised,
            ):
                agent_batch_dispatch.dispatch_batch(
                    items,
                    lambda _request: agent_batch_dispatch.DispatchOutcome(
                        agent_batch_dispatch.SUCCEEDED
                    ),
                    max_workers=workers,
                )
            self.assertEqual(raised.exception.code, "invalid_workers")

    def test_json_parser_accepts_array_and_requests_wrapper(self):
        expected = [{"route": "one", "message": "instruction"}]
        self.assertEqual(
            agent_batch_dispatch.parse_batch_json(
                '[{"route":"one","message":"instruction"}]'
            ),
            expected,
        )
        self.assertEqual(
            agent_batch_dispatch.parse_batch_json(
                '{"requests":[{"route":"one","message":"instruction"}]}'
            ),
            expected,
        )


if __name__ == "__main__":
    unittest.main()
