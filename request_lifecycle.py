"""Conservative request lifecycle state machine for Herdr agents.

The state machine deliberately knows nothing about labels, route token versions,
SSH, or Herdr subprocess syntax.  Those details are supplied by a transport so a
resolver can be replaced without changing request-state semantics.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import re
import subprocess
import tempfile
import time
from typing import Any, Callable, Generic, Mapping, Protocol, TypeVar


class RequestState(str, Enum):
    SUBMISSION_FAILED = "submission_failed"
    SUBMITTED_WORKING = "submitted_working"
    SUBMITTED_SETTLED = "submitted_settled"
    SUBMITTED_UNKNOWN = "submitted_unknown"


@dataclass(frozen=True)
class SubmissionResult:
    """Whether the prompt command definitely accepted or rejected a request."""

    accepted: bool | None
    error: str = ""
    timed_out: bool = False

    @classmethod
    def submitted(cls) -> "SubmissionResult":
        return cls(True)

    @classmethod
    def failed(cls, error: str) -> "SubmissionResult":
        return cls(False, error=error)

    @classmethod
    def unknown(
        cls,
        error: str,
        *,
        timed_out: bool = False,
    ) -> "SubmissionResult":
        return cls(None, error=error, timed_out=timed_out)


@dataclass(frozen=True)
class OutputSnapshot:
    """A bounded tail of terminal output, never an unbounded transcript."""

    text: str
    truncated: bool = False


class RequestTarget(Protocol):
    identity: str
    status: str


TargetT = TypeVar("TargetT", bound=RequestTarget)


class RequestTransport(Protocol, Generic[TargetT]):
    """Small boundary between request semantics and the current route version."""

    def resolve(self) -> TargetT:
        """Resolve the current recipient occupant."""

    def describe(self, target: TargetT) -> Mapping[str, Any]:
        """Return JSON-safe recipient metadata."""

    def submit(self, target: TargetT, prompt: str) -> SubmissionResult:
        """Submit without using Herdr's settled-state wait."""

    def read_output(
        self,
        target: TargetT,
        *,
        max_lines: int,
        max_chars: int,
    ) -> OutputSnapshot:
        """Read a bounded output tail for the resolved occupant."""


class RequestStateStore(Protocol):
    def save(self, request_id: str, payload: Mapping[str, Any]) -> None:
        """Atomically save the latest queryable request state."""

    def load(self, request_id: str) -> dict[str, Any] | None:
        """Load one request state, returning None when it does not exist."""


_REQUEST_ID_PATTERN = re.compile(r"[0-9a-f]{32}")


