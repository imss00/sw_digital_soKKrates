"""
역할 A — A-2. HDBSCAN 클러스터링 (RAPTOR 1단계 적용 🚀)
임베딩 벡터를 클러스터링해서 관심 주제 그룹을 만들고 unified_documents.cluster_id에 저장.
"""
import json
from datetime import date, datetime, timedelta, timezone

import numpy as np
import hdbscan
from sklearn.metrics.pairwise import cosine_distances
from sqlalchemy.orm import Session

from backend.models.unified_document import UnifiedDocument

KST = timezone(timedelta(hours=9))


def cluster_embeddings(vectors: np.ndarray) -> np.ndarray:
    """
    HDBSCAN으로 벡터 클러스터링. 라벨 배열 반환 (-1은 노이즈).
    
    기존 DBSCAN의 치명적 단점이었던 고정된 eps(거리) 값을 설정할 필요 없이,
    계층적 밀도(Hierarchical Density)를 기반으로 가장 안정적인 군집을 스스로 찾아냅니다.
    """
    # 코사인 거리 계산 (HDBSCAN 연산을 위해 float64 타입으로 변환)
    distance_matrix = cosine_distances(vectors).astype(np.float64)
    
    # HDBSCAN 군집화 연산
    # 하루 치 데이터(보통 10~20건 내외)의 특성을 고려하여 파라미터 세팅
    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=2,  # 최소 2개 이상 모여야 유의미한 테마(클러스터)로 인정
        min_samples=1,       # 노이즈 판별을 조금 덜 엄격하게 하여 파편화된 데이터도 잘 묶이도록 유도
        metric="precomputed",
    )
    
    labels = clusterer.fit_predict(distance_matrix)
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
    
    # 3. HDBSCAN 알고리즘으로 가까운 관심사끼리 그룹(라벨) 달기
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