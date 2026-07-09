
"""
역할 A — A-1. 임베딩 파이프라인 (OpenAI 버전)
unified_documents의 content_text를 OpenAI 임베딩 벡터로 변환하고 DB에 저장한다.

Gemini 대신 OpenAI를 쓰는 이유:
- Gemini 무료 한도/계정 정지로 파이프라인이 막히는 문제 회피 (유료 → 정지·한도 리스크 없음)
- 배포 서버(Fly.io 256MB)에 임베딩 모델을 올리지 않고 API 호출만 함 → 서버 부담 0
- 생성(recommender)도 OpenAI로 통일 → 키·결제 하나로 관리
"""
import json
from datetime import date, datetime, timedelta, timezone

from openai import OpenAI
from sqlalchemy.orm import Session

from backend.models.unified_document import UnifiedDocument
from backend.config import settings

KST = timezone(timedelta(hours=9))

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIM = 1536

# 클라이언트는 프로세스당 1회만 생성(싱글턴)
_client = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=settings.openai_api_key or None)
    return _client


def embed_texts(texts: list[str]) -> list[list[float]]:
    """텍스트 배열을 OpenAI 임베딩 API로 변환 (벡터 좌표로 변환).

    빈 텍스트는 0 벡터로 채워 인덱스 정렬을 유지한다.
    비어있지 않은 텍스트만 한 번의 배치 요청으로 임베딩한다.
    """
    nonempty_idx = [i for i, t in enumerate(texts) if t and t.strip()]
    out: list[list[float]] = [[0.0] * EMBEDDING_DIM for _ in texts]

    if nonempty_idx:
        resp = _get_client().embeddings.create(
            model=EMBEDDING_MODEL,
            input=[texts[i] for i in nonempty_idx],
        )
        # resp.data 각 항목의 index로 원래 위치에 정확히 매핑
        for item in resp.data:
            out[nonempty_idx[item.index]] = item.embedding

    return out


def embed_and_store(user_id: int, target_date: date, db: Session) -> dict:
    """
    하루치 미처리 unified_documents를 임베딩해서 embedding_json에 저장.
    이후 clusterer.py가 이 함수가 저장한 embedding_json을 읽어갑니다.
    """
    day_start = datetime.combine(target_date, datetime.min.time()).replace(tzinfo=KST)
    day_end = day_start + timedelta(days=1)

    # 1. DB에서 오늘 치 전체 데이터를 먼저 가져와서, "그날 문서가 아예 없음"과
    #    "이미 다 임베딩됨"을 구분한다 (호출부가 같은 걸 구분하려고 별도 쿼리를 또 만들지 않도록).
    day_docs = (
        db.query(UnifiedDocument)
        .filter(
            UnifiedDocument.user_id == user_id,
            UnifiedDocument.occurred_at >= day_start,
            UnifiedDocument.occurred_at < day_end,
        )
        .all()
    )
    if not day_docs:
        return {"status": "skip", "reason": "no documents for this day"}

    docs = [d for d in day_docs if d.embedding_json is None]
    if not docs:
        return {"status": "skip", "reason": "no unembedded documents"}

    # 2. 가져온 데이터에서 텍스트만 쏙쏙 뽑아내기
    texts = [doc.content_text for doc in docs]

    # 3. OpenAI 임베딩 API에 넣어서 벡터(좌표)로 변환해 오기
    vectors = embed_texts(texts)

    # 4. 변환된 좌표를 다시 DB의 각 줄(row)에 예쁘게 JSON으로 저장하기
    for doc, vector in zip(docs, vectors):
        doc.embedding_json = json.dumps(vector)

    # 5. DB에 최종 도장 찍기(저장 확정)
    db.commit()
    return {"status": "ok", "embedded": len(docs)}
