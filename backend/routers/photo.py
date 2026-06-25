import os
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, UploadFile, File
from PIL import Image
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.photo import Photo
from backend.collectors.photo_processor import extract_exif

router = APIRouter()

UPLOAD_DIR = "uploads/photos"


@router.post("/upload")
async def upload_photos(
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    """사진 업로드 + EXIF 파싱"""
    user_id = 1  # TODO: JWT에서 추출
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

        photo = Photo(
            user_id=user_id,
            file_path=filepath,
            original_filename=original_name,
            taken_at=exif_data.get("taken_at") or datetime.now(),
            latitude=exif_data.get("latitude"),
            longitude=exif_data.get("longitude"),
            camera_model=exif_data.get("camera_model"),
            file_size=len(content),
            width=width,
            height=height,
        )
        db.add(photo)
        results.append({"filename": filename, "exif": exif_data})

    db.commit()
    return {"uploaded": len(results), "results": results}
