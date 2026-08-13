#!/usr/bin/env python3
"""Interactive installer for the bundled Herdr Agent Messenger skill."""

from __future__ import annotations

import argparse
import curses
from dataclasses import dataclass
import filecmp
import os
from pathlib import Path
import shutil
import sys
from typing import Mapping, Sequence

from agent_messenger import (
    bundled_skill_path,
    decode_json_object,
    display_width,
    launch_plugin_popup,
    SKILL_INSTALLER_ENTRYPOINT,
    SKILL_INSTALLER_HEIGHT,
    SKILL_INSTALLER_WIDTH,
    SKILL_PROJECT_ROOT_ENV,
    shortcut_help_spans,
    show_notification,
    wrap_display_text,
)
from messenger_i18n import detect_language


SKILL_NAME = "herdr-agent-messenger"
STATUS_CURRENT = "current"
STATUS_OUTDATED = "outdated"
STATUS_MISSING = "missing"
STATUS_CONFLICT = "conflict"
STATUS_UNAVAILABLE = "unavailable"
STATUS_BADGES = {
    STATUS_CURRENT: "✓",
    STATUS_OUTDATED: "↑",
    STATUS_MISSING: "○",
    STATUS_CONFLICT: "!",
    STATUS_UNAVAILABLE: "–",
}


@dataclass(frozen=True)
class InstallTarget:
    scope: str
    agent: str
    destination: Path | None

