import json
import os
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, UploadFile, File
from PIL import Image
from sqlalchemy.orm import Session

from backend.config import settings
from backend.database import get_db
from backend.models.photo import Photo
from backend.models.unified_document import UnifiedDocument
from backend.collectors.photo_processor import extract_exif, extract_text_vision, is_screenshot

router = APIRouter()

UPLOAD_DIR = "uploads/photos"


@router.post("/upload")
async def upload_photos(
    files: list[UploadFile] = File(...),
    user_id: int = 3,
    db: Session = Depends(get_db),
):
    """사진 업로드 + EXIF 파싱. 스크린샷은 Vision API OCR로 텍스트 추출."""
    today = datetime.now().strftime("%Y-%m-%d")
    save_dir = os.path.join(UPLOAD_DIR, str(user_id), today)
    os.makedirs(save_dir, exist_ok=True)

    results = []
    for file in files:
        original_name = file.filename or "unknown.jpg"
        ext = os.path.splitext(original_name)[1]
        filename = f"{uuid.uuid4()}{ext}"
        filepath = os.path.join(save_dir, filename)

        content = await file.read()
        with open(filepath, "wb") as f:
            f.write(content)

        exif_data = extract_exif(filepath)

        width, height = None, None
        try:
            img = Image.open(filepath)
            width, height = img.size
        except Exception:
            pass

        ocr_text = None
        screenshot = is_screenshot(filepath, exif_data)
        if screenshot and settings.google_api_key:
            ocr_text = extract_text_vision(filepath, settings.google_api_key)

        now = datetime.now(timezone.utc)
        photo = Photo(
            user_id=user_id,
            file_path=filepath,
            original_filename=original_name,
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
                content_text=ocr_text[:2000],
                content_type="screenshot",
                title=original_name,
                occurred_at=exif_data.get("taken_at") or now,
            )
            db.add(doc)

        results.append({
            "filename": filename,
            "exif": exif_data,
            "screenshot": screenshot,
            "ocr_text": ocr_text,
        })

    db.commit()
    return {"uploaded": len(results), "results": results}
