import unittest
from datetime import datetime, timedelta

from pomodoro_math import current_stage

FOCUS = 25 * 60
BREAK = 5 * 60
START = datetime(2026, 7, 11, 12, 0)


class TestCurrentStage(unittest.TestCase):
    def test_start_is_focus(self):
        stage, stage_start, stage_end = current_stage(START, FOCUS, BREAK, START)
        self.assertEqual(stage, "focus")
        self.assertEqual(stage_start, START)
        self.assertEqual(stage_end, START + timedelta(seconds=FOCUS))

    def test_last_second_of_focus(self):
        now = START + timedelta(seconds=FOCUS - 1)
        stage, _, stage_end = current_stage(START, FOCUS, BREAK, now)
        self.assertEqual(stage, "focus")
        self.assertEqual(stage_end, START + timedelta(seconds=FOCUS))

    def test_focus_boundary_switches_to_break(self):
        now = START + timedelta(seconds=FOCUS)
        stage, stage_start, stage_end = current_stage(START, FOCUS, BREAK, now)
        self.assertEqual(stage, "break")
        self.assertEqual(stage_start, START + timedelta(seconds=FOCUS))
        self.assertEqual(stage_end, START + timedelta(seconds=FOCUS + BREAK))

    def test_cycle_wraps_back_to_focus(self):
        now = START + timedelta(seconds=FOCUS + BREAK)
        stage, stage_start, stage_end = current_stage(START, FOCUS, BREAK, now)
        self.assertEqual(stage, "focus")
        self.assertEqual(stage_start, START + timedelta(seconds=FOCUS + BREAK))
        self.assertEqual(
            stage_end, START + timedelta(seconds=FOCUS + BREAK + FOCUS)
        )

    def test_mid_break_in_third_cycle(self):
        two_cycles = 2 * (FOCUS + BREAK)
        now = START + timedelta(seconds=two_cycles + FOCUS + 120)
        stage, stage_start, stage_end = current_stage(START, FOCUS, BREAK, now)
        self.assertEqual(stage, "break")
        self.assertEqual(stage_start, START + timedelta(seconds=two_cycles + FOCUS))
        self.assertEqual(
            stage_end, START + timedelta(seconds=two_cycles + FOCUS + BREAK)
        )


if __name__ == "__main__":
    unittest.main()
