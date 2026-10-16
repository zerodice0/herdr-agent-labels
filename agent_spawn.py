"""Create interactive Herdr agents with immediately addressable HAM labels."""

from __future__ import annotations

import argparse
import os
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from agent_directory import (
    REMOTE_DISCOVERY_TIMEOUT_SECONDS,
    AgentRecord,
    decode_json_object,
    extract_agent_list_payload,
    herdr_executable,
    is_agent_list_payload,
    parse_agent_payload,
    run_bounded_command,
    ssh_command,
    ssh_config_path,
    ssh_hosts,
)
from agent_labels import ALIASES, LEGACY_SOURCE, SOURCE, Alias, candidates
from agent_output import compact_agent_payload, compact_spawn_payload
from agent_route import encode_agent_route


class SpawnError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class _Placement:
    created: str
    pane_id: str
    terminal_id: str
    workspace_id: str
    tab_id: str

    @property
    def close_target(self) -> tuple[str, str]:
        if self.created == "workspace" and self.workspace_id:
            return "workspace", self.workspace_id
        if self.created == "tab" and self.tab_id:
            return "tab", self.tab_id
        return "pane", self.pane_id


def add_spawn_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser(
        "spawn",
        help="Start a new interactive agent with a HAM address.",
        description="Start an interactive agent; pass agent arguments after --.",
    )
    parser.add_argument("--kind", required=True, help="Herdr agent kind (e.g. codex).")
    parser.add_argument("--host", default="local", help="Local server or a configured SSH host alias.")
    parser.add_argument("--cwd", help="Working directory; required for SSH hosts.")
    parser.add_argument(
        "--placement", choices=("split", "tab", "workspace"), default="split",
        help="Create a split pane (default), a tab, or a workspace.",
    )
    parser.add_argument("--from-pane", help="Source pane on the selected host.")
    parser.add_argument(
        "--direction", choices=("right", "down"), default="right",
        help="Split direction (default: right).",
    )
    parser.add_argument("--workspace", help="Workspace for a new tab.")
    parser.add_argument("--workspace-label", help="Label for the new tab or workspace.")
    parser.add_argument("--label", help="Agent label; defaults to a free HAM color-animal.")
    parser.add_argument(
        "--timeout", type=int, default=90_000, metavar="MS",
        help="Interactive readiness timeout in ms (1–300000; default: 90000).",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Print the full legacy payload including the route.",
    )
    parser.add_argument(
        "agent_args", nargs=argparse.REMAINDER,
        help="Arguments forwarded to the interactive agent after --.",
    )


def _command(
    host: str, arguments: Sequence[str], environment: Mapping[str, str],
) -> list[str]:
    if host == "local":
        return [herdr_executable(environment), *arguments]
    return ssh_command(host, arguments, config_path=ssh_config_path(environment))


def _payload(stdout: str) -> dict[str, Any]:
    payload = decode_json_object(stdout)
    if payload:
        return payload
    # SSH login banners can precede Herdr's JSON response.
    for line in reversed(stdout.splitlines()):
        payload = decode_json_object(line)
        if payload:
            return payload
    return {}


def _failure(result: subprocess.CompletedProcess[str]) -> str:
    return result.stderr.strip() or result.stdout.strip() or "Herdr command failed."


def _failed(result: subprocess.CompletedProcess[str]) -> bool:
    payload = _payload(result.stdout)
    return result.returncode != 0 or bool(payload.get("error")) or payload.get("ok") is False


def _result_payload(result: subprocess.CompletedProcess[str], code: str) -> dict[str, Any]:
    if _failed(result):
        raise SpawnError(code, _failure(result))
    payload = _payload(result.stdout).get("result")
    if not isinstance(payload, dict):
        raise SpawnError(code, "Herdr returned no placement information.")
    return payload


def _placement(result: Mapping[str, Any], created: str) -> _Placement:
    pane = result.get("pane" if created == "pane" else "root_pane")
    pane = pane if isinstance(pane, dict) else {}
    workspace = result.get("workspace")
    workspace = workspace if isinstance(workspace, dict) else {}
    tab = result.get("tab")
    tab = tab if isinstance(tab, dict) else {}
    pane_id = str(pane.get("pane_id") or "")
    return _Placement(
        created=created,
        pane_id=pane_id,
        terminal_id=str(pane.get("terminal_id") or result.get("terminal_id") or pane_id),
        workspace_id=str(
            result.get("workspace_id") or pane.get("workspace_id")
            or workspace.get("workspace_id") or tab.get("workspace_id") or ""
        ),
        tab_id=str(result.get("tab_id") or pane.get("tab_id") or tab.get("tab_id") or ""),
    )


