import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import TestCase

from backend.analysis.journal_input import build_photo_section

KST = timezone(timedelta(hours=9))


class FakeQuery:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def all(self):
        return self.rows


class FakeSession:
    def __init__(self, rows):
        self.rows = rows

    def query(self, *_args, **_kwargs):
        return FakeQuery(self.rows)


class JournalInputPhotoTest(TestCase):
    def test_build_photo_section_uses_vision_labels(self):
        rows = [
            SimpleNamespace(
                vision_labels=json.dumps({
                    "labels": [
                        {"description": "Mountain", "score": 0.98},
                        {"description": "Trail", "score": 0.92},
                    ]
                }),
                latitude=37.123456,
                longitude=127.654321,
                taken_at=datetime(2026, 7, 10, 8, 30, tzinfo=KST),
            ),
            SimpleNamespace(
                vision_labels=json.dumps({
                    "labels": [
                        {"description": "Mountain", "score": 0.95},
                        {"description": "Backpack", "score": 0.88},
                    ]
                }),
                latitude=None,
                longitude=None,
                taken_at=None,
            ),
        ]

        section = build_photo_section(
            user_id=1,
            target_date=datetime(2026, 7, 10, tzinfo=KST).date(),
            db=FakeSession(rows),
        )

        self.assertTrue(section["_available"])
        self.assertEqual(section["_source"], "photos.vision_labels")
        self.assertEqual(section["photo_keywords"][:3], ["Mountain", "Trail", "Backpack"])
        self.assertEqual(section["recommend_category"], "Mountain")
        self.assertEqual(section["photo_labels"][0]["location"], "37.1235, 127.6543")

    def test_build_photo_section_is_unavailable_without_labels(self):
        row = SimpleNamespace(
            vision_labels=json.dumps({"ocr_text": "receipt text", "labels": []}),
            latitude=None,
            longitude=None,
            taken_at=None,
        )

        section = build_photo_section(
            user_id=1,
            target_date=datetime(2026, 7, 10, tzinfo=KST).date(),
            db=FakeSession([row]),
        )

        self.assertFalse(section["_available"])
        self.assertEqual(section["photo_keywords"], [])
