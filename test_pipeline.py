# test_pipeline.py
print("🚀 [테스트] 스크립트가 무사히 켜졌습니다!")

from datetime import date
from backend.database import SessionLocal
# ... (나머지 기존 코드) ...
from datetime import date
from backend.database import SessionLocal
from backend.analysis.embedder import embed_and_store
from backend.analysis.clusterer import run_clustering
from backend.analysis.recommender import run_recommendation
from backend.analysis.journal_composer import run_journal_composition

def run_test():
    db = SessionLocal()
    
    # ⚠️ 중요: 테스트할 유저 ID와 데이터가 실제로 존재하는 날짜를 설정하세요!
    # DB에 테스트용 데이터가 없다면 날짜를 맞춰주어야 합니다.
    user_id = 1 
    target_date = date(2026, 6, 27) 
    
    print("🚀 [1단계] 임베딩 파이프라인 가동...")
    embed_res = embed_and_store(user_id, target_date, db)
    print(f"👉 1단계 결과: {embed_res}\n")
    
    print("🚀 [2단계] DBSCAN 클러스터링 가동...")
    cluster_res = run_clustering(user_id, target_date, db)
    print(f"👉 2단계 결과: {cluster_res}\n")
    
    if cluster_res.get("status") == "skip":
        print("❌ 오늘 치 데이터가 너무 적어서 클러스터링을 건너뜁니다. 테스트 데이터를 더 넣어주세요.")
        return

    print("🚀 [3단계] HyDE 미끼 생성 및 FAISS 실제 뉴스 매칭 가동...")
    recommend_res = run_recommendation(user_id, target_date, db)
    print(f"👉 3단계 도출된 핵심 관심사 테마:\n{recommend_res.get('core_theme')}\n")
    print(f"👉 HyDE 가상 문서(검색 질의):\n{recommend_res.get('hyde_document')}\n")
    print(f"👉 매칭된 실제 기사 개수: {len(recommend_res.get('recommended_articles', []))}개\n")

    # 역할 A 최종 산출물 — 구조화 JSON 출력
    import json
    print("🧩=================== [역할 A 구조화 JSON] ===================🧩")
    print(json.dumps(recommend_res.get("structured", {}), ensure_ascii=False, indent=2))
    print("===============================================================\n")

    print("🚀 [4단계] OpenAI 기반 AI 저널 최종 편집...")
    final_journal = run_journal_composition(user_id, target_date, recommend_res, db)
    
    print("\n🎉=================== [최종 생성된 AI 저널] ===================🎉")
    print(final_journal)
    print("===============================================================\n")

if __name__ == "__main__":
    run_test()