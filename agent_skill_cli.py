"""Non-interactive label and verified-route interface for agent messaging."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict
from typing import Any

from agent_batch_dispatch import (
    CANCELLED,
    DEFAULT_BATCH_WORKERS,
    FAILED,
    SUBMITTED,
    SUCCEEDED,
    TIMED_OUT,
    BatchDispatchError,
    BatchRequest,
    DispatchOutcome,
    dispatch_batch,
    parse_batch_json,
)
from agent_directory import (
    REMOTE_DISCOVERY_TIMEOUT_SECONDS,
    AgentRecord,
    fetch_local_agent,
    herdr_executable,
    query_local_agents,
    query_remote_agents,
    run_bounded_command,
    ssh_command,
    ssh_config_path,
    ssh_hosts,
)
from agent_route import (
    AgentRouteError,
    ROUTE_TOKEN_VERSION,
    RouteResolution,
    encode_agent_route,
    resolve_agent_route,
    route_host,
)
from agent_output import (
    InvalidOutputCursor,
    agent_address,
    compact_agent_payload,
    compact_output,
    output_stream_id,
)
from request_lifecycle import (
    JsonRequestStateStore,
    OutputSnapshot,
    RequestLifecycleMachine,
    RequestStateStore,
    RequestTransport,
    SubmissionResult,
    limit_output,
)

DEFAULT_WAIT_TIMEOUT_MS = 120_000
DEFAULT_READ_LINES = 120
DEFAULT_REQUEST_OUTPUT_CHARS = 12_000
DEFAULT_REQUEST_POLL_INTERVAL_SECONDS = 0.5
DEFAULT_READ_MAX_BYTES = 64 * 1024


class SkillCommandError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _write_json(payload: Mapping[str, Any], *, compact: bool = False) -> None:
    json.dump(
        payload,
        sys.stdout,
        ensure_ascii=False,
        separators=(",", ":") if compact else None,
    )
    sys.stdout.write("\n")


def _record_payload(agent: AgentRecord) -> dict[str, Any]:
    payload = asdict(agent)
    payload["label"] = agent.name
    payload["qualified_name"] = agent.qualified_name
    payload["address"] = agent_address(agent)
    return payload


def _is_local_host(host: str) -> bool:
    return host == "local"


def discover_agents(
    host: str,
    environment: Mapping[str, str] | None = None,
) -> list[AgentRecord]:
    if _is_local_host(host):
        return query_local_agents(environment)

    configured_hosts = ssh_hosts(environment)
    if host not in configured_hosts:
        raise SkillCommandError(
            "host_not_configured",
            f"SSH host {host!r} is not a concrete alias in the configured SSH config.",
        )
    result = query_remote_agents(host, config_path=ssh_config_path(environment))
    if not result.success:
        raise SkillCommandError(
            "host_unavailable",
            result.error or f"SSH host {host!r} is unavailable.",
        )
    return list(result.agents)


def resolve_labeled_agent(
    host: str,
    label: str,
    environment: Mapping[str, str] | None = None,
) -> AgentRecord:
    matches = [
        agent
        for agent in discover_agents(host, environment)
        if agent.name == label
    ]
    if not matches:
        raise SkillCommandError(
            "agent_not_found",
            f"No current agent with label {label!r} was found on host {host!r}.",
        )
    if len(matches) > 1:
        raise SkillCommandError(
            "agent_ambiguous",
            f"More than one current agent uses label {label!r} on host {host!r}.",
        )
    return matches[0]


def resolve_routed_agent(
    route: str,
    environment: Mapping[str, str] | None = None,
) -> AgentRecord:
    """Resolve or safely refresh the occupant selected by Agent Messenger."""

    return resolve_or_refresh_routed_agent(route, environment).agent


def resolve_or_refresh_routed_agent(
    route: str,
    environment: Mapping[str, str] | None = None,
) -> RouteResolution:
    try:
        host = route_host(route)
        return resolve_agent_route(route, discover_agents(host, environment))
    except AgentRouteError as error:
        raise SkillCommandError(error.code, error.message) from None


def resolve_recipient(
    *,
    host: str,
    label: str | None,
    route: str | None,
    environment: Mapping[str, str] | None = None,
) -> AgentRecord:
    return resolve_or_refresh_recipient(
        host=host,
        label=label,
        route=route,
        environment=environment,
    ).agent


def resolve_or_refresh_recipient(
    *,
    host: str,
    label: str | None,
    route: str | None,
    environment: Mapping[str, str] | None = None,
) -> RouteResolution:
    if route:
        if label:
            raise SkillCommandError(
                "conflicting_address",
                "Use either an agent route token or a host/label address, not both.",
            )
        return resolve_or_refresh_routed_agent(route, environment)
    if not label:
        raise SkillCommandError(
            "missing_address",
            "An agent route token or label is required.",
        )
    recipient = resolve_labeled_agent(host, label, environment)
    return RouteResolution(
        recipient,
        route_refreshed=False,
        route=encode_agent_route(recipient),
    )


def current_sender(
    environment: Mapping[str, str] | None = None,
) -> AgentRecord:
    values = os.environ if environment is None else environment
    resolved_pane_id = values.get("HERDR_PANE_ID", "")
    sender = fetch_local_agent(resolved_pane_id, values) if resolved_pane_id else None
    if sender is None:
        raise SkillCommandError(
            "sender_unavailable",
            "Run this command from a Herdr pane containing a current agent.",
        )
    return sender


def _agent_command(
    agent: AgentRecord,
    arguments: Sequence[str],
    environment: Mapping[str, str] | None = None,
) -> list[str]:
    if agent.local:
        return [herdr_executable(environment), *arguments]
    return ssh_command(
        agent.host,
        arguments,
        config_path=ssh_config_path(environment),
    )


def _request_state_store(
    environment: Mapping[str, str] | None = None,
) -> JsonRequestStateStore:
    values = os.environ if environment is None else environment
    configured = values.get("HERDR_AGENT_REQUEST_STATE_DIR")
    if configured:
        directory = Path(configured).expanduser()
    elif values.get("HERDR_PLUGIN_STATE_DIR"):
        directory = Path(values["HERDR_PLUGIN_STATE_DIR"]).expanduser() / "requests"
    else:
        state_home = values.get("XDG_STATE_HOME")
        configured_home = values.get("HOME")
        home = Path(configured_home).expanduser() if configured_home else Path.home()
        root = Path(state_home).expanduser() if state_home else home / ".local/state"
        directory = root / "herdr-agent-labels" / "requests"
    return JsonRequestStateStore(directory)


def _submission_failure_is_uncertain(result: subprocess.CompletedProcess[str]) -> bool:
    detail = result.stderr.strip()
    return (
        detail in {"cancelled", "output_limit_exceeded"}
        or "timed out after" in detail
    )


class AgentRequestTransport(RequestTransport[AgentRecord]):
    """Current v1 route adapter for the route-independent state machine."""

    def __init__(
        self,
        *,
        resolver: Callable[[], AgentRecord],
        sender_identity: str,
        environment: Mapping[str, str] | None,
        command_runner: Callable[..., subprocess.CompletedProcess[str]],
    ) -> None:
        self._resolver = resolver
        self._sender_identity = sender_identity
        self._environment = environment
        self._command_runner = command_runner

    def resolve(self) -> AgentRecord:
        return self._resolver()

    def describe(self, target: AgentRecord) -> Mapping[str, Any]:
        return _record_payload(target)

    def submit(self, target: AgentRecord, prompt: str) -> SubmissionResult:
        if target.identity == self._sender_identity:
            return SubmissionResult.failed(
                "The current sender cannot also be the recipient."
            )
        command = _agent_command(
            target,
            ["agent", "prompt", target.target, prompt],
            self._environment,
        )
        try:
            result = self._command_runner(
                command,
                timeout=REMOTE_DISCOVERY_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return SubmissionResult.unknown(
                "Prompt submission timed out before acceptance could be confirmed.",
                timed_out=True,
            )
        if result.returncode == 0:
            return SubmissionResult.submitted()
        detail = result.stderr.strip() or result.stdout.strip() or "prompt failed"
        if _submission_failure_is_uncertain(result):
            timed_out = "timed out after" in result.stderr
            return SubmissionResult.unknown(
                (
                    "Prompt submission timed out before acceptance could be confirmed."
                    if timed_out
                    else "Prompt submission was interrupted after it may have run."
                ),
                timed_out=timed_out,
            )
        return SubmissionResult.failed(detail)

    def read_output(
        self,
        target: AgentRecord,
        *,
        max_lines: int,
        max_chars: int,
    ) -> OutputSnapshot:
        result = self._command_runner(
            _agent_command(
                target,
                [
                    "agent",
                    "read",
                    target.target,
                    "--source",
                    "recent-unwrapped",
                    "--lines",
                    str(max_lines + 1),
                    "--format",
                    "text",
                ],
                self._environment,
            ),
            timeout=REMOTE_DISCOVERY_TIMEOUT_SECONDS * 2,
        )
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or "read failed"
            raise RuntimeError(detail)
        return limit_output(
            result.stdout,
            max_lines=max_lines,
            max_chars=max_chars,
        )


def list_command(
    host: str,
    environment: Mapping[str, str] | None = None,
    *,
    verbose: bool = False,
) -> dict[str, Any]:
    agents = [agent for agent in discover_agents(host, environment) if agent.name]
    return {
        "host": host,
        "agents": [
            _record_payload(agent) if verbose else compact_agent_payload(agent)
            for agent in agents
        ],
    }


def status_command(
    *,
    host: str,
    label: str | None = None,
    route: str | None = None,
    verbose: bool = False,
    environment: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    recipient = resolve_recipient(
        host=host,
        label=label,
        route=route,
        environment=environment,
    )
    return {
        "agent": (
            _record_payload(recipient)
            if verbose
            else compact_agent_payload(recipient)
        )
    }


def send_command(
    *,
    host: str,
    label: str | None = None,
    route: str | None = None,
    message: str,
    wait: bool,
    timeout_ms: int,
    environment: Mapping[str, str] | None = None,
    cancel_event: threading.Event | None = None,
) -> dict[str, Any]:
    if not message.strip():
        raise SkillCommandError("empty_message", "The message must not be empty.")
    if timeout_ms <= 0:
        raise SkillCommandError(
            "invalid_timeout",
            "--timeout must be greater than zero.",
        )

    resolution = resolve_or_refresh_recipient(
        host=host,
        label=label,
        route=route,
        environment=environment,
    )
    recipient = resolution.agent
    sender = current_sender(environment)
    if recipient.identity == sender.identity:
        raise SkillCommandError(
            "recipient_is_sender",
            "The current sender cannot also be the recipient.",
        )
    prompt = f"Message from {sender.qualified_name}:\n\n{message.strip()}"
    arguments = ["agent", "prompt", recipient.target, prompt]
    if wait:
        arguments.extend(["--wait", "--timeout", str(timeout_ms)])
    command_timeout = (
        (timeout_ms / 1000) + REMOTE_DISCOVERY_TIMEOUT_SECONDS
        if wait
        else REMOTE_DISCOVERY_TIMEOUT_SECONDS
    )
    run_options: dict[str, Any] = {"timeout": command_timeout}
    if cancel_event is not None:
        run_options["cancel_event"] = cancel_event
    result = run_bounded_command(
        _agent_command(recipient, arguments, environment),
        **run_options,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "prompt failed"
        lowered_detail = detail.lower()
        if lowered_detail == "cancelled":
            error_code = "prompt_cancelled"
        elif lowered_detail == "timeout" or "timed out after" in lowered_detail:
            error_code = "prompt_timeout"
        else:
            error_code = "prompt_failed"
        raise SkillCommandError(error_code, detail)
    payload: dict[str, Any] = {
        "sent": True,
        "recipient": agent_address(recipient),
        "waited": wait,
        "route_refreshed": resolution.route_refreshed,
        "route": resolution.route,
    }
    if wait:
        payload["wait_can_track_submitted_turn"] = recipient.status != "working"
    payload["warnings"] = (
        ["recipient_already_working"]
        if wait and recipient.status == "working"
        else []
    )
    return payload


def _batch_outcome_from_payload(
    payload: Mapping[str, Any],
    *,
    waited: bool,
) -> DispatchOutcome:
    """Normalize current and future single-send lifecycle payloads."""

    if payload.get("timed_out") is True:
        return DispatchOutcome(TIMED_OUT, "prompt_timeout")
    lifecycle_status = payload.get("status") or payload.get("state")
    if isinstance(lifecycle_status, str):
        normalized = lifecycle_status.lower().replace("-", "_")
        if normalized in {
            "success",
            "succeeded",
            "completed",
            "done",
            "submitted_settled",
        }:
            return DispatchOutcome(SUCCEEDED)
        if normalized in {
            "submitted",
            "submitted_in_progress",
            "submitted_working",
            "submitted_unknown",
            "in_progress",
            "working",
        }:
            return DispatchOutcome(SUBMITTED)
        if normalized in {"timeout", "timed_out"}:
            return DispatchOutcome(TIMED_OUT, "prompt_timeout")
        if normalized in {"cancelled", "canceled"}:
            return DispatchOutcome(CANCELLED, "prompt_cancelled")
        if normalized in {"failed", "failure", "blocked", "submission_failed"}:
            error = payload.get("error")
            return DispatchOutcome(
                FAILED,
                error if isinstance(error, str) else "prompt_failed",
            )
    if (
        not waited
        or payload.get("wait_can_track_submitted_turn") is False
        or payload.get("wait_trackable") is False
    ):
        return DispatchOutcome(SUBMITTED)
    return DispatchOutcome(SUCCEEDED)


def batch_command(
    *,
    requests_json: str,
    wait: bool,
    timeout_ms: int,
    max_workers: int,
    environment: Mapping[str, str] | None = None,
    cancel_event: threading.Event | None = None,
) -> dict[str, Any]:
    """Mechanically dispatch pre-tailored route/message pairs."""

    if timeout_ms <= 0:
        raise SkillCommandError(
            "invalid_timeout",
            "--timeout must be greater than zero.",
        )
    items = parse_batch_json(requests_json)

    def send_one(request: BatchRequest) -> DispatchOutcome:
        try:
            payload = send_command(
                host="local",
                route=request.route,
                message=request.message,
                wait=wait,
                timeout_ms=timeout_ms,
                environment=environment,
                cancel_event=cancel_event,
            )
        except SkillCommandError as error:
            if error.code == "prompt_timeout":
                return DispatchOutcome(TIMED_OUT, error.code, error.message)
            if error.code == "prompt_cancelled":
                return DispatchOutcome(CANCELLED, error.code, error.message)
            return DispatchOutcome(FAILED, error.code, error.message)
        outcome = _batch_outcome_from_payload(payload, waited=wait)
        refreshed_route = payload.get("route")
        if isinstance(refreshed_route, str) and refreshed_route:
            return DispatchOutcome(
                outcome.status,
                outcome.error,
                outcome.detail,
                refreshed_route,
            )
        return outcome

    return dispatch_batch(
        items,
        send_one,
        max_workers=max_workers,
        cancel_event=cancel_event,
    )


def read_command(
    *,
    host: str,
    label: str | None = None,
    route: str | None = None,
    lines: int,
    max_bytes: int = DEFAULT_READ_MAX_BYTES,
    cursor: str | None = None,
    environment: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    if lines <= 0:
        raise SkillCommandError("invalid_lines", "--lines must be greater than zero.")
    if max_bytes <= 0:
        raise SkillCommandError(
            "invalid_max_bytes",
            "--max-bytes must be greater than zero.",
        )
    resolution = resolve_or_refresh_recipient(
        host=host,
        label=label,
        route=route,
        environment=environment,
    )
    recipient = resolution.agent
    result = run_bounded_command(
        _agent_command(
            recipient,
            [
                "agent",
                "read",
                recipient.target,
                "--source",
                "recent-unwrapped",
                "--lines",
                str(lines),
                "--format",
                "text",
            ],
            environment,
        ),
        timeout=REMOTE_DISCOVERY_TIMEOUT_SECONDS * 2,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "read failed"
        raise SkillCommandError("read_failed", detail)
    try:
        delta = compact_output(
            result.stdout,
            stream=output_stream_id(recipient.identity),
            max_bytes=max_bytes,
            cursor=cursor,
        )
    except InvalidOutputCursor as error:
        raise SkillCommandError("invalid_cursor", str(error)) from None
    return {
        "address": agent_address(recipient),
        "output": delta.output,
        "truncated": delta.truncated,
        "delta": delta.delta,
        "cursor_status": delta.cursor_status,
        "cursor": delta.cursor,
        "route_refreshed": resolution.route_refreshed,
        "route": resolution.route,
    }


def request_command(
    *,
    host: str,
    label: str | None = None,
    route: str | None = None,
    message: str,
    timeout_ms: int,
    output_lines: int,
    output_chars: int,
    environment: Mapping[str, str] | None = None,
    resolver: Callable[[], AgentRecord] | None = None,
    state_store: RequestStateStore | None = None,
    command_runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    request_id: str | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Run one prompt through submission, observation, and bounded output read."""

    if not message.strip():
        raise SkillCommandError("empty_message", "The message must not be empty.")
    if timeout_ms <= 0:
        raise SkillCommandError(
            "invalid_timeout",
            "--timeout must be greater than zero.",
        )
    if output_lines <= 0:
        raise SkillCommandError(
            "invalid_output_lines",
            "--output-lines must be greater than zero.",
        )
    if output_chars <= 0:
        raise SkillCommandError(
            "invalid_output_chars",
            "--output-chars must be greater than zero.",
        )

    sender = current_sender(environment)
    recipient_resolver = resolver or (
        lambda: resolve_recipient(
            host=host,
            label=label,
            route=route,
            environment=environment,
        )
    )
    transport = AgentRequestTransport(
        resolver=recipient_resolver,
        sender_identity=sender.identity,
        environment=environment,
        command_runner=command_runner or run_bounded_command,
    )
    resolved_request_id = request_id or uuid.uuid4().hex
    machine = RequestLifecycleMachine(
        transport,
        state_store or _request_state_store(environment),
        monotonic=monotonic,
        sleep=sleep,
    )
    prompt = f"Message from {sender.qualified_name}:\n\n{message.strip()}"
    try:
        payload = machine.run(
            request_id=resolved_request_id,
            prompt=prompt,
            timeout_seconds=timeout_ms / 1000,
            poll_interval_seconds=DEFAULT_REQUEST_POLL_INTERVAL_SECONDS,
            max_output_lines=output_lines,
            max_output_chars=output_chars,
            metadata={
                "sender": _record_payload(sender),
                "_context": {
                    "host": host,
                    "label": label,
                    "route": route,
                },
            },
        )
        return _public_request_payload(payload)
    except (OSError, ValueError) as error:
        raise SkillCommandError(
            "request_state_unavailable",
            str(error) or "Request state storage is unavailable.",
        ) from error


