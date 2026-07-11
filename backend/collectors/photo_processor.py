import base64
from datetime import datetime, timezone, timedelta

import httpx
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS

KST = timezone(timedelta(hours=9))
MIN_LABEL_SCORE = 0.65
GENERIC_LABELS = {
    "adaptation",
    "atmosphere",
    "black",
    "blue",
    "darkness",
    "event",
    "font",
    "fun",
    "happy",
    "human",
    "image",
    "line",
    "material property",
    "mode of transport",
    "natural environment",
    "organism",
    "people",
    "person",
    "photograph",
    "rectangle",
    "snapshot",
    "sky",
    "text",
    "white",
    "world",
}


def _convert_gps_to_decimal(gps_coords, gps_ref) -> float | None:
    """GPS 도분초 → 소수점 좌표 변환"""
    try:
        degrees = float(gps_coords[0])
        minutes = float(gps_coords[1])
        seconds = float(gps_coords[2])
        decimal = degrees + minutes / 60 + seconds / 3600
        if gps_ref in ("S", "W"):
            decimal = -decimal
        return decimal
    except (IndexError, TypeError, ValueError):
        return None


async def analyze_image_vision(image_bytes: bytes, api_key: str) -> dict:
    """Google Vision API로 OCR 텍스트와 장면 라벨을 함께 추출한다."""
    image_b64 = base64.b64encode(image_bytes).decode()

    payload = {
        "requests": [{
            "image": {"content": image_b64},
            "features": [
                {"type": "TEXT_DETECTION", "maxResults": 1},
                {"type": "LABEL_DETECTION", "maxResults": 8},
            ],
        }]
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"https://vision.googleapis.com/v1/images:annotate?key={api_key}",
            json=payload,
        )

    if resp.status_code != 200:
        return {"ocr_text": None, "labels": []}

    responses = resp.json().get("responses", [])
    if not responses:
        return {"ocr_text": None, "labels": []}

    first = responses[0]
    text = first.get("fullTextAnnotation", {}).get("text", "")
    labels = filter_scene_labels(first.get("labelAnnotations", []))
    return {"ocr_text": text.strip() or None, "labels": labels}


async def extract_text_vision(image_bytes: bytes, api_key: str) -> str | None:
    """Google Vision API TEXT_DETECTION으로 이미지에서 텍스트 추출."""
    result = await analyze_image_vision(image_bytes, api_key)
    return result["ocr_text"]


def filter_scene_labels(raw_labels: list[dict], *, limit: int = 8) -> list[dict]:
    """Vision 라벨 중 저널 장면 설명에 쓸 만한 항목만 남긴다."""
    filtered: list[dict] = []
    seen: set[str] = set()
    for item in raw_labels:
        description = (item.get("description") or "").strip()
        if not description:
            continue
        key = description.lower()
        if key in seen or key in GENERIC_LABELS:
            continue
        score = item.get("score")
        if score is not None and score < MIN_LABEL_SCORE:
            continue
        filtered.append({"description": description, "score": score})
        seen.add(key)
        if len(filtered) >= limit:
            break
    return filtered


def is_screenshot(filename: str, exif_data: dict) -> bool:
    """EXIF(촬영시각+위치) 없는 PNG면 스크린샷으로 판단. EXIF 있는 PNG 사진은 제외."""
    if not filename.lower().endswith(".png"):
        return False
    return not exif_data.get("taken_at") and not exif_data.get("latitude")


def extract_exif(image_bytes: bytes) -> dict:
    """사진 바이트에서 EXIF 메타데이터 추출 (디스크 저장 불필요)"""
    import io

    result = {
        "taken_at": None,
        "latitude": None,
        "longitude": None,
        "camera_model": None,
    }

    try:
        img = Image.open(io.BytesIO(image_bytes))
        exif_data = img._getexif()
        if not exif_data:
            return result
    except Exception:
        return result

    exif = {}
    for tag_id, value in exif_data.items():
        tag_name = TAGS.get(tag_id, tag_id)
        exif[tag_name] = value

    if "DateTimeOriginal" in exif:
        try:
            # EXIF 시각은 로컬 시간(KST)으로 저장됨 — timezone-aware로 변환
            result["taken_at"] = datetime.strptime(
                exif["DateTimeOriginal"], "%Y:%m:%d %H:%M:%S"
            ).replace(tzinfo=KST)
        except ValueError:
            pass

    if "Model" in exif:
        result["camera_model"] = exif["Model"]

    if "GPSInfo" in exif:
        gps = {}
        for key, val in exif["GPSInfo"].items():
            gps_tag = GPSTAGS.get(key, key)
            gps[gps_tag] = val

        if "GPSLatitude" in gps and "GPSLatitudeRef" in gps:
            result["latitude"] = _convert_gps_to_decimal(gps["GPSLatitude"], gps["GPSLatitudeRef"])
        if "GPSLongitude" in gps and "GPSLongitudeRef" in gps:
            result["longitude"] = _convert_gps_to_decimal(gps["GPSLongitude"], gps["GPSLongitudeRef"])

    return result
