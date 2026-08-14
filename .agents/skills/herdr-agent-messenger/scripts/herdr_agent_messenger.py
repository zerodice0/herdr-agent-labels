"""Run the Agent Messenger skill CLI from a managed plugin checkout."""

from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path


PLUGIN_IDS = ("herdr.agent-messenger", "herdr.agent-labels")


def find_plugin_root(
    script_path: Path | None = None,
    runner=subprocess.run,
) -> Path:
    source_path = Path(__file__) if script_path is None else script_path
    for bundled_root in source_path.resolve().parents:
        if (bundled_root / "agent_skill_cli.py").is_file():
            return bundled_root

    last_error: Exception | None = None
    for plugin_id in PLUGIN_IDS:
        try:
            result = runner(
                [
                    "herdr",
                    "plugin",
                    "list",
                    "--json",
                    "--plugin",
                    plugin_id,
                ],
                capture_output=True,
                check=False,
                text=True,
                timeout=10,
            )
            payload = json.loads(result.stdout)
            plugins = payload["result"]["plugins"]
            installed_root = Path(plugins[0]["plugin_root"])
        except (
            IndexError,
            KeyError,
            OSError,
            subprocess.TimeoutExpired,
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ) as error:
            last_error = error
            continue
        if result.returncode == 0 and (installed_root / "agent_skill_cli.py").is_file():
            return installed_root

    raise SystemExit(
        "Could not locate HAM as herdr.agent-messenger or the legacy "
        "herdr.agent-labels plugin."
    ) from last_error


PLUGIN_ROOT = find_plugin_root()
sys.path.insert(0, str(PLUGIN_ROOT))
main = importlib.import_module("agent_skill_cli").main


if __name__ == "__main__":
    raise SystemExit(main())
