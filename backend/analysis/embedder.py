
"""
역할 A — A-1. 임베딩 파이프라인 (Gemini 버전 🚀)
unified_documents의 content_text를 구글 Gemini 벡터로 변환하고 DB에 저장한다.
"""
import json
import os
from datetime import date, datetime, timedelta, timezone

from google import genai
from sqlalchemy.orm import Session

from backend.models.unified_document import UnifiedDocument

KST = timezone(timedelta(hours=9))
# OpenAI 대신 우리가 검증한 최신 Gemini 임베딩 모델 사용
EMBEDDING_MODEL = "gemini-embedding-001"  


def embed_texts(texts: list[str]) -> list[list[float]]:
    """텍스트 배열을 Gemini API를 호출하여 임베딩 (벡터 좌표로 변환)"""
    # .env 파일에 있는 GEMINI_API_KEY를 자동으로 읽어와서 작동합니다.
    client = genai.Client()
    
    vectors = []
    for text in texts:
        # 텍스트가 비어있지 않은 경우에만 임베딩 수행
        if text and text.strip():
            response = client.models.embed_content(
                model=EMBEDDING_MODEL,
                contents=text
            )
            # 변환된 좌표(float 리스트)를 추출하여 추가
            vectors.append(response.embeddings[0].values)
        else:
            # 빈 텍스트일 경우 더미(0) 벡터 삽입 (에러 방지용)
            vectors.append([0.0] * 768) 
            
    return vectors


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

    # 3. Gemini 공장에 넣어서 벡터(좌표)로 변환해 오기
    vectors = embed_texts(texts)

    # 4. 변환된 좌표를 다시 DB의 각 줄(row)에 예쁘게 JSON으로 저장하기
    for doc, vector in zip(docs, vectors):
        doc.embedding_json = json.dumps(vector)

    # 5. DB에 최종 도장 찍기(저장 확정)
    db.commit()
    return {"status": "ok", "embedded": len(docs)}
