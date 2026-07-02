#!/usr/bin/env python3
"""
임베딩 초기화 스크립트 — LLM provider 변경 후 재임베딩용.

임베딩 모델을 바꾸면(예: Gemini→OpenAI) 벡터 차원이 달라진다.
과거에 다른 provider로 임베딩된 문서(embedding_json 이미 채워짐)는
embed_and_store가 건너뛰므로 옛 벡터가 그대로 남아, 새 벡터와 섞이면
클러스터링/FAISS에서 차원 불일치 크래시가 난다.

이 스크립트로 해당 날짜의 embedding_json / cluster_id / is_processed를 비우면,
다음 run_phase2 실행 시 전부 새 provider(OpenAI)로 재임베딩된다.

사용법 (레포 루트에서):
  ./ai_env/bin/python scripts/reset_embeddings.py --user 1 --date 2026-06-27
"""
import argparse
import os
import sys
from datetime import date, datetime, timedelta, timezone

# 어디서 실행해도 backend 패키지를 찾도록 레포 루트를 path에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database import SessionLocal
from backend.models.unified_document import UnifiedDocument

KST = timezone(timedelta(hours=9))


def main() -> None:
    parser = argparse.ArgumentParser(description="해당 날짜의 임베딩을 비워 재임베딩되게 한다.")
    parser.add_argument("--user", type=int, required=True, help="user_id")
    parser.add_argument("--date", required=True, help="대상 날짜 YYYY-MM-DD")
    args = parser.parse_args()

    target = date.fromisoformat(args.date)
    day_start = datetime.combine(target, datetime.min.time()).replace(tzinfo=KST)
    day_end = day_start + timedelta(days=1)

    db = SessionLocal()
    try:
        docs = (
            db.query(UnifiedDocument)
            .filter(
                UnifiedDocument.user_id == args.user,
                UnifiedDocument.occurred_at >= day_start,
                UnifiedDocument.occurred_at < day_end,
            )
            .all()
        )
        for d in docs:
            d.embedding_json = None   # 벡터 비움 → 다음 run에서 재임베딩
            d.cluster_id = None       # 군집도 초기화
            d.is_processed = False    # 역할 B까지 다시 돌게 플래그 리셋
        db.commit()
        print(
            f"✅ user={args.user} {args.date}: {len(docs)}건 초기화 완료 "
            f"— 다음 run_phase2에서 OpenAI로 재임베딩됩니다."
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
