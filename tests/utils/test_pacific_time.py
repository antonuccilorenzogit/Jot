import unittest
from datetime import UTC, datetime
from unittest.mock import patch

from jot.services.lesson_planning import next_quota_reset
from jot.utils import pacific_time


class PacificTimeTests(unittest.TestCase):
    def _without_tzdata(self):
        return patch.object(pacific_time, "pacific_zone", return_value=None)

    def test_manual_rule_matches_the_time_zone_database(self):
        moments = [
            datetime(2026, 1, 15, 12, tzinfo=UTC),
            datetime(2026, 3, 8, 9, 59, tzinfo=UTC),  # just before DST starts
            datetime(2026, 3, 8, 10, 0, tzinfo=UTC),  # DST starts
            datetime(2026, 7, 1, 0, tzinfo=UTC),
            datetime(2026, 11, 1, 8, 59, tzinfo=UTC),  # just before DST ends
            datetime(2026, 11, 1, 9, 0, tzinfo=UTC),  # DST ends
            datetime(2026, 12, 31, 23, tzinfo=UTC),
        ]
        for moment in moments:
            expected = pacific_time.to_pacific(moment)
            with self._without_tzdata():
                manual = pacific_time.to_pacific(moment)
            self.assertEqual(manual.utcoffset(), expected.utcoffset(), moment)
            self.assertEqual(manual.replace(tzinfo=None), expected.replace(tzinfo=None))

    def test_quota_reset_without_tzdata(self):
        # 13 October 2026, 17:00 in Italy: the reset is at 09:00 Italian time (07:00 UTC) tomorrow
        now = datetime(2026, 10, 13, 15, 0, tzinfo=UTC)
        with self._without_tzdata():
            reset = next_quota_reset(now)
        self.assertEqual(reset, datetime(2026, 10, 14, 7, 0, tzinfo=UTC))
        self.assertEqual(next_quota_reset(now), reset)

    def test_quota_reset_in_winter(self):
        now = datetime(2026, 12, 10, 15, 0, tzinfo=UTC)
        with self._without_tzdata():
            self.assertEqual(
                next_quota_reset(now), datetime(2026, 12, 11, 8, 0, tzinfo=UTC)
            )


if __name__ == "__main__":
    unittest.main()
