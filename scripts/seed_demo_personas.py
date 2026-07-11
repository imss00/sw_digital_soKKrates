#!/usr/bin/env python3
"""
심사위원 데모용 중년 페르소나 더미데이터 생성.

새 데모 유저 2명(이은정 48세 워킹맘 / 52세 자영업+등산)을 만들고
캘린더/브라우징/스포티파이/노션 raw 테이블 + 사진(unified_documents 직접)을
채운 뒤, normalize -> phase2(임베딩/클러스터링/저널작성)까지 실행한다.

Usage:
  insert: python scripts/seed_demo_personas.py --action insert
  cleanup: python scripts/seed_demo_personas.py --action cleanup
"""
import argparse
from datetime import datetime, timedelta, timezone

from backend.database import SessionLocal
from backend.models.user import User
from backend.models.browsing_history import BrowsingHistory
from backend.models.spotify_history import SpotifyHistory
from backend.models.calendar_event import CalendarEvent
from backend.models.notion_page import NotionPage
from backend.models.unified_document import UnifiedDocument

KST = timezone(timedelta(hours=9))
TARGET_DATE = datetime(2026, 7, 4, tzinfo=KST)

DEMO_EMAILS = ["demo.eunjeong@paperback.local", "demo.hiker52@paperback.local"]


def _t(hour, minute=0):
    return TARGET_DATE.replace(hour=hour, minute=minute)


def build_persona_a(user_id: int):
    calendar = [
        dict(summary="OO입시학원 정시 지원전략 설명회", description="재원생 학부모 대상 2027학년도 정시 지원전략 설명회, 배치표 배포",
             start=_t(10, 0), end=_t(11, 30), location="강남 학원가"),
        dict(summary="점심약속 - 대학 동기 미영", description="근처 파스타집",
             start=_t(13, 0), end=_t(14, 0), location=None),
        dict(summary="동네 내과 - 갱년기 호르몬 검사 결과 상담", description=None,
             start=_t(16, 0), end=_t(16, 30), location=None),
        dict(summary="가족 저녁 - 딸 학원 마치고 외식", description="소민이 좋아하는 제육 먹으러",
             start=_t(19, 30), end=_t(20, 30), location=None),
    ]

    browsing = [
        dict(domain="land.naver.com", title="OO동 아파트 시세, 국평 실거래가", is_article=False, hour=9, minute=15, spent=480),
        dict(domain="blog.naver.com", title="연금저축펀드 세액공제 한도 2026년 기준 정리", is_article=True, hour=9, minute=40, spent=300),
        dict(domain="veritas-a.com", title="2027 정시 배치표 무료 다운로드", is_article=True, hour=21, minute=10, spent=720),
        dict(domain="veritas-a.com", title="논술전형 vs 정시, 뭐가 유리할까", is_article=True, hour=21, minute=30, spent=400),
        dict(domain="hidoc.co.kr", title="갱년기 여성 호르몬 검사 비용과 준비물", is_article=True, hour=15, minute=20, spent=260),
        dict(domain="hidoc.co.kr", title="폐경기 골밀도 검사, 얼마나 자주 받아야 할까", is_article=True, hour=15, minute=35, spent=200),
        dict(domain="post.naver.com", title="저속노화 식단, 40대부터 시작하는 이유", is_article=True, hour=22, minute=0, spent=340),
    ]

    spotify = [
        dict(track="보이지 않는 사랑", artist="신승훈", album="보이지 않는 사랑", hour=7, minute=40, dur=270000,
             valence=0.3, energy=0.3, genres=["ballad"]),
        dict(track="잘못된 만남", artist="김건모", album="잘못된 만남", hour=7, minute=55, dur=250000,
             valence=0.6, energy=0.75, genres=["k-pop", "dance"]),
        dict(track="그 안에 갇혀", artist="이수영", album="그 안에 갇혀", hour=12, minute=20, dur=260000,
             valence=0.35, energy=0.35, genres=["ballad"]),
        dict(track="내사람", artist="SG워너비", album="내사람", hour=18, minute=40, dur=280000,
             valence=0.4, energy=0.4, genres=["r-n-b", "ballad"]),
        dict(track="다시 만날 수 있을까", artist="임영웅", album="다시 만날 수 있을까", hour=19, minute=10, dur=240000,
             valence=0.25, energy=0.3, genres=["trot"]),
        dict(track="두 사람", artist="성시경", album="어제 그리고 오늘", hour=20, minute=30, dur=290000,
             valence=0.3, energy=0.25, genres=["ballad"]),
        dict(track="야생화", artist="박효신", album="I Am A Dreamer", hour=21, minute=0, dur=300000,
             valence=0.35, energy=0.4, genres=["ballad", "rock"]),
    ]

    notion = [
        dict(title="2026-07-04 다이어리",
             content="오늘 OO학원 설명회 다녀옴. 정시 배치표 보니 막막... 그래도 애 옆에서 흔들리지 말자 다짐. "
                     "갱년기 검사 결과는 다음주에나 나온다고. 연금저축 세액공제 한도 채워야 하는데 이번달 카드값 보니 빠듯. "
                     "저녁에 소민이 좋아하는 제육 해줌.",
             hour=22, minute=30),
        dict(title="재테크 메모",
             content="연금저축 400만원 한도 - 지금까지 250만원 납입, 나머지 150만원 연말까지 채우기. 청약통장은 계속 유지.",
             hour=9, minute=50),
    ]

    photos = [
        dict(desc="학원 설명회장에서 배치표 촬영 - 자리 꽉 찬 강당, 다들 심각한 표정으로 필기 중", hour=10, minute=40),
        dict(desc="저녁 식탁 사진 - 제육볶음과 계란찜, 딸이 좋아하는 반찬으로 차린 야식", hour=21, minute=15),
    ]

    return calendar, browsing, spotify, notion, photos


