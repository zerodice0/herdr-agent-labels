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
            "skill-installer",
            width=52,
            height=12,
            environment={"LANG": "ko_KR.UTF-8"},
        )

    def test_popup_arrow_selection_installs_the_highlighted_target(self):
        screen = mock.Mock()
        screen.getmaxyx.return_value = (12, 52)
        screen.get_wch.side_effect = [curses.KEY_DOWN, "\n", "\x1b"]

        def run_wrapper(callback):
            return callback(screen)

        with (
            mock.patch.object(
                agent_skill_installer.curses,
                "wrapper",
                side_effect=run_wrapper,
            ),
            mock.patch.object(agent_skill_installer.curses, "curs_set"),
            mock.patch.object(agent_skill_installer, "install_selected") as install,
        ):
            self.assertEqual(
                agent_skill_installer.popup(
                    {"HOME": "/tmp/example-home", "LANG": "en_US.UTF-8"}
                ),
                0,
            )

        install.assert_called_once_with(
            "claude",
            {"HOME": "/tmp/example-home", "LANG": "en_US.UTF-8"},
        )


if __name__ == "__main__":
    unittest.main()
