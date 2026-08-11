#!/usr/bin/env python3
"""Assign unique, human-readable names to unnamed Herdr agents."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from typing import Any


SOURCE = "herdr.agent-labels"
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
)
ALIASES = tuple(
    (f"{color}-{animal}", marker, color)
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


def event_data() -> dict[str, Any]:
    payload = decode_json(os.environ.get("HERDR_PLUGIN_EVENT_JSON", "{}"))
    data = payload.get("data")
    return data if isinstance(data, dict) else payload


def context_pane_id() -> str:
    context = decode_json(os.environ.get("HERDR_PLUGIN_CONTEXT_JSON", "{}"))
    return str(
        context.get("focused_pane_id")
        or context.get("pane_id")
        or os.environ.get("HERDR_PANE_ID")
        or ""
    )


def agent_info(pane_id: str) -> dict[str, Any]:
    result = run_herdr("agent", "get", pane_id)
    if result.returncode != 0:
        return {}
    payload = decode_json(result.stdout)
    agent = payload.get("result", {}).get("agent", {})
    return agent if isinstance(agent, dict) else {}


def clear_display(pane_id: str) -> None:
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


def report_display(pane_id: str, agent: str, alias: str, marker: str, color: str) -> None:
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


def candidates(seed: str):
    start = int.from_bytes(hashlib.sha256(seed.encode()).digest()[:4], "big") % len(ALIASES)
    for offset in range(len(ALIASES)):
        yield ALIASES[(start + offset * 37) % len(ALIASES)]


def assign_label(pane_id: str) -> int:
    info = agent_info(pane_id)
    if not info:
        return 0
    if info.get("name") or info.get("agent_name"):
        return 0

    agent = str(info.get("agent") or "")
    if not agent:
        return 0
    session = info.get("agent_session") or {}
    seed = f"{info.get('terminal_id', pane_id)}:{session.get('value', '')}"

    for alias, marker, color in candidates(seed):
        renamed = run_herdr("agent", "rename", pane_id, alias)
        if renamed.returncode == 0:
            report_display(pane_id, agent, alias, marker, color)
            print(alias)
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
        clear_display(pane_id)
        return 0
    return assign_label(pane_id)


def main() -> int:
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "event":
        return handle_event()
    if command == "label":
        pane_id = sys.argv[2] if len(sys.argv) > 2 else context_pane_id()
        return assign_label(pane_id) if pane_id else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
