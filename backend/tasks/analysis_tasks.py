"""
Phase 2-3 분석 파이프라인.
collection_tasks.normalize_and_trigger()가 정규화 완료 후 run_phase2(celery task)를 호출한다.
webhook에서 즉시 시연용으로 트리거할 때는 정규화만 동기로 처리하고, 이 celery task는
run_phase2.delay(...)로 큐에 넣어 비동기로 실행한다(HTTP 요청을 수 분간 붙잡지 않기 위함).
"""
from datetime import date

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from backend.tasks.celery_app import celery_app
from backend.database import SessionLocal
from backend.models.journal import Journal, JOURNAL_RESULT_FIELDS


def _save_journal(user_id: int, target_date: date, journal_result: dict, db: Session) -> int:
    """compose_journal() 결과를 journals 테이블에 원자적으로 upsert하고 id를 반환.

    이전에는 이 결과가 celery task 리턴값으로만 존재하고 DB에 남지 않아
    프론트엔드/프린터가 완성된 저널을 조회할 방법이 없었다.

    SELECT로 존재를 확인한 뒤 INSERT/UPDATE를 나누는 방식은 동시에 두 요청이 같은
    user_id+target_date로 들어오면(시연 중 재트리거는 흔한 상황) 유니크 제약 위반으로
    한쪽이 처리되지 않은 예외를 던질 수 있어, DB의 INSERT ... ON CONFLICT로 원자적으로 처리한다.
    """
    values = {
        "user_id": user_id,
        "target_date": target_date,
        "date_label": journal_result.get("date"),
        **{field: journal_result.get(field) for field in JOURNAL_RESULT_FIELDS},
    }

    stmt = pg_insert(Journal).values(**values)
    # ON CONFLICT DO UPDATE는 Core 레벨 구문이라 모델의 onupdate=func.now()(ORM 훅)가
    # 적용되지 않는다 — updated_at을 여기서 직접 넣어주지 않으면 재저장해도 값이 안 바뀐다.
    update_values = {k: stmt.excluded[k] for k in values if k not in ("user_id", "target_date")}
    update_values["updated_at"] = func.now()
    stmt = stmt.on_conflict_do_update(
        constraint="uq_journal_user_date",
        set_=update_values,
    ).returning(Journal.id)

    journal_id = db.execute(stmt).scalar_one()
    db.commit()
    return journal_id


def run_phase2_sync(user_id: int, target_date: date, db: Session) -> dict:
    """
    Phase 2-3 전체 파이프라인(동기 실행):
      1. 임베딩 생성 (embedder)
      2. HDBSCAN 클러스터링 (clusterer)
      3. 추천 엔진 (recommender)
      4. 저널 구성 (journal_composer)
      5. journals 테이블에 저장

    celery task(run_phase2)의 실행 본체. HTTP 요청을 직접 붙잡지 않도록, webhook에서는
    이 함수를 직접 호출하지 않고 run_phase2.delay(...)로 큐에 넣어 실행한다.
    """
    from backend.analysis.embedder import embed_and_store
    from backend.analysis.clusterer import run_clustering
    from backend.analysis.recommender import run_recommendation
    from backend.analysis.journal_composer import run_journal_composition

    embed_result = embed_and_store(user_id, target_date, db)
    # embed_and_store가 이제 "그날 문서가 아예 없음"과 "이미 다 임베딩됨"을 reason으로
    # 구분해서 반환하므로, 전자일 때만 전체 파이프라인을 건너뛴다(후자는 재트리거 시 흔하고,
    # 클러스터링~저널생성은 계속 진행해야 저널이 저장된다).
    if embed_result.get("reason") == "no documents for this day":
        return {"status": "skip", "reason": embed_result["reason"]}

    cluster_result = run_clustering(user_id, target_date, db)

    analysis_result = run_recommendation(user_id, target_date, db)

    journal_result = run_journal_composition(user_id, target_date, analysis_result, db)

    journal_id = _save_journal(user_id, target_date, journal_result, db)

    # TODO: Phase 4 — journal_result를 프린터로 전송 (python-escpos 연동 예정)

    preview_text = journal_result.get("reflection") or journal_result.get("headline") or ""

    return {
        "status": "ok",
        "user_id": user_id,
        "date": target_date.isoformat(),
        "embed": embed_result,
        "cluster": cluster_result,
        "journal_id": journal_id,
        "journal_preview": preview_text[:200],
    }


@celery_app.task(name="backend.tasks.analysis_tasks.run_phase2")
def run_phase2(user_id: int, target_date_str: str):
    target_date = date.fromisoformat(target_date_str)
    db = SessionLocal()
    try:
        return run_phase2_sync(user_id, target_date, db)
    finally:
        db.close()
