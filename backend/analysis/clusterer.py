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


def _preview_text(doc: UnifiedDocument) -> str:
    """title이 없을 수도 있으므로 안전하게 content_text의 앞부분 50자로 대체."""
    return getattr(doc, "title", None) or doc.content_text[:50]


def extract_cluster_keywords(docs: list[UnifiedDocument], labels: np.ndarray) -> list[dict]:
    """
    클러스터별 대표 문서 텍스트를 모아 반환.
    (본격적인 LLM 테마 요약은 다음 단계인 recommender.py에서 진행합니다.)
    """
    clusters: dict[int, list[str]] = {}
    for doc, label in zip(docs, labels):
        if label == -1:
            continue  # 노이즈(외톨이 데이터)는 제외
        clusters.setdefault(label, []).append(_preview_text(doc))

    return [
        {"cluster_id": int(cid), "keywords": texts, "doc_count": len(texts)}
        for cid, texts in clusters.items()
    ]


def _mark_processed(docs: list[UnifiedDocument], cluster_id_by_doc: dict[int, int] | None = None) -> None:
    """문서를 Phase 2 처리 완료로 표시하고 keywords 힌트를 채운다.

    journal_composer.extract_keywords()가 is_processed=True인 문서의 keywords만 읽는데
    지금까지 이 두 컬럼을 채우는 코드가 어디에도 없어서 매번 빈 배열이 나가고 있었음.
    본격적인 LLM 키워드 추출 전이라, 관심 주제 군집에 속한 문서는 제목/본문 미리보기를
    키워드 힌트로 채운다. 노이즈(군집 없음)는 extract_cluster_keywords()와 동일하게
    "관심 주제"로 취급하지 않으므로 keywords는 비워두되(엉뚱한 한 줄짜리 텍스트가 관심사
    키워드인 것처럼 프롬프트에 섞이는 걸 막기 위함), 임베딩·클러스터링 자체는 끝났으므로
    is_processed는 True로 표시해 나중에 재처리 로직이 이 문서들을 "미처리"로 오인해
    한없이 기다리지 않게 한다.
    """
    for doc in docs:
        cluster_id = cluster_id_by_doc[doc.id] if cluster_id_by_doc is not None else -1
        doc.keywords = [_preview_text(doc)] if cluster_id != -1 else []
        doc.is_processed = True


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
        # 문서가 0~1건이면 HDBSCAN 자체가 의미 없어 군집화는 건너뛰지만, 있는 문서는
        # (1건이라도) 임베딩까지는 끝난 상태이므로 처리 완료로 표시해야 한다. 안 그러면
        # 활동이 적은 날은 is_processed가 영원히 False로 남아 keywords가 계속 비게 된다.
        if docs:
            _mark_processed(docs)
            db.commit()
        return {"status": "skip", "reason": "not enough documents to cluster"}

    # 2. JSON으로 저장된 좌표 리스트를 수학 연산용 배열(numpy)로 변환
    vectors = np.array([json.loads(doc.embedding_json) for doc in docs], dtype=np.float32)

    # 3. HDBSCAN 알고리즘으로 가까운 관심사끼리 그룹(라벨) 달기
    labels = cluster_embeddings(vectors)

    # 4. 판별된 그룹 번호(cluster_id)를 DB 데이터에 업데이트
    cluster_id_by_doc = {}
    for doc, label in zip(docs, labels):
        doc.cluster_id = int(label)
        cluster_id_by_doc[doc.id] = int(label)
    _mark_processed(docs, cluster_id_by_doc)

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
