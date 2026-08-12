#!/usr/bin/env python3
"""Assign unique, human-readable names to unnamed Herdr agents."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from typing import Any, Iterator, NamedTuple


SOURCE = "herdr.agent-labels"
SEED_HASH_BYTES = 4
# Coprime with the current alias count, so every alias is visited exactly once.
CANDIDATE_STRIDE = 37


class Alias(NamedTuple):
    name: str
    marker: str
    color: str


COLORS = (
    ("white", "⬜"),
    ("blue", "🟦"),
    ("green", "🟩"),
    ("yellow", "🟨"),
    ("orange", "🟧"),
    ("red", "🟥"),
    ("purple", "🟪"),
    ("brown", "🟫"),
)
ANIMALS = (
    "owl",
    "otter",
    "fox",
    "raven",
    "panda",
    "koala",
    "tiger",
    "gecko",
    "heron",
    "wolf",
    "seal",
    "yak",
    "badger",
    "falcon",
    "rabbit",
    "turtle",
    "bear",
    "beaver",
    "bison",
    "camel",
    "cobra",
    "crane",
    "deer",
    "dolphin",
    "eagle",
    "ferret",
    "frog",
    "horse",
    "lemur",
    "lynx",
    "moose",
    "penguin",
)
ALIASES = tuple(
    Alias(name=f"{color}-{animal}", marker=marker, color=color)
    for color, marker in COLORS
    for animal in ANIMALS
)


def run_herdr(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["herdr", *args],
        capture_output=True,
        check=False,
        text=True,
    )


def decode_json(value: str) -> dict[str, Any]:
    try:
        decoded = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def read_json_environment_variable(name: str) -> dict[str, Any]:
    value = os.environ.get(name)
    if value is None:
        return {}
    return decode_json(value)


def event_data() -> dict[str, Any]:
    payload = read_json_environment_variable("HERDR_PLUGIN_EVENT_JSON")
    data = payload.get("data")
    return data if isinstance(data, dict) else payload


def context_pane_id() -> str:
    context = read_json_environment_variable("HERDR_PLUGIN_CONTEXT_JSON")
    return str(
        context.get("focused_pane_id")
        or context.get("pane_id")
        or os.environ.get("HERDR_PANE_ID")
        or ""
    )


def fetch_agent_info(pane_id: str) -> dict[str, Any]:
    result = run_herdr("agent", "get", pane_id)
    if result.returncode != 0:
        return {}
    payload = decode_json(result.stdout)
    result_data = payload.get("result")
    if not isinstance(result_data, dict):
        return {}
    agent_data = result_data.get("agent")
    return agent_data if isinstance(agent_data, dict) else {}


def clear_agent_label_metadata(pane_id: str) -> None:
    run_herdr(
        "pane",
        "report-metadata",
        pane_id,
        "--source",
        SOURCE,
        "--clear-display-agent",
        "--clear-token",
        "alias",
        "--clear-token",
        "color",
    )


def report_agent_label_metadata(
    pane_id: str,
    agent: str,
    alias: str,
    marker: str,
    color: str,
) -> None:
    run_herdr(
        "pane",
        "report-metadata",
        pane_id,
        "--source",
        SOURCE,
        "--agent",
        agent,
        "--display-agent",
        f"{marker} {alias}",
        "--token",
        f"alias={alias}",
        "--token",
        f"color={color}",
    )


def candidates(seed: str) -> Iterator[Alias]:
    digest = hashlib.sha256(seed.encode()).digest()
    start = int.from_bytes(digest[:SEED_HASH_BYTES], "big") % len(ALIASES)
    for offset in range(len(ALIASES)):
        index = (start + offset * CANDIDATE_STRIDE) % len(ALIASES)
        yield ALIASES[index]


def assign_label(pane_id: str) -> int:
    info = fetch_agent_info(pane_id)
    if not info:
        return 0
    if info.get("name") or info.get("agent_name"):
        return 0

    agent = str(info.get("agent") or "")
    if not agent:
        return 0
    session_data = info.get("agent_session")
    session = session_data if isinstance(session_data, dict) else {}
    terminal_id = str(info.get("terminal_id") or pane_id)
    session_id = str(session.get("value") or "")
    seed = f"{terminal_id}:{session_id}"

    for candidate in candidates(seed):
        renamed = run_herdr("agent", "rename", pane_id, candidate.name)
        if renamed.returncode == 0:
            report_agent_label_metadata(
                pane_id,
                agent,
                candidate.name,
                candidate.marker,
                candidate.color,
            )
            print(candidate.name)
            return 0
        if "agent_name_taken" not in renamed.stderr:
            return 0
    return 1


def handle_event() -> int:
    data = event_data()
    pane_id = str(data.get("pane_id") or "")
    if not pane_id:
        return 0
    if data.get("released") or not data.get("agent"):
        clear_agent_label_metadata(pane_id)
        return 0
    return assign_label(pane_id)


def parse_cli_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Assign a readable label to an unnamed Herdr agent."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "event",
        help="Handle an agent detection event from Herdr.",
    )

    label_parser = subparsers.add_parser(
        "label",
        help="Assign a label to an agent pane.",
    )
    label_parser.add_argument(
        "pane_id",
        nargs="?",
        help="Pane ID to label; defaults to the focused pane.",
    )

    return parser.parse_args(argv)


def main() -> int:
    arguments = parse_cli_arguments()

    if arguments.command == "event":
        return handle_event()

    pane_id = arguments.pane_id or context_pane_id()
    if not pane_id:
        return 1

    return assign_label(pane_id)


if __name__ == "__main__":
    raise SystemExit(main())