class JsonRequestStateStore:
    """Private, atomic JSON state files used by the CLI's status command."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    @staticmethod
    def _validate_request_id(request_id: str) -> None:
        if not _REQUEST_ID_PATTERN.fullmatch(request_id):
            raise ValueError("The request ID is invalid.")

    def _path(self, request_id: str) -> Path:
        self._validate_request_id(request_id)
        return self.directory / f"{request_id}.json"

    def save(self, request_id: str, payload: Mapping[str, Any]) -> None:
        destination = self._path(request_id)
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=self.directory,
            prefix=f".{request_id}.",
            suffix=".tmp",
        )
        temporary = Path(temporary_name)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                descriptor = -1
                json.dump(payload, stream, ensure_ascii=False, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def load(self, request_id: str) -> dict[str, Any] | None:
        path = self._path(request_id)
        try:
            with path.open(encoding="utf-8") as stream:
                payload = json.load(stream)
        except FileNotFoundError:
            return None
        if not isinstance(payload, dict):
            raise ValueError("The stored request state is invalid.")
        return payload


def limit_output(text: str, *, max_lines: int, max_chars: int) -> OutputSnapshot:
    """Keep only the newest configured lines and characters."""

    if max_lines <= 0 or max_chars <= 0:
        raise ValueError("Output limits must be greater than zero.")
    truncated = False
    lines = text.splitlines(keepends=True)
    if len(lines) > max_lines:
        lines = lines[-max_lines:]
        truncated = True
    bounded = "".join(lines)
    if len(bounded) > max_chars:
        bounded = bounded[-max_chars:]
        truncated = True
    return OutputSnapshot(bounded, truncated)


def _suffix_prefix_overlap(before: str, after: str) -> int:
    """Return the longest suffix of before that is a prefix of after."""

    maximum = min(len(before), len(after))
    if maximum == 0:
        return 0
    pattern = after[:maximum]
    values: list[str | None] = [*pattern, None, *before[-maximum:]]
    prefix = [0] * len(values)
    for index in range(1, len(values)):
        candidate = prefix[index - 1]
        while candidate and values[index] != values[candidate]:
            candidate = prefix[candidate - 1]
        if values[index] == values[candidate]:
            candidate += 1
        prefix[index] = candidate
    return min(prefix[-1], maximum)


def capture_new_output(
    before: OutputSnapshot,
    after: OutputSnapshot,
    *,
    max_lines: int,
    max_chars: int,
) -> OutputSnapshot:
    """Return only output added after a baseline, conservatively marked."""

    if not before.text:
        bounded = limit_output(
            after.text,
            max_lines=max_lines,
            max_chars=max_chars,
        )
        return OutputSnapshot(
            bounded.text,
            before.truncated or after.truncated or bounded.truncated,
        )
    overlap = _suffix_prefix_overlap(before.text, after.text)
    if (
        overlap
        and overlap < len(before.text)
        and "\n" not in before.text[-overlap:]
    ):
        # A few coincidental characters are not a reliable rolling-tail anchor.
        overlap = 0
    if overlap == 0:
        delta = after.text
        correlation_lost = before.text != after.text
    else:
        delta = after.text[overlap:]
        correlation_lost = False
    bounded = limit_output(delta, max_lines=max_lines, max_chars=max_chars)
    return OutputSnapshot(
        bounded.text,
        correlation_lost or after.truncated or bounded.truncated,
    )


class RequestLifecycleMachine(Generic[TargetT]):
    """Submit, observe a fresh turn, and capture its bounded new output."""

    def __init__(
        self,
        transport: RequestTransport[TargetT],
        store: RequestStateStore,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.transport = transport
        self.store = store
        self.monotonic = monotonic
        self.sleep = sleep

    def run(
        self,
        *,
        request_id: str,
        prompt: str,
        timeout_seconds: float,
        poll_interval_seconds: float,
        max_output_lines: int,
        max_output_chars: int,
        metadata: Mapping[str, Any] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        if timeout_seconds <= 0 or poll_interval_seconds <= 0:
            raise ValueError("Timeouts and poll intervals must be greater than zero.")
        if max_output_lines <= 0 or max_output_chars <= 0:
            raise ValueError("Output limits must be greater than zero.")

        record: dict[str, Any] = {
            "request_id": request_id,
            "state": None,
            "phase": "resolving",
            "terminal": False,
            "submitted": None,
            "submission_timed_out": False,
            "timed_out": False,
            "preexisting_working": None,
            "requested_turn_observed": False,
            "wait_safe": None,
            "recipient_status": None,
            "response": {
                "output": "",
                "truncated": False,
                "correlated": False,
            },
            "error": None,
            "_limits": {
                "lines": max_output_lines,
                "chars": max_output_chars,
            },
        }
        if metadata:
            record.update(metadata)
        self.store.save(request_id, record)

        try:
            initial = self.transport.resolve()
        except Exception as error:
            return self._finish_without_target(
                record,
                state=RequestState.SUBMISSION_FAILED,
                phase="resolve_failed",
                error=str(error) or error.__class__.__name__,
            )

        initial_working = initial.status == "working"
        record.update(
            {
                "phase": "capturing_baseline",
                "recipient": dict(self.transport.describe(initial)),
                "recipient_status": initial.status,
                "preexisting_working": initial_working,
                "wait_safe": not initial_working,
                "_target_identity": initial.identity,
            }
        )
        self.store.save(request_id, record)
        baseline, baseline_error = self._read_output(
            initial,
            max_lines=max_output_lines,
            max_chars=max_output_chars,
        )
        self._store_baseline(record, baseline, baseline_error)

        record["phase"] = "submitting"
        if baseline_error:
            record["baseline_error"] = baseline_error
        self.store.save(request_id, record)
        try:
            submission = self.transport.submit(initial, prompt)
        except subprocess.TimeoutExpired:
            submission = SubmissionResult.unknown(
                "Prompt submission timed out before acceptance could be confirmed.",
                timed_out=True,
            )
        except Exception as error:
            submission = SubmissionResult.failed(
                str(error) or error.__class__.__name__
            )

        record.update(
            {
                "submitted": submission.accepted,
                "submission_timed_out": submission.timed_out,
                "submission_error": submission.error or None,
            }
        )
        if submission.accepted is False:
            return self._finish(
                record,
                target=initial,
                baseline=baseline,
                baseline_reliable=not baseline_error,
                state=RequestState.SUBMISSION_FAILED,
                phase="submission_failed",
                error=submission.error or "Prompt submission failed.",
                max_lines=max_output_lines,
                max_chars=max_output_chars,
            )

        boundary_seen = not initial_working
        requested_working_seen = False
        last_target = initial
        record.update(
            {
                "state": (
                    RequestState.SUBMITTED_WORKING.value
                    if initial_working
                    else RequestState.SUBMITTED_UNKNOWN.value
                ),
                "phase": (
                    "waiting_for_preexisting_turn"
                    if initial_working
                    else "waiting_for_requested_turn"
                ),
            }
        )
        self.store.save(request_id, record)
        deadline = self.monotonic() + timeout_seconds
        last_resolve_error = ""

        while self.monotonic() < deadline:
            if cancelled is not None and cancelled():
                record["cancelled"] = True
                state = (
                    RequestState.SUBMITTED_WORKING
                    if last_target.status == "working"
                    else RequestState.SUBMITTED_UNKNOWN
                )
                return self._finish(
                    record,
                    target=last_target,
                    baseline=baseline,
                    baseline_reliable=not baseline_error,
                    state=state,
                    phase="wait_cancelled",
                    error="Waiting was cancelled after prompt submission.",
                    max_lines=max_output_lines,
                    max_chars=max_output_chars,
                )
            try:
                current = self.transport.resolve()
            except Exception as error:
                last_resolve_error = str(error) or error.__class__.__name__
                self._sleep_until(deadline, poll_interval_seconds)
                continue
            if current.identity != initial.identity:
                return self._finish(
                    record,
                    target=last_target,
                    baseline=baseline,
                    baseline_reliable=not baseline_error,
                    state=RequestState.SUBMITTED_UNKNOWN,
                    phase="recipient_changed",
                    error="The resolved recipient occupant changed during the request.",
                    max_lines=max_output_lines,
                    max_chars=max_output_chars,
                    terminal=True,
                )

            last_target = current
            record["recipient_status"] = current.status
            if not boundary_seen:
                if current.status == "working":
                    record["state"] = RequestState.SUBMITTED_WORKING.value
                    self.store.save(request_id, record)
                    self._sleep_until(deadline, poll_interval_seconds)
                    continue
                boundary_seen = True
                baseline, baseline_error = self._read_output(
                    current,
                    max_lines=max_output_lines,
                    max_chars=max_output_chars,
                )
                self._store_baseline(record, baseline, baseline_error)
                record.update(
                    {
                        "state": RequestState.SUBMITTED_UNKNOWN.value,
                        "phase": "waiting_for_requested_turn",
                        "wait_safe": True,
                        "response": {
                            "output": "",
                            "truncated": bool(baseline_error),
                            "correlated": False,
                        },
                    }
                )
                if baseline_error:
                    record["baseline_error"] = baseline_error
                self.store.save(request_id, record)
                self._sleep_until(deadline, poll_interval_seconds)
                continue

            if current.status == "working":
                requested_working_seen = True
                record.update(
                    {
                        "state": RequestState.SUBMITTED_WORKING.value,
                        "phase": "waiting_for_requested_settlement",
                        "requested_turn_observed": True,
                    }
                )
                self.store.save(request_id, record)
            elif requested_working_seen:
                record["recipient_status"] = current.status
                return self._finish(
                    record,
                    target=current,
                    baseline=baseline,
                    baseline_reliable=not baseline_error,
                    state=RequestState.SUBMITTED_SETTLED,
                    phase="settled",
                    error=None,
                    max_lines=max_output_lines,
                    max_chars=max_output_chars,
                    correlated=True,
                )
            self._sleep_until(deadline, poll_interval_seconds)

        timeout_state = (
            RequestState.SUBMITTED_WORKING
            if last_target.status == "working"
            else RequestState.SUBMITTED_UNKNOWN
        )
        error = last_resolve_error or (
            "Timed out while the recipient was working."
            if timeout_state is RequestState.SUBMITTED_WORKING
            else "Timed out before a fresh requested turn could be confirmed."
        )
        record["timed_out"] = True
        return self._finish(
            record,
            target=last_target,
            baseline=baseline,
            baseline_reliable=not baseline_error,
            state=timeout_state,
            phase="wait_timed_out",
            error=error,
            max_lines=max_output_lines,
            max_chars=max_output_chars,
        )

    def refresh(self, *, request_id: str) -> dict[str, Any]:
        """Advance one stored nonterminal request using a fresh observation."""

        record = self.store.load(request_id)
        if record is None:
            raise KeyError(request_id)
        if record.get("terminal"):
            return record
        limits = record.get("_limits")
        if not isinstance(limits, dict):
            raise ValueError("The stored request output limits are invalid.")
        try:
            max_lines = int(limits.get("lines") or 0)
            max_chars = int(limits.get("chars") or 0)
        except (TypeError, ValueError) as error:
            raise ValueError(
                "The stored request output limits are invalid."
            ) from error
        if max_lines <= 0 or max_chars <= 0:
            raise ValueError("The stored request output limits are invalid.")
        baseline_data = record.get("_baseline")
        if not isinstance(baseline_data, dict):
            raise ValueError("The stored request baseline is invalid.")
        baseline = OutputSnapshot(
            str(baseline_data.get("text") or ""),
            bool(baseline_data.get("truncated")),
        )
        baseline_error = str(baseline_data.get("error") or "")

        try:
            current = self.transport.resolve()
        except Exception as error:
            record.update(
                {
                    "phase": "refresh_unavailable",
                    "error": str(error) or error.__class__.__name__,
                }
            )
            self.store.save(request_id, record)
            return record
        expected_identity = record.get("_target_identity")
        if (
            not isinstance(expected_identity, str)
            or current.identity != expected_identity
        ):
            record.update(
                {
                    "state": RequestState.SUBMITTED_UNKNOWN.value,
                    "phase": "recipient_changed",
                    "terminal": True,
                    "error": (
                        "The resolved recipient occupant changed during the request."
                    ),
                }
            )
            self.store.save(request_id, record)
            return record

        record["recipient_status"] = current.status
        if not record.get("wait_safe"):
            if current.status == "working":
                record.update(
                    {
                        "state": RequestState.SUBMITTED_WORKING.value,
                        "phase": "waiting_for_preexisting_turn",
                    }
                )
                self._capture_live_response(
                    record,
                    current,
                    baseline,
                    baseline_reliable=not baseline_error,
                    max_lines=max_lines,
                    max_chars=max_chars,
                )
                self.store.save(request_id, record)
                return record
            baseline, baseline_error = self._read_output(
                current,
                max_lines=max_lines,
                max_chars=max_chars,
            )
            self._store_baseline(record, baseline, baseline_error)
            record.update(
                {
                    "state": RequestState.SUBMITTED_UNKNOWN.value,
                    "phase": "waiting_for_requested_turn",
                    "wait_safe": True,
                    "error": None,
                    "timed_out": False,
                    "response": {
                        "output": "",
                        "truncated": bool(baseline_error),
                        "correlated": False,
                    },
                }
            )
            self.store.save(request_id, record)
            return record

        if current.status == "working":
            record.update(
                {
                    "state": RequestState.SUBMITTED_WORKING.value,
                    "phase": "waiting_for_requested_settlement",
                    "requested_turn_observed": True,
                    "error": None,
                    "timed_out": False,
                }
            )
            self._capture_live_response(
                record,
                current,
                baseline,
                baseline_reliable=not baseline_error,
                max_lines=max_lines,
                max_chars=max_chars,
            )
            self.store.save(request_id, record)
            return record
        if record.get("requested_turn_observed"):
            record["timed_out"] = False
            return self._finish(
                record,
                target=current,
                baseline=baseline,
                baseline_reliable=not baseline_error,
                state=RequestState.SUBMITTED_SETTLED,
                phase="settled",
                error=None,
                max_lines=max_lines,
                max_chars=max_chars,
                correlated=True,
            )

        record.update(
            {
                "state": RequestState.SUBMITTED_UNKNOWN.value,
                "phase": "waiting_for_requested_turn",
                "error": None,
            }
        )
        self._capture_live_response(
            record,
            current,
            baseline,
            baseline_reliable=not baseline_error,
            max_lines=max_lines,
            max_chars=max_chars,
        )
        self.store.save(request_id, record)
        return record

    def _sleep_until(self, deadline: float, interval: float) -> None:
        remaining = deadline - self.monotonic()
        if remaining > 0:
            self.sleep(min(interval, remaining))

    def _read_output(
        self,
        target: TargetT,
        *,
        max_lines: int,
        max_chars: int,
    ) -> tuple[OutputSnapshot, str]:
        try:
            return (
                self.transport.read_output(
                    target,
                    max_lines=max_lines,
                    max_chars=max_chars,
                ),
                "",
            )
        except Exception as error:
            return OutputSnapshot("", truncated=True), (
                str(error) or error.__class__.__name__
            )

    @staticmethod
    def _store_baseline(
        record: dict[str, Any],
        baseline: OutputSnapshot,
        error: str,
    ) -> None:
        record["_baseline"] = {
            "text": baseline.text,
            "truncated": baseline.truncated,
            "error": error or None,
        }

    def _capture_live_response(
        self,
        record: dict[str, Any],
        target: TargetT,
        baseline: OutputSnapshot,
        *,
        baseline_reliable: bool,
        max_lines: int,
        max_chars: int,
    ) -> None:
        final_output, read_error = self._read_output(
            target,
            max_lines=max_lines,
            max_chars=max_chars,
        )
        captured = capture_new_output(
            baseline,
            final_output,
            max_lines=max_lines,
            max_chars=max_chars,
        )
        response: dict[str, Any] = {
            "output": captured.text,
            "truncated": captured.truncated or not baseline_reliable,
            "correlated": False,
        }
        if read_error:
            response["error"] = read_error
        record["response"] = response

    def _finish_without_target(
        self,
        record: dict[str, Any],
        *,
        state: RequestState,
        phase: str,
        error: str,
    ) -> dict[str, Any]:
        record.update(
            {
                "state": state.value,
                "phase": phase,
                "terminal": True,
                "submitted": False,
                "error": error,
            }
        )
        self.store.save(str(record["request_id"]), record)
        return record

    def _finish(
        self,
        record: dict[str, Any],
        *,
        target: TargetT,
        baseline: OutputSnapshot,
        baseline_reliable: bool,
        state: RequestState,
        phase: str,
        error: str | None,
        max_lines: int,
        max_chars: int,
        correlated: bool = False,
        terminal: bool | None = None,
    ) -> dict[str, Any]:
        final_output, read_error = self._read_output(
            target,
            max_lines=max_lines,
            max_chars=max_chars,
        )
        captured = capture_new_output(
            baseline,
            final_output,
            max_lines=max_lines,
            max_chars=max_chars,
        )
        response = {
            "output": captured.text,
            "truncated": captured.truncated or not baseline_reliable,
            "correlated": correlated and baseline_reliable and not read_error,
        }
        if read_error:
            response["error"] = read_error
        record.update(
            {
                "state": state.value,
                "phase": phase,
                "terminal": (
                    terminal
                    if terminal is not None
                    else state
                    in {
                        RequestState.SUBMISSION_FAILED,
                        RequestState.SUBMITTED_SETTLED,
                    }
                ),
                "recipient_status": target.status,
                "response": response,
                "error": error,
            }
        )
        self.store.save(str(record["request_id"]), record)
        return record
