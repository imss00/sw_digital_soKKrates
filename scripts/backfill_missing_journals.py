#!/usr/bin/env python3
"""Backfill missing journals for users that have source data on a target date.

Default mode is dry-run. Use --execute to run normalization + Phase2 synchronously.
"""
import argparse
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import text

from backend.database import SessionLocal
from backend.normalizer.normalize import normalize_daily
from backend.tasks.analysis_tasks import run_phase2_sync

KST = timezone(timedelta(hours=9))


def _users_with_activity(db, target_date: date, user_ids: list[int] | None) -> list[int]:
    day_start = datetime.combine(target_date, datetime.min.time()).replace(tzinfo=KST)
    day_end = day_start + timedelta(days=1)
    rows = db.execute(
        text(
            """
            select distinct user_id from (
              select user_id from browsing_history where visited_at >= :start and visited_at < :end
              union
              select user_id from calendar_events where start_time >= :start and start_time < :end
              union
              select user_id from youtube_history where watched_at >= :start and watched_at < :end
              union
              select user_id from spotify_history where played_at >= :start and played_at < :end
              union
              select user_id from photos where taken_at >= :start and taken_at < :end
              union
              select user_id from unified_documents where occurred_at >= :start and occurred_at < :end
            ) s
            where (:user_ids_is_null or user_id = any(:user_ids))
            order by user_id
            """
        ),
        {
            "start": day_start,
            "end": day_end,
            "user_ids_is_null": user_ids is None,
            "user_ids": user_ids or [],
        },
    )
    return [int(row.user_id) for row in rows]


def _users_with_journal(db, target_date: date) -> set[int]:
    rows = db.execute(
        text("select user_id from journals where target_date = :target_date"),
        {"target_date": target_date},
    )
    return {int(row.user_id) for row in rows}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="Target date YYYY-MM-DD")
    parser.add_argument("--user", type=int, action="append", dest="users")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    target_date = date.fromisoformat(args.date)
    db = SessionLocal()
    try:
        active_users = _users_with_activity(db, target_date, args.users)
        done_users = _users_with_journal(db, target_date)
        missing_users = [uid for uid in active_users if uid not in done_users]
        print({"target_date": str(target_date), "active_users": active_users, "missing_users": missing_users})

        if not args.execute:
            print("dry_run: pass --execute to normalize and generate missing journals")
            return

        for uid in missing_users:
            normalize_result = normalize_daily(uid, target_date, db)
            print("normalize", uid, normalize_result)
            phase2_result = run_phase2_sync(uid, target_date, db)
            print("phase2", uid, phase2_result)
    finally:
        db.close()


if __name__ == "__main__":
    main()
