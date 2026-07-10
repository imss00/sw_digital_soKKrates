import hashlib
import io
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, UploadFile, File, Query
from PIL import Image
from sqlalchemy.orm import Session

from backend.config import settings
from backend.database import get_db
from backend.models.photo import Photo
from backend.models.unified_document import UnifiedDocument
from backend.collectors.photo_processor import extract_exif, extract_text_vision, is_screenshot
from backend.utils.pii_mask import mask_pii

router = APIRouter()


@router.post("/upload")
async def upload_photos(
    files: list[UploadFile] = File(...),
    user_id: int = Query(..., description="업로드할 유저 ID"),
    db: Session = Depends(get_db),
):
    """사진 업로드 + EXIF 파싱. 파일은 디스크에 저장하지 않고 메모리에서 처리.

    같은 사진이 다시 업로드되면(자동 동기화가 카메라롤을 재스캔하는 경우 등)
    content_hash로 감지해서 EXIF/OCR 재처리 없이 건너뛴다 — 프론트가 "마지막
    동기화 이후"를 추적하지 못해도 서버 쪽에서 안전하게 중복을 막는다.
    """
    results = []
    for file in files:
        original_name = file.filename or "unknown.jpg"
        content = await file.read()
        content_hash = hashlib.sha256(content).hexdigest()

        existing = (
            db.query(Photo)
            .filter(Photo.user_id == user_id, Photo.content_hash == content_hash)
            .first()
        )
        if existing:
            results.append({
                "filename": original_name,
                "duplicate": True,
                "photo_id": existing.id,
            })
            continue

        exif_data = extract_exif(content)

        width, height = None, None
        try:
            img = Image.open(io.BytesIO(content))
            width, height = img.size
        except Exception:
            pass

        ocr_text = None
        screenshot = is_screenshot(original_name, exif_data)
        if screenshot and settings.google_api_key:
            try:
                ocr_text = await extract_text_vision(content, settings.google_api_key)
            except Exception:
                ocr_text = None

        now = datetime.now(timezone.utc)
        photo = Photo(
            user_id=user_id,
            file_path=None,
            original_filename=original_name,
            content_hash=content_hash,
            taken_at=exif_data.get("taken_at") or now,
            latitude=exif_data.get("latitude"),
            longitude=exif_data.get("longitude"),
            camera_model=exif_data.get("camera_model"),
            file_size=len(content),
            width=width,
            height=height,
            vision_labels=json.dumps({"ocr_text": ocr_text}, ensure_ascii=False) if ocr_text else None,
        )
        db.add(photo)
        db.flush()

        if ocr_text:
            doc = UnifiedDocument(
                user_id=user_id,
                source="photo",
                source_id=photo.id,
                content_text=mask_pii(ocr_text)[:2000],
                content_type="screenshot",
                title=original_name,
                occurred_at=exif_data.get("taken_at") or now,
            )
            db.add(doc)

        results.append({
            "filename": original_name,
            "exif": exif_data,
            "screenshot": screenshot,
            "ocr_text": ocr_text,
        })

    db.commit()
    return {"uploaded": len(results), "results": results}
