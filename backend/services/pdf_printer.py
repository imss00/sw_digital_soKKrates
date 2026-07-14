"""매일 신문 페이지를 헤드리스 브라우저(Playwright)로 렌더링해 인쇄용 PDF로 만든다.

FE(App_realistic.jsx)는 라우터가 없는 SPA라서, 특정 날짜 화면으로 바로 들어가려면
쿼리 파라미터를 이용한다:
  - ?token=<JWT>        로그인 없이 인증 (backend/routers/auth.py의 웹 로그인 리다이렉트와 동일한 방식)
  - ?print_date=YYYY-MM-DD  우편함 화면을 건너뛰고 바로 해당 날짜의 신문 페이지로 진입

FE는 저널/사진 데이터까지 다 실리고 레이아웃이 안정되면
body[data-print-ready="true"] 를 세팅한다 (App_realistic.jsx 참고). 그 신호를 기다린 뒤
@media print 스타일(App_realistic.jsx 하단 @page A3 규칙)을 그대로 살려서 PDF로 뽑는다.
"""

import asyncio

from playwright.async_api import async_playwright

from backend.config import settings
from backend.routers.auth import issue_jwt_for_user

PRINT_READY_SELECTOR = 'body[data-print-ready="true"]'
PRINT_READY_TIMEOUT_MS = 20_000


async def render_journal_pdf(target_date: str, user_id: int) -> bytes:
    """target_date(YYYY-MM-DD) 신문 페이지를 A3 PDF 바이트로 렌더링한다.

    실패(저널 없음/타임아웃 등)는 그대로 예외를 올려서 호출자(celery task)가
    이메일을 보내지 않고 실패 처리하게 한다.
    """
    token = issue_jwt_for_user(user_id)
    url = f"{settings.frontend_base_url}/?token={token}&print_date={target_date}"

    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
        try:
            page = await browser.new_page(viewport={"width": 1240, "height": 1754})
            await page.goto(url, wait_until="networkidle", timeout=30_000)
            await page.wait_for_selector(PRINT_READY_SELECTOR, timeout=PRINT_READY_TIMEOUT_MS)
            await page.emulate_media(media="print")
            pdf_bytes = await page.pdf(
                print_background=True,
                prefer_css_page_size=True,  # App_realistic.jsx의 @page { size: A3; margin: 16mm } 그대로 사용
            )
            return pdf_bytes
        finally:
            await browser.close()


def render_journal_pdf_sync(target_date: str, user_id: int) -> bytes:
    """Celery(동기) 태스크에서 호출하기 위한 래퍼."""
    return asyncio.run(render_journal_pdf(target_date, user_id))
