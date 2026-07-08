#!/usr/bin/env python3
"""
기존 unified_documents.content_text 일회성 PII 마스킹 백필 스크립트.

mask_pii()를 normalize.py/photo.py에 연결하기 전에 이미 정규화되어 저장된
문서들은 여전히 원문(비마스킹) 상태다 — journal_composer가 저널 생성 시
이 content_text를 그대로 프롬프트에 넣어 OpenAI로 보내므로, 과거 문서도
백필해야 한다.

mask_pii()는 이미 마스킹된 텍스트에 다시 적용해도 안전(idempotent, 마스킹
토큰([EMAIL] 등)은 PII 패턴과 매치되지 않음)하므로 전체 재실행해도 무해하다.

주의: embedding_json은 재계산하지 않는다 — 과거 임베딩 벡터는 마스킹 전
원문 기준으로 이미 OpenAI에 전송되어 계산된 것이라 지금 다시 계산해도
그 사실 자체를 되돌릴 수는 없다. 이 스크립트는 "앞으로" 저널 생성 등에서
content_text가 재사용될 때 마스킹된 버전이 쓰이도록 하는 것이 목적이다.

사용법 (레포 루트에서):
  python scripts/mask_existing_content.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database import SessionLocal
from backend.models.unified_document import UnifiedDocument
from backend.utils.pii_mask import mask_pii


def main() -> None:
    db = SessionLocal()
    try:
        docs = db.query(UnifiedDocument).filter(UnifiedDocument.content_text.isnot(None)).all()

        changed = 0
        for doc in docs:
            masked = mask_pii(doc.content_text)
            if masked != doc.content_text:
                doc.content_text = masked
                changed += 1

        db.commit()
        print(f"검사 완료: {len(docs)}건 중 {changed}건에서 PII 마스킹 적용됨.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
