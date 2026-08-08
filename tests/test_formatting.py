import unittest

from ui.formatting import format_seconds


class FormatSecondsTest(unittest.TestCase):
    def test_zero_seconds(self):
        self.assertEqual(format_seconds(0.0), "00:00")

    def test_minutes_and_seconds(self):
        self.assertEqual(format_seconds(65.0), "01:05")
        self.assertEqual(format_seconds(3599.0), "59:59")

    def test_hours_minutes_and_seconds(self):
        self.assertEqual(format_seconds(3600.0), "1:00:00")
        self.assertEqual(format_seconds(3725.0), "1:02:05")

    def test_negative_time_clamps_to_zero(self):
        self.assertEqual(format_seconds(-12.0), "00:00")


if __name__ == "__main__":
    unittest.main()