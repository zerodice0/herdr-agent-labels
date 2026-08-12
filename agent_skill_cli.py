"""Non-interactive host/label interface for the bundled agent skill."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
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

DEFAULT_WAIT_TIMEOUT_MS = 120_000
DEFAULT_READ_LINES = 120


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
    label: str,
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

    recipient = resolve_labeled_agent(host, label, environment)
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
    label: str,
    lines: int,
    environment: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    if lines <= 0:
        raise SkillCommandError("invalid_lines", "--lines must be greater than zero.")
    recipient = resolve_labeled_agent(host, label, environment)
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


def parse_cli_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Route Herdr prompts using an SSH host and agent label."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List current labeled agents.")
    list_parser.add_argument("--host", default="local")

    send_parser = subparsers.add_parser(
        "send",
        help="Send a prompt to one labeled agent.",
    )
    send_parser.add_argument("--host", default="local")
    send_parser.add_argument("--label", required=True)
    send_parser.add_argument("--message", required=True)
    wait_group = send_parser.add_mutually_exclusive_group()
    wait_group.add_argument("--wait", dest="wait", action="store_true", default=True)
    wait_group.add_argument("--no-wait", dest="wait", action="store_false")
    send_parser.add_argument("--timeout", type=int, default=DEFAULT_WAIT_TIMEOUT_MS)

    read_parser = subparsers.add_parser(
        "read",
        help="Read a labeled agent's recent output.",
    )
    read_parser.add_argument("--host", default="local")
    read_parser.add_argument("--label", required=True)
    read_parser.add_argument("--lines", type=int, default=DEFAULT_READ_LINES)
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
                message=arguments.message,
                wait=arguments.wait,
                timeout_ms=arguments.timeout,
                environment=environment,
            )
        else:
            payload = read_command(
                host=arguments.host,
                label=arguments.label,
                lines=arguments.lines,
                environment=environment,
            )
    except SkillCommandError as error:
        _write_json({"error": {"code": error.code, "message": error.message}})
        return 1
    _write_json(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
