#!/usr/bin/env python3

from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock

import agent_directory
import agent_messenger
import messenger_i18n


def agent(
    *,
    name: str = "blue-raven",
    pane_id: str = "w1:p1",
    session_id: str = "session-1",
    workspace_label: str = "project",
    workspace_is_worktree: bool = False,
) -> agent_directory.AgentRecord:
    return agent_directory.AgentRecord(
        host="local",
        name=name,
        pane_id=pane_id,
        workspace_id="w1",
        workspace_label=workspace_label,
        status="idle",
        session_id=session_id,
        cwd="/work/project",
        local=True,
        revision=1,
        agent_kind="codex",
        terminal_id=f"terminal-{pane_id}",
        workspace_is_worktree=workspace_is_worktree,
    )


class ImmediateThread:
    def __init__(self, *, target, args=(), **_kwargs):
        self.target = target
        self.args = args

    def start(self):
        self.target(*self.args)


class AgentMessengerTest(unittest.TestCase):
    def test_agents_sort_by_workspace_before_status_and_label(self):
        sender = agent()
        zeta = agent(
            name="alpha-agent",
            pane_id="w1:p2",
            session_id="session-2",
            workspace_label="한글 작업공간",
        )
        alpha = agent(
            name="zeta-agent",
            pane_id="w2:p1",
            session_id="session-3",
            workspace_label="alpha-worktree",
            workspace_is_worktree=True,
        )
        with tempfile.TemporaryDirectory() as state_directory:
            environment = {
                "LANG": "ko_KR.UTF-8",
                "HERDR_PLUGIN_STATE_DIR": state_directory,
            }
            with (
                mock.patch.object(
                    agent_messenger,
                    "query_local_agents",
                    return_value=[sender, zeta, alpha],
                ),
                mock.patch.object(agent_messenger, "ssh_hosts", return_value=[]),
            ):
                app = agent_messenger.MessengerApp(mock.Mock(), sender, environment)

        self.assertEqual(
            [record.name for record in app.filtered_agents()],
            ["zeta-agent", "alpha-agent"],
        )
        self.assertEqual(agent_messenger.workspace_display(alpha), "WT:alpha-worktree")
        self.assertEqual(agent_messenger.workspace_display(zeta), "한글 작업공간")

    def test_narrow_recipient_line_preserves_unicode_workspace_and_target(self):
        record = agent(
            name="white-bison",
            workspace_label="결제 기능 작업트리",
            workspace_is_worktree=True,
        )
        sender = agent(name="blue-raven", pane_id="w1:p9", session_id="sender")
        screen = mock.Mock()
        screen.getmaxyx.return_value = (25, 58)
        with tempfile.TemporaryDirectory() as state_directory:
            environment = {"HERDR_PLUGIN_STATE_DIR": state_directory}
            with (
                mock.patch.object(
                    agent_messenger,
                    "query_local_agents",
                    return_value=[sender, record],
                ),
                mock.patch.object(agent_messenger, "ssh_hosts", return_value=[]),
            ):
                app = agent_messenger.MessengerApp(screen, sender, environment)

        line = app._recipient_line(record, " ", "idle")
        self.assertLessEqual(agent_messenger.display_width(line), 58)
        self.assertIn("WT:결제 기능", line)
        self.assertIn("white-bison", line)

    def test_focused_pane_id_prefers_plugin_context(self):
        environment = {
            "HERDR_PLUGIN_CONTEXT_JSON": '{"focused_pane_id":"w2:p3"}',
            "HERDR_ACTIVE_PANE_ID": "w1:p1",
        }
        self.assertEqual(agent_messenger.focused_pane_id(environment), "w2:p3")

    def test_launch_notifies_when_focused_pane_has_no_agent(self):
        environment = {"HERDR_PANE_ID": "w1:p1", "LANG": "en_US.UTF-8"}
        with (
            mock.patch.object(agent_messenger, "fetch_local_agent", return_value=None),
            mock.patch.object(agent_messenger, "show_notification", return_value=True) as notify,
            mock.patch.object(agent_messenger, "launch_popup") as popup,
        ):
            self.assertEqual(agent_messenger.launch(environment), 0)
        self.assertIn("No agent is running", notify.call_args.args[0])
        popup.assert_not_called()

    def test_launch_opens_popup_for_focused_agent(self):
        environment = {"HERDR_PANE_ID": "w1:p1", "LANG": "en_US.UTF-8"}
        with (
            mock.patch.object(agent_messenger, "fetch_local_agent", return_value=agent()),
            mock.patch.object(agent_messenger, "launch_popup", return_value=True) as popup,
        ):
            self.assertEqual(agent_messenger.launch(environment), 0)
        popup.assert_called_once_with("w1:p1", environment)

    def test_launch_popup_uses_compact_dimensions(self):
        completed = mock.Mock(returncode=0)
        with mock.patch.object(agent_messenger, "run_herdr", return_value=completed) as run:
            self.assertTrue(agent_messenger.launch_popup("w1:p1", {}))
        arguments = run.call_args.args[0]
        self.assertEqual(arguments[arguments.index("--width") + 1], "88")
        self.assertEqual(arguments[arguments.index("--height") + 1], "23")

    def test_popup_dimensions_fit_small_viewport(self):
        layout = mock.Mock(
            returncode=0,
            stdout=(
                '{"result":{"layout":{"area":{"width":80,"height":29}}}}'
            ),
        )
        opened = mock.Mock(returncode=0, stdout="")
        with mock.patch.object(
            agent_messenger,
            "run_herdr",
            side_effect=[layout, opened],
        ) as run:
            self.assertTrue(agent_messenger.launch_popup("w1:p1", {}))
        arguments = run.call_args_list[-1].args[0]
        self.assertEqual(arguments[arguments.index("--width") + 1], "72")
        self.assertEqual(arguments[arguments.index("--height") + 1], "23")

    def test_skill_guide_action_uses_compact_popup_and_bundled_skill(self):
        completed = mock.Mock(returncode=0)
        with mock.patch.object(agent_messenger, "run_herdr", return_value=completed) as run:
            self.assertEqual(agent_messenger.launch_skill_guide({}), 0)
        arguments = run.call_args.args[0]
        self.assertEqual(
            arguments[arguments.index("--entrypoint") + 1],
            agent_messenger.SKILL_GUIDE_ENTRYPOINT,
        )
        self.assertEqual(arguments[arguments.index("--width") + 1], "80")
        self.assertEqual(arguments[arguments.index("--height") + 1], "16")
        self.assertTrue(agent_messenger.bundled_skill_path().is_file())

    def test_language_detection_supports_three_locales(self):
        self.assertEqual(messenger_i18n.detect_language({"LANG": "en_US.UTF-8"}), "en")
        self.assertEqual(messenger_i18n.detect_language({"LANG": "ja_JP.UTF-8"}), "ja")
        self.assertEqual(messenger_i18n.detect_language({"LANG": "ko_KR.UTF-8"}), "ko")

    def test_unknown_language_falls_back_to_english(self):
        with mock.patch.object(messenger_i18n, "_macos_language", return_value=None):
            self.assertEqual(messenger_i18n.detect_language({"LANG": "fr_FR.UTF-8"}), "en")

    def test_delivery_mode_copy_and_key_help_exist_in_every_language(self):
        required = {
            "coordinator",
            "mode_question",
            "delivery_mode",
            "delegate_option",
            "delegate_privacy",
            "direct_option",
            "direct_privacy",
            "help_mode",
        }
        english_keys = set(messenger_i18n.messages("en"))
        for language in messenger_i18n.SUPPORTED_LANGUAGES:
            text = messenger_i18n.messages(language)
            self.assertEqual(set(text), english_keys, language)
            self.assertTrue(required.issubset(text), language)
            self.assertIn("Ctrl+O", text["help_recipients"])
            self.assertIn("Ctrl+O", text["help_message"])
            self.assertIn("Ctrl+G", text["help_recipients"])
            self.assertIn("host/label", text["skill_guide_target"])

    def test_locale_precedence_stops_at_first_configured_value(self):
        self.assertEqual(
            messenger_i18n.detect_language(
                {"LC_ALL": "fr_FR.UTF-8", "LANG": "ko_KR.UTF-8"}
            ),
            "en",
        )
        self.assertEqual(
            messenger_i18n.detect_language(
                {"LC_ALL": "", "LC_MESSAGES": "ja_JP.UTF-8", "LANG": "ko_KR.UTF-8"}
            ),
            "ja",
        )

    def test_display_width_accounts_for_wide_characters(self):
        self.assertEqual(agent_messenger.display_width("Agent 한글"), 10)

    def test_ctrl_g_toggles_skill_guide_without_changing_editor_state(self):
        sender = agent()
        with tempfile.TemporaryDirectory() as state_directory:
            environment = {
                "LANG": "en_US.UTF-8",
                "HERDR_PLUGIN_STATE_DIR": state_directory,
            }
            with (
                mock.patch.object(
                    agent_messenger,
                    "query_local_agents",
                    return_value=[sender],
                ),
                mock.patch.object(agent_messenger, "ssh_hosts", return_value=[]),
            ):
                app = agent_messenger.MessengerApp(mock.Mock(), sender, environment)

        app.mode_choice = True
        app.section = "message"
        app.message_lines = ["keep this"]
        app.handle_key(agent_messenger.SKILL_GUIDE_KEY)
        self.assertTrue(app.skill_guide_visible)
        app.handle_key(agent_messenger.SKILL_GUIDE_KEY)
        self.assertFalse(app.skill_guide_visible)
        self.assertEqual(app.section, "message")
        self.assertEqual(app.message_lines, ["keep this"])

    def test_question_mark_is_inserted_while_editing_message(self):
        sender = agent()
        with tempfile.TemporaryDirectory() as state_directory:
            environment = {
                "LANG": "en_US.UTF-8",
                "HERDR_PLUGIN_STATE_DIR": state_directory,
            }
            with (
                mock.patch.object(
                    agent_messenger,
                    "query_local_agents",
                    return_value=[sender],
                ),
                mock.patch.object(agent_messenger, "ssh_hosts", return_value=[]),
            ):
                app = agent_messenger.MessengerApp(mock.Mock(), sender, environment)

        app.mode_choice = True
        app.section = "message"
        app.message_lines = ["Can you review"]
        app.message_column = len(app.message_lines[0])
        app.handle_key("?")

        self.assertFalse(app.skill_guide_visible)
        self.assertEqual(app.message_lines, ["Can you review?"])

    def test_skill_guide_wraps_long_paths_inside_popup(self):
        screen = mock.Mock()
        screen.getmaxyx.return_value = (14, 42)
        with mock.patch.object(agent_messenger.curses, "curs_set"):
            agent_messenger.render_skill_guide_screen(
                screen,
                messenger_i18n.messages("en"),
                Path(
                    "/a/very/long/plugin/path/skills/herdr-agent-messenger/SKILL.md"
                ),
            )
        for call in screen.addnstr.call_args_list:
            row, column, _value, maximum = call.args[:4]
            self.assertLess(row, 14)
            self.assertLess(column, 42)
            self.assertLessEqual(maximum, 41 - column)

    def test_message_soft_wrap_preserves_text_and_maps_cursor(self):
        message = "현재 프로젝트 내용을 분석하고 리뷰한 내용을 종합해서 보고해줘."
        wrapped, cursor_row, cursor_column = agent_messenger.wrap_message_lines(
            [message],
            width=16,
            cursor_row=0,
            cursor_column=len(message),
        )

        self.assertEqual("".join(line.text for line in wrapped), message)
        self.assertTrue(
            all(agent_messenger.display_width(line.text) <= 16 for line in wrapped)
        )
        self.assertEqual(cursor_row, len(wrapped) - 1)
        self.assertEqual(
            cursor_column,
            agent_messenger.display_width(wrapped[-1].text),
        )

    def test_cursor_at_soft_wrap_boundary_moves_to_next_visual_line(self):
        wrapped, cursor_row, cursor_column = agent_messenger.wrap_message_lines(
            ["abcdef"],
            width=3,
            cursor_row=0,
            cursor_column=3,
        )

        self.assertEqual([line.text for line in wrapped], ["abc", "def"])
        self.assertEqual((cursor_row, cursor_column), (1, 0))

    def test_display_column_maps_to_cjk_character_boundary(self):
        self.assertEqual(
            agent_messenger.character_index_at_display_column("가나다", 3),
            1,
        )

    def test_discovery_choice_supports_arrows_and_enter(self):
        sender = agent()
        with tempfile.TemporaryDirectory() as state_directory:
            environment = {
                "LANG": "en_US.UTF-8",
                "HERDR_PLUGIN_STATE_DIR": state_directory,
            }
            with (
                mock.patch.object(
                    agent_messenger,
                    "query_local_agents",
                    return_value=[sender],
                ),
                mock.patch.object(
                    agent_messenger,
                    "ssh_hosts",
                    return_value=["macbook"],
                ),
            ):
                app = agent_messenger.MessengerApp(mock.Mock(), sender, environment)

        self.assertFalse(app.discovery_choice)
        app.handle_key(agent_messenger.curses.KEY_DOWN)
        self.assertEqual(app.discovery_option, 1)
        with mock.patch.object(app, "_start_remote_discovery") as discover:
            app.handle_key("\n")
        self.assertTrue(app.discovery_choice)
        self.assertFalse(app.mode_choice)
        self.assertFalse(app.remote_enabled)
        discover.assert_not_called()

    def test_delivery_mode_defaults_to_delegate_and_supports_keyboard_flow(self):
        sender = agent()
        with tempfile.TemporaryDirectory() as state_directory:
            environment = {
                "LANG": "en_US.UTF-8",
                "HERDR_PLUGIN_STATE_DIR": state_directory,
            }
            with (
                mock.patch.object(
                    agent_messenger,
                    "query_local_agents",
                    return_value=[sender],
                ),
                mock.patch.object(agent_messenger, "ssh_hosts", return_value=[]),
            ):
                app = agent_messenger.MessengerApp(mock.Mock(), sender, environment)

        self.assertTrue(app.discovery_choice)
        self.assertFalse(app.mode_choice)
        self.assertEqual(app.mode_option, 0)
        self.assertEqual(app.delivery_mode, agent_messenger.DELIVERY_DELEGATE)

        app.handle_key(agent_messenger.curses.KEY_DOWN)
        self.assertEqual(app.mode_option, 1)
        app.handle_key("\n")
        self.assertTrue(app.mode_choice)
        self.assertEqual(app.delivery_mode, agent_messenger.DELIVERY_DIRECT)

        app.handle_key("\x0f")
        self.assertFalse(app.mode_choice)
        self.assertTrue(app.mode_return_to_editor)
        app.handle_key("\x1b")
        self.assertTrue(app.mode_choice)
        self.assertEqual(app.delivery_mode, agent_messenger.DELIVERY_DIRECT)

        app.handle_key("\x0f")
        app.handle_key("c")
        self.assertTrue(app.mode_choice)
        self.assertEqual(app.delivery_mode, agent_messenger.DELIVERY_DELEGATE)

        app.handle_key("\x0f")
        app.handle_key("d")
        self.assertTrue(app.mode_choice)
        self.assertEqual(app.delivery_mode, agent_messenger.DELIVERY_DIRECT)

    def test_escape_from_initial_mode_choice_returns_to_ssh_discovery(self):
        sender = agent()
        with tempfile.TemporaryDirectory() as state_directory:
            environment = {
                "LANG": "en_US.UTF-8",
                "HERDR_PLUGIN_STATE_DIR": state_directory,
            }
            with (
                mock.patch.object(
                    agent_messenger,
                    "query_local_agents",
                    return_value=[sender],
                ),
                mock.patch.object(
                    agent_messenger,
                    "ssh_hosts",
                    return_value=["macbook"],
                ),
            ):
                app = agent_messenger.MessengerApp(mock.Mock(), sender, environment)

        app.handle_key("l")
        self.assertTrue(app.discovery_choice)
        self.assertFalse(app.mode_choice)
        app.handle_key("\x1b")
        self.assertFalse(app.discovery_choice)
        self.assertTrue(app.running)

    def test_local_only_cancels_discovery_and_removes_remote_agents(self):
        sender = agent()
        local_recipient = agent(
            name="red-fox",
            pane_id="w1:p2",
            session_id="session-2",
        )
        remote_recipient = agent_directory.replace(
            local_recipient,
            host="macbook",
            name="white-owl",
            pane_id="w2:p1",
            session_id="remote-session",
            local=False,
        )
        with tempfile.TemporaryDirectory() as state_directory:
            environment = {
                "LANG": "en_US.UTF-8",
                "HERDR_PLUGIN_STATE_DIR": state_directory,
            }
            with (
                mock.patch.object(
                    agent_messenger,
                    "query_local_agents",
                    return_value=[sender, local_recipient],
                ),
                mock.patch.object(
                    agent_messenger,
                    "ssh_hosts",
                    return_value=["macbook"],
                ),
            ):
                app = agent_messenger.MessengerApp(mock.Mock(), sender, environment)

        discovery = mock.Mock()
        app.discovery_choice = True
        app.mode_choice = False
        app.discovery = discovery
        app.remote_enabled = True
        app.pending_hosts = {"macbook"}
        app.host_status = {"macbook": app.text["refreshing"]}
        app.agents.append(remote_recipient)
        app.selected = {local_recipient.identity, remote_recipient.identity}

        app.handle_key("\x1b")
        app.handle_key("l")

        discovery.cancel.assert_called_once_with()
        self.assertIsNone(app.discovery)
        self.assertFalse(app.remote_enabled)
        self.assertFalse(app.pending_hosts)
        self.assertFalse(app.host_status)
        self.assertEqual(app.agents, [local_recipient])
        self.assertEqual(app.selected, {local_recipient.identity})

    def test_mode_privacy_copy_wraps_on_narrow_screens_in_every_language(self):
        sender = agent()
        for language in messenger_i18n.SUPPORTED_LANGUAGES:
            environment = {"LANG": f"{language}_TEST.UTF-8"}
            screen = mock.Mock()
            screen.getmaxyx.return_value = (22, 44)
            with tempfile.TemporaryDirectory() as state_directory:
                environment["HERDR_PLUGIN_STATE_DIR"] = state_directory
                with (
                    mock.patch.object(
                        agent_messenger,
                        "query_local_agents",
                        return_value=[sender],
                    ),
                    mock.patch.object(agent_messenger, "ssh_hosts", return_value=[]),
                ):
                    app = agent_messenger.MessengerApp(screen, sender, environment)

            rendered: list[tuple[int, int, str]] = []

            def record(row, column, value, _attribute=0):
                rendered.append((row, column, value))

            with mock.patch.object(app, "_safe_add", side_effect=record):
                app._render_mode_choice(3)

            descriptions = "".join(
                value for _row, column, value in rendered if column == 6
            )
            self.assertEqual(
                descriptions,
                app.text["delegate_privacy"] + app.text["direct_privacy"],
                language,
            )
            self.assertTrue(
                all(
                    agent_messenger.display_width(value) <= 37
                    for _row, column, value in rendered
                    if column == 6
                ),
                language,
            )
            for mode, privacy_key in (
                (agent_messenger.DELIVERY_DELEGATE, "delegate_privacy"),
                (agent_messenger.DELIVERY_DIRECT, "direct_privacy"),
            ):
                rendered.clear()
                app.delivery_mode = mode
                with mock.patch.object(app, "_safe_add", side_effect=record):
                    app._render_mode_summary(3)
                summary = "".join(
                    value for _row, column, value in rendered if column == 2
                )
                self.assertEqual(summary, app.text[privacy_key], language)

    def test_color_pairs_use_terminal_palette(self):
        sender = agent()
        with tempfile.TemporaryDirectory() as state_directory:
            environment = {
                "LANG": "en_US.UTF-8",
                "HERDR_PLUGIN_STATE_DIR": state_directory,
            }
            with (
                mock.patch.object(
                    agent_messenger,
                    "query_local_agents",
                    return_value=[sender],
                ),
                mock.patch.object(agent_messenger, "ssh_hosts", return_value=[]),
            ):
                app = agent_messenger.MessengerApp(mock.Mock(), sender, environment)

        with (
            mock.patch.object(agent_messenger.curses, "has_colors", return_value=True),
            mock.patch.object(agent_messenger.curses, "start_color"),
            mock.patch.object(agent_messenger.curses, "use_default_colors"),
            mock.patch.object(agent_messenger.curses, "init_pair") as init_pair,
        ):
            app._initialize_colors()

        self.assertTrue(app.colors_enabled)
        self.assertEqual(init_pair.call_count, 5)
        self.assertTrue(all(call.args[2] == -1 for call in init_pair.call_args_list))

    def test_message_cursor_is_placed_after_footer_rendering(self):
        sender = agent()
        screen = mock.Mock()
        screen.getmaxyx.return_value = (34, 110)
        with tempfile.TemporaryDirectory() as state_directory:
            environment = {
                "LANG": "en_US.UTF-8",
                "HERDR_PLUGIN_STATE_DIR": state_directory,
            }
            with (
                mock.patch.object(
                    agent_messenger,
                    "query_local_agents",
                    return_value=[sender],
                ),
                mock.patch.object(agent_messenger, "ssh_hosts", return_value=[]),
            ):
                app = agent_messenger.MessengerApp(screen, sender, environment)

        app.mode_choice = True
        app.section = "message"
        app.message_lines = ["hello"]
        app.message_column = 5
        with mock.patch.object(app, "_set_cursor_visibility"):
            app.render()

        self.assertEqual(screen.move.call_args.args, app.message_cursor)
        self.assertEqual(app.message_cursor[1], 7)

    def test_long_message_cursor_remains_inside_editor(self):
        sender = agent()
        screen = mock.Mock()
        screen.getmaxyx.return_value = (22, 44)
        with tempfile.TemporaryDirectory() as state_directory:
            environment = {
                "LANG": "ko_KR.UTF-8",
                "HERDR_PLUGIN_STATE_DIR": state_directory,
            }
            with (
                mock.patch.object(
                    agent_messenger,
                    "query_local_agents",
                    return_value=[sender],
                ),
                mock.patch.object(agent_messenger, "ssh_hosts", return_value=[]),
            ):
                app = agent_messenger.MessengerApp(screen, sender, environment)

        app.mode_choice = True
        app.section = "message"
        app.message_lines = ["긴 메시지를 입력해도 화면에서 잘리지 않아야 합니다. " * 4]
        app.message_column = len(app.message_lines[0])
        with mock.patch.object(app, "_set_cursor_visibility"):
            app.render()

        cursor_row, cursor_column = screen.move.call_args.args
        self.assertLess(cursor_row, 20)
        self.assertLess(cursor_column, 43)
        self.assertEqual(screen.move.call_args.args, app.message_cursor)

    def test_arrow_keys_move_between_soft_wrapped_message_rows(self):
        sender = agent()
        screen = mock.Mock()
        screen.getmaxyx.return_value = (22, 12)
        with tempfile.TemporaryDirectory() as state_directory:
            environment = {
                "LANG": "en_US.UTF-8",
                "HERDR_PLUGIN_STATE_DIR": state_directory,
            }
            with (
                mock.patch.object(
                    agent_messenger,
                    "query_local_agents",
                    return_value=[sender],
                ),
                mock.patch.object(agent_messenger, "ssh_hosts", return_value=[]),
            ):
                app = agent_messenger.MessengerApp(screen, sender, environment)

        app.mode_choice = True
        app.section = "message"
        app.message_lines = ["abcdefghijklmnopqrst"]
        app.message_column = 20
        app.handle_key(agent_messenger.curses.KEY_UP)
        self.assertEqual((app.message_row, app.message_column), (0, 12))
        app.handle_key(agent_messenger.curses.KEY_UP)
        self.assertEqual((app.message_row, app.message_column), (0, 4))

    def test_ctrl_s_invokes_send_from_message_editor(self):
        sender = agent()
        with tempfile.TemporaryDirectory() as state_directory:
            environment = {
                "LANG": "en_US.UTF-8",
                "HERDR_PLUGIN_STATE_DIR": state_directory,
            }
            with (
                mock.patch.object(
                    agent_messenger,
                    "query_local_agents",
                    return_value=[sender],
                ),
                mock.patch.object(agent_messenger, "ssh_hosts", return_value=[]),
            ):
                app = agent_messenger.MessengerApp(mock.Mock(), sender, environment)

        app.mode_choice = True
        app.section = "message"
        with mock.patch.object(app, "_send") as send:
            app.handle_key("\x13")
        send.assert_called_once_with()

    def test_local_refresh_removes_disappeared_agent_selection(self):
        sender = agent()
        recipient = agent(name="red-fox", pane_id="w1:p2", session_id="session-2")
        with tempfile.TemporaryDirectory() as state_directory:
            environment = {
                "LANG": "en_US.UTF-8",
                "HERDR_PLUGIN_STATE_DIR": state_directory,
            }
            with (
                mock.patch.object(
                    agent_messenger,
                    "query_local_agents",
                    return_value=[sender, recipient],
                ),
                mock.patch.object(agent_messenger, "ssh_hosts", return_value=[]),
            ):
                app = agent_messenger.MessengerApp(mock.Mock(), sender, environment)

        app.mode_choice = True
        app.selected.add(recipient.identity)
        with mock.patch.object(
            agent_messenger,
            "query_local_agents",
            return_value=[sender],
        ):
            app.handle_key("\x12")
        self.assertNotIn(recipient.identity, app.selected)

    def test_remote_scope_does_not_replace_local_agents_with_same_host(self):
        sender = agent()
        local_recipient = agent(
            name="red-fox",
            pane_id="w1:p2",
            session_id="session-2",
        )
        remote_recipient = agent_directory.replace(
            local_recipient,
            local=False,
            name="white-owl",
            pane_id="w2:p1",
            session_id="remote-session",
        )
        with tempfile.TemporaryDirectory() as state_directory:
            environment = {
                "LANG": "en_US.UTF-8",
                "HERDR_PLUGIN_STATE_DIR": state_directory,
            }
            with (
                mock.patch.object(
                    agent_messenger,
                    "query_local_agents",
                    return_value=[sender, local_recipient],
                ),
                mock.patch.object(agent_messenger, "ssh_hosts", return_value=[]),
            ):
                app = agent_messenger.MessengerApp(mock.Mock(), sender, environment)

        app._replace_agent_scope(
            local=False,
            host=local_recipient.host,
            records=[remote_recipient],
        )
        self.assertIn(local_recipient, app.agents)
        self.assertIn(remote_recipient, app.agents)

    @unittest.skipIf(agent_messenger.termios is None, "termios unavailable")
    def test_terminal_flow_control_is_disabled_and_restored(self):
        stream = mock.Mock()
        stream.fileno.return_value = 7
        original = [
            agent_messenger.termios.IXON | agent_messenger.termios.IXOFF | 1,
            0,
            0,
            0,
            0,
            0,
            [],
        ]
        with (
            mock.patch.object(
                agent_messenger.termios,
                "tcgetattr",
                return_value=original,
            ),
            mock.patch.object(agent_messenger.termios, "tcsetattr") as set_attributes,
        ):
            with agent_messenger.terminal_flow_control_disabled(stream):
                pass

        disabled = set_attributes.call_args_list[0].args[2]
        self.assertFalse(disabled[0] & agent_messenger.termios.IXON)
        self.assertFalse(disabled[0] & agent_messenger.termios.IXOFF)
        self.assertEqual(set_attributes.call_args_list[1].args[2], original)

    def test_delegate_sends_one_orchestration_request_to_coordinator_only(self):
        sender = agent()
        first = agent(name="red-fox", pane_id="w1:p2", session_id="session-2")
        second = agent(name="white-owl", pane_id="w1:p3", session_id="session-3")
        with tempfile.TemporaryDirectory() as state_directory:
            environment = {
                "LANG": "en_US.UTF-8",
                "HERDR_PLUGIN_STATE_DIR": state_directory,
            }
            with (
                mock.patch.object(
                    agent_messenger,
                    "query_local_agents",
                    return_value=[sender, first, second],
                ),
                mock.patch.object(agent_messenger, "ssh_hosts", return_value=[]),
            ):
                app = agent_messenger.MessengerApp(mock.Mock(), sender, environment)

        app.selected = {first.identity, second.identity}
        original_request = "\n  Please review this change.  \n"
        app.message_lines = original_request.split("\n")
        results = [agent_directory.SendResult(sender, True)]
        with (
            mock.patch.object(agent_messenger, "fetch_local_agent", return_value=sender),
            mock.patch.object(
                agent_messenger,
                "dispatch_prompts",
                return_value=results,
            ) as dispatch,
            mock.patch.object(agent_messenger, "show_notification"),
            mock.patch.object(agent_messenger.threading, "Thread", ImmediateThread),
        ):
            app._send()
            app._poll_send()

        self.assertFalse(app.running)
        self.assertEqual(dispatch.call_count, 1)
        self.assertEqual(dispatch.call_args.args[1], (sender,))
        self.assertNotIn(first, dispatch.call_args.args[1])
        self.assertNotIn(second, dispatch.call_args.args[1])
        orchestration_request = dispatch.call_args.args[2]
        self.assertIn(first.qualified_name, orchestration_request)
        self.assertIn(second.qualified_name, orchestration_request)
        self.assertIn(
            "--- BEGIN ORIGINAL REQUEST ---\n"
            f"{original_request}\n"
            "--- END ORIGINAL REQUEST ---",
            orchestration_request,
        )
        self.assertIn("tailored", orchestration_request)
        self.assertIn("Use Herdr", orchestration_request)
        self.assertIn("Wait for the workers", orchestration_request)
        self.assertIn("Verify every result", orchestration_request)
        self.assertIn("report the final outcome", orchestration_request)

    def test_direct_mode_dispatches_to_multiple_selected_recipients(self):
        sender = agent()
        first = agent(name="red-fox", pane_id="w1:p2", session_id="session-2")
        second = agent(name="white-owl", pane_id="w1:p3", session_id="session-3")
        with tempfile.TemporaryDirectory() as state_directory:
            environment = {
                "LANG": "en_US.UTF-8",
                "HERDR_PLUGIN_STATE_DIR": state_directory,
            }
            with (
                mock.patch.object(
                    agent_messenger,
                    "query_local_agents",
                    return_value=[sender, first, second],
                ),
                mock.patch.object(agent_messenger, "ssh_hosts", return_value=[]),
            ):
                app = agent_messenger.MessengerApp(mock.Mock(), sender, environment)

        app.selected = {first.identity, second.identity}
        app.delivery_mode = agent_messenger.DELIVERY_DIRECT
        app.message_lines = ["  Please review this change.  "]
        results = [
            agent_directory.SendResult(first, True),
            agent_directory.SendResult(second, True),
        ]
        with (
            mock.patch.object(agent_messenger, "fetch_local_agent", return_value=sender),
            mock.patch.object(
                agent_messenger,
                "dispatch_prompts",
                return_value=results,
            ) as dispatch,
            mock.patch.object(agent_messenger, "show_notification"),
            mock.patch.object(agent_messenger.threading, "Thread", ImmediateThread),
        ):
            app._send()
            app._poll_send()

        self.assertFalse(app.running)
        self.assertCountEqual(dispatch.call_args.args[1], [first, second])
        self.assertEqual(dispatch.call_args.args[2], "Please review this change.")

    def test_send_runs_in_background_and_escape_cancels_pending_work(self):
        sender = agent()
        recipient = agent(name="red-fox", pane_id="w1:p2", session_id="session-2")
        started = threading.Event()
        stopped = threading.Event()

        def cancellable_dispatch(*_args, cancel_event, **_kwargs):
            started.set()
            cancel_event.wait(1)
            stopped.set()
            return []

        with tempfile.TemporaryDirectory() as state_directory:
            environment = {
                "LANG": "en_US.UTF-8",
                "HERDR_PLUGIN_STATE_DIR": state_directory,
            }
            with (
                mock.patch.object(
                    agent_messenger,
                    "query_local_agents",
                    return_value=[sender, recipient],
                ),
                mock.patch.object(agent_messenger, "ssh_hosts", return_value=[]),
            ):
                app = agent_messenger.MessengerApp(mock.Mock(), sender, environment)

        app.mode_choice = True
        app.delivery_mode = agent_messenger.DELIVERY_DIRECT
        app.selected = {recipient.identity}
        app.message_lines = ["Review"]
        with (
            mock.patch.object(agent_messenger, "fetch_local_agent", return_value=sender),
            mock.patch.object(
                agent_messenger,
                "dispatch_prompts",
                side_effect=cancellable_dispatch,
            ),
        ):
            before = time.monotonic()
            app._send()
            self.assertLess(time.monotonic() - before, 0.1)
            self.assertTrue(started.wait(1))
            app.handle_key("\x1b")
            self.assertTrue(stopped.wait(1))
            deadline = time.monotonic() + 1
            while app.send_results.empty() and time.monotonic() < deadline:
                time.sleep(0.001)
            app._poll_send()

        self.assertFalse(app.sending)
        self.assertEqual(app.status, app.text["send_cancelled"])

    def test_cancelled_sender_revalidation_reports_send_cancelled(self):
        sender = agent()
        recipient = agent(name="red-fox", pane_id="w1:p2", session_id="session-2")
        with tempfile.TemporaryDirectory() as state_directory:
            environment = {
                "LANG": "en_US.UTF-8",
                "HERDR_PLUGIN_STATE_DIR": state_directory,
            }
            with (
                mock.patch.object(
                    agent_messenger,
                    "query_local_agents",
                    return_value=[sender, recipient],
                ),
                mock.patch.object(agent_messenger, "ssh_hosts", return_value=[]),
            ):
                app = agent_messenger.MessengerApp(mock.Mock(), sender, environment)

        def cancelled_fetch(*_args, cancel_event, **_kwargs):
            cancel_event.set()
            return None

        with mock.patch.object(
            agent_messenger,
            "fetch_local_agent",
            side_effect=cancelled_fetch,
        ):
            app.sending = True
            app._dispatch_send_job((recipient,), "Review")
            app._poll_send()

        self.assertFalse(app.sending)
        self.assertEqual(app.status, app.text["send_cancelled"])

    def test_partial_send_failure_keeps_only_failed_recipients_selected(self):
        sender = agent()
        succeeded = agent(name="red-fox", pane_id="w1:p2", session_id="session-2")
        failed = agent(name="white-owl", pane_id="w1:p3", session_id="session-3")
        with tempfile.TemporaryDirectory() as state_directory:
            environment = {
                "LANG": "en_US.UTF-8",
                "HERDR_PLUGIN_STATE_DIR": state_directory,
            }
            with (
                mock.patch.object(
                    agent_messenger,
                    "query_local_agents",
                    return_value=[sender, succeeded, failed],
                ),
                mock.patch.object(agent_messenger, "ssh_hosts", return_value=[]),
            ):
                app = agent_messenger.MessengerApp(mock.Mock(), sender, environment)

        app.sending = True
        app.delivery_mode = agent_messenger.DELIVERY_DIRECT
        app.selected = {succeeded.identity, failed.identity}
        app.send_results.put(
            agent_messenger.SendJobResult(
                True,
                (
                    agent_directory.SendResult(succeeded, True),
                    agent_directory.SendResult(failed, False, "unavailable"),
                ),
            )
        )
        app._poll_send()

        self.assertEqual(app.selected, {failed.identity})
        self.assertIn("failed for 1", app.status)


if __name__ == "__main__":
    unittest.main()
