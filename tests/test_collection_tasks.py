from datetime import datetime, timedelta, timezone
from unittest import TestCase
from unittest.mock import patch

from backend.tasks import collection_tasks


class CollectionTasksTest(TestCase):
    def test_default_target_date_uses_kst_not_system_date(self):
        class FakeDatetime:
            @classmethod
            def now(cls, tz=None):
                self.assertEqual(tz, collection_tasks.KST)
                return datetime(2026, 7, 11, 1, 0, tzinfo=timezone(timedelta(hours=9)))

        with patch.object(collection_tasks, "datetime", FakeDatetime):
            self.assertEqual(str(collection_tasks._default_target_date()), "2026-07-10")

    def test_calendar_collection_dates_include_journal_date_and_next_day(self):
        target_date = datetime(2026, 7, 10, tzinfo=collection_tasks.KST).date()

        dates = collection_tasks._calendar_collection_dates(target_date)

        self.assertEqual([str(d) for d in dates], ["2026-07-10", "2026-07-11"])
