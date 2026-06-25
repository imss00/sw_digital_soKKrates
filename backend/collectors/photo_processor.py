from datetime import datetime

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
