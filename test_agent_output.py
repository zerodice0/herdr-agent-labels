import unittest

import agent_output


class AgentOutputTest(unittest.TestCase):
    def read(
        self,
        snapshot: str,
        *,
        cursor: str | None = None,
        stream: str = "a" * 64,
        max_bytes: int = 64 * 1024,
    ) -> agent_output.OutputDelta:
        return agent_output.compact_output(
            snapshot,
            stream=stream,
            max_bytes=max_bytes,
            cursor=cursor,
        )

    def test_exact_append_returns_only_new_output(self):
        initial = self.read("first\n")
        delta = self.read("first\nsecond\n", cursor=initial.cursor)

        self.assertEqual(delta.output, "second\n")
        self.assertTrue(delta.delta)
        self.assertEqual(delta.cursor_status, "current")

    def test_unchanged_snapshot_removes_duplicate_output(self):
        initial = self.read("same output\n")
        delta = self.read("same output\n", cursor=initial.cursor)

        self.assertEqual(delta.output, "")
        self.assertTrue(delta.delta)
        self.assertFalse(delta.truncated)

    def test_rightmost_complete_snapshot_avoids_repeated_block(self):
        initial = self.read("old block\n")
        delta = self.read(
            "old block\nold block\nnew output\n",
            cursor=initial.cursor,
        )

        self.assertEqual(delta.output, "new output\n")

    def test_rolling_window_uses_partial_tail_overlap(self):
        previous = "x" * 5000
        initial = self.read(previous)
        current = previous[-1000:] + "new output\n"
        delta = self.read(current, cursor=initial.cursor)

        self.assertEqual(delta.output, "new output\n")
        self.assertTrue(delta.delta)

    def test_screen_rewrite_safely_returns_current_snapshot(self):
        initial = self.read("progress 10%\n")
        delta = self.read("progress 20%\n", cursor=initial.cursor)

        self.assertEqual(delta.output, "progress 20%\n")
        self.assertFalse(delta.delta)
        self.assertEqual(delta.cursor_status, "expired")

    def test_lost_overlap_expires_cursor_and_falls_back(self):
        initial = self.read("a" * 5000)
        delta = self.read("entirely replaced\n", cursor=initial.cursor)

        self.assertEqual(delta.output, "entirely replaced\n")
        self.assertFalse(delta.delta)
        self.assertEqual(delta.cursor_status, "expired")

    def test_cursor_for_another_occupant_expires(self):
        initial = self.read("old agent\n")
        delta = self.read(
            "new agent\n",
            cursor=initial.cursor,
            stream="b" * 64,
        )

        self.assertEqual(delta.output, "new agent\n")
        self.assertFalse(delta.delta)
        self.assertEqual(delta.cursor_status, "expired")

    def test_utf8_byte_cap_never_splits_a_character(self):
        result = self.read("prefix 가나다", max_bytes=4)

        self.assertEqual(result.output, "다")
        self.assertLessEqual(len(result.output.encode("utf-8")), 4)
        self.assertTrue(result.truncated)

    def test_cap_smaller_than_one_character_returns_empty_text(self):
        result = self.read("가", max_bytes=2)

        self.assertEqual(result.output, "")
        self.assertTrue(result.truncated)

    def test_cursor_is_deterministic_for_the_same_snapshot(self):
        first = self.read("stable\n")
        second = self.read("stable\n")

        self.assertEqual(first.cursor, second.cursor)

    def test_invalid_cursor_is_rejected(self):
        with self.assertRaises(agent_output.InvalidOutputCursor):
            self.read("output\n", cursor="not-a-cursor")


if __name__ == "__main__":
    unittest.main()
