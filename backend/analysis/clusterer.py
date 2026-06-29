"""
역할 A — A-2. DBSCAN 클러스터링 (RAPTOR 1단계 적용)
임베딩 벡터를 클러스터링해서 관심 주제 그룹을 만들고 unified_documents.cluster_id에 저장.
"""
import json
from datetime import date, datetime, timedelta, timezone

import numpy as np
from sklearn.cluster import DBSCAN
from sklearn.metrics.pairwise import cosine_distances
from sqlalchemy.orm import Session

from backend.models.unified_document import UnifiedDocument

KST = timezone(timedelta(hours=9))


def cluster_embeddings(vectors: np.ndarray) -> np.ndarray:
    """
    DBSCAN으로 벡터 클러스터링. 라벨 배열 반환 (-1은 노이즈).
    
    eps, min_samples 튜닝 가이드:
      eps=0.2 → 엄격 (클러스터 적고 노이즈 많음)
      eps=0.3 → 기본값 (권장)
      eps=0.5 → 느슨 (다양한 주제가 합쳐짐)
    """
    # 코사인 거리 계산 (1 - 코사인 유사도)
    distance_matrix = cosine_distances(vectors)
    
    # DBSCAN 군집화 연산
    labels = DBSCAN(
        eps=0.3,
        min_samples=2,
        metric="precomputed",
    ).fit_predict(distance_matrix)
    
    return labels


def extract_cluster_keywords(docs: list[UnifiedDocument], labels: np.ndarray) -> list[dict]:
    """
    클러스터별 대표 문서 텍스트를 모아 반환.
    (본격적인 LLM 테마 요약은 다음 단계인 recommender.py에서 진행합니다.)
    """
    clusters: dict[int, list[str]] = {}
    for doc, label in zip(docs, labels):
        if label == -1:
            continue  # 노이즈(외톨이 데이터)는 제외
            
        # title 컬럼이 없을 수도 있으므로 안전하게 content_text의 앞부분 50자 사용
        preview_text = getattr(doc, 'title', None) or doc.content_text[:50]
        clusters.setdefault(label, []).append(preview_text)

    return [
        {"cluster_id": int(cid), "keywords": texts, "doc_count": len(texts)}
        for cid, texts in clusters.items()
    ]


def run_clustering(user_id: int, target_date: date, db: Session) -> dict:
    """
    하루치 임베딩을 읽어 클러스터링하고 cluster_id를 DB에 저장.
    embedder.embed_and_store() 완료 후 호출해야 한다.
    """
    day_start = datetime.combine(target_date, datetime.min.time()).replace(tzinfo=KST)
    day_end = day_start + timedelta(days=1)

    # 1. DB에서 임베딩이 완료된 오늘 치 데이터 가져오기
    docs = (
        db.query(UnifiedDocument)
        .filter(
            UnifiedDocument.user_id == user_id,
            UnifiedDocument.occurred_at >= day_start,
            UnifiedDocument.occurred_at < day_end,
            UnifiedDocument.embedding_json.isnot(None), # 임베딩 값이 존재하는 것만
        )
        .all()
    )

    if len(docs) < 2:
        return {"status": "skip", "reason": "not enough documents to cluster"}

    # 2. JSON으로 저장된 좌표 리스트를 수학 연산용 배열(numpy)로 변환
    vectors = np.array([json.loads(doc.embedding_json) for doc in docs], dtype=np.float32)
    
    # 3. DBSCAN 알고리즘으로 가까운 관심사끼리 그룹(라벨) 달기
    labels = cluster_embeddings(vectors)

    # 4. 판별된 그룹 번호(cluster_id)를 DB 데이터에 업데이트
    for doc, label in zip(docs, labels):
        doc.cluster_id = int(label)

    # DB에 저장 확정
    db.commit()

    # 결과 요약 리포트 생성
    interest_clusters = extract_cluster_keywords(docs, labels)
    return {
        "status": "ok",
        "total_docs": len(docs),
        "num_clusters": len({l for l in labels if l != -1}),
        "noise_count": int(np.sum(labels == -1)),
        "interest_clusters": interest_clusters,
    }
