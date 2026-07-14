"""Resend REST API로 이메일(PDF 첨부) 발송.

별도 SDK 없이 httpx로 직접 호출 — requirements.txt에 httpx가 이미 있어서 새 의존성이 없음.
https://resend.com/docs/api-reference/emails/send-email
"""

import base64

import httpx

from backend.config import settings

RESEND_API_URL = "https://api.resend.com/emails"


def send_pdf_email(
    *,
    to: str,
    subject: str,
    body_text: str,
    pdf_bytes: bytes,
    filename: str,
) -> dict:
    """PDF를 첨부해 이메일을 보낸다. 실패 시 예외를 올린다(호출자가 재시도/알림 처리)."""
    if not settings.resend_api_key:
        raise RuntimeError("RESEND_API_KEY가 설정되지 않았습니다.")
    if not to:
        raise RuntimeError("PRINTER_EMAIL이 설정되지 않았습니다.")

    payload = {
        "from": settings.print_from_email,
        "to": [to],
        "subject": subject,
        "text": body_text,
        "attachments": [
            {
                "filename": filename,
                "content": base64.b64encode(pdf_bytes).decode("ascii"),
            }
        ],
    }

    resp = httpx.post(
        RESEND_API_URL,
        headers={
            "Authorization": f"Bearer {settings.resend_api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=30.0,
    )
    if resp.status_code >= 300:
        raise RuntimeError(f"Resend 이메일 발송 실패: HTTP {resp.status_code} {resp.text}")
    return resp.json()
