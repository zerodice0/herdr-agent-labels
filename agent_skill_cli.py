"""Non-interactive label and verified-route interface for agent messaging."""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict
from typing import Any

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
ROUTE_TOKEN_VERSION = 1


class SkillCommandError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _write_json(payload: Mapping[str, Any]) -> None:
    json.dump(payload, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")


def _record_payload(agent: AgentRecord) -> dict[str, Any]:
    payload = asdict(agent)
    payload["label"] = agent.name
    payload["qualified_name"] = agent.qualified_name
    route_host = "local" if agent.local else agent.host
    payload["address"] = f"{route_host}/{agent.name}"
    return payload


def _is_local_host(host: str) -> bool:
    return host == "local"


def _route_fingerprint(agent: AgentRecord) -> str:
    """Return a non-reversible fingerprint for one observed pane occupant."""

    return hashlib.sha256(agent.identity.encode("utf-8")).hexdigest()


def encode_agent_route(agent: AgentRecord) -> str:
    """Encode a GUI-selected agent without exposing its session metadata."""

    payload = {
        "host": "local" if agent.local else agent.host,
        "occupant": _route_fingerprint(agent),
        "version": ROUTE_TOKEN_VERSION,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(encoded).decode("ascii").rstrip("=")


def _decode_agent_route(route: str) -> tuple[str, str]:
    if not route or len(route) > 4096:
        raise SkillCommandError("invalid_route", "The agent route token is invalid.")
    try:
        padding = "=" * (-len(route) % 4)
        decoded = base64.b64decode(
            route + padding,
            altchars=b"-_",
            validate=True,
        )
        payload = json.loads(decoded)
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise SkillCommandError(
            "invalid_route",
            "The agent route token is invalid.",
        ) from None
    if not isinstance(payload, dict):
        raise SkillCommandError("invalid_route", "The agent route token is invalid.")
    host = payload.get("host")
    occupant = payload.get("occupant")
    if (
        payload.get("version") != ROUTE_TOKEN_VERSION
        or not isinstance(host, str)
        or not host
        or not isinstance(occupant, str)
        or len(occupant) != 64
        or any(character not in "0123456789abcdef" for character in occupant)
    ):
        raise SkillCommandError("invalid_route", "The agent route token is invalid.")
    return host, occupant


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
    """Resolve the exact current occupant selected by Agent Messenger."""

    host, expected_occupant = _decode_agent_route(route)
    matches = [
        agent
        for agent in discover_agents(host, environment)
        if _route_fingerprint(agent) == expected_occupant
    ]
    if not matches:
        raise SkillCommandError(
            "route_expired",
            "The selected agent is no longer the current pane occupant.",
        )
    if len(matches) > 1:
        raise SkillCommandError(
            "route_ambiguous",
            "The selected agent route matches more than one current occupant.",
        )
    return matches[0]


def resolve_recipient(
    *,
    host: str,
    label: str | None,
    route: str | None,
    environment: Mapping[str, str] | None = None,
) -> AgentRecord:
    if route:
        if label:
            raise SkillCommandError(
                "conflicting_address",
                "Use either an agent route token or a host/label address, not both.",
            )
        return resolve_routed_agent(route, environment)
    if not label:
        raise SkillCommandError(
            "missing_address",
            "An agent route token or label is required.",
        )
    return resolve_labeled_agent(host, label, environment)


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
) -> dict[str, Any]:
    agents = [agent for agent in discover_agents(host, environment) if agent.name]
    return {
        "host": host,
        "agents": [_record_payload(agent) for agent in agents],
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
) -> dict[str, Any]:
    if not message.strip():
        raise SkillCommandError("empty_message", "The message must not be empty.")
    if timeout_ms <= 0:
        raise SkillCommandError(
            "invalid_timeout",
            "--timeout must be greater than zero.",
        )

    recipient = resolve_recipient(
        host=host,
        label=label,
        route=route,
        environment=environment,
    )
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
    result = run_bounded_command(
        _agent_command(recipient, arguments, environment),
        timeout=(
            (timeout_ms / 1000) + REMOTE_DISCOVERY_TIMEOUT_SECONDS
            if wait
            else REMOTE_DISCOVERY_TIMEOUT_SECONDS
        ),
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "prompt failed"
        raise SkillCommandError("prompt_failed", detail)
    return {
        "sent": True,
        "waited": wait,
        "wait_can_track_submitted_turn": (
            recipient.status != "working" if wait else None
        ),
        "warnings": (
            [
                (
                    "The recipient was already working, so Herdr --wait may match the "
                    "previous active turn. Read and verify the requested response "
                    "before reporting completion."
                )
            ]
            if wait and recipient.status == "working"
            else []
        ),
        "sender": _record_payload(sender),
        "recipient": _record_payload(recipient),
        "result": result.stdout.strip(),
    }


def read_command(
    *,
    host: str,
    label: str | None = None,
    route: str | None = None,
    lines: int,
    environment: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    if lines <= 0:
        raise SkillCommandError("invalid_lines", "--lines must be greater than zero.")
    recipient = resolve_recipient(
        host=host,
        label=label,
        route=route,
        environment=environment,
    )
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
    return {
        "recipient": _record_payload(recipient),
        "output": result.stdout,
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

    read_parser = subparsers.add_parser(
        "read",
        help="Read one resolved agent's recent output.",
    )
    read_parser.add_argument("--host", default="local")
    read_address = read_parser.add_mutually_exclusive_group(required=True)
    read_address.add_argument("--label")
    read_address.add_argument("--route")
    read_parser.add_argument("--lines", type=int, default=DEFAULT_READ_LINES)

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

    status_parser = subparsers.add_parser(
        "status",
        help="Read the latest stored state for a request ID.",
    )
    status_parser.add_argument("--request-id", required=True)
    return parser.parse_args(argv)


def main(
    argv: Sequence[str] | None = None,
    environment: Mapping[str, str] | None = None,
) -> int:
    arguments = parse_cli_arguments(argv)
    try:
        if arguments.command == "list":
            payload = list_command(arguments.host, environment)
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
        elif arguments.command == "read":
            payload = read_command(
                host=arguments.host,
                label=arguments.label,
                route=arguments.route,
                lines=arguments.lines,
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
        else:
            payload = request_status_command(
                request_id=arguments.request_id,
                environment=environment,
            )
    except SkillCommandError as error:
        _write_json({"error": {"code": error.code, "message": error.message}})
        return 1
    _write_json(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
