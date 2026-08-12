"""Run the Agent Messenger skill CLI from a managed plugin checkout."""

from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path


def find_plugin_root(
    script_path: Path | None = None,
    runner=subprocess.run,
) -> Path:
    source_path = Path(__file__) if script_path is None else script_path
    for bundled_root in source_path.resolve().parents:
        if (bundled_root / "agent_skill_cli.py").is_file():
            return bundled_root

    try:
        result = runner(
            [
                "herdr",
                "plugin",
                "list",
                "--json",
                "--plugin",
                "herdr.agent-labels",
            ],
            capture_output=True,
            check=False,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise SystemExit(
            "Could not query the installed herdr.agent-labels plugin."
        ) from error
    try:
        payload = json.loads(result.stdout)
        plugins = payload["result"]["plugins"]
        installed_root = Path(plugins[0]["plugin_root"])
    except (IndexError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(
            "Could not locate the installed herdr.agent-labels plugin."
        ) from error
    if result.returncode != 0 or not (installed_root / "agent_skill_cli.py").is_file():
        raise SystemExit(
            "The installed herdr.agent-labels plugin does not include the skill CLI."
        )
    return installed_root


PLUGIN_ROOT = find_plugin_root()
sys.path.insert(0, str(PLUGIN_ROOT))
main = importlib.import_module("agent_skill_cli").main


if __name__ == "__main__":
    raise SystemExit(main())