def request_status_command(
    *,
    request_id: str,
    environment: Mapping[str, str] | None = None,
    state_store: RequestStateStore | None = None,
    resolver: Callable[[], AgentRecord] | None = None,
    command_runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
) -> dict[str, Any]:
    store = state_store or _request_state_store(environment)
    try:
        payload = store.load(request_id)
    except ValueError as error:
        raise SkillCommandError("invalid_request_id", str(error)) from error
    except OSError as error:
        raise SkillCommandError("request_state_unavailable", str(error)) from error
    if payload is None:
        raise SkillCommandError(
            "request_not_found",
            f"No stored request state was found for {request_id!r}.",
        )
    if payload.get("terminal"):
        return _public_request_payload(payload)
    context = payload.get("_context")
    if not isinstance(context, dict):
        raise SkillCommandError(
            "request_state_invalid",
            "The stored request context is invalid.",
        )
    host = context.get("host")
    label = context.get("label")
    route = context.get("route")
    if not isinstance(host, str):
        raise SkillCommandError(
            "request_state_invalid",
            "The stored request address is invalid.",
        )
    recipient_resolver = resolver or (
        lambda: resolve_recipient(
            host=host,
            label=label if isinstance(label, str) else None,
            route=route if isinstance(route, str) else None,
            environment=environment,
        )
    )
    transport = AgentRequestTransport(
        resolver=recipient_resolver,
        sender_identity="",
        environment=environment,
        command_runner=command_runner or run_bounded_command,
    )
    try:
        refreshed = RequestLifecycleMachine(transport, store).refresh(
            request_id=request_id
        )
    except (OSError, ValueError) as error:
        raise SkillCommandError("request_state_unavailable", str(error)) from error
    return _public_request_payload(refreshed)


