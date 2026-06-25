from datetime import datetime, timedelta, timezone
import time

import httpx
from sqlalchemy.orm import Session

from backend.models.notion_page import NotionPage
from backend.models.user import User

NOTION_VERSION = "2022-06-28"


def _extract_text_from_blocks(blocks: list) -> str:
    """블록 리스트에서 plain text 추출"""
    texts = []
    for block in blocks:
        block_type = block.get("type", "")
        block_data = block.get(block_type, {})

        if "rich_text" in block_data:
            line = "".join(rt.get("plain_text", "") for rt in block_data["rich_text"])
            if line.strip():
                texts.append(line.strip())

    return "\n".join(texts)


def collect_notion(user_id: int, db: Session) -> dict:
    """최근 24시간 내 수정된 Notion 페이지 수집"""
    user = db.query(User).filter(User.id == user_id).first()
    token = user.notion_token if user and user.notion_token else ""
    if not token:
        return {"status": "skip", "reason": "no notion token"}

    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }

    since = datetime.now(timezone.utc) - timedelta(days=1)

    resp = httpx.post(
        "https://api.notion.com/v1/search",
        headers=headers,
        json={
            "filter": {"property": "object", "value": "page"},
            "sort": {"direction": "descending", "timestamp": "last_edited_time"},
        },
        timeout=30,
    )

    if resp.status_code != 200:
        return {"status": "error", "reason": f"search failed: {resp.status_code}"}

    pages = resp.json().get("results", [])

    inserted = 0
    for page in pages:
        last_edited = datetime.fromisoformat(page["last_edited_time"].replace("Z", "+00:00"))
        if last_edited < since:
            continue

        page_id = page["id"]

        title_parts = []
        for prop in page.get("properties", {}).values():
            if prop.get("type") == "title":
                for t in prop.get("title", []):
                    title_parts.append(t.get("plain_text", ""))
        title = " ".join(title_parts) or "Untitled"

        time.sleep(0.35)  # rate limit: 3 req/sec
        blocks_resp = httpx.get(
            f"https://api.notion.com/v1/blocks/{page_id}/children",
            headers=headers,
            timeout=30,
        )

        content_text = ""
        if blocks_resp.status_code == 200:
            blocks = blocks_resp.json().get("results", [])
            content_text = _extract_text_from_blocks(blocks)

        content_text = content_text[:5000]

        existing = (
            db.query(NotionPage)
            .filter_by(user_id=user_id, notion_page_id=page_id)
            .first()
        )
        if existing:
            existing.title = title
            existing.content_text = content_text
            existing.last_edited = last_edited
        else:
            db.add(NotionPage(
                user_id=user_id,
                notion_page_id=page_id,
                title=title,
                content_text=content_text,
                last_edited=last_edited,
            ))
        inserted += 1

    db.commit()
    return {"status": "ok", "inserted": inserted}
