from types import SimpleNamespace
from unittest import TestCase

from backend.normalizer.normalize import normalize_calendar


class NormalizeCalendarTest(TestCase):
    def test_keeps_short_but_meaningful_summary(self):
        record = SimpleNamespace(
            id=1,
            summary="회의",
            description=None,
            start_time=None,
        )

        normalized = normalize_calendar(record)

        self.assertIsNotNone(normalized)
        self.assertEqual(normalized["content_text"], "회의")
        self.assertEqual(normalized["content_type"], "event")

    def test_skips_empty_event(self):
        record = SimpleNamespace(
            id=1,
            summary="  ",
            description=None,
            start_time=None,
        )

        self.assertIsNone(normalize_calendar(record))
