"""
역할 A — A-1. 임베딩 파이프라인
unified_documents의 content_text를 OpenAI 벡터로 변환하고 DB에 저장한다.
"""
import json
from datetime import date, datetime, timedelta, timezone

from openai import OpenAI
from sqlalchemy.orm import Session

from backend.models.unified_document import UnifiedDocument

KST = timezone(timedelta(hours=9))
EMBEDDING_MODEL = "text-embedding-3-small"  # 1536차원


def embed_texts(texts: list[str]) -> list[list[float]]:
    """텍스트 배열을 한 번의 API 호출로 임베딩 (최대 2048개)"""
    client = OpenAI()
    response = client.embeddings.create(model=EMBEDDING_MODEL, input=texts)
    return [item.embedding for item in response.data]


def embed_and_store(user_id: int, target_date: date, db: Session) -> dict:
    """
    하루치 미처리 unified_documents를 임베딩해서 embedding_json에 저장.
    clusterer.py가 이 함수 호출 후 embedding_json을 읽어간다.
    """
    day_start = datetime.combine(target_date, datetime.min.time()).replace(tzinfo=KST)
    day_end = day_start + timedelta(days=1)

    docs = (
        db.query(UnifiedDocument)
        .filter(
            UnifiedDocument.user_id == user_id,
            UnifiedDocument.occurred_at >= day_start,
            UnifiedDocument.occurred_at < day_end,
            UnifiedDocument.embedding_json.is_(None),  # 아직 임베딩 안 된 것만
        )
        .all()
    )

    if not docs:
        return {"status": "skip", "reason": "no unembedded documents"}

    texts = [doc.content_text for doc in docs]

    # TODO: 텍스트가 너무 길면 OpenAI 토큰 제한 초과 가능 — 필요 시 청크 처리
    vectors = embed_texts(texts)

    for doc, vector in zip(docs, vectors):
        doc.embedding_json = json.dumps(vector)

    db.commit()
    return {"status": "ok", "embedded": len(docs)}
