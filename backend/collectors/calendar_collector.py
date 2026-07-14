import logging
from datetime import date, datetime, timedelta, timezone

from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from sqlalchemy.orm import Session

from backend.config import settings
from backend.models.calendar_event import CalendarEvent
from backend.models.user import User

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))


def collect_calendar(user_id: int, db: Session, target_date: date | None = None) -> dict:
    """Google Calendar 이벤트를 하루 단위로 수집한다.

    target_date를 생략하면 기존 동작과 같이 KST 기준 어제를 수집한다.
    저널 생성은 target_date+1의 일정도 필요로 하므로 호출자가 날짜를 명시할 수 있어야 한다.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.google_refresh_token:
        return {"status": "skip", "reason": "no google token"}

    creds = Credentials(
        token=None,
        refresh_token=user.google_refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
    )

    service = build("calendar", "v3", credentials=creds)

    if target_date is None:
        target_date = datetime.now(KST).date() - timedelta(days=1)
    day_start = datetime.combine(target_date, datetime.min.time()).replace(tzinfo=KST)
    day_end = day_start + timedelta(days=1)

    try:
        events_result = service.events().list(
            calendarId="primary",
            timeMin=day_start.isoformat(),
            timeMax=day_end.isoformat(),
            singleEvents=True,
            orderBy="startTime",
        ).execute()
    except (RefreshError, HttpError) as e:
        logger.error("calendar collection failed user_id=%s error=%s", user_id, e)
        return {"status": "error", "reason": str(e)}

    inserted = 0
    updated = 0
    for event in events_result.get("items", []):
        if event.get("status") == "cancelled":
            continue

        start = event["start"]
        end = event["end"]

        if "dateTime" in start:
            start_time = datetime.fromisoformat(start["dateTime"])
            end_time = datetime.fromisoformat(end["dateTime"])
        else:
            start_time = datetime.fromisoformat(start["date"]).replace(tzinfo=KST)
            end_time = datetime.fromisoformat(end["date"]).replace(tzinfo=KST)

        duration_min = int((end_time - start_time).total_seconds() / 60)

        existing = (
            db.query(CalendarEvent)
            .filter_by(user_id=user_id, google_event_id=event["id"])
            .first()
        )
        if existing:
            existing.summary = event.get("summary", "")
            existing.description = event.get("description")
            existing.start_time = start_time
            existing.end_time = end_time
            existing.duration_min = duration_min
            existing.location = event.get("location")
            existing.is_recurring = "recurringEventId" in event
            existing.attendee_count = len(event.get("attendees", []))
            updated += 1
            continue

        entry = CalendarEvent(
            user_id=user_id,
            google_event_id=event["id"],
            summary=event.get("summary", ""),
            description=event.get("description"),
            start_time=start_time,
            end_time=end_time,
            duration_min=duration_min,
            location=event.get("location"),
            is_recurring="recurringEventId" in event,
            attendee_count=len(event.get("attendees", [])),
        )
        db.add(entry)
        inserted += 1

    db.commit()
    return {"status": "ok", "inserted": inserted, "updated": updated, "date": target_date.isoformat()}
