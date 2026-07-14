#!/usr/bin/env python3
"""
test_pipeline.py와 동일한 4단계(임베딩→클러스터링→추천→저널)를 임의의 user/date로 돌리는
범용 러너. test_pipeline.py는 user_id=1, 2026-06-27로 하드코딩돼 있어 다른 테스트 유저를
돌리려면 이 스크립트를 쓴다.

Usage:
  ai_env/Scripts/python.exe scripts/run_pipeline.py --user 8 --date 2026-07-05
"""
import argparse
import json
from datetime import date

from backend.database import SessionLocal
from backend.analysis.embedder import embed_and_store
from backend.analysis.clusterer import run_clustering
from backend.analysis.recommender import run_recommendation
from backend.analysis.journal_composer import run_journal_composition


def run(user_id: int, target_date: date):
    db = SessionLocal()

    print("[1단계] 임베딩...")
    print(embed_and_store(user_id, target_date, db))

    print("\n[2단계] 클러스터링...")
    cluster_res = run_clustering(user_id, target_date, db)
    print(cluster_res)
    if cluster_res.get("status") == "skip":
        print("데이터가 너무 적어 클러스터링을 건너뜁니다.")
        return

    print("\n[3단계] 추천...")
    recommend_res = run_recommendation(user_id, target_date, db)
    print(f"core_theme: {recommend_res.get('core_theme')}")
    print(json.dumps(recommend_res.get("structured", {}), ensure_ascii=False, indent=2))

    print("\n[4단계] 저널 생성...")
    final_journal = run_journal_composition(user_id, target_date, recommend_res, db)
    print(json.dumps(final_journal, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--user", type=int, required=True)
    p.add_argument("--date", type=str, required=True)
    args = p.parse_args()
    run(args.user, date.fromisoformat(args.date))
