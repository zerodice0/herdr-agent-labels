from pathlib import Path
import curses
import tempfile
import unittest
from unittest import mock

import agent_skill_installer


class AgentSkillInstallerTest(unittest.TestCase):
    def test_destinations_use_selected_home(self):
        destinations = agent_skill_installer.install_destinations(
            {"HOME": "/tmp/example-home"}
        )

        self.assertEqual(
            destinations["codex"],
            Path("/tmp/example-home/.agents/skills/herdr-agent-messenger"),
        )
        self.assertEqual(
            destinations["claude"],
            Path("/tmp/example-home/.claude/skills/herdr-agent-messenger"),
        )

    def test_targets_include_project_and_system_scopes(self):
        targets = agent_skill_installer.installation_targets(
            {
                "HOME": "/tmp/example-home",
                "HERDR_PLUGIN_CONTEXT_JSON": (
                    '{"workspace_cwd":"/tmp/example-project"}'
                ),
            }
        )

        self.assertEqual(
            [(target.scope, target.agent) for target in targets],
            [
                ("project", "codex"),
                ("project", "claude"),
                ("system", "codex"),
                ("system", "claude"),
            ],
        )
        self.assertEqual(
            targets[0].destination,
            Path("/tmp/example-project").resolve()
            / ".agents"
            / "skills"
            / "herdr-agent-messenger",
        )

    def test_installation_status_distinguishes_current_outdated_and_conflict(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current = root / "current"
            agent_skill_installer.install_skill(current)
            self.assertEqual(
                agent_skill_installer.installation_status(current),
                agent_skill_installer.STATUS_CURRENT,
            )

            (current / "SKILL.md").write_text(
                "---\nname: herdr-agent-messenger\n---\nchanged\n",
                encoding="utf-8",
            )
            self.assertEqual(
                agent_skill_installer.installation_status(current),
                agent_skill_installer.STATUS_OUTDATED,
            )

            conflict = root / "conflict"
            conflict.mkdir()
            (conflict / "SKILL.md").write_text("unrelated", encoding="utf-8")
            self.assertEqual(
                agent_skill_installer.installation_status(conflict),
                agent_skill_installer.STATUS_CONFLICT,
            )
            self.assertEqual(
                agent_skill_installer.installation_status(root / "missing"),
                agent_skill_installer.STATUS_MISSING,
            )

    def test_install_both_copies_the_bundled_skill(self):
        with tempfile.TemporaryDirectory() as directory:
            environment = {"HOME": directory}

            installed = agent_skill_installer.install_selected("both", environment)

            self.assertEqual(len(installed), 2)
            for destination in installed:
                self.assertTrue((destination / "SKILL.md").is_file())
                self.assertTrue(
                    (destination / "scripts" / "herdr_agent_messenger.py").is_file()
                )

    def test_install_refuses_to_replace_unrelated_skill(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "herdr-agent-messenger"
            destination.mkdir()
            sentinel = destination / "keep.txt"
            sentinel.write_text("mine", encoding="utf-8")

            with self.assertRaisesRegex(OSError, "unrelated skill"):
                agent_skill_installer.install_skill(destination)

            self.assertEqual(sentinel.read_text(encoding="utf-8"), "mine")

    def test_launch_opens_a_responsive_installer_popup(self):
        with mock.patch.object(
            agent_skill_installer,
            "launch_plugin_popup",
            return_value=True,
        ) as launch_popup:
            self.assertEqual(agent_skill_installer.launch({"LANG": "ko_KR.UTF-8"}), 0)

        launch_popup.assert_called_once_with(
            agent_skill_installer.SKILL_INSTALLER_ENTRYPOINT,
            width=60,
            height=22,
            environment={"LANG": "ko_KR.UTF-8"},
            extra_arguments=(),
        )

    def test_popup_arrow_selection_installs_the_highlighted_target(self):
        screen = mock.Mock()
        screen.getmaxyx.return_value = (22, 60)
        screen.get_wch.side_effect = [curses.KEY_DOWN, curses.KEY_DOWN, "\n", "\x1b"]

        def run_wrapper(callback):
            return callback(screen)

        with (
            mock.patch.object(
                agent_skill_installer.curses,
                "wrapper",
                side_effect=run_wrapper,
            ),
            mock.patch.object(agent_skill_installer.curses, "curs_set"),
            mock.patch.object(agent_skill_installer.curses, "has_colors", return_value=False),
            mock.patch.object(agent_skill_installer, "install_target") as install,
        ):
            self.assertEqual(
                agent_skill_installer.popup(
                    {"HOME": "/tmp/example-home", "LANG": "en_US.UTF-8"}
                ),
                0,
            )

        target = install.call_args.args[0]
        self.assertEqual((target.scope, target.agent), ("system", "codex"))

    def test_question_mark_opens_usage_and_escape_returns_to_targets(self):
        screen = mock.Mock()
        screen.getmaxyx.return_value = (22, 60)
        screen.get_wch.side_effect = ["?", "\x1b", "\x1b"]

        with (
            mock.patch.object(
                agent_skill_installer.curses,
                "wrapper",
                side_effect=lambda callback: callback(screen),
            ),
            mock.patch.object(agent_skill_installer.curses, "curs_set"),
            mock.patch.object(agent_skill_installer.curses, "has_colors", return_value=False),
        ):
            self.assertEqual(
                agent_skill_installer.popup(
                    {"HOME": "/tmp/example-home", "LANG": "en_US.UTF-8"}
                ),
                0,
            )

        rendered = [call.args[2] for call in screen.addnstr.call_args_list]
        rendered_text = "".join(rendered)
        self.assertIn("Use HAM", rendered)
        self.assertIn(
            "Codex: type $ham, then select HAM — Herdr Agent Messenger.",
            rendered_text,
        )
        self.assertIn("Claude Code: invoke /herdr-agent-messenger.", rendered)
        self.assertIn("Example target: local/yellow-falcon", rendered)


if __name__ == "__main__":
    unittest.main()
