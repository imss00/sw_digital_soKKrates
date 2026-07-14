from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from backend.routers.webhook import trigger_generate_journal


class GenerateJournalCalendarTest(TestCase):
    def test_generate_journal_collects_target_date_and_next_day_calendar(self):
        db = object()
        delayed_task = SimpleNamespace(id="task-1")
        run_phase2 = SimpleNamespace(delay=Mock(return_value=delayed_task))

        with (
            patch(
                "backend.collectors.calendar_collector.collect_calendar",
                side_effect=lambda user_id, db, target_date: {
                    "status": "ok",
                    "date": target_date.isoformat(),
                },
            ) as collect_calendar,
            patch(
                "backend.normalizer.normalize.normalize_daily",
                return_value={"status": "ok", "inserted": 0},
            ) as normalize_daily,
            patch("backend.tasks.analysis_tasks.run_phase2", run_phase2),
        ):
            result = trigger_generate_journal(
                user_id=9,
                target_date="2026-07-10",
                db=db,
                _=None,
            )

        self.assertEqual(
            [call.kwargs["target_date"].isoformat() for call in collect_calendar.call_args_list],
            ["2026-07-10", "2026-07-11"],
        )
        normalize_daily.assert_called_once()
        self.assertEqual(normalize_daily.call_args.kwargs["target_date"].isoformat(), "2026-07-10")
        run_phase2.delay.assert_called_once_with(user_id=9, target_date_str="2026-07-10")
        self.assertEqual(result["calendar"]["2026-07-11"]["date"], "2026-07-11")
