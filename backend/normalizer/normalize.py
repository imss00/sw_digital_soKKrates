import json
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from backend.models.browsing_history import BrowsingHistory
from backend.models.spotify_history import SpotifyHistory
from backend.models.calendar_event import CalendarEvent
from backend.models.youtube_history import YouTubeHistory
from backend.models.notion_page import NotionPage
from backend.models.photo import Photo
from backend.models.unified_document import UnifiedDocument
from backend.utils.pii_mask import mask_pii

KST = timezone(timedelta(hours=9))

SKIP_DOMAINS = {"accounts.google.com", "chrome://", "localhost", "mail.google.com"}


def _should_skip(content_text: str | None) -> bool:
    if not content_text or len(content_text.strip()) < 10:
        return True
    return False


def normalize_chrome(record: BrowsingHistory) -> dict | None:
    if record.domain and any(d in record.domain for d in SKIP_DOMAINS):
        return None

    content = record.article_text or record.title or ""
    if _should_skip(content):
        return None
    content = mask_pii(content)

    return {
        "source": "chrome",
        "source_id": record.id,
        "content_text": content[:2000],
        "content_type": "article" if record.is_article else "browsing",
        "title": record.title,
        "occurred_at": record.visited_at,
    }


def normalize_spotify(record: SpotifyHistory) -> dict | None:
    genres_str = ", ".join(record.genres) if record.genres else ""
    parts = [f"{record.track_name} - {record.artist_name}"]
    if record.album_name:
        parts.append(f"앨범: {record.album_name}")
    if genres_str:
        parts.append(f"장르: {genres_str}")
    content = mask_pii(". ".join(parts))

    return {
        "source": "spotify",
        "source_id": record.id,
        "content_text": content[:2000],
        "content_type": "music",
        "title": record.track_name,
        "occurred_at": record.played_at,
        "mood_valence": record.valence,
        "mood_energy": record.energy,
    }


def normalize_calendar(record: CalendarEvent) -> dict | None:
    content = record.summary or ""
    if record.description:
        content += f": {record.description}"
    # 짧은 일정명도 그날의 유일한 활동일 수 있다. 일반 웹/문서용 최소 길이 규칙을
    # 캘린더에 적용하면 "회의", "근무" 같은 유효한 일정만 있는 날은 저널 생성
    # 대상에서 완전히 빠지므로, 캘린더는 비어 있는 일정만 제외한다.
    if not content.strip():
        return None
    content = mask_pii(content)

    return {
        "source": "calendar",
        "source_id": record.id,
        "content_text": content[:2000],
        "content_type": "event",
        "title": record.summary,
        "occurred_at": record.start_time,
    }


def normalize_youtube(record: YouTubeHistory) -> dict | None:
    content = record.title or ""
    if record.description:
        content += f". {record.description[:200]}"
    if record.tags:
        content += f" Tags: {', '.join(record.tags)}"
    if _should_skip(content):
        return None
    content = mask_pii(content)

    return {
        "source": "youtube",
        "source_id": record.id,
        "content_text": content[:2000],
        "content_type": "video",
        "title": record.title,
        "occurred_at": record.watched_at,
    }


def normalize_notion(record: NotionPage) -> dict | None:
    if _should_skip(record.content_text):
        return None
    content = mask_pii(record.content_text)

    return {
        "source": "notion",
        "source_id": record.id,
        "content_text": content[:2000],
        "content_type": "note",
        "title": record.title,
        "occurred_at": record.last_edited,
    }


def normalize_photo(record: Photo) -> dict | None:
    # 스크린샷 OCR 텍스트가 있으면 이미 upload 시점에 unified_documents에 직접 삽입됨
    if record.vision_labels:
        try:
            labels = json.loads(record.vision_labels)
            if labels.get("ocr_text"):
                return None  # 중복 삽입 방지
        except Exception:
            pass

    parts = [f"사진 촬영: {record.taken_at}"]
    if record.latitude and record.longitude:
        # 소수점 2자리(~1.1km)로 정밀도를 낮춰 정확한 자택/직장 위치가 드러나지 않게 함
        parts.append(f"위치: ({record.latitude:.2f}, {record.longitude:.2f})")
    if record.camera_model:
        parts.append(f"카메라: {record.camera_model}")

    return {
        "source": "photo",
        "source_id": record.id,
        "content_text": ", ".join(parts),
        "content_type": "photo",
        "title": f"사진 {record.taken_at}",
        "occurred_at": record.taken_at or record.created_at,
    }


def normalize_daily(user_id: int, target_date: date, db: Session) -> dict:
    """하루치 데이터를 unified_documents로 정규화 (중복 방지 포함)"""
    day_start = datetime.combine(target_date, datetime.min.time()).replace(tzinfo=KST)
    day_end = day_start + timedelta(days=1)

    normalizers = [
        (BrowsingHistory, "visited_at", normalize_chrome),
        (SpotifyHistory, "played_at", normalize_spotify),
        (CalendarEvent, "start_time", normalize_calendar),
        (YouTubeHistory, "watched_at", normalize_youtube),
        (NotionPage, "last_edited", normalize_notion),
        (Photo, "taken_at", normalize_photo),
    ]

    total_inserted = 0
    skipped_duplicate = 0

    for model, time_col, norm_func in normalizers:
        source_name = {
            BrowsingHistory: "chrome",
            SpotifyHistory: "spotify",
            CalendarEvent: "calendar",
            YouTubeHistory: "youtube",
            NotionPage: "notion",
            Photo: "photo",
        }[model]

        col = getattr(model, time_col)
        records = (
            db.query(model)
            .filter(model.user_id == user_id, col >= day_start, col < day_end)
            .all()
        )

        for record in records:
            # 중복 체크: 같은 user + source + source_id가 이미 있으면 스킵
            exists = (
                db.query(UnifiedDocument)
                .filter(
                    UnifiedDocument.user_id == user_id,
                    UnifiedDocument.source == source_name,
                    UnifiedDocument.source_id == record.id,
                )
                .first()
            )
            if exists:
                skipped_duplicate += 1
                continue

            normalized = norm_func(record)
            if not normalized:
                continue

            doc = UnifiedDocument(user_id=user_id, **normalized)
            db.add(doc)
            total_inserted += 1

    db.commit()
    return {
        "status": "ok",
        "inserted": total_inserted,
        "skipped_duplicate": skipped_duplicate,
        "date": str(target_date),
    }