def build_persona_b(user_id: int):
    calendar = [
        dict(summary="OO산악회 정기 산행 - 관악산", description="산악회 정기모임, 관악산 코스, 하산 후 뒤풀이",
             start=_t(5, 30), end=_t(10, 0), location="관악산"),
        dict(summary="하산 후 뒤풀이 - 파전에 막걸리", description=None,
             start=_t(10, 30), end=_t(12, 0), location="관악산 입구"),
        dict(summary="가게 매출 정산", description="이번달 매출 정리, 자재 단가 인상분 반영해서 견적 다시 내기",
             start=_t(15, 0), end=_t(16, 0), location=None),
        dict(summary="고등학교 동창모임 (30주년)", description="OO고 30주년 동창회, OO호텔 연회장",
             start=_t(18, 0), end=_t(21, 0), location="OO호텔"),
    ]

    browsing = [
        dict(domain="cafe.naver.com", title="관악산 코스 후기, 등산화 뭐 신으세요", is_article=True, hour=4, minute=50, spent=420),
        dict(domain="hankyung.com", title="금리 인하기 배당주 투자 전략", is_article=True, hour=13, minute=10, spent=380),
        dict(domain="hankyung.com", title="지방 소형 아파트 갭투자, 요즘도 될까", is_article=True, hour=13, minute=30, spent=300),
        dict(domain="hidoc.co.kr", title="전립선 건강검진, 50대 이후 주기는", is_article=True, hour=14, minute=20, spent=240),
        dict(domain="hidoc.co.kr", title="대장내시경 용종 제거 후 주의사항", is_article=True, hour=14, minute=35, spent=200),
        dict(domain="b2b.naver.com", title="인테리어 자재 도매가 비교", is_article=False, hour=14, minute=50, spent=360),
        dict(domain="blog.naver.com", title="소상공인 카드 수수료 절감 방법", is_article=True, hour=15, minute=10, spent=280),
        dict(domain="blog.naver.com", title="OO고 동창회 회비 계좌 안내", is_article=False, hour=17, minute=20, spent=90),
    ]

    spotify = [
        dict(track="옛사랑", artist="이문세", album="이문세 6집", hour=5, minute=20, dur=280000,
             valence=0.35, energy=0.3, genres=["ballad"]),
        dict(track="잘못된 만남", artist="김건모", album="잘못된 만남", hour=5, minute=35, dur=250000,
             valence=0.6, energy=0.75, genres=["k-pop", "dance"]),
        dict(track="홀로 된다는 것", artist="변진섭", album="홀로 된다는 것", hour=12, minute=10, dur=260000,
             valence=0.3, energy=0.3, genres=["ballad"]),
        dict(track="사랑은 아무나 하나", artist="태진아", album="사랑은 아무나 하나", hour=18, minute=40, dur=220000,
             valence=0.55, energy=0.6, genres=["trot"]),
        dict(track="나침반", artist="설운도", album="나침반", hour=19, minute=20, dur=230000,
             valence=0.6, energy=0.65, genres=["trot"]),
        dict(track="이제 나만 믿어요", artist="임영웅", album="IM HERO", hour=19, minute=50, dur=245000,
             valence=0.5, energy=0.55, genres=["trot"]),
        dict(track="보이지 않는 사랑", artist="신승훈", album="보이지 않는 사랑", hour=21, minute=30, dur=270000,
             valence=0.3, energy=0.3, genres=["ballad"]),
    ]

    notion = [
        dict(title="동창회 준비 메모",
             content="30주년 동창회 회비 10만원 입금 확인. 영수랑 재석이도 온다고 함. 오랜만이라 기대반 걱정반.",
             hour=17, minute=30),
        dict(title="가게 매출 메모",
             content="이번달 매출 전월 대비 소폭 감소. 자재 단가 인상분 반영해서 견적 다시 내야 함. "
                     "대장내시경 예약 더 미루지 말기.",
             hour=15, minute=40),
    ]

    photos = [
        dict(desc="관악산 정상 인증샷 - 뒤로 서울 시내 전경, 산악회 깃발과 함께", hour=8, minute=10),
        dict(desc="동창회 단체사진 - 30년 만에 다 모인 얼굴들, 다들 많이 변했지만 반가운 표정", hour=19, minute=0),
    ]

    return calendar, browsing, spotify, notion, photos