COPY = {
    "en": {
        "title": "Install Agent Skill",
        "intro": "Select where the bundled skill should be available.",
        "project": "Project",
        "system": "System",
        "codex": "Codex",
        "claude": "Claude",
        "current": "Current",
        "outdated": "Update available",
        "missing": "Not installed",
        "conflict": "Conflicting files",
        "unavailable": "Project unavailable",
        "ready": "Select a target and press Enter.",
        "already_current": "Already current.",
        "installed": "Installed. Start a new agent session to load it.",
        "failed": "Installation failed: {error}",
        "usage_title": "Usage",
        "usage_intro": "Address a current agent with its SSH host and Agent Labels name.",
        "usage_target": "Target: host/label",
        "usage_example": "Example: Ask macbook-pro/purple-koala for a status report.",
        "help": "↑↓ Move  Enter Install/Update  ? Usage  Esc Close",
        "usage_help": "? Back  Esc Back",
        "open_failed": "Could not open the skill installer.",
    },
    "ko": {
        "title": "에이전트 스킬 설치",
        "intro": "내장 스킬을 사용할 범위를 선택하세요.",
        "project": "프로젝트",
        "system": "시스템",
        "codex": "Codex",
        "claude": "Claude",
        "current": "최신",
        "outdated": "업데이트 가능",
        "missing": "설치되지 않음",
        "conflict": "다른 파일과 충돌",
        "unavailable": "프로젝트를 확인할 수 없음",
        "ready": "대상을 선택하고 Enter를 누르세요.",
        "already_current": "이미 최신 상태입니다.",
        "installed": "설치했습니다. 새 에이전트 세션부터 불러옵니다.",
        "failed": "설치 실패: {error}",
        "usage_title": "사용법",
        "usage_intro": "SSH 호스트와 Agent Labels 이름으로 현재 에이전트를 지정합니다.",
        "usage_target": "대상: host/label",
        "usage_example": "예: macbook-pro/purple-koala에게 상태 보고를 요청해줘.",
        "help": "↑↓ 이동  Enter 설치/업데이트  ? 사용법  Esc 닫기",
        "usage_help": "? 뒤로  Esc 뒤로",
        "open_failed": "스킬 설치 창을 열 수 없습니다.",
    },
    "ja": {
        "title": "エージェントスキルをインストール",
        "intro": "同梱スキルを使用する範囲を選択してください。",
        "project": "プロジェクト",
        "system": "システム",
        "codex": "Codex",
        "claude": "Claude",
        "current": "最新",
        "outdated": "更新可能",
        "missing": "未インストール",
        "conflict": "別のファイルと競合",
        "unavailable": "プロジェクトを確認できません",
        "ready": "対象を選び Enter を押してください。",
        "already_current": "すでに最新です。",
        "installed": "インストールしました。新しいセッションから読み込まれます。",
        "failed": "インストール失敗: {error}",
        "usage_title": "使い方",
        "usage_intro": "SSH ホストと Agent Labels 名で現在のエージェントを指定します。",
        "usage_target": "宛先: host/label",
        "usage_example": "例: macbook-pro/purple-koala に状態報告を依頼する。",
        "help": "↑↓ 移動  Enter インストール/更新  ? 使い方  Esc 閉じる",
        "usage_help": "? 戻る  Esc 戻る",
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


def project_root(environment: Mapping[str, str] | None = None) -> Path | None:
    values = os.environ if environment is None else environment
    explicit = values.get(SKILL_PROJECT_ROOT_ENV)
    context = decode_json_object(values.get("HERDR_PLUGIN_CONTEXT_JSON", "{}"))
    workspace = context.get("workspace")
    nested_cwd = workspace.get("cwd") if isinstance(workspace, dict) else None
    raw_path = explicit or context.get("workspace_cwd") or nested_cwd
    if not isinstance(raw_path, str) or not raw_path.strip():
        return None
    return Path(raw_path).expanduser().resolve()


def installation_targets(
    environment: Mapping[str, str] | None = None,
) -> tuple[InstallTarget, ...]:
    values = os.environ if environment is None else environment
    root = project_root(values)
    system = install_destinations(values)
    project = {
        "codex": root / ".agents" / "skills" / SKILL_NAME if root else None,
        "claude": root / ".claude" / "skills" / SKILL_NAME if root else None,
    }
    return tuple(
        InstallTarget(scope, agent, destinations[agent])
        for scope, destinations in (("project", project), ("system", system))
        for agent in ("codex", "claude")
    )


def _bundled_claude_skill_path() -> Path:
    return bundled_skill_path().parents[3] / ".claude" / "skills" / SKILL_NAME


def _source_files(source: Path) -> list[Path]:
    return sorted(
        path
        for path in source.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix not in {".pyc", ".pyo"}
        and path.name != ".DS_Store"
    )


def _matches_source(destination: Path, source: Path) -> bool:
    try:
        if destination.resolve() == source.resolve():
            return True
        source_files = _source_files(source)
        return bool(source_files) and all(
            (destination / path.relative_to(source)).is_file()
            and filecmp.cmp(
                path,
                destination / path.relative_to(source),
                shallow=False,
            )
            for path in source_files
        )
    except OSError:
        return False


def _is_managed_destination(destination: Path) -> bool:
    skill_file = destination / "SKILL.md"
    script_file = destination / "scripts" / "herdr_agent_messenger.py"
    try:
        contents = skill_file.read_text(encoding="utf-8")
    except OSError:
        return False
    canonical = "name: herdr-agent-messenger" in contents and script_file.is_file()
    claude_bridge = (
        "name: herdr-agent-messenger" in contents
        and "../../../.agents/skills/herdr-agent-messenger/SKILL.md" in contents
    )
    return canonical or claude_bridge


def installation_status(destination: Path | None) -> str:
    if destination is None:
        return STATUS_UNAVAILABLE
    if not destination.exists():
        return STATUS_MISSING
    if destination.is_symlink() or not destination.is_dir():
        return STATUS_CONFLICT
    if not _is_managed_destination(destination):
        return STATUS_CONFLICT
    sources = (bundled_skill_path().parent, _bundled_claude_skill_path())
    if any(source.is_dir() and _matches_source(destination, source) for source in sources):
        return STATUS_CURRENT
    return STATUS_OUTDATED


def install_skill(destination: Path, source: Path | None = None) -> None:
    source_directory = (
        bundled_skill_path().parent if source is None else source
    ).resolve()
    if destination.resolve() == source_directory:
        return
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


def install_target(target: InstallTarget) -> Path:
    if target.destination is None:
        raise OSError("project workspace is unavailable")
    install_skill(target.destination)
    return target.destination


def launch(environment: Mapping[str, str] | None = None) -> int:
    language = detect_language(environment)
    text = COPY[language]
    root = project_root(environment)
    extra_arguments: tuple[str, ...] = ()
    if root is not None:
        extra_arguments = ("--env", f"{SKILL_PROJECT_ROOT_ENV}={root}")
    if launch_plugin_popup(
        SKILL_INSTALLER_ENTRYPOINT,
        width=SKILL_INSTALLER_WIDTH,
        height=SKILL_INSTALLER_HEIGHT,
        environment=environment,
        extra_arguments=extra_arguments,
    ):
        return 0
    if not show_notification(text["open_failed"], environment):
        print(text["open_failed"], file=sys.stderr)
    return 1


def popup(environment: Mapping[str, str] | None = None) -> int:
    values = dict(os.environ if environment is None else environment)
    text = COPY[detect_language(values)]
    targets = installation_targets(values)

    def run(screen: curses.window) -> int:
        screen.keypad(True)
        cursor = 0
        status = text["ready"]
        usage_visible = False
        colors_enabled = False
        if curses.has_colors():
            try:
                curses.start_color()
                try:
                    curses.use_default_colors()
                    background = -1
                except curses.error:
                    background = curses.COLOR_BLACK
                curses.init_pair(1, curses.COLOR_GREEN, background)
                curses.init_pair(2, curses.COLOR_YELLOW, background)
                curses.init_pair(3, curses.COLOR_RED, background)
                curses.init_pair(4, curses.COLOR_CYAN, background)
                colors_enabled = True
            except curses.error:
                pass

        def badge_style(skill_status: str) -> int:
            if not colors_enabled:
                return curses.A_BOLD
            pair = {
                STATUS_CURRENT: 1,
                STATUS_OUTDATED: 2,
                STATUS_CONFLICT: 3,
            }.get(skill_status)
            return curses.color_pair(pair) | curses.A_BOLD if pair else curses.A_DIM

        def render_footer(value: str, height: int, width: int) -> int:
            lines = shortcut_help_spans(value, max(1, width - 1))
            start = max(0, height - len(lines))
            key_attribute = curses.A_BOLD
            if colors_enabled:
                key_attribute |= curses.color_pair(4)
            for offset, spans in enumerate(lines):
                column = 0
                for span in spans:
                    add(
                        start + offset,
                        column,
                        span.text,
                        key_attribute if span.keycap else curses.A_DIM,
                    )
                    column += display_width(span.text)
            return len(lines)

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

            if usage_visible:
                add(0, 0, text["usage_title"], curses.A_BOLD)
                row = 2
                for value in (
                    text["usage_intro"],
                    "",
                    text["usage_target"],
                    "",
                    text["usage_example"],
                ):
                    if not value:
                        row += 1
                        continue
                    for line in wrap_display_text(value, max(1, width - 4)):
                        add(row, 2, line)
                        row += 1
                render_footer(text["usage_help"], height, width)
                try:
                    curses.curs_set(0)
                except curses.error:
                    pass
                screen.refresh()
                key = screen.get_wch()
                if key in ("?", "\x1b", "q", "Q", "\n", "\r", curses.KEY_ENTER):
                    usage_visible = False
                continue

            add(0, 0, text["title"], curses.A_BOLD)
            row = 1
            for line in wrap_display_text(text["intro"], max(1, width - 4)):
                add(row, 2, line)
                row += 1
            row += 1
            for scope in ("project", "system"):
                scope_targets = [target for target in targets if target.scope == scope]
                scope_label = text[scope]
                if scope == "project":
                    root = project_root(values)
                    if root is not None:
                        scope_label += f" · {root.name}"
                add(row, 2, scope_label, curses.A_BOLD)
                row += 1
                for target in scope_targets:
                    index = targets.index(target)
                    selected = index == cursor
                    marker = "›" if selected else " "
                    attribute = curses.A_REVERSE | curses.A_BOLD if selected else 0
                    skill_status = installation_status(target.destination)
                    add(row, 4, f"{marker} {text[target.agent]}", attribute)
                    badge = f" {STATUS_BADGES[skill_status]} "
                    add(
                        row,
                        max(4, width - len(badge) - 2),
                        badge,
                        badge_style(skill_status) | curses.A_REVERSE,
                    )
                    row += 1
                row += 1
            row += 1
            footer_line_count = len(
                shortcut_help_spans(text["help"], max(1, width - 1))
            )
            footer_start = height - footer_line_count
            selected_status = installation_status(targets[cursor].destination)
            detail = f"{STATUS_BADGES[selected_status]} {text[selected_status]}"
            add(min(row, footer_start - 2), 2, detail, badge_style(selected_status))
            row += 1
            for line in wrap_display_text(status, max(1, width - 2)):
                add(min(row, footer_start - 1), 0, line)
                row += 1
            render_footer(text["help"], height, width)
            try:
                curses.curs_set(0)
            except curses.error:
                pass
            screen.refresh()

            key = screen.get_wch()
            if key == "?":
                usage_visible = True
            elif key == curses.KEY_UP:
                cursor = (cursor - 1) % len(targets)
            elif key == curses.KEY_DOWN:
                cursor = (cursor + 1) % len(targets)
            elif key in ("\n", "\r", curses.KEY_ENTER, " "):
                target = targets[cursor]
                try:
                    if installation_status(target.destination) == STATUS_CURRENT:
                        status = text["already_current"]
                    else:
                        install_target(target)
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
