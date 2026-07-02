
"""
역할 A — A-1. 임베딩 파이프라인 (로컬 bge-m3 버전 🚀)
unified_documents의 content_text를 로컬 임베딩 모델(BAAI/bge-m3)로 벡터화하고 DB에 저장한다.

Gemini API 대신 로컬 모델을 쓰는 이유:
- API 한도(무료 일일 한도)·계정 정지 리스크 없음 → 반복 테스트에 안전
- 비용 0, 인터넷/키 불필요
- bge-m3는 다국어(한국어 강함) 모델이라 한국어 활동/기사 매칭에 적합
"""
import json
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from backend.models.unified_document import UnifiedDocument

KST = timezone(timedelta(hours=9))

# 로컬 임베딩 모델 (다국어·한국어) — 1024차원
EMBEDDING_MODEL = "BAAI/bge-m3"
EMBEDDING_DIM = 1024

# 모델은 무거우므로 프로세스당 1회만 로드하는 싱글턴
_MODEL = None


def _get_model():
    """SentenceTransformer 모델을 지연 로드(첫 호출 시 1회)."""
    global _MODEL
    if _MODEL is None:
        from sentence_transformers import SentenceTransformer
        _MODEL = SentenceTransformer(EMBEDDING_MODEL)
    return _MODEL


def embed_texts(texts: list[str]) -> list[list[float]]:
    """텍스트 배열을 로컬 bge-m3 모델로 임베딩 (벡터 좌표로 변환).

    빈 텍스트는 0 벡터로 채워 인덱스 정렬을 유지한다.
    """
    # 비어있지 않은 텍스트만 골라 한 번에 배치 인코딩(속도 ↑)
    nonempty_idx = [i for i, t in enumerate(texts) if t and t.strip()]
    out: list[list[float]] = [[0.0] * EMBEDDING_DIM for _ in texts]

    if nonempty_idx:
        model = _get_model()
        vecs = model.encode(
            [texts[i] for i in nonempty_idx],
            normalize_embeddings=True,  # 코사인 유사도용 정규화
        )
        for j, i in enumerate(nonempty_idx):
            out[i] = vecs[j].tolist()

    return out


def embed_and_store(user_id: int, target_date: date, db: Session) -> dict:
    """
    하루치 미처리 unified_documents를 임베딩해서 embedding_json에 저장.
    이후 clusterer.py가 이 함수가 저장한 embedding_json을 읽어갑니다.
    """
    day_start = datetime.combine(target_date, datetime.min.time()).replace(tzinfo=KST)
    day_end = day_start + timedelta(days=1)

    # 1. DB에서 오늘 치 미처리(임베딩 안 된) 데이터 가져오기
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

    # 2. 가져온 데이터에서 텍스트만 쏙쏙 뽑아내기
    texts = [doc.content_text for doc in docs]

    # 3. 로컬 임베딩 모델에 넣어서 벡터(좌표)로 변환해 오기
    vectors = embed_texts(texts)

    # 4. 변환된 좌표를 다시 DB의 각 줄(row)에 예쁘게 JSON으로 저장하기
    for doc, vector in zip(docs, vectors):
        doc.embedding_json = json.dumps(vector)

    # 5. DB에 최종 도장 찍기(저장 확정)
    db.commit()
    return {"status": "ok", "embedded": len(docs)}
