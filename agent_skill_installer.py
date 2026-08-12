#!/usr/bin/env python3
"""Interactive installer for the bundled Herdr Agent Messenger skill."""

from __future__ import annotations

import argparse
import curses
import os
from pathlib import Path
import shutil
import sys
from typing import Mapping, Sequence

from agent_messenger import (
    bundled_skill_path,
    launch_plugin_popup,
    show_notification,
    wrap_display_text,
)
from messenger_i18n import detect_language


INSTALLER_ENTRYPOINT = "skill-installer"
INSTALLER_WIDTH = 52
INSTALLER_HEIGHT = 12
SKILL_NAME = "herdr-agent-messenger"

COPY = {
    "en": {
        "title": "Install Agent Skill",
        "intro": "Install or update the bundled skill for your coding agents.",
        "codex": "Codex",
        "claude": "Claude",
        "both": "Codex and Claude",
        "ready": "Select a destination and press Enter.",
        "installed": "Installed. Start a new agent session to load the skill.",
        "failed": "Installation failed: {error}",
        "help": "↑↓ Move  Enter Install  Esc Close",
        "open_failed": "Could not open the skill installer.",
    },
    "ko": {
        "title": "에이전트 스킬 설치",
        "intro": "내장 스킬을 코딩 에이전트용으로 설치하거나 업데이트합니다.",
        "codex": "Codex",
        "claude": "Claude",
        "both": "Codex와 Claude 모두",
        "ready": "설치 대상을 선택하고 Enter를 누르세요.",
        "installed": "설치했습니다. 새 에이전트 세션부터 스킬을 불러옵니다.",
        "failed": "설치 실패: {error}",
        "help": "↑↓ 이동  Enter 설치  Esc 닫기",
        "open_failed": "스킬 설치 창을 열 수 없습니다.",
    },
    "ja": {
        "title": "エージェントスキルをインストール",
        "intro": "同梱スキルをコーディングエージェント用にインストール・更新します。",
        "codex": "Codex",
        "claude": "Claude",
        "both": "Codex と Claude",
        "ready": "対象を選び Enter を押してください。",
        "installed": "インストールしました。新しいエージェントセッションから読み込まれます。",
        "failed": "インストール失敗: {error}",
        "help": "↑↓ 移動  Enter インストール  Esc 閉じる",
        "open_failed": "スキルインストーラーを開けませんでした。",
    },
}


def install_destinations(
    environment: Mapping[str, str] | None = None,
) -> dict[str, Path]:
    values = os.environ if environment is None else environment
    home = Path(values.get("HOME") or Path.home()).expanduser()
    return {
        "codex": home / ".agents" / "skills" / SKILL_NAME,
        "claude": home / ".claude" / "skills" / SKILL_NAME,
    }


def _is_managed_destination(destination: Path) -> bool:
    skill_file = destination / "SKILL.md"
    script_file = destination / "scripts" / "herdr_agent_messenger.py"
    try:
        contents = skill_file.read_text(encoding="utf-8")
    except OSError:
        return False
    return "name: herdr-agent-messenger" in contents and script_file.is_file()


def install_skill(destination: Path, source: Path | None = None) -> None:
    source_directory = (
        bundled_skill_path().parent if source is None else source
    ).resolve()
    if destination.is_symlink() or (
        destination.exists() and not destination.is_dir()
    ):
        raise OSError(f"destination is not a managed skill directory: {destination}")
    if destination.exists() and not _is_managed_destination(destination):
        raise OSError(f"refusing to overwrite an unrelated skill: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_directory, destination, dirs_exist_ok=True)


def install_selected(
    selection: str,
    environment: Mapping[str, str] | None = None,
) -> list[Path]:
    destinations = install_destinations(environment)
    if selection not in {"codex", "claude", "both"}:
        raise ValueError(f"unknown installation target: {selection}")
    names = ("codex", "claude") if selection == "both" else (selection,)
    installed: list[Path] = []
    for name in names:
        destination = destinations[name]
        install_skill(destination)
        installed.append(destination)
    return installed


def launch(environment: Mapping[str, str] | None = None) -> int:
    language = detect_language(environment)
    text = COPY[language]
    if launch_plugin_popup(
        INSTALLER_ENTRYPOINT,
        width=INSTALLER_WIDTH,
        height=INSTALLER_HEIGHT,
        environment=environment,
    ):
        return 0
    if not show_notification(text["open_failed"], environment):
        print(text["open_failed"], file=sys.stderr)
    return 1


def popup(environment: Mapping[str, str] | None = None) -> int:
    values = dict(os.environ if environment is None else environment)
    text = COPY[detect_language(values)]
    options = (
        ("codex", text["codex"]),
        ("claude", text["claude"]),
        ("both", text["both"]),
    )

    def run(screen: curses.window) -> int:
        screen.keypad(True)
        cursor = 0
        status = text["ready"]
        while True:
            screen.erase()
            height, width = screen.getmaxyx()

            def add(row: int, column: int, value: str, attribute: int = 0) -> None:
                if not (0 <= row < height and 0 <= column < width):
                    return
                try:
                    screen.addnstr(
                        row,
                        column,
                        value,
                        max(0, width - column - 1),
                        attribute,
                    )
                except curses.error:
                    pass

            add(0, 0, text["title"], curses.A_BOLD)
            row = 2
            for line in wrap_display_text(text["intro"], max(1, width - 4)):
                add(row, 2, line)
                row += 1
            row += 1
            for index, (_key, label) in enumerate(options):
                marker = "›" if index == cursor else " "
                attribute = curses.A_REVERSE | curses.A_BOLD if index == cursor else 0
                add(row, 2, f"{marker} {label}", attribute)
                row += 1
            row += 1
            for line in wrap_display_text(status, max(1, width - 2)):
                add(min(row, height - 2), 0, line, curses.A_BOLD)
                row += 1
            add(height - 1, 0, text["help"], curses.A_DIM)
            try:
                curses.curs_set(0)
            except curses.error:
                pass
            screen.refresh()

            key = screen.get_wch()
            if key == curses.KEY_UP:
                cursor = (cursor - 1) % len(options)
            elif key == curses.KEY_DOWN:
                cursor = (cursor + 1) % len(options)
            elif key in ("\n", "\r", curses.KEY_ENTER, " "):
                try:
                    install_selected(options[cursor][0], values)
                    status = text["installed"]
                except OSError as error:
                    status = text["failed"].format(error=error)
            elif key in ("\x1b", "q", "Q"):
                return 0

    return curses.wrapper(run)


def parse_cli_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install the Agent Messenger skill.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("launch")
    subparsers.add_parser("popup")
    install_parser = subparsers.add_parser("install")
    install_parser.add_argument("target", choices=("codex", "claude", "both"))
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parse_cli_arguments(argv)
    if arguments.command == "launch":
        return launch()
    if arguments.command == "popup":
        return popup()
    try:
        install_selected(arguments.target)
    except OSError as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
