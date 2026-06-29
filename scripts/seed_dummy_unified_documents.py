#!/usr/bin/env python3
"""
Insert or remove dummy `UnifiedDocument` rows for testing.

Usage:
  Insert: ./ai_env/bin/python scripts/seed_dummy_unified_documents.py --action insert --user 1 --date 2026-06-27 --count 5
  Remove: ./ai_env/bin/python scripts/seed_dummy_unified_documents.py --action cleanup

This script marks inserted rows with a clear marker in `content_text` and `source='dummy_test'` so
they can be safely identified and removed later.
"""
import argparse
from datetime import datetime, timezone
import itertools

from backend.database import SessionLocal
from backend.models.unified_document import UnifiedDocument

MARKER = "[DUMMY_TEST_MARKER]"


def insert_dummy(user_id: int, target_date: str, count: int = 5):
    db = SessionLocal()
    # parse date as yyyy-mm-dd
    dt = datetime.fromisoformat(target_date)
    # ensure timezone-aware (naive -> UTC)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    created = []
    # choose negative source_id values to avoid colliding with real sources
    for i in range(1, count + 1):
        src_id = -i
        doc = UnifiedDocument(
            user_id=user_id,
            source="dummy_test",
            source_id=src_id,
            content_text=f"{MARKER} 자동 생성 더미 문서 #{i} for user {user_id} on {target_date}",
            content_type="note",
            title=f"DUMMY TEST {i}",
            occurred_at=dt,
            is_processed=False,
        )
        db.add(doc)
        created.append(doc)

    db.commit()

    print(f"Inserted {len(created)} dummy UnifiedDocument rows (marker={MARKER}).")
    for d in created:
        print(f" - id={d.id} source_id={d.source_id}")


def cleanup_dummy():
    db = SessionLocal()
    rows = db.query(UnifiedDocument).filter(UnifiedDocument.source == "dummy_test").all()
    if not rows:
        print("No dummy_test rows found to remove.")
        return
    ids = [r.id for r in rows]
    print(f"Removing {len(ids)} rows: {ids}")
    for r in rows:
        db.delete(r)
    db.commit()
    print("Cleanup finished.")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--action", choices=["insert", "cleanup"], required=True)
    p.add_argument("--user", type=int, default=1)
    p.add_argument("--date", type=str, default="2026-06-27")
    p.add_argument("--count", type=int, default=5)
    args = p.parse_args()

    if args.action == "insert":
        insert_dummy(args.user, args.date, args.count)
    else:
        cleanup_dummy()


if __name__ == "__main__":
    main()
