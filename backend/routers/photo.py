import hashlib
import io
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, UploadFile, File
from PIL import Image
from sqlalchemy.orm import Session

from backend.config import settings
from backend.database import get_db
from backend.models.photo import Photo
from backend.models.unified_document import UnifiedDocument
from backend.collectors.photo_processor import extract_exif, extract_text_vision, is_screenshot
from backend.routers.auth import decode_jwt
from backend.utils.pii_mask import mask_pii

router = APIRouter()

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_FILES_PER_UPLOAD = 20
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024
MAX_TOTAL_UPLOAD_BYTES = 80 * 1024 * 1024


def _resolve_user_id(authorization: str | None) -> int:
    if authorization and authorization.startswith("Bearer "):
        return decode_jwt(authorization.removeprefix("Bearer "))
    raise HTTPException(status_code=401, detail="인증 필요: Authorization 헤더가 필요합니다")


def _validate_file(original_name: str, content_type: str | None, content: bytes) -> None:
    if content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported image type for {original_name}: {content_type or 'unknown'}",
        )
    if not content:
        raise HTTPException(status_code=400, detail=f"Empty file: {original_name}")
    if len(content) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(status_code=413, detail=f"File too large: {original_name}")

    try:
        with Image.open(io.BytesIO(content)) as img:
            img.verify()
    except Exception:
        raise HTTPException(status_code=400, detail=f"Invalid image file: {original_name}")


def _build_photo_content(original_name: str, exif_data: dict, width: int | None, height: int | None) -> str:
    parts = [f"사진 업로드: {original_name}"]
    if exif_data.get("camera_model"):
        parts.append(f"카메라: {exif_data['camera_model']}")
    if width and height:
        parts.append(f"크기: {width}x{height}")
    if exif_data.get("latitude") is not None and exif_data.get("longitude") is not None:
        parts.append(f"위치: {exif_data['latitude']:.6f}, {exif_data['longitude']:.6f}")
    return "\n".join(parts)


@router.post("/upload")
async def upload_photos(
    files: list[UploadFile] = File(...),
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """사진 업로드 + EXIF 파싱. 파일은 디스크에 저장하지 않고 메모리에서 처리.

    같은 사진이 다시 업로드되면(자동 동기화가 카메라롤을 재스캔하는 경우 등)
    content_hash로 감지해서 EXIF/OCR 재처리 없이 건너뛴다 — 프론트가 "마지막
    동기화 이후"를 추적하지 못해도 서버 쪽에서 안전하게 중복을 막는다.
    """
    user_id = _resolve_user_id(authorization)
    if len(files) > MAX_FILES_PER_UPLOAD:
        raise HTTPException(status_code=413, detail="Too many files in one upload")

    results = []
    total_size = 0
    for file in files:
        original_name = file.filename or "unknown.jpg"
        content = await file.read()
        _validate_file(original_name, file.content_type, content)
        total_size += len(content)
        if total_size > MAX_TOTAL_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="Upload batch too large")
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

        doc_content = mask_pii(ocr_text)[:2000] if ocr_text else _build_photo_content(
            original_name,
            exif_data,
            width,
            height,
        )
        doc = UnifiedDocument(
            user_id=user_id,
            source="photo",
            source_id=photo.id,
            content_text=doc_content,
            content_type="screenshot" if screenshot else "photo",
            title=original_name if screenshot else f"사진 {original_name}",
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
