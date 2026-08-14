"""Safely roll out one exact Agent Labels commit to selected SSH aliases."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import posixpath
import re
import subprocess
import sys
import tarfile
import tomllib
from typing import Any

from agent_directory import (
    run_bounded_command,
    ssh_command,
    ssh_config_path,
    ssh_hosts,
    ssh_program_command,
)


PLUGIN_ID = "herdr.agent-labels"
PLUGIN_SOURCE = "zerodice0/herdr-agent-labels"
SOURCE_OWNER, SOURCE_REPO = PLUGIN_SOURCE.split("/", 1)
CORE_ACTION_IDS = frozenset(
    {"agent-skill-guide", "label-current", "message-agents"}
)
PLUGIN_ROOT = Path(__file__).resolve().parent
EXACT_COMMIT_PATTERN = re.compile(r"[0-9a-fA-F]{40}")
INSTALL_TIMEOUT_SECONDS = 120.0
CHECK_TIMEOUT_SECONDS = 15.0
FULL_TEST_TIMEOUT_SECONDS = 300.0

SMOKE_CHECKS = (
    "install",
    "enabled",
    "source",
    "version",
    "config",
    "reload",
    "actions",
)
FULL_CHECKS = (*SMOKE_CHECKS, "hashes", "unittest")

_HASH_SCRIPT = """\
import hashlib
import json
import os
import sys

root = sys.argv[1]
paths = json.loads(sys.argv[2])
result = {}
for relative in paths:
    path = os.path.join(root, *relative.split("/"))
    if os.path.islink(path):
        content = os.readlink(path).encode("utf-8", "surrogateescape")
        kind = "symlink"
    elif os.path.isfile(path):
        with open(path, "rb") as stream:
            content = stream.read()
        kind = "file"
    else:
        result[relative] = {"kind": "missing", "sha256": ""}
        continue
    result[relative] = {
        "kind": kind,
        "sha256": hashlib.sha256(content).hexdigest(),
    }
