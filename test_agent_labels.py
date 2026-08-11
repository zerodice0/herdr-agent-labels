#!/usr/bin/env python3

import importlib.util
import os
from pathlib import Path
import unittest
from unittest import mock


MODULE_PATH = Path(__file__).with_name("agent_labels.py")
SPEC = importlib.util.spec_from_file_location("agent_labels", MODULE_PATH)
assert SPEC and SPEC.loader
agent_labels = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(agent_labels)


class AgentLabelsTest(unittest.TestCase):
    def test_aliases_are_valid_and_unique(self):
        names = [alias for alias, _marker, _color in agent_labels.ALIASES]
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(all(len(name) <= 32 and name.replace("-", "").islower() for name in names))

    def test_conflict_retries_without_listing_agents(self):
        calls = []

        def fake_run(*args):
            calls.append(args)
            if args[:2] == ("agent", "get"):
                return mock.Mock(
                    returncode=0,
                    stdout='{"result":{"agent":{"agent":"codex","terminal_id":"term-1"}}}',
                    stderr="",
                )
            if args[:2] == ("agent", "rename") and sum(
                call[:2] == ("agent", "rename") for call in calls
            ) == 1:
                return mock.Mock(returncode=1, stdout="", stderr="agent_name_taken")
            return mock.Mock(returncode=0, stdout="{}", stderr="")

        with mock.patch.object(agent_labels, "run_herdr", side_effect=fake_run):
            self.assertEqual(agent_labels.assign_label("w1:p2"), 0)

        self.assertFalse(any(call[:2] == ("agent", "list") for call in calls))
        self.assertEqual(sum(call[:2] == ("agent", "rename") for call in calls), 2)
        self.assertTrue(any(call[:2] == ("pane", "report-metadata") for call in calls))

    def test_named_agent_is_preserved(self):
        result = mock.Mock(
            returncode=0,
            stdout='{"result":{"agent":{"agent":"claude","name":"reviewer"}}}',
            stderr="",
        )
        with mock.patch.object(agent_labels, "run_herdr", return_value=result) as run:
            self.assertEqual(agent_labels.assign_label("w1:p3"), 0)
        self.assertEqual(run.call_count, 1)

    def test_event_envelope_is_supported(self):
        value = '{"event":"pane.agent_detected","data":{"pane_id":"w1:p4","agent":"codex"}}'
        with mock.patch.dict(os.environ, {"HERDR_PLUGIN_EVENT_JSON": value}):
            self.assertEqual(agent_labels.event_data()["pane_id"], "w1:p4")


if __name__ == "__main__":
    unittest.main()