def insert_persona(db, email: str, name: str, builder):
    user = User(email=email, name=name, wake_up_time="07:00", timezone="Asia/Seoul")
    db.add(user)
    db.flush()

    calendar, browsing, spotify, notion, photos = builder(user.id)

    for c in calendar:
        db.add(CalendarEvent(
            user_id=user.id, google_event_id=f"demo-{user.id}-{c['start'].isoformat()}",
            summary=c["summary"], description=c["description"],
            start_time=c["start"], end_time=c["end"],
            duration_min=int((c["end"] - c["start"]).total_seconds() / 60),
            location=c["location"], is_recurring=False, attendee_count=0,
        ))

    for b in browsing:
        db.add(BrowsingHistory(
            user_id=user.id, url=f"https://{b['domain']}/demo-{hash(b['title']) & 0xffffff}",
            domain=b["domain"], title=b["title"], article_text=b["title"] if b["is_article"] else None,
            is_article=b["is_article"], visited_at=_t(b["hour"], b["minute"]),
            time_spent_sec=b["spent"], visit_count=1,
        ))

    for s in spotify:
        played_at = _t(s["hour"], s["minute"])
        db.add(SpotifyHistory(
            user_id=user.id, spotify_track_id=f"demo-{user.id}-{s['track']}",
            track_name=s["track"], artist_name=s["artist"], artist_id=f"demo-artist-{s['artist']}",
            album_name=s["album"], played_at=played_at, duration_ms=s["dur"],
            valence=s["valence"], energy=s["energy"], genres=s["genres"],
        ))

    for n in notion:
        db.add(NotionPage(
            user_id=user.id, notion_page_id=f"demo-{user.id}-{n['title']}"[:36],
            title=n["title"], content_text=n["content"], last_edited=_t(n["hour"], n["minute"]),
        ))

    for i, p in enumerate(photos, start=1):
        db.add(UnifiedDocument(
            user_id=user.id, source="photo", source_id=-(i),
            content_text=p["desc"], content_type="photo", title=p["desc"][:30],
            occurred_at=_t(p["hour"], p["minute"]),
        ))

    db.commit()
    print(f"Inserted persona '{name}' as user_id={user.id} ({email})")
    return user.id


def insert_all():
    db = SessionLocal()
    try:
        uid_a = insert_persona(db, DEMO_EMAILS[0], "이은정", build_persona_a)
        uid_b = insert_persona(db, DEMO_EMAILS[1], "김etc(52세 자영업)", build_persona_b)
        print(f"\nTARGET_DATE={TARGET_DATE.date()}  user_ids=({uid_a}, {uid_b})")
    finally:
        db.close()


def cleanup():
    db = SessionLocal()
    try:
        users = db.query(User).filter(User.email.in_(DEMO_EMAILS)).all()
        ids = [u.id for u in users]
        if not ids:
            print("No demo users found.")
            return
        for model in [CalendarEvent, BrowsingHistory, SpotifyHistory, NotionPage, UnifiedDocument]:
            db.query(model).filter(model.user_id.in_(ids)).delete(synchronize_session=False)
        for u in users:
            db.delete(u)
        db.commit()
        print(f"Removed demo users {ids} and their data.")
    finally:
        db.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--action", choices=["insert", "cleanup"], required=True)
    args = p.parse_args()
    if args.action == "insert":
        insert_all()
    else:
        cleanup()