def _public_request_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Hide private routing and baseline data from the CLI interface."""

    return {
        key: value
        for key, value in payload.items()
        if not key.startswith("_")
    }


def parse_cli_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Route Herdr prompts using a label or verified GUI route."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List current labeled agents.")
    list_parser.add_argument("--host", default="local")
    list_parser.add_argument(
        "--verbose",
        action="store_true",
        help="Include the full AgentRecord-compatible payload.",
    )
    list_parser.add_argument(
        "--legacy",
        dest="verbose",
        action="store_true",
        help="Alias for --verbose for legacy consumers.",
    )

    status_parser = subparsers.add_parser(
        "status",
        help="Read one resolved agent's current status.",
    )
    status_parser.add_argument("--host", default="local")
    status_address = status_parser.add_mutually_exclusive_group(required=True)
    status_address.add_argument("--label")
    status_address.add_argument("--route")
    status_parser.add_argument(
        "--verbose",
        action="store_true",
        help="Include the full AgentRecord-compatible payload.",
    )

    send_parser = subparsers.add_parser(
        "send",
        help="Send a prompt to one resolved agent.",
    )
    send_parser.add_argument("--host", default="local")
    send_address = send_parser.add_mutually_exclusive_group(required=True)
    send_address.add_argument("--label")
    send_address.add_argument("--route")
    send_parser.add_argument("--message", required=True)
    wait_group = send_parser.add_mutually_exclusive_group()
    wait_group.add_argument("--wait", dest="wait", action="store_true", default=True)
    wait_group.add_argument("--no-wait", dest="wait", action="store_false")
    send_parser.add_argument("--timeout", type=int, default=DEFAULT_WAIT_TIMEOUT_MS)

    batch_parser = subparsers.add_parser(
        "batch",
        help="Send pre-tailored route/message JSON with bounded concurrency.",
    )
    batch_parser.add_argument(
        "--requests-json",
        required=True,
        help="JSON request array, or '-' to read it from stdin.",
    )
    batch_wait_group = batch_parser.add_mutually_exclusive_group()
    batch_wait_group.add_argument(
        "--wait",
        dest="wait",
        action="store_true",
        default=True,
    )
    batch_wait_group.add_argument("--no-wait", dest="wait", action="store_false")
    batch_parser.add_argument("--timeout", type=int, default=DEFAULT_WAIT_TIMEOUT_MS)
    batch_parser.add_argument(
        "--max-workers",
        type=int,
        default=DEFAULT_BATCH_WORKERS,
    )

    read_parser = subparsers.add_parser(
        "read",
        help="Read one resolved agent's recent output.",
    )
    read_parser.add_argument("--host", default="local")
    read_address = read_parser.add_mutually_exclusive_group(required=True)
    read_address.add_argument("--label")
    read_address.add_argument("--route")
    read_parser.add_argument("--lines", type=int, default=DEFAULT_READ_LINES)
    read_parser.add_argument(
        "--max-bytes",
        type=int,
        default=DEFAULT_READ_MAX_BYTES,
    )
    read_parser.add_argument(
        "--cursor",
        "--watermark",
        dest="cursor",
        help="Return only output after this prior read cursor when safe.",
    )

    request_parser = subparsers.add_parser(
        "request",
        help="Submit, safely observe, and read one agent request.",
    )
    request_parser.add_argument("--host", default="local")
    request_address = request_parser.add_mutually_exclusive_group(required=True)
    request_address.add_argument("--label")
    request_address.add_argument("--route")
    request_parser.add_argument("--message", required=True)
    request_parser.add_argument("--timeout", type=int, default=DEFAULT_WAIT_TIMEOUT_MS)
    request_parser.add_argument(
        "--output-lines",
        type=int,
        default=DEFAULT_READ_LINES,
    )
    request_parser.add_argument(
        "--output-chars",
        type=int,
        default=DEFAULT_REQUEST_OUTPUT_CHARS,
    )

    request_status_parser = subparsers.add_parser(
        "request-status",
        help="Read the latest stored state for a request ID.",
    )
    request_status_parser.add_argument("--request-id", required=True)
    return parser.parse_args(argv)


def main(
    argv: Sequence[str] | None = None,
    environment: Mapping[str, str] | None = None,
) -> int:
    arguments = parse_cli_arguments(argv)
    exit_code = 0
    try:
        if arguments.command == "list":
            payload = list_command(
                arguments.host,
                environment,
                verbose=arguments.verbose,
            )
        elif arguments.command == "status":
            payload = status_command(
                host=arguments.host,
                label=arguments.label,
                route=arguments.route,
                verbose=arguments.verbose,
                environment=environment,
            )
        elif arguments.command == "send":
            payload = send_command(
                host=arguments.host,
                label=arguments.label,
                route=arguments.route,
                message=arguments.message,
                wait=arguments.wait,
                timeout_ms=arguments.timeout,
                environment=environment,
            )
        elif arguments.command == "batch":
            requests_json = (
                sys.stdin.read()
                if arguments.requests_json == "-"
                else arguments.requests_json
            )
            payload = batch_command(
                requests_json=requests_json,
                wait=arguments.wait,
                timeout_ms=arguments.timeout,
                max_workers=arguments.max_workers,
                environment=environment,
            )
            if payload["status"] != SUCCEEDED:
                exit_code = 1
        elif arguments.command == "read":
            payload = read_command(
                host=arguments.host,
                label=arguments.label,
                route=arguments.route,
                lines=arguments.lines,
                max_bytes=arguments.max_bytes,
                cursor=arguments.cursor,
                environment=environment,
            )
        elif arguments.command == "request":
            payload = request_command(
                host=arguments.host,
                label=arguments.label,
                route=arguments.route,
                message=arguments.message,
                timeout_ms=arguments.timeout,
                output_lines=arguments.output_lines,
                output_chars=arguments.output_chars,
                environment=environment,
            )
        elif arguments.command == "request-status":
            payload = request_status_command(
                request_id=arguments.request_id,
                environment=environment,
            )
        else:  # pragma: no cover - argparse rejects unknown commands
            raise SkillCommandError("invalid_command", "Unsupported command.")
    except (BatchDispatchError, SkillCommandError) as error:
        _write_json(
            {"error": {"code": error.code, "message": error.message}},
            compact=arguments.command == "batch",
        )
        return 1
    _write_json(payload, compact=arguments.command == "batch")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
