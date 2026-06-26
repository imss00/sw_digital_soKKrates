import base64
from datetime import datetime

import httpx
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS


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


def extract_text_vision(file_path: str, api_key: str) -> str | None:
    """Google Vision API TEXT_DETECTION으로 이미지에서 텍스트 추출"""
    with open(file_path, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode()

    payload = {
        "requests": [{
            "image": {"content": image_b64},
            "features": [{"type": "TEXT_DETECTION", "maxResults": 1}],
        }]
    }

    resp = httpx.post(
        f"https://vision.googleapis.com/v1/images:annotate?key={api_key}",
        json=payload,
        timeout=30,
    )
    if resp.status_code != 200:
        return None

    responses = resp.json().get("responses", [])
    if not responses:
        return None

    text = responses[0].get("fullTextAnnotation", {}).get("text", "")
    return text.strip() or None


def is_screenshot(file_path: str, exif_data: dict) -> bool:
    """EXIF가 없는 PNG면 스크린샷으로 판단"""
    if file_path.lower().endswith(".png"):
        return True
    return not exif_data.get("taken_at") and not exif_data.get("latitude")


def extract_exif(file_path: str) -> dict:
    """사진 파일에서 EXIF 메타데이터 추출"""
    result = {
        "taken_at": None,
        "latitude": None,
        "longitude": None,
        "camera_model": None,
    }

    try:
        img = Image.open(file_path)
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
            result["taken_at"] = datetime.strptime(exif["DateTimeOriginal"], "%Y:%m:%d %H:%M:%S")
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
