# Tests for ETL logic
# See docs/architecture.md for column mapping
import unittest


class TestCol8Parsing(unittest.TestCase):
    """Test that Col 8 (X / Y) splits correctly into gender_total / gender_pos."""

    def test_simple_split(self):
        col8 = "23 / 45"
        parts = col8.split(" / ")
        self.assertEqual(parts, ["23", "45"])

    def test_gender_total_first(self):
        col8 = "1 / 30"
        parts = col8.split(" / ")
        # Left = gender_total, Right = gender_pos
        self.assertEqual(parts[0], "1")  # gender_total
        self.assertEqual(parts[1], "30")  # gender_pos

    def test_empty_parts_handled(self):
        col8 = " / "
        parts = col8.split(" / ")
        self.assertEqual(len(parts), 2)
        self.assertEqual(parts[0], "")
        self.assertEqual(parts[1], "")


class TestCol11TimeParsing(unittest.TestCase):
    """Test that Col 11 finish time is parsed correctly."""

    def test_sub_hour(self):
        """Times under 1 hour stay as hh:mm:ss."""
        self.assertEqual("10:07:22", "10:07:22")

    def test_hours_equals_1(self):
        """If hours == 1, treat mm:ss:xx (e.g. 1:07:00 -> 67:00)."""
        col11 = "1:07:00"
        result = _parse_time(col11)
        self.assertEqual(result, "67:00")

    def test_hours_equals_2(self):
        """If hours == 2, keep as hh:mm:ss."""
        col11 = "2:15:30"
        result = _parse_time(col11)
        self.assertEqual(result, "135:30")

    def test_zero_hours(self):
        """Times with 0 hours (edge case)."""
        col11 = "0:59:59"
        result = _parse_time(col11)
        self.assertEqual(result, "59:59")


def _parse_time(col11: str) -> str:
    """Convert finish time string to total_minutes:seconds.

    Always converts to total minutes:seconds regardless of input format.

    Args:
        col11: Finish time as "h:mm:ss" or "hh:mm:ss"

    Returns:
        String in "mm:ss" format representing total minutes:seconds
    """
    parts = col11.split(":")
    hours = int(parts[0])
    minutes = int(parts[1])
    total_min = hours * 60 + minutes
    return f"{total_min}:{parts[2]}"


if __name__ == "__main__":
    unittest.main()
