"""
Phase 2-3 분석 파이프라인 Celery 태스크.
collection_tasks.normalize_and_trigger()가 정규화 완료 후 이 태스크를 호출한다.
"""
from datetime import date

from backend.tasks.celery_app import celery_app
from backend.database import SessionLocal


@celery_app.task(name="backend.tasks.analysis_tasks.run_phase2")
def run_phase2(user_id: int, target_date_str: str):
    """
    Phase 2-3 전체 파이프라인:
      1. 임베딩 생성 (embedder)
      2. DBSCAN 클러스터링 (clusterer)
      3. 추천 엔진 (recommender)
      4. 저널 구성 (journal_composer)
    """
    target_date = date.fromisoformat(target_date_str)
    db = SessionLocal()
    try:
        from backend.analysis.embedder import embed_and_store
        from backend.analysis.clusterer import run_clustering
        from backend.analysis.recommender import run_recommendation
        from backend.analysis.journal_composer import run_journal_composition

        embed_result = embed_and_store(user_id, target_date, db)
        if embed_result.get("status") == "skip":
            return {"status": "skip", "reason": embed_result["reason"]}

        cluster_result = run_clustering(user_id, target_date, db)

        analysis_result = run_recommendation(user_id, target_date, db)

        journal_text = run_journal_composition(user_id, target_date, analysis_result, db)

        # TODO: Phase 4 — journal_text를 프린터로 전송하거나 저장
        # from backend.tasks.print_tasks import send_to_printer
        # send_to_printer.delay(user_id=user_id, journal_text=journal_text)

        return {
            "status": "ok",
            "user_id": user_id,
            "date": target_date_str,
            "embed": embed_result,
            "cluster": cluster_result,
            "journal_preview": journal_text[:200],
        }
    finally:
        db.close()
