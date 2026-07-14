import logging

from backend.config import settings
from backend.tasks.celery_app import celery_app
from backend.tasks.collection_tasks import default_target_date

logger = logging.getLogger(__name__)


@celery_app.task(name="backend.tasks.print_tasks.print_daily_newspaper")
def print_daily_newspaper():
    """매일 아침: 어제자 신문을 A3 PDF로 렌더링해 프린터 이메일로 발송.

    PRINT_ENABLED=false(기본값)면 아무 것도 하지 않고 건너뛴다.
    PRINTER_EMAIL / RESEND_API_KEY / PRINT_USER_ID 중 하나라도 비어있으면 스킵하고 경고 로그만 남긴다
    (설정 전에 배포해도 다른 스케줄(수집/정규화)에 영향 없게 하기 위함).
    """
    if not settings.print_enabled:
        logger.info("print_daily_newspaper: PRINT_ENABLED=false, 건너뜀")
        return {"skipped": "print_disabled"}

    missing = [
        name
        for name, value in [
            ("PRINTER_EMAIL", settings.printer_email),
            ("RESEND_API_KEY", settings.resend_api_key),
            ("PRINT_USER_ID", settings.print_user_id),
        ]
        if not value
    ]
    if missing:
        logger.warning("print_daily_newspaper: 설정 누락 %s, 건너뜀", missing)
        return {"skipped": "missing_config", "missing": missing}

    target_date = default_target_date()  # KST 기준 어제 — journal_composer의 대상 날짜와 동일
    target_date_str = str(target_date)

    try:
        from backend.services.pdf_printer import render_journal_pdf_sync

        pdf_bytes = render_journal_pdf_sync(target_date_str, settings.print_user_id)
    except Exception:
        logger.exception("print_daily_newspaper: PDF 렌더링 실패 (target_date=%s)", target_date_str)
        raise

    try:
        from backend.services.emailer import send_pdf_email

        send_pdf_email(
            to=settings.printer_email,
            subject=f"[PaperBack] {target_date_str} 신문 인쇄",
            body_text=f"{target_date_str}자 신문을 첨부합니다. 자동 발송 메일입니다.",
            pdf_bytes=pdf_bytes,
            filename=f"paperback-{target_date_str}.pdf",
        )
    except Exception:
        logger.exception("print_daily_newspaper: 이메일 발송 실패 (target_date=%s)", target_date_str)
        raise

    logger.info("print_daily_newspaper: 발송 완료 (target_date=%s)", target_date_str)
    return {"target_date": target_date_str, "sent_to": settings.printer_email}