def _raw_agents(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    result = payload.get("result")
    if not isinstance(result, dict):
        return []
    snapshot = result.get("snapshot")
    container = snapshot if isinstance(snapshot, dict) else result
    return [agent for agent in container.get("agents", []) if isinstance(agent, dict)]


def _report_metadata(
    run: Callable[[Sequence[str]], subprocess.CompletedProcess[str]],
    pane_id: str,
    kind: str,
    alias: Alias,
) -> bool:
    # Match agent_labels.report_agent_label_metadata on the selected host,
    # including clearing legacy metadata before reporting the current source.
    commands = (
        [
            "pane", "report-metadata", pane_id, "--source", LEGACY_SOURCE,
            "--clear-display-agent", "--clear-token", "alias", "--clear-token", "color",
        ],
        [
            "pane", "report-metadata", pane_id, "--source", SOURCE,
            "--agent", kind, "--display-agent", f"{alias.marker} {alias.name}",
            "--token", f"alias={alias.name}", "--token", f"color={alias.color}",
        ],
    )
    succeeded = True
    for command in commands:
        try:
            if _failed(run(command)):
                succeeded = False
        except (OSError, subprocess.SubprocessError):
            succeeded = False
    return succeeded


def spawn_command(
    arguments: argparse.Namespace,
    environment: Mapping[str, str] | None = None,
    *,
    command_runner: Callable[..., subprocess.CompletedProcess[str]] = run_bounded_command,
) -> dict[str, Any]:
    values = os.environ if environment is None else environment
    host = arguments.host
    kind = arguments.kind
    if not kind or not kind.strip() or any(character.isspace() for character in kind):
        raise SpawnError("agent_start_failed", "--kind must be a non-empty agent-kind token.")
    if not 1 <= arguments.timeout <= 300_000:
        raise SpawnError("invalid_timeout", "--timeout must be between 1 and 300000 milliseconds.")
    label = arguments.label
    if label is not None and (not label.strip() or "/" in label):
        raise SpawnError("invalid_label", "--label must be non-empty and must not contain '/'.")
    local = host == "local"
    from_pane = arguments.from_pane
    if arguments.placement == "split" and not from_pane:
        if not local or not values.get("HERDR_PANE_ID"):
            raise SpawnError(
                "sender_pane_unavailable",
                "A split needs --from-pane on SSH hosts, or HERDR_PANE_ID locally.",
            )
        from_pane = values["HERDR_PANE_ID"]
    cwd = arguments.cwd or (os.getcwd() if local else "")
    if not cwd:
        raise SpawnError("cwd_required", "--cwd is required for an SSH host.")
    if not local and host not in ssh_hosts(values):
        raise SpawnError(
            "host_not_configured",
            f"SSH host {host!r} is not a concrete alias in the configured SSH config.",
        )

    def run(
        command: Sequence[str], *, timeout: float = REMOTE_DISCOVERY_TIMEOUT_SECONDS,
    ) -> subprocess.CompletedProcess[str]:
        return command_runner(_command(host, command, values), timeout=timeout)

    def discover() -> tuple[dict[str, Any], list[AgentRecord]]:
        try:
            result = run(["agent", "list"])
        except (OSError, subprocess.SubprocessError) as error:
            raise SpawnError("host_unavailable", str(error)) from None
        if _failed(result):
            raise SpawnError("host_unavailable", _failure(result))
        payload = extract_agent_list_payload(result.stdout)
        if not is_agent_list_payload(payload):
            raise SpawnError("host_unavailable", "Herdr returned no agent list.")
        return payload, parse_agent_payload(payload, host=host, local=local)

    placement_name = "pane" if arguments.placement == "split" else arguments.placement
    create_label = arguments.workspace_label or label
    if arguments.placement == "split":
        create = [
            "pane", "split", "--pane", from_pane,
            "--direction", arguments.direction, "--cwd", cwd, "--no-focus",
        ]
    elif arguments.placement == "tab":
        workspace = arguments.workspace
        source = arguments.from_pane or (values.get("HERDR_PANE_ID") if local else None)
        if not workspace and source:
            try:
                result = _result_payload(run(["pane", "get", source]), "placement_failed")
            except (OSError, subprocess.SubprocessError) as error:
                raise SpawnError("placement_failed", str(error)) from None
            workspace = _placement(result, "pane").workspace_id
            if not workspace:
                raise SpawnError("placement_failed", "The source pane has no workspace ID.")
        create = ["tab", "create", "--cwd", cwd, "--no-focus"]
        if workspace:
            create.extend(["--workspace", workspace])
        if create_label is not None:
            create.extend(["--label", create_label])
    else:
        create = ["workspace", "create", "--cwd", cwd, "--no-focus"]
        if create_label is not None:
            create.extend(["--label", create_label])
    try:
        placement = _placement(_result_payload(run(create), "placement_failed"), placement_name)
    except (OSError, subprocess.SubprocessError) as error:
        raise SpawnError("placement_failed", str(error)) from None

    def cleanup() -> str:
        entity, target = placement.close_target
        if not target:
            return "cleanup: failed (Herdr returned no created-resource ID)"
        try:
            result = run([entity, "close", target])
        except (OSError, subprocess.SubprocessError) as error:
            return f"cleanup: failed ({error})"
        if _failed(result):
            return f"cleanup: failed ({_failure(result)})"
        return f"cleanup: closed {entity} {target}"

    try:
        if not placement.pane_id:
            raise SpawnError("placement_failed", "Herdr returned no new pane ID.")
        # Inspect both registered-name fields: agent_label() deliberately selects
        # just one, but either name can prevent Herdr from registering a candidate.
        snapshot, _ = discover()
        taken = {
            str(agent.get(key))
            for agent in _raw_agents(snapshot)
            for key in ("name", "agent_name")
            if agent.get(key)
        }
        aliases = (
            [Alias(label, "", "")] if label is not None
            else (alias for alias in candidates(f"{placement.terminal_id}:") if alias.name not in taken)
        )
        selected: Alias | None = None
        for alias in aliases:
            command = [
                "agent", "start", alias.name, "--kind", kind, "--pane", placement.pane_id,
                "--timeout", str(arguments.timeout),
            ]
            agent_args = list(arguments.agent_args)
            if agent_args[:1] == ["--"]:
                agent_args = agent_args[1:]
            if agent_args:
                command.extend(["--", *agent_args])
            try:
                result = run(
                    command, timeout=arguments.timeout / 1000 + REMOTE_DISCOVERY_TIMEOUT_SECONDS,
                )
            except (OSError, subprocess.SubprocessError) as error:
                raise SpawnError("agent_start_failed", str(error)) from None
            if not _failed(result):
                selected = alias
                break
            detail = _failure(result)
            if label is None and "agent_name_taken" in (result.stderr + result.stdout):
                continue
            raise SpawnError("agent_start_failed", detail)
        if selected is None:
            raise SpawnError("label_unavailable", "No HAM color-animal label is available.")
        label = selected.name
        palette_alias = next((alias for alias in ALIASES if alias.name == label), None)
        metadata_reported = False
        if palette_alias is not None:
            metadata_reported = _report_metadata(run, placement.pane_id, kind, palette_alias)
        placement_label_reported = True
        if placement.created != "pane" and create_label is None:
            entity, target = placement.close_target
            if entity != placement.created or not target:
                placement_label_reported = False
            else:
                try:
                    placement_label_reported = not _failed(run([entity, "rename", target, label]))
                except (OSError, subprocess.SubprocessError):
                    placement_label_reported = False
        _, agents = discover()
        matches = [
            agent for agent in agents
            if agent.pane_id == placement.pane_id and agent.name == label
        ]
        if len(matches) != 1:
            raise SpawnError("agent_start_failed", "The started agent could not be resolved uniquely.")
        agent = matches[0]
        # Short, decision-relevant fields first: agent tool outputs often truncate
        # long single-line JSON, so the opaque route and nested record go last.
        payload: dict[str, Any] = {
            "address": f"{host}/{label}",
            "label": label,
            "marker": palette_alias.marker if palette_alias else "",
            "color": palette_alias.color if palette_alias else "",
            "host": host,
            "created": placement.created,
            "pane_id": placement.pane_id,
        }
        if placement.tab_id:
            payload["tab_id"] = placement.tab_id
        payload.update(
            {
                "workspace_id": agent.workspace_id or placement.workspace_id,
                "kind": kind,
                "cwd": cwd,
                "label_metadata_reported": metadata_reported,
                "placement_label_reported": placement_label_reported,
                "agent": compact_agent_payload(agent),
                "route": encode_agent_route(agent),
            }
        )
        return payload if arguments.verbose else compact_spawn_payload(payload)
    except SpawnError as error:
        raise SpawnError(error.code, f"{error.message}; {cleanup()}") from None