print(json.dumps(result, separators=(",", ":"), sort_keys=True))
"""

CommandRunner = Callable[
    [Sequence[str], float],
    subprocess.CompletedProcess[str],
]


class RolloutError(Exception):
    """A preflight or validation failure that prevents all remote changes."""


@dataclass(frozen=True)
class FileFingerprint:
    kind: str
    sha256: str


@dataclass(frozen=True)
class TargetSnapshot:
    ref: str
    version: str
    files: Mapping[str, FileFingerprint]


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str
    detail: str


@dataclass
class HostResult:
    host: str
    profile: str
    checks: list[CheckResult] = field(default_factory=list)
    commands: list[dict[str, Any]] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return all(check.status in {"pass", "planned"} for check in self.checks)

    def record_command(self, step: str, command: Sequence[str]) -> None:
        self.commands.append({"step": step, "argv": list(command)})

    def add(self, name: str, status: str, detail: str) -> None:
        self.checks.append(CheckResult(name, status, _one_line(detail)))


def _one_line(value: str, limit: int = 240) -> str:
    compact = " ".join(value.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1] + "…"


def _command_failure(result: subprocess.CompletedProcess[str]) -> str:
    return _one_line(
        result.stderr.strip()
        or result.stdout.strip()
        or f"command exited with status {result.returncode}"
    )


def _default_runner(
    command: Sequence[str],
    timeout: float,
) -> subprocess.CompletedProcess[str]:
    return run_bounded_command(command, timeout=timeout)


def _run_local_bytes(
    command: Sequence[str],
    *,
    cwd: Path,
) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            list(command),
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RolloutError(f"local target inspection failed: {error}") from error


def _safe_archive_path(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise RolloutError(f"target archive contains an unsafe path: {value!r}")
    return path.as_posix()


def load_target_snapshot(
    ref: str,
    *,
    repo_root: Path = PLUGIN_ROOT,
) -> TargetSnapshot:
    """Read version and expected file hashes from one immutable local Git object."""

    if EXACT_COMMIT_PATTERN.fullmatch(ref) is None:
        raise RolloutError("--ref must be a full 40-character Git commit SHA")
    normalized_ref = ref.lower()
    resolved = _run_local_bytes(
        ["git", "rev-parse", "--verify", f"{normalized_ref}^{{commit}}"],
        cwd=repo_root,
    )
    if resolved.returncode != 0:
        detail = resolved.stderr.decode("utf-8", errors="replace").strip()
        raise RolloutError(detail or f"Git commit {normalized_ref} is unavailable locally")
    if resolved.stdout.decode("ascii", errors="replace").strip().lower() != normalized_ref:
        raise RolloutError("--ref did not resolve to the exact requested commit")

    archived = _run_local_bytes(
        ["git", "archive", "--format=tar", normalized_ref],
        cwd=repo_root,
    )
    if archived.returncode != 0:
        detail = archived.stderr.decode("utf-8", errors="replace").strip()
        raise RolloutError(detail or "could not archive the requested Git commit")

    fingerprints: dict[str, FileFingerprint] = {}
    manifest_bytes: bytes | None = None
    try:
        with tarfile.open(fileobj=io.BytesIO(archived.stdout), mode="r:") as archive:
            for member in archive.getmembers():
                relative = _safe_archive_path(member.name)
                if member.isfile():
                    stream = archive.extractfile(member)
                    if stream is None:
                        raise RolloutError(f"could not read {relative!r} from target")
                    content = stream.read()
                    kind = "file"
                elif member.issym():
                    content = member.linkname.encode("utf-8", errors="surrogateescape")
                    kind = "symlink"
                else:
                    continue
                fingerprints[relative] = FileFingerprint(
                    kind,
                    hashlib.sha256(content).hexdigest(),
                )
                if relative == "herdr-plugin.toml":
                    manifest_bytes = content
    except (tarfile.TarError, UnicodeError) as error:
        raise RolloutError(f"could not inspect target archive: {error}") from error

    if manifest_bytes is None:
        raise RolloutError("target commit does not contain herdr-plugin.toml")
    try:
        manifest = tomllib.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise RolloutError(f"target plugin manifest is invalid: {error}") from error
    if manifest.get("id") != PLUGIN_ID:
        raise RolloutError(f"target manifest id is not {PLUGIN_ID!r}")
    version = manifest.get("version")
    if not isinstance(version, str) or not version:
        raise RolloutError("target manifest does not contain a valid version")
    actions = manifest.get("actions")
    action_ids = {
        action.get("id")
        for action in actions
        if isinstance(action, dict) and isinstance(action.get("id"), str)
    } if isinstance(actions, list) else set()
    missing_actions = sorted(CORE_ACTION_IDS - action_ids)
    if missing_actions:
        raise RolloutError(
            "target manifest is missing core actions: " + ", ".join(missing_actions)
        )
    return TargetSnapshot(normalized_ref, version, fingerprints)


def resolve_selected_hosts(
    requested_hosts: Sequence[str],
    environment: Mapping[str, str] | None = None,
) -> list[str]:
    """Keep only explicit, unique aliases after validating the existing policy."""

    selected: list[str] = []
    for host in requested_hosts:
        if host not in selected:
            selected.append(host)
    if not selected:
        raise RolloutError("at least one --host is required")
    configured = set(ssh_hosts(environment))
    invalid = [host for host in selected if host == "local" or host not in configured]
    if invalid:
        raise RolloutError(
            "not authorized concrete SSH aliases: " + ", ".join(repr(host) for host in invalid)
        )
    return selected


def install_command(host: str, ref: str, *, config_path: Path) -> list[str]:
    return ssh_command(
        host,
        ["plugin", "install", PLUGIN_SOURCE, "--ref", ref, "--yes"],
        config_path=config_path,
    )


def plugin_list_command(host: str, *, config_path: Path) -> list[str]:
    return ssh_command(
        host,
        ["plugin", "list", "--plugin", PLUGIN_ID, "--json"],
        config_path=config_path,
    )


def config_check_command(host: str, *, config_path: Path) -> list[str]:
    return ssh_command(host, ["config", "check"], config_path=config_path)


def reload_command(host: str, *, config_path: Path) -> list[str]:
    return ssh_command(host, ["server", "reload-config"], config_path=config_path)


def action_list_command(host: str, *, config_path: Path) -> list[str]:
    return ssh_command(
        host,
        ["plugin", "action", "list", "--plugin", PLUGIN_ID],
        config_path=config_path,
    )


def hash_command(
    host: str,
    target: TargetSnapshot,
    *,
    plugin_root: str,
    config_path: Path,
) -> list[str]:
    paths = json.dumps(sorted(target.files), ensure_ascii=True, separators=(",", ":"))
    return ssh_program_command(
        host,
        ["python3", "-c", _HASH_SCRIPT, plugin_root, paths],
        config_path=config_path,
    )


def unittest_command(
    host: str,
    *,
    plugin_root: str,
    config_path: Path,
) -> list[str]:
    return ssh_program_command(
        host,
        [
            "env",
            "PYTHONDONTWRITEBYTECODE=1",
            "python3",
            "-W",
            "error",
            "-m",
            "unittest",
            "-q",
        ],
        cwd=plugin_root,
        config_path=config_path,
    )


def _json_object(value: str) -> dict[str, Any]:
    candidates = [value, *reversed(value.splitlines())]
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(payload, dict):
            return payload
    return {}


def _installed_plugin(payload: Mapping[str, Any]) -> dict[str, Any] | None:
    result = payload.get("result")
    plugins = result.get("plugins") if isinstance(result, dict) else None
    if not isinstance(plugins, list):
        return None
    for plugin in plugins:
        if isinstance(plugin, dict) and plugin.get("plugin_id") == PLUGIN_ID:
            return plugin
    return None


def _active_action_ids(payload: Mapping[str, Any]) -> set[str] | None:
    result = payload.get("result")
    actions = result.get("actions") if isinstance(result, dict) else None
    if not isinstance(actions, list):
        return None
    return {
        action.get("action_id")
        for action in actions
        if isinstance(action, dict) and isinstance(action.get("action_id"), str)
    }


def _remote_root(plugin: Mapping[str, Any]) -> str | None:
    root = plugin.get("plugin_root")
    source = plugin.get("source")
    managed = source.get("managed_path") if isinstance(source, dict) else None
    if (
        not isinstance(root, str)
        or not root.startswith("/")
        or root == "/"
        or posixpath.normpath(root) != root
        or "\x00" in root
        or "\n" in root
        or managed != root
    ):
        return None
    return root


def _source_matches(plugin: Mapping[str, Any], ref: str) -> tuple[bool, str]:
    source = plugin.get("source")
    if not isinstance(source, dict):
        return False, "missing GitHub source metadata"
    actual = (
        source.get("kind"),
        source.get("owner"),
        source.get("repo"),
        source.get("requested_ref"),
        source.get("resolved_commit"),
    )
    expected = ("github", SOURCE_OWNER, SOURCE_REPO, ref, ref)
    detail = (
        f"{source.get('owner', '?')}/{source.get('repo', '?')} "
        f"requested={source.get('requested_ref', '?')} "
        f"resolved={source.get('resolved_commit', '?')}"
    )
    return actual == expected, detail


def _invoke(
    host_result: HostResult,
    step: str,
    command: Sequence[str],
    timeout: float,
    runner: CommandRunner,
) -> subprocess.CompletedProcess[str]:
    host_result.record_command(step, command)
    try:
        return runner(command, timeout)
    except (OSError, subprocess.TimeoutExpired) as error:
        return subprocess.CompletedProcess(list(command), 1, "", str(error))


def _skip(host_result: HostResult, names: Sequence[str], reason: str) -> None:
    recorded = {check.name for check in host_result.checks}
    for name in names:
        if name not in recorded:
            host_result.add(name, "skipped", reason)


def _planned_result(
    host: str,
    profile: str,
    target: TargetSnapshot,
    *,
    config_path: Path,
) -> HostResult:
    result = HostResult(host, profile)
    commands = [
        ("install", install_command(host, target.ref, config_path=config_path)),
        ("metadata", plugin_list_command(host, config_path=config_path)),
        ("config", config_check_command(host, config_path=config_path)),
        ("reload", reload_command(host, config_path=config_path)),
        ("actions", action_list_command(host, config_path=config_path)),
    ]
    if profile == "full":
        commands.extend(
            [
                (
                    "hashes",
                    hash_command(
                        host,
                        target,
                        plugin_root="<managed-plugin-root>",
                        config_path=config_path,
                    ),
                ),
                (
                    "unittest",
                    unittest_command(
                        host,
                        plugin_root="<managed-plugin-root>",
                        config_path=config_path,
                    ),
                ),
            ]
        )
    for step, command in commands:
        result.record_command(step, command)
    for check in FULL_CHECKS if profile == "full" else SMOKE_CHECKS:
        result.add(check, "planned", "no remote command executed")
    return result


def _rollout_host(
    host: str,
    profile: str,
    target: TargetSnapshot,
    *,
    config_path: Path,
    runner: CommandRunner,
) -> HostResult:
    host_result = HostResult(host, profile)
    remaining = FULL_CHECKS if profile == "full" else SMOKE_CHECKS

    command = install_command(host, target.ref, config_path=config_path)
    installed = _invoke(
        host_result,
        "install",
        command,
        INSTALL_TIMEOUT_SECONDS,
        runner,
    )
    if installed.returncode != 0:
        host_result.add("install", "fail", _command_failure(installed))
        _skip(host_result, remaining, "install failed")
        return host_result
    host_result.add("install", "pass", f"exact ref {target.ref}")

    listed = _invoke(
        host_result,
        "metadata",
        plugin_list_command(host, config_path=config_path),
        CHECK_TIMEOUT_SECONDS,
        runner,
    )
    plugin = _installed_plugin(_json_object(listed.stdout)) if listed.returncode == 0 else None
    if plugin is None:
        detail = _command_failure(listed) if listed.returncode != 0 else "plugin metadata missing"
        host_result.add("enabled", "fail", detail)
        _skip(host_result, remaining, "metadata validation failed")
        return host_result

    enabled = plugin.get("enabled") is True
    host_result.add("enabled", "pass" if enabled else "fail", str(plugin.get("enabled")))
    source_matches, source_detail = _source_matches(plugin, target.ref)
    plugin_root = _remote_root(plugin)
    if plugin_root is None:
        source_matches = False
        source_detail += " managed_root=invalid"
    host_result.add("source", "pass" if source_matches else "fail", source_detail)
    version_matches = plugin.get("version") == target.version
    host_result.add(
        "version",
        "pass" if version_matches else "fail",
        f"actual={plugin.get('version', '?')} expected={target.version}",
    )
    if not enabled or not source_matches or not version_matches or plugin_root is None:
        _skip(host_result, remaining, "metadata validation failed")
        return host_result

    checked = _invoke(
        host_result,
        "config",
        config_check_command(host, config_path=config_path),
        CHECK_TIMEOUT_SECONDS,
        runner,
    )
    if checked.returncode != 0:
        host_result.add("config", "fail", _command_failure(checked))
        _skip(host_result, remaining, "config check failed; reload was not attempted")
        return host_result
    host_result.add("config", "pass", "herdr config check")

    reloaded = _invoke(
        host_result,
        "reload",
        reload_command(host, config_path=config_path),
        CHECK_TIMEOUT_SECONDS,
        runner,
    )
    if reloaded.returncode != 0:
        host_result.add("reload", "fail", _command_failure(reloaded))
        _skip(host_result, remaining, "server reload failed")
        return host_result
    host_result.add("reload", "pass", "herdr server reload-config")

    action_result = _invoke(
        host_result,
        "actions",
        action_list_command(host, config_path=config_path),
        CHECK_TIMEOUT_SECONDS,
        runner,
    )
    action_ids = (
        _active_action_ids(_json_object(action_result.stdout))
        if action_result.returncode == 0
        else None
    )
    missing_actions = sorted(CORE_ACTION_IDS - action_ids) if action_ids is not None else []
    if action_ids is None or missing_actions:
        detail = (
            _command_failure(action_result)
            if action_result.returncode != 0
            else "missing: " + ", ".join(missing_actions or sorted(CORE_ACTION_IDS))
        )
        host_result.add("actions", "fail", detail)
        _skip(host_result, remaining, "core action validation failed")
        return host_result
    host_result.add("actions", "pass", ", ".join(sorted(CORE_ACTION_IDS)))

    if profile != "full":
        return host_result

    hashed = _invoke(
        host_result,
        "hashes",
        hash_command(
            host,
            target,
            plugin_root=plugin_root,
            config_path=config_path,
        ),
        CHECK_TIMEOUT_SECONDS,
        runner,
    )
    remote_hashes = _json_object(hashed.stdout) if hashed.returncode == 0 else {}
    expected_hashes = {
        path: asdict(fingerprint) for path, fingerprint in target.files.items()
    }
    mismatches = sorted(
        path
        for path, expected in expected_hashes.items()
        if remote_hashes.get(path) != expected
    )
    if hashed.returncode != 0 or mismatches:
        detail = (
            _command_failure(hashed)
            if hashed.returncode != 0
            else "mismatch: " + ", ".join(mismatches[:8])
        )
        host_result.add("hashes", "fail", detail)
        _skip(host_result, remaining, "file hash validation failed; tests were not run")
        return host_result
    host_result.add("hashes", "pass", f"{len(expected_hashes)} tracked files")

    tested = _invoke(
        host_result,
        "unittest",
        unittest_command(
            host,
            plugin_root=plugin_root,
            config_path=config_path,
        ),
        FULL_TEST_TIMEOUT_SECONDS,
        runner,
    )
    if tested.returncode != 0:
        host_result.add("unittest", "fail", _command_failure(tested))
    else:
        host_result.add("unittest", "pass", "python3 -W error -m unittest -q")
    return host_result


def rollout_hosts(
    hosts: Sequence[str],
    profile: str,
    target: TargetSnapshot,
    *,
    config_path: Path,
    dry_run: bool,
    runner: CommandRunner = _default_runner,
) -> list[HostResult]:
    """Roll out sequentially, retaining a complete result for every host."""

    if profile not in {"smoke", "full"}:
        raise ValueError(f"unsupported rollout profile: {profile}")
    results: list[HostResult] = []
    for host in hosts:
        if dry_run:
            results.append(
                _planned_result(host, profile, target, config_path=config_path)
            )
        else:
            results.append(
                _rollout_host(
                    host,
                    profile,
                    target,
                    config_path=config_path,
                    runner=runner,
                )
            )
    return results


def result_payload(
    results: Sequence[HostResult],
    target: TargetSnapshot,
    *,
    profile: str,
    dry_run: bool,
) -> dict[str, Any]:
    hosts_payload: list[dict[str, Any]] = []
    for result in results:
        host_payload = {
            "host": result.host,
            "success": result.success,
            "checks": [asdict(check) for check in result.checks],
        }
        if dry_run:
            host_payload["commands"] = result.commands
        hosts_payload.append(host_payload)
    return {
        "plugin": PLUGIN_ID,
        "ref": target.ref,
        "version": target.version,
        "profile": profile,
        "dry_run": dry_run,
        "success": all(result.success for result in results),
        "hosts": hosts_payload,
    }


def render_table(results: Sequence[HostResult]) -> str:
    rows = [("HOST", "CHECK", "RESULT", "DETAIL")]
    for result in results:
        for check in result.checks:
            rows.append(
                (
                    result.host,
                    check.name,
                    check.status.upper(),
                    _one_line(check.detail, 96),
                )
            )
    widths = [max(len(row[index]) for row in rows) for index in range(3)]
    return "\n".join(
        f"{row[0]:<{widths[0]}}  {row[1]:<{widths[1]}}  "
        f"{row[2]:<{widths[2]}}  {row[3]}"
        for row in rows
    )


def parse_cli_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Install and validate one exact Agent Labels commit on explicit SSH aliases."
        )
    )
    parser.add_argument("--host", action="append", required=True, dest="hosts")
    parser.add_argument("--ref", required=True, help="Full 40-character commit SHA.")
    parser.add_argument("--profile", choices=("smoke", "full"), default="smoke")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Explicitly authorize install/update and server reload on selected hosts.",
    )
    parser.add_argument("--format", choices=("table", "json"), default="table")
    return parser.parse_args(argv)


def _write_error(message: str, output_format: str) -> None:
    if output_format == "json":
        json.dump(
            {"success": False, "error": message},
            sys.stdout,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        sys.stdout.write("\n")
    else:
        sys.stderr.write(f"error: {message}\n")


def main(
    argv: Sequence[str] | None = None,
    environment: Mapping[str, str] | None = None,
) -> int:
    arguments = parse_cli_arguments(argv)
    if not arguments.dry_run and not arguments.confirm:
        _write_error(
            "--confirm is required unless --dry-run is used",
            arguments.format,
        )
        return 2
    try:
        hosts = resolve_selected_hosts(arguments.hosts, environment)
        target = load_target_snapshot(arguments.ref)
    except RolloutError as error:
        _write_error(str(error), arguments.format)
        return 2

    results = rollout_hosts(
        hosts,
        arguments.profile,
        target,
        config_path=ssh_config_path(environment),
        dry_run=arguments.dry_run,
    )
    payload = result_payload(
        results,
        target,
        profile=arguments.profile,
        dry_run=arguments.dry_run,
    )
    if arguments.format == "json":
        json.dump(payload, sys.stdout, ensure_ascii=False, separators=(",", ":"))
        sys.stdout.write("\n")
    else:
        sys.stdout.write(render_table(results) + "\n")
    return 0 if payload["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
