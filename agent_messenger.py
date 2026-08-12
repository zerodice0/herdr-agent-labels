#!/usr/bin/env python3
"""Keyboard-first popup for sending prompts to local and SSH-hosted agents."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import curses
from dataclasses import dataclass
import json
import locale
import os
from pathlib import Path
import queue
import subprocess
import sys

try:
    import termios
except ImportError:  # pragma: no cover - the plugin currently targets macOS/Linux.
    termios = None  # type: ignore[assignment]
import threading
import time
import unicodedata
from typing import Any, Iterator, Mapping, Sequence, TextIO

from agent_directory import (
    AgentCache,
    AgentRecord,
    ProbeResult,
    RemoteDiscovery,
    SendResult,
    dispatch_prompts,
    fetch_local_agent,
    herdr_executable,
    query_local_agents,
    ssh_config_path,
    ssh_hosts,
)
from messenger_i18n import detect_language, messages


PLUGIN_ID = "herdr.agent-labels"
POPUP_ENTRYPOINT = "messenger"
POPUP_WIDTH = "110"
POPUP_HEIGHT = "34"
SENDER_PANE_ENV = "HERDR_AGENT_MESSENGER_SENDER_PANE_ID"
STATUS_ORDER = {"blocked": 0, "working": 1, "done": 2, "idle": 3, "unknown": 4}
PAIR_ACCENT = 1
PAIR_SUCCESS = 2
PAIR_WARNING = 3
PAIR_ERROR = 4
PAIR_REMOTE = 5
DELIVERY_DELEGATE = "delegate"
DELIVERY_DIRECT = "direct"


@dataclass(frozen=True)
class WrappedMessageLine:
    text: str
    logical_row: int
    start: int
    end: int


@dataclass(frozen=True)
class SendJobResult:
    sender_available: bool
    results: tuple[SendResult, ...]
    error: str = ""
    cancelled: bool = False


def _single_line(value: str) -> str:
    return " ".join(value.split())


def build_orchestration_request(
    recipients: Sequence[AgentRecord],
    original_request: str,
) -> str:
    """Ask the coordinator to do semantic decomposition and worker orchestration."""

    worker_lines = []
    for index, recipient in enumerate(recipients, start=1):
        transport = "local Herdr" if recipient.local else f"SSH host {recipient.host}"
        workspace = _single_line(recipient.workspace_label) or "unknown workspace"
        worker_lines.append(
            f"{index}. {recipient.qualified_name} "
            f"(route: {transport}; workspace: {workspace}; status: {recipient.status})"
        )
    workers = "\n".join(worker_lines)
    return (
        "Agent Messenger orchestration request\n\n"
        "You are the coordinator: the focused agent that opened Agent Messenger. "
        "The plugin intentionally did not perform semantic task decomposition and did "
        "not dispatch the user's request to the selected workers.\n\n"
        "Selected workers:\n"
        f"{workers}\n\n"
        "User's original request (verbatim):\n"
        "--- BEGIN ORIGINAL REQUEST ---\n"
        f"{original_request}\n"
        "--- END ORIGINAL REQUEST ---\n\n"
        "Orchestrate this request now:\n"
        "1. Analyze the complete original request and create a specific, tailored, "
        "non-overlapping assignment for every selected worker listed above. Keep "
        "dependencies and each worker's route/workspace in mind.\n"
        "2. Use Herdr to send each worker its individual instruction. Use SSH transport "
        "for remote routes when needed. Include only the context each worker needs; do "
        "not automatically copy the full original request to every worker.\n"
        "3. Wait for the workers' responses or settled states. Follow up when work is "
        "missing, blocked, duplicated, or inconsistent.\n"
        "4. Verify every result against the original request and the relevant workspace. "
        "Run or request appropriate checks before accepting the work.\n"
        "5. Integrate and synthesize the verified results, then report the final outcome "
        "to the user, including failures or remaining risks.\n"
    )


def decode_json_object(value: str) -> dict[str, Any]:
    try:
        decoded = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def focused_pane_id(environment: Mapping[str, str] | None = None) -> str:
    values = os.environ if environment is None else environment
    context = decode_json_object(values.get("HERDR_PLUGIN_CONTEXT_JSON", "{}"))
    pane = context.get("pane")
    nested_pane_id = pane.get("pane_id") if isinstance(pane, dict) else None
    return str(
        context.get("focused_pane_id")
        or context.get("pane_id")
        or nested_pane_id
        or values.get("HERDR_ACTIVE_PANE_ID")
        or values.get("HERDR_PANE_ID")
        or ""
    )


def run_herdr(
    arguments: Sequence[str],
    environment: Mapping[str, str] | None = None,
    *,
    timeout: float = 10,
) -> subprocess.CompletedProcess[str]:
    command = [herdr_executable(environment), *arguments]
    try:
        return subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return subprocess.CompletedProcess(command, 1, "", str(error))


def show_notification(
    body: str,
    environment: Mapping[str, str] | None = None,
) -> bool:
    text = messages(detect_language(environment))
    result = run_herdr(
        [
            "notification",
            "show",
            text["title"],
            "--body",
            body,
            "--sound",
            "none",
        ],
        environment,
    )
    return result.returncode == 0


def launch_popup(
    pane_id: str,
    environment: Mapping[str, str] | None = None,
) -> bool:
    result = run_herdr(
        [
            "plugin",
            "pane",
            "open",
            "--plugin",
            PLUGIN_ID,
            "--entrypoint",
            POPUP_ENTRYPOINT,
            "--placement",
            "popup",
            "--width",
            POPUP_WIDTH,
            "--height",
            POPUP_HEIGHT,
            "--focus",
            "--env",
            f"{SENDER_PANE_ENV}={pane_id}",
        ],
        environment,
    )
    return result.returncode == 0


def launch(environment: Mapping[str, str] | None = None) -> int:
    values = os.environ if environment is None else environment
    text = messages(detect_language(values))
    pane_id = focused_pane_id(values)
    sender = fetch_local_agent(pane_id, values) if pane_id else None
    if sender is None:
        if not show_notification(text["no_focused_agent"], values):
            print(text["no_focused_agent"], file=sys.stderr)
        return 0
    if not launch_popup(pane_id, values):
        if not show_notification(text["popup_open_failed"], values):
            print(text["popup_open_failed"], file=sys.stderr)
        return 1
    return 0


def _same_occupant(left: AgentRecord, right: AgentRecord | None) -> bool:
    if right is None:
        return False
    if left.session_id:
        return left.session_id == right.session_id
    if left.revision <= 0:
        return False
    return (
        left.pane_id == right.pane_id
        and left.target == right.target
        and left.revision == right.revision
        and left.agent_kind == right.agent_kind
        and left.terminal_id == right.terminal_id
        and left.cwd == right.cwd
    )


def display_width(value: str) -> int:
    return sum(
        0
        if unicodedata.combining(character)
        else 2
        if unicodedata.east_asian_width(character) in ("F", "W")
        else 1
        for character in value
    )


def wrap_message_lines(
    lines: Sequence[str],
    *,
    width: int,
    cursor_row: int,
    cursor_column: int,
) -> tuple[list[WrappedMessageLine], int, int]:
    """Soft-wrap logical message lines and map the logical cursor to the result."""

    width = max(1, width)
    wrapped: list[WrappedMessageLine] = []
    visual_cursor_row = 0
    visual_cursor_column = 0

    for logical_row, line in enumerate(lines):
        segments: list[WrappedMessageLine] = []
        start = 0
        current_width = 0
        for index, character in enumerate(line):
            character_width = display_width(character)
            if index > start and current_width + character_width > width:
                segments.append(
                    WrappedMessageLine(line[start:index], logical_row, start, index)
                )
                start = index
                current_width = 0
            current_width += character_width
        segments.append(
            WrappedMessageLine(line[start:], logical_row, start, len(line))
        )

        for segment_index, segment in enumerate(segments):
            visual_index = len(wrapped)
            wrapped.append(segment)
            cursor_in_segment = (
                logical_row == cursor_row
                and (
                    segment.start <= cursor_column < segment.end
                    or (
                        cursor_column == segment.end
                        and (
                            segment.end == len(line)
                            or segment_index == len(segments) - 1
                        )
                    )
                )
            )
            if cursor_in_segment:
                visual_cursor_row = visual_index
                visual_cursor_column = display_width(
                    line[segment.start:cursor_column]
                )

    return wrapped, visual_cursor_row, visual_cursor_column


def character_index_at_display_column(value: str, column: int) -> int:
    """Map a terminal-cell column to the nearest character boundary."""

    current_width = 0
    for index, character in enumerate(value):
        character_width = display_width(character)
        if current_width + character_width > column:
            return index
        current_width += character_width
    return len(value)


@contextmanager
def terminal_flow_control_disabled(stream: TextIO) -> Iterator[None]:
    """Let curses receive Ctrl+S instead of treating it as terminal XOFF."""

    if termios is None:
        yield
        return
    try:
        descriptor = stream.fileno()
        original = termios.tcgetattr(descriptor)
        updated = list(original)
        updated[0] &= ~(termios.IXON | termios.IXOFF)
        termios.tcsetattr(descriptor, termios.TCSANOW, updated)
    except (OSError, ValueError, termios.error):
        yield
        return
    try:
        yield
    finally:
        try:
            termios.tcsetattr(descriptor, termios.TCSANOW, original)
        except (OSError, ValueError, termios.error):
            pass


class MessengerApp:
    def __init__(
        self,
        screen: curses.window,
        sender: AgentRecord,
        environment: Mapping[str, str],
    ) -> None:
        self.screen = screen
        self.sender = sender
        self.environment = environment
        self.text = messages(detect_language(environment))
        self.config_path = ssh_config_path(environment)
        self.hosts = ssh_hosts(environment)
        self.cache = AgentCache.from_environment(environment)
        self.agents = [
            agent
            for agent in query_local_agents(environment)
            if agent.identity != sender.identity
        ]
        self.selected: set[str] = set()
        self.search = ""
        self.cursor = 0
        self.recipient_offset = 0
        self.section = "recipients"
        self.message_lines = [""]
        self.message_row = 0
        self.message_column = 0
        self.status = self.text["no_ssh_hosts"] if not self.hosts else ""
        self.discovery_choice = bool(not self.hosts)
        self.discovery_option = 0
        self.mode_choice = False
        self.mode_return_to_editor = False
        self.mode_option = 0
        self.delivery_mode = DELIVERY_DELEGATE
        self.remote_enabled = False
        self.discovery: RemoteDiscovery | None = None
        self.pending_hosts: set[str] = set()
        self.host_status: dict[str, str] = {}
        self.skipped_hosts = 0
        self.running = True
        self.colors_enabled = False
        self.message_cursor: tuple[int, int] | None = None
        self.sending = False
        self.send_results: queue.Queue[SendJobResult] = queue.Queue()
        self.send_cancel = threading.Event()

    def _initialize_colors(self) -> None:
        if not curses.has_colors():
            return
        try:
            curses.start_color()
            try:
                curses.use_default_colors()
                background = -1
            except curses.error:
                background = curses.COLOR_BLACK
            curses.init_pair(PAIR_ACCENT, curses.COLOR_CYAN, background)
            curses.init_pair(PAIR_SUCCESS, curses.COLOR_GREEN, background)
            curses.init_pair(PAIR_WARNING, curses.COLOR_YELLOW, background)
            curses.init_pair(PAIR_ERROR, curses.COLOR_RED, background)
            curses.init_pair(PAIR_REMOTE, curses.COLOR_MAGENTA, background)
        except curses.error:
            return
        self.colors_enabled = True

    def _style(self, pair: int = 0, attribute: int = 0) -> int:
        if pair and self.colors_enabled:
            attribute |= curses.color_pair(pair)
        return attribute

    def filtered_agents(self) -> list[AgentRecord]:
        needle = self.search.casefold().strip()
        records = self.agents
        if needle:
            records = [
                agent
                for agent in records
                if needle
                in " ".join(
                    (
                        agent.host,
                        agent.target,
                        agent.workspace_label,
                        agent.workspace_id,
                        agent.status,
                    )
                ).casefold()
            ]
        return sorted(
            records,
            key=lambda agent: (
                not agent.local,
                agent.host.casefold(),
                STATUS_ORDER.get(agent.status, 9),
                agent.target.casefold(),
            ),
        )

    def _replace_agent_scope(
        self,
        *,
        local: bool,
        host: str,
        records: Sequence[AgentRecord],
    ) -> None:
        selected_for_scope = {
            agent.identity
            for agent in self.agents
            if agent.local == local
            and agent.host == host
            and agent.identity in self.selected
        }
        self.agents = [
            agent
            for agent in self.agents
            if not (agent.local == local and agent.host == host)
        ]
        self.agents.extend(records)
        available = {agent.identity for agent in records if not agent.stale}
        self.selected.difference_update(selected_for_scope - available)
        self._clamp_cursor()

    def _start_remote_discovery(self, *, force: bool) -> None:
        if self.discovery:
            self.discovery.cancel()
        self.remote_enabled = True
        self.skipped_hosts = 0
        hosts_to_probe: list[str] = []
        now = time.time()
        for host in self.hosts:
            entry = self.cache.host_entry(host)
            fresh = self.cache.is_fresh(host, now)
            if fresh and not force:
                if entry.get("reachable"):
                    self._replace_agent_scope(
                        local=False,
                        host=host,
                        records=self.cache.agents(host),
                    )
                    self.host_status[host] = self.text["cached"]
                else:
                    self._replace_agent_scope(
                        local=False,
                        host=host,
                        records=self.cache.agents(host, stale=True),
                    )
                    self.host_status[host] = self.text["unavailable"]
                    self.skipped_hosts += 1
                continue

            cached_agents = self.cache.agents(host, stale=True)
            self._replace_agent_scope(
                local=False,
                host=host,
                records=cached_agents,
            )
            self.host_status[host] = self.text["refreshing"]
            hosts_to_probe.append(host)

        self.pending_hosts = set(hosts_to_probe)
        if not hosts_to_probe:
            self.discovery = None
            self.status = self._discovery_summary()
            return
        self.discovery = RemoteDiscovery(hosts_to_probe, config_path=self.config_path)
        self.discovery.start()
        self.status = self.text["discovering"]

    def _discovery_summary(self) -> str:
        summary = self.text["discovery_complete"]
        if self.skipped_hosts:
            summary += " " + self.text["hosts_skipped"].format(count=self.skipped_hosts)
        return summary

    def _poll_discovery(self) -> None:
        if not self.discovery:
            return
        for result in self.discovery.poll():
            if result.host not in self.pending_hosts:
                continue
            self.pending_hosts.discard(result.host)
            self.cache.update(result)
            if result.success:
                self._replace_agent_scope(
                    local=False,
                    host=result.host,
                    records=result.agents,
                )
                self.host_status[result.host] = ""
            else:
                stale_agents = self.cache.agents(result.host, stale=True)
                self._replace_agent_scope(
                    local=False,
                    host=result.host,
                    records=stale_agents,
                )
                self.host_status[result.host] = self.text["unavailable"]
                self.skipped_hosts += 1
        if not self.pending_hosts:
            self.cache.save()
            self.discovery = None
            self.status = self._discovery_summary()
            return
        if time.monotonic() >= self.discovery.deadline:
            self.discovery.cancel()
            for host in tuple(self.pending_hosts):
                result = ProbeResult(host, (), False, "timeout")
                self.cache.update(result)
                self.host_status[host] = self.text["unavailable"]
                self.skipped_hosts += 1
            self.pending_hosts.clear()
            self.cache.save()
            self.discovery = None
            self.status = self._discovery_summary()

    def _cancel_discovery(self) -> None:
        if self.discovery:
            self.discovery.cancel()
            self.discovery = None
        self.pending_hosts.clear()
        self.status = self.text["discovery_cancelled"]

    def _clamp_cursor(self) -> None:
        records = self.filtered_agents()
        self.cursor = max(0, min(self.cursor, max(0, len(records) - 1)))

    def _safe_add(self, row: int, column: int, value: str, attribute: int = 0) -> None:
        height, width = self.screen.getmaxyx()
        if row < 0 or row >= height or column >= width - 1:
            return
        try:
            self.screen.addnstr(row, column, value, max(0, width - column - 1), attribute)
        except curses.error:
            pass

    def _render_choice(self, row: int) -> int:
        self._safe_add(
            row,
            0,
            self.text["discover_question"],
            self._style(PAIR_ACCENT, curses.A_BOLD),
        )
        options = (
            self.text["discover_remote_option"],
            self.text["local_only_option"],
        )
        for index, label in enumerate(options):
            marker = "›" if index == self.discovery_option else " "
            attribute = self._style(
                PAIR_ACCENT if index == self.discovery_option else 0,
                curses.A_REVERSE | curses.A_BOLD
                if index == self.discovery_option
                else 0,
            )
            self._safe_add(row + 2 + index, 2, f"{marker} {label}", attribute)
        return row + 5

    def _render_mode_choice(self, row: int) -> int:
        self._safe_add(
            row,
            0,
            self.text["mode_question"],
            self._style(PAIR_ACCENT, curses.A_BOLD),
        )
        options = (
            (
                self.text["delegate_option"],
                self.text["delegate_privacy"],
            ),
            (
                self.text["direct_option"],
                self.text["direct_privacy"],
            ),
        )
        for index, (label, description) in enumerate(options):
            marker = "›" if index == self.mode_option else " "
            attribute = self._style(
                PAIR_ACCENT if index == self.mode_option else 0,
                curses.A_REVERSE | curses.A_BOLD
                if index == self.mode_option
                else curses.A_BOLD,
            )
            option_row = row + 2 + index * 3
            self._safe_add(option_row, 2, f"{marker} {label}", attribute)
            self._safe_add(option_row + 1, 6, description, curses.A_DIM)
        return row + 8

    def _render_mode_summary(self, row: int) -> int:
        if self.delivery_mode == DELIVERY_DIRECT:
            label = self.text["direct_option"]
            description = self.text["direct_privacy"]
            pair = PAIR_WARNING
        else:
            label = self.text["delegate_option"]
            description = self.text["delegate_privacy"]
            pair = PAIR_SUCCESS
        self._safe_add(
            row,
            0,
            f'{self.text["delivery_mode"]}: {label}',
            self._style(pair, curses.A_BOLD),
        )
        self._safe_add(row + 1, 2, description, curses.A_DIM)
        return row + 2

    def _render_recipients(self, row: int, available_rows: int) -> int:
        records = self.filtered_agents()
        selected_count = len(self.selected)
        heading = f'{self.text["recipients"]}: {selected_count} {self.text["selected"]}'
        attribute = self._style(
            PAIR_ACCENT,
            curses.A_REVERSE if self.section == "recipients" else curses.A_BOLD,
        )
        self._safe_add(row, 0, heading, attribute)
        row += 1
        self._safe_add(
            row,
            0,
            f'{self.text["search"]}: {self.search}',
            self._style(PAIR_ACCENT),
        )
        row += 1

        list_rows = max(1, available_rows - 2)
        if self.cursor < self.recipient_offset:
            self.recipient_offset = self.cursor
        if self.cursor >= self.recipient_offset + list_rows:
            self.recipient_offset = self.cursor - list_rows + 1
        visible = records[self.recipient_offset : self.recipient_offset + list_rows]
        for visible_index, agent in enumerate(visible):
            absolute_index = self.recipient_offset + visible_index
            marker = "x" if agent.identity in self.selected else " "
            disabled = agent.stale
            state = (
                self.text["stale"]
                if disabled
                else self.text.get(f"status_{agent.status}", agent.status)
            )
            line = (
                f"[{marker}] {agent.host}/{agent.target:<20} "
                f"{state:<10} {agent.workspace_label}"
            )
            if disabled:
                line_attribute = curses.A_DIM
            elif agent.identity in self.selected:
                line_attribute = self._style(PAIR_SUCCESS, curses.A_BOLD)
            elif agent.status == "blocked":
                line_attribute = self._style(PAIR_ERROR)
            elif agent.status == "working":
                line_attribute = self._style(PAIR_WARNING)
            elif agent.status == "done":
                line_attribute = self._style(PAIR_SUCCESS)
            elif not agent.local:
                line_attribute = self._style(PAIR_REMOTE)
            else:
                line_attribute = 0
            if absolute_index == self.cursor and self.section == "recipients":
                line_attribute |= curses.A_REVERSE
            self._safe_add(row + visible_index, 0, line, line_attribute)
        return row + list_rows

    def _render_message(self, row: int, available_rows: int) -> int:
        attribute = self._style(
            PAIR_ACCENT,
            curses.A_REVERSE if self.section == "message" else curses.A_BOLD,
        )
        self._safe_add(row, 0, self.text["message"], attribute)
        row += 1
        visible_rows = max(2, available_rows - 1)
        _height, width = self.screen.getmaxyx()
        wrapped_lines, cursor_row, cursor_column = wrap_message_lines(
            self.message_lines,
            width=max(1, width - 4),
            cursor_row=self.message_row,
            cursor_column=self.message_column,
        )
        start = max(0, cursor_row - visible_rows + 1)
        visible_lines = wrapped_lines[start : start + visible_rows]
        for offset in range(visible_rows):
            marker = "│"
            if offset == 0 and start > 0:
                marker = "↑"
            elif (
                offset == visible_rows - 1
                and start + visible_rows < len(wrapped_lines)
            ):
                marker = "↓"
            self._safe_add(
                row + offset,
                0,
                marker,
                self._style(PAIR_ACCENT, curses.A_DIM),
            )
            line = visible_lines[offset].text if offset < len(visible_lines) else ""
            if not line and offset == 0 and self.message_lines == [""]:
                self._safe_add(
                    row + offset,
                    2,
                    self.text["message_placeholder"],
                    curses.A_DIM,
                )
            else:
                self._safe_add(row + offset, 2, line)
        if self.section == "message":
            self.message_cursor = (
                row + cursor_row - start,
                2 + cursor_column,
            )
        return row + visible_rows

    def render(self) -> None:
        self.screen.erase()
        self.message_cursor = None
        height, _width = self.screen.getmaxyx()
        self._safe_add(
            0,
            0,
            self.text["send_prompt"],
            self._style(PAIR_ACCENT, curses.A_BOLD),
        )
        self._safe_add(
            1,
            0,
            f'{self.text["coordinator"]}: {self.sender.qualified_name}',
            self._style(PAIR_SUCCESS),
        )
        row = 3

        if not self.discovery_choice:
            self._render_choice(row)
            self._safe_add(
                height - 1,
                0,
                self.text["help_discovery"],
                curses.A_DIM,
            )
            self._set_cursor_visibility(False)
            self.screen.refresh()
            return

        if not self.mode_choice:
            self._render_mode_choice(row)
            self._safe_add(
                height - 1,
                0,
                self.text["help_mode"],
                curses.A_DIM,
            )
            self._set_cursor_visibility(False)
            self.screen.refresh()
            return

        reserved_footer = 3
        row = self._render_mode_summary(row)
        content_height = max(6, height - row - reserved_footer)
        recipient_height = max(4, content_height // 2)
        row = self._render_recipients(row, recipient_height)
        row = self._render_message(row + 1, max(3, height - row - reserved_footer - 1))

        if self.remote_enabled:
            host_summary = "  ".join(
                f'{host}:{status or self.text["available"]}'
                for host, status in sorted(self.host_status.items())
            )
            self._safe_add(
                height - 3,
                0,
                host_summary,
                self._style(PAIR_REMOTE, curses.A_DIM),
            )
        self._safe_add(
            height - 2,
            0,
            self.status,
            self._style(PAIR_WARNING, curses.A_BOLD),
        )
        if self.sending:
            help_text = self.text["help_sending"]
        elif self.section == "message":
            help_text = self.text["help_message"]
        else:
            help_text = self.text["help_recipients"]
        self._safe_add(height - 1, 0, help_text, curses.A_DIM)
        if self.sending:
            self.message_cursor = None
        self._set_cursor_visibility(self.message_cursor is not None)
        if self.message_cursor is not None:
            try:
                self.screen.move(*self.message_cursor)
            except curses.error:
                pass
        self.screen.refresh()

    def _set_cursor_visibility(self, visible: bool) -> None:
        try:
            curses.curs_set(2 if visible else 0)
        except curses.error:
            pass

    def _toggle_current(self) -> None:
        records = self.filtered_agents()
        if not records:
            return
        agent = records[self.cursor]
        if agent.stale:
            return
        if agent.identity in self.selected:
            self.selected.remove(agent.identity)
        else:
            self.selected.add(agent.identity)

    def _handle_recipient_key(self, key: str | int) -> None:
        records = self.filtered_agents()
        if key == curses.KEY_UP:
            self.cursor = max(0, self.cursor - 1)
        elif key == curses.KEY_DOWN:
            self.cursor = min(max(0, len(records) - 1), self.cursor + 1)
        elif key == " ":
            self._toggle_current()
        elif key == "\t":
            self.section = "message"
        elif key in (curses.KEY_BACKSPACE, "\x7f", "\b"):
            self.search = self.search[:-1]
            self._clamp_cursor()
        elif key == "\x01":
            self.selected.update(agent.identity for agent in records if not agent.stale)
        elif key == "\x04":
            self.selected.clear()
        elif key == "\x12":
            local_agents = [
                agent
                for agent in query_local_agents(self.environment)
                if agent.local and agent.identity != self.sender.identity
            ]
            self._replace_agent_scope(
                local=True,
                host=self.sender.host,
                records=local_agents,
            )
            if self.remote_enabled:
                self._start_remote_discovery(force=True)
            self._clamp_cursor()
        elif isinstance(key, str) and key.isprintable() and key not in ("\n", "\r"):
            self.search += key
            self._clamp_cursor()

    def _handle_message_key(self, key: str | int) -> None:
        line = self.message_lines[self.message_row]
        if key == "\t":
            self.section = "recipients"
        elif key == "\x13":
            self._send()
        elif key in ("\n", "\r", curses.KEY_ENTER):
            before = line[: self.message_column]
            after = line[self.message_column :]
            self.message_lines[self.message_row] = before
            self.message_lines.insert(self.message_row + 1, after)
            self.message_row += 1
            self.message_column = 0
        elif key in (curses.KEY_BACKSPACE, "\x7f", "\b"):
            if self.message_column > 0:
                self.message_lines[self.message_row] = (
                    line[: self.message_column - 1] + line[self.message_column :]
                )
                self.message_column -= 1
            elif self.message_row > 0:
                previous = self.message_lines[self.message_row - 1]
                self.message_column = len(previous)
                self.message_lines[self.message_row - 1] = previous + line
                self.message_lines.pop(self.message_row)
                self.message_row -= 1
        elif key == curses.KEY_LEFT:
            if self.message_column > 0:
                self.message_column -= 1
        elif key == curses.KEY_RIGHT:
            if self.message_column < len(line):
                self.message_column += 1
        elif key == curses.KEY_UP:
            self._move_message_cursor_visual(-1)
        elif key == curses.KEY_DOWN:
            self._move_message_cursor_visual(1)
        elif isinstance(key, str) and key.isprintable():
            self.message_lines[self.message_row] = (
                line[: self.message_column] + key + line[self.message_column :]
            )
            self.message_column += len(key)

    def _move_message_cursor_visual(self, delta: int) -> None:
        _height, width = self.screen.getmaxyx()
        wrapped_lines, cursor_row, cursor_column = wrap_message_lines(
            self.message_lines,
            width=max(1, width - 4),
            cursor_row=self.message_row,
            cursor_column=self.message_column,
        )
        target_row = max(0, min(cursor_row + delta, len(wrapped_lines) - 1))
        if target_row == cursor_row:
            return
        target = wrapped_lines[target_row]
        column_offset = character_index_at_display_column(
            target.text,
            cursor_column,
        )
        self.message_row = target.logical_row
        self.message_column = target.start + column_offset

    def _send(self) -> None:
        if self.sending:
            return
        recipients = [
            agent
            for agent in self.agents
            if agent.identity in self.selected and not agent.stale
        ]
        message = "\n".join(self.message_lines).strip()
        if not recipients:
            self.status = self.text["no_recipients"]
            return
        if not message:
            self.status = self.text["empty_message"]
            return
        self.status = (
            self.text["delegating"]
            if self.delivery_mode == DELIVERY_DELEGATE
            else self.text["sending"]
        )
        self.sending = True
        self.send_cancel.clear()
        threading.Thread(
            target=self._dispatch_send_job,
            args=(tuple(recipients), message),
            daemon=True,
        ).start()

    def _dispatch_send_job(
        self,
        recipients: tuple[AgentRecord, ...],
        message: str,
    ) -> None:
        try:
            current_sender = fetch_local_agent(
                self.sender.pane_id,
                self.environment,
                cancel_event=self.send_cancel,
            )
            if not _same_occupant(self.sender, current_sender):
                self.send_results.put(SendJobResult(False, ()))
                return
            if self.send_cancel.is_set():
                self.send_results.put(SendJobResult(True, (), cancelled=True))
                return
            dispatch_recipients = recipients
            dispatch_message = message
            if self.delivery_mode == DELIVERY_DELEGATE:
                dispatch_recipients = (self.sender,)
                dispatch_message = build_orchestration_request(recipients, message)
            results = dispatch_prompts(
                self.sender,
                dispatch_recipients,
                dispatch_message,
                config_path=self.config_path,
                environment=self.environment,
                cancel_event=self.send_cancel,
            )
        except Exception as error:
            self.send_results.put(SendJobResult(True, (), str(error)))
            return
        self.send_results.put(
            SendJobResult(
                True,
                tuple(results),
                cancelled=self.send_cancel.is_set(),
            )
        )

    def _poll_send(self) -> None:
        try:
            job = self.send_results.get_nowait()
        except queue.Empty:
            return
        self.sending = False
        if job.cancelled:
            self.status = self.text["send_cancelled"]
            return
        if not job.sender_available:
            self.status = self.text["sender_unavailable"]
            return
        if job.error:
            self.status = (
                self.text["delegate_failed"]
                if self.delivery_mode == DELIVERY_DELEGATE
                else self.text["all_failed"]
            )
            return
        results = list(job.results)
        if not results:
            self.status = (
                self.text["delegate_failed"]
                if self.delivery_mode == DELIVERY_DELEGATE
                else self.text["all_failed"]
            )
            return
        succeeded = [result for result in results if result.success]
        failed = [result for result in results if not result.success]
        if not failed:
            if self.delivery_mode == DELIVERY_DELEGATE:
                body = self.text["delegated"]
            else:
                body = self.text["sent"].format(count=len(succeeded))
            show_notification(body, self.environment)
            self.running = False
            return
        if self.delivery_mode == DELIVERY_DELEGATE:
            self.status = self.text["delegate_failed"]
            return
        self.selected = {result.agent.identity for result in failed}
        if succeeded:
            self.status = self.text["partial_failure"].format(
                sent=len(succeeded),
                failed=len(failed),
            )
        else:
            self.status = self.text["all_failed"]

    def handle_key(self, key: str | int) -> None:
        if not self.discovery_choice:
            if key == curses.KEY_UP:
                self.discovery_option = (self.discovery_option - 1) % 2
            elif key == curses.KEY_DOWN:
                self.discovery_option = (self.discovery_option + 1) % 2
            elif key in ("\n", "\r", curses.KEY_ENTER, " "):
                self.discovery_choice = True
                if self.discovery_option == 0:
                    self._start_remote_discovery(force=False)
                else:
                    self.status = ""
            elif isinstance(key, str) and key.lower() == "d":
                self.discovery_choice = True
                self.discovery_option = 0
                self._start_remote_discovery(force=False)
            elif isinstance(key, str) and key.lower() == "l":
                self.discovery_choice = True
                self.discovery_option = 1
                self.status = ""
            elif key == "\x1b":
                self.running = False
            return

        if not self.mode_choice:
            if key == curses.KEY_UP:
                self.mode_option = (self.mode_option - 1) % 2
            elif key == curses.KEY_DOWN:
                self.mode_option = (self.mode_option + 1) % 2
            elif key in ("\n", "\r", curses.KEY_ENTER, " "):
                self.delivery_mode = (
                    DELIVERY_DELEGATE if self.mode_option == 0 else DELIVERY_DIRECT
                )
                self.mode_choice = True
                self.mode_return_to_editor = False
            elif isinstance(key, str) and key.lower() == "c":
                self.mode_option = 0
                self.delivery_mode = DELIVERY_DELEGATE
                self.mode_choice = True
                self.mode_return_to_editor = False
            elif isinstance(key, str) and key.lower() == "d":
                self.mode_option = 1
                self.delivery_mode = DELIVERY_DIRECT
                self.mode_choice = True
                self.mode_return_to_editor = False
            elif key == "\x1b":
                if self.mode_return_to_editor:
                    self.mode_choice = True
                    self.mode_return_to_editor = False
                elif self.hosts:
                    self.discovery_choice = False
                else:
                    self.running = False
            return

        if self.sending:
            if key == "\x1b":
                self.send_cancel.set()
                self.status = self.text["cancelling_send"]
            return

        if key == "\x1b":
            if self.discovery:
                self._cancel_discovery()
            else:
                self.running = False
            return
        if key == "\x0f":
            self.mode_option = 0 if self.delivery_mode == DELIVERY_DELEGATE else 1
            self.mode_choice = False
            self.mode_return_to_editor = True
            return
        if self.section == "recipients":
            self._handle_recipient_key(key)
        else:
            self._handle_message_key(key)

    def run(self) -> int:
        self._initialize_colors()
        self.screen.keypad(True)
        self.screen.timeout(100)
        while self.running:
            self._poll_discovery()
            self._poll_send()
            self.render()
            try:
                key = self.screen.get_wch()
            except curses.error:
                continue
            self.handle_key(key)
        if self.discovery:
            self.discovery.cancel()
        return 0


def popup(environment: Mapping[str, str] | None = None) -> int:
    values = dict(os.environ if environment is None else environment)
    text = messages(detect_language(values))
    pane_id = values.get(SENDER_PANE_ENV, "")
    sender = fetch_local_agent(pane_id, values) if pane_id else None
    if sender is None:
        if not show_notification(text["no_focused_agent"], values):
            print(text["no_focused_agent"], file=sys.stderr)
        return 0
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print(text["interactive_required"], file=sys.stderr)
        return 1
    try:
        locale.setlocale(locale.LC_ALL, "")
    except locale.Error:
        pass
    with terminal_flow_control_disabled(sys.stdin):
        return curses.wrapper(lambda screen: MessengerApp(screen, sender, values).run())


def parse_cli_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send prompts to Herdr agents.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("launch", help="Validate the focused agent and open the popup.")
    subparsers.add_parser("popup", help="Run the interactive popup.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parse_cli_arguments(argv)
    if arguments.command == "launch":
        return launch()
    return popup()


if __name__ == "__main__":
    raise SystemExit(main())
