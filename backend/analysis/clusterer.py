"""
역할 A — A-2. DBSCAN 클러스터링
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
    distance_matrix = cosine_distances(vectors)
    labels = DBSCAN(
        eps=0.3,
        min_samples=2,
        metric="precomputed",
    ).fit_predict(distance_matrix)
    return labels


def extract_cluster_keywords(docs: list[UnifiedDocument], labels: np.ndarray) -> list[dict]:
    """
    클러스터별 대표 문서 제목을 모아 keywords 구조 반환.

    TODO: 단순 제목 수집 → TF-IDF나 Claude 키워드 추출로 고도화 가능
    """
    clusters: dict[int, list[str]] = {}
    for doc, label in zip(docs, labels):
        if label == -1:
            continue  # 노이즈는 제외 (또는 "기타"로 묶으려면 여기 수정)
        clusters.setdefault(label, []).append(doc.title or doc.content_text[:50])

    return [
        {"cluster_id": int(cid), "keywords": titles, "doc_count": len(titles)}
        for cid, titles in clusters.items()
    ]


def run_clustering(user_id: int, target_date: date, db: Session) -> dict:
    """
    하루치 임베딩을 읽어 클러스터링하고 cluster_id를 DB에 저장.
    embedder.embed_and_store() 완료 후 호출해야 한다.
    """
    day_start = datetime.combine(target_date, datetime.min.time()).replace(tzinfo=KST)
    day_end = day_start + timedelta(days=1)

    docs = (
        db.query(UnifiedDocument)
        .filter(
            UnifiedDocument.user_id == user_id,
            UnifiedDocument.occurred_at >= day_start,
            UnifiedDocument.occurred_at < day_end,
            UnifiedDocument.embedding_json.isnot(None),
        )
        .all()
    )

    if len(docs) < 2:
        return {"status": "skip", "reason": "not enough documents to cluster"}

    vectors = np.array([json.loads(doc.embedding_json) for doc in docs], dtype=np.float32)
    labels = cluster_embeddings(vectors)

    for doc, label in zip(docs, labels):
        doc.cluster_id = int(label)

    db.commit()

    interest_clusters = extract_cluster_keywords(docs, labels)
    return {
        "status": "ok",
        "total_docs": len(docs),
        "num_clusters": len({l for l in labels if l != -1}),
        "noise_count": int(np.sum(labels == -1)),
        "interest_clusters": interest_clusters,
    }
