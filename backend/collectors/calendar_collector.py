from datetime import datetime, timedelta, timezone

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from sqlalchemy.orm import Session

from backend.config import settings
from backend.models.calendar_event import CalendarEvent
from backend.models.user import User

KST = timezone(timedelta(hours=9))


def collect_calendar(user_id: int, db: Session) -> dict:
    """어제의 Google Calendar 이벤트 수집"""
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

    now = datetime.now(KST)
    yesterday_start = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_end = yesterday_start + timedelta(days=1)

    events_result = service.events().list(
        calendarId="primary",
        timeMin=yesterday_start.isoformat(),
        timeMax=yesterday_end.isoformat(),
        singleEvents=True,
        orderBy="startTime",
    ).execute()

    inserted = 0
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
    return {"status": "ok", "inserted": inserted}
