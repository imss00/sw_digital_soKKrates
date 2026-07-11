#!/usr/bin/env python3
"""Backfill Google Vision scene labels for stored photos.

Default mode is dry-run. Use --execute to write photos.vision_labels and update
matching unified_documents rows with scene keywords.
"""
import argparse
import asyncio
import json

from backend.collectors.photo_processor import analyze_image_vision
from backend.config import settings
from backend.database import SessionLocal
from backend.models.photo import Photo
from backend.models.unified_document import UnifiedDocument
from backend.utils.pii_mask import mask_pii


def _merge_vision(existing_raw: str | None, vision: dict) -> str:
    try:
        existing = json.loads(existing_raw or "{}")
    except json.JSONDecodeError:
        existing = {}
    existing["ocr_text"] = vision.get("ocr_text") or existing.get("ocr_text")
    existing["labels"] = vision.get("labels") or existing.get("labels") or []
    return json.dumps(existing, ensure_ascii=False)


def _build_scene_text(filename: str | None, vision: dict) -> str:
    labels = [
        item["description"]
        for item in vision.get("labels", [])
        if item.get("description")
    ]
    parts = [f"사진 업로드: {filename or 'photo'}"]
    if labels:
        parts.append(f"장면 키워드: {', '.join(labels[:8])}")
    if vision.get("ocr_text"):
        parts.append(f"OCR 텍스트: {mask_pii(vision['ocr_text'])[:1200]}")
    return "\n".join(parts)


async def backfill(*, execute: bool, user_id: int | None, limit: int | None) -> None:
    if not settings.google_api_key:
        raise SystemExit("GOOGLE_API_KEY or google_api_key is required for Vision backfill")

    db = SessionLocal()
    try:
        query = db.query(Photo).filter(Photo.image_data.isnot(None))
        if user_id is not None:
            query = query.filter(Photo.user_id == user_id)
        query = query.order_by(Photo.id)
        if limit is not None:
            query = query.limit(limit)
        photos = query.all()

        updated = 0
        skipped = 0
        for photo in photos:
            try:
                existing = json.loads(photo.vision_labels or "{}")
            except json.JSONDecodeError:
                existing = {}
            if existing.get("labels"):
                skipped += 1
                continue

            vision = await analyze_image_vision(photo.image_data, settings.google_api_key)
            labels = vision.get("labels") or []
            if not labels and not vision.get("ocr_text"):
                skipped += 1
                print(f"skip photo_id={photo.id}: no Vision labels/OCR")
                continue

            print(
                f"{'update' if execute else 'dry-run'} photo_id={photo.id} "
                f"user_id={photo.user_id} labels={[l['description'] for l in labels]}"
            )
            if execute:
                photo.vision_labels = _merge_vision(photo.vision_labels, vision)
                doc = (
                    db.query(UnifiedDocument)
                    .filter(
                        UnifiedDocument.user_id == photo.user_id,
                        UnifiedDocument.source == "photo",
                        UnifiedDocument.source_id == photo.id,
                    )
                    .first()
                )
                if doc:
                    doc.content_text = _build_scene_text(photo.original_filename, vision)[:2000]
                    doc.is_processed = False
                    doc.embedding_json = None
                    doc.cluster_id = None
                db.commit()
            updated += 1

        print(f"done updated={updated} skipped={skipped} execute={execute}")
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="write labels to the database")
    parser.add_argument("--user-id", type=int)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    asyncio.run(backfill(execute=args.execute, user_id=args.user_id, limit=args.limit))


if __name__ == "__main__":
    main()
